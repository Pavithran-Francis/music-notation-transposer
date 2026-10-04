"""Background job execution.

Jobs are persisted in the database (so the UI can poll them and they survive
page reloads) and executed by an in-process thread pool. This keeps local
deployment to a single process; the `submit` function is the only seam to
replace with Celery/RQ for multi-machine deployments.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Callable

from sqlalchemy import select

from app.config import get_settings
from app.db import Job, Project, add_history, now, session
from app.services import storage

log = logging.getLogger("smt.jobs")
_executor: ThreadPoolExecutor | None = None


def executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=get_settings().workers, thread_name_prefix="smt-job")
    return _executor


def _update(job_id: str, **fields) -> None:
    with session() as s:
        job = s.get(Job, job_id)
        if job:
            for k, v in fields.items():
                setattr(job, k, v)


ACTIVE_STATUS = {"analyze": "analyzing", "transpose": "transposing"}
DONE_STATUS = {"analyze": "analyzed", "transpose": "transposed"}


def submit(project_id: str, kind: str, fn: Callable[[str, Callable], None]) -> str:
    with session() as s:
        running = s.scalars(
            select(Job).where(Job.project_id == project_id, Job.status.in_(["queued", "running"]))
        ).first()
        if running:
            return running.id
        job = Job(project_id=project_id, kind=kind)
        s.add(job)
        project = s.get(Project, project_id)
        project.status = ACTIVE_STATUS.get(kind, project.status)
        project.error = None
        s.flush()
        job_id = job.id

    def progress(step: str, message: str, fraction: float) -> None:
        _update(job_id, step=step, message=message, progress=max(0.0, min(1.0, fraction)))

    def run() -> None:
        _update(job_id, status="running", step="starting", message="Starting…")
        try:
            fn(project_id, progress)
        except Exception as e:  # report every failure to the user, never crash the worker
            from app.services.pipeline import PipelineError

            user_msg = str(e) if isinstance(e, PipelineError) else f"Unexpected error: {e}"
            if not isinstance(e, PipelineError):
                log.error("job %s failed\n%s", job_id, traceback.format_exc())
            _update(job_id, status="failed", step="failed", message=user_msg, error=user_msg)
            with session() as s:
                project = s.get(Project, project_id)
                if project:
                    project.status = "failed"
                    project.error = user_msg
                    add_history(s, project_id, f"{kind}_failed", error=user_msg)
            return
        _update(job_id, status="succeeded", step="complete", message="Complete.", progress=1.0)
        with session() as s:
            project = s.get(Project, project_id)
            if project:
                project.status = DONE_STATUS.get(kind, project.status)

    executor().submit(run)
    return job_id


def recover_interrupted() -> None:
    """Jobs that were running when the server stopped are marked failed."""
    with session() as s:
        for job in s.scalars(select(Job).where(Job.status.in_(["queued", "running"]))):
            job.status = "failed"
            job.message = job.error = "Processing was interrupted by a server restart. Please try again."
            project = s.get(Project, job.project_id)
            if project and project.status in ("analyzing", "transposing"):
                project.status = "failed"
                project.error = job.error


def cleanup_expired() -> int:
    """Delete unsaved projects (and their files) older than the retention period."""
    cutoff = now() - timedelta(hours=get_settings().retention_hours)
    removed = 0
    with session() as s:
        for project in s.scalars(select(Project).where(Project.saved.is_(False))):
            updated = project.updated_at
            if updated.tzinfo is None:
                from datetime import timezone
                updated = updated.replace(tzinfo=timezone.utc)
            if updated < cutoff:
                storage.delete_project_files(project.id)
                s.delete(project)
                removed += 1
    if removed:
        log.info("cleanup removed %d expired project(s)", removed)
    return removed


def start_cleanup_thread() -> None:
    interval = get_settings().cleanup_interval_minutes * 60

    def loop() -> None:
        while True:
            try:
                cleanup_expired()
            except Exception:
                log.exception("cleanup failed")
            time.sleep(interval)

    threading.Thread(target=loop, name="smt-cleanup", daemon=True).start()

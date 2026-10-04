"""SQLite persistence for projects, jobs and processing history."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.config import get_settings


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), default="Untitled score")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    # created | uploaded | analyzing | analyzed | transposing | transposed | failed
    status: Mapped[str] = mapped_column(String(20), default="created")
    source_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)  # musicxml|pdf|image|mscz
    original_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    page_rotations: Mapped[list] = mapped_column(JSON, default=list)
    source_instrument: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    target_instrument: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    corrections: Mapped[list] = mapped_column(JSON, default=list)
    range_actions: Mapped[list] = mapped_column(JSON, default=list)
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recognition: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    jobs: Mapped[list["Job"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    history: Mapped[list["HistoryEntry"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="HistoryEntry.at"
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # analyze | transpose
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|succeeded|failed
    step: Mapped[str] = mapped_column(String(50), default="queued")
    message: Mapped[str] = mapped_column(Text, default="Queued…")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    project: Mapped[Project] = relationship(back_populates="jobs")


class HistoryEntry(Base):
    __tablename__ = "history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    action: Mapped[str] = mapped_column(String(50))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    project: Mapped[Project] = relationship(back_populates="history")


_engine = None
_Session: sessionmaker | None = None


def init_db(url: str | None = None) -> None:
    global _engine, _Session
    settings = get_settings()
    url = url or f"sqlite:///{settings.data_dir / 'app.db'}"
    _engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(_engine, "connect")
    def _pragma(dbapi_conn, _):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    Base.metadata.create_all(_engine)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)


@contextmanager
def session() -> Iterator[Session]:
    if _Session is None:
        init_db()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def add_history(s: Session, project_id: str, action: str, **detail) -> None:
    s.add(HistoryEntry(project_id=project_id, action=action, detail=detail))

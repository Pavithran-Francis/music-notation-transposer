# Production image: FastAPI backend + built frontend + Audiveris (OMR) + MuseScore 3 (engraving).
# Audiveris publishes x86_64 Linux packages only, so build/run with --platform linux/amd64.

FROM node:22-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ubuntu:24.04
ARG AUDIVERIS_VERSION=5.11.0
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 QT_QPA_PLATFORM=offscreen \
    SMT_DATA_DIR=/data SMT_AUDIVERIS_PATH=/opt/audiveris/bin/Audiveris SMT_MSCORE_PATH=/usr/bin/mscore3
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv ca-certificates curl libcairo2 fonts-dejavu-core \
      musescore3 libgl1 libglib2.0-0 \
    && curl -fsSL -o /tmp/audiveris.deb \
      "https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-ubuntu24.04-x86_64.deb" \
    && apt-get install -y --no-install-recommends /tmp/audiveris.deb \
    && rm -rf /tmp/audiveris.deb /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app /data
# Second OMR engine (homr) in its own venv, with models pre-downloaded.
RUN python3 -m venv /opt/homr && /opt/homr/bin/pip install --no-cache-dir homr==0.7.0 && /opt/homr/bin/homr --init \
    && chmod -R a+rX /opt/homr
ENV SMT_HOMR_PATH=/opt/homr/bin/homr
# OCR language data so Audiveris can read titles, tempo text and lyrics.
RUN mkdir -p /home/app/.config/AudiverisLtd/audiveris/tessdata \
    && curl -fsSL -o /home/app/.config/AudiverisLtd/audiveris/tessdata/eng.traineddata \
       https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata \
    && chown -R app /home/app/.config
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /src/frontend/dist /app/frontend/dist
USER app
EXPOSE 8000
VOLUME ["/data"]
# One process: background jobs run in-process and share the SQLite database.
CMD ["/venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

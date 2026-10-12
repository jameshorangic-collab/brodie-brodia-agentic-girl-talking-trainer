# syntax=docker/dockerfile:1
# Brodia worker for LiveKit Cloud (lk agent create / lk agent deploy). LiveKit Cloud injects LIVEKIT_URL/API_KEY/API_SECRET;
# GEMINI_API_KEY and the BRODIA_* settings are agent secrets. Local test: podman build -t brodia-worker . && see docs/DEPLOY.md.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy VIRTUAL_ENV=/app/.venv PATH=/app/.venv/bin:$PATH
# PortAudio for sounddevice; libGL/glib for MediaPipe's OpenCV import
RUN apt-get update && apt-get install -y --no-install-recommends libportaudio2 libgl1 libglib2.0-0 curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

FROM base AS build
WORKDIR /app
RUN uv venv /app/.venv
RUN uv pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements-worker.txt .
RUN uv pip install -r requirements-worker.txt
# MediaPipe pose models for --vision-notes and --mirror (the same files scripts/install.sh fetches)
RUN mkdir -p models && for m in lite full heavy; do \
      curl -sSfL -o models/pose_landmarker_$m.task "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_$m/float16/latest/pose_landmarker_$m.task"; \
    done
COPY facetime facetime
COPY src src
COPY starter starter
COPY assets assets

FROM base
ARG UID=10001
RUN adduser --disabled-password --gecos "" --home /app --shell /sbin/nologin --uid "${UID}" appuser
WORKDIR /app
COPY --from=build --chown=appuser:appuser /app /app
USER appuser
# The recommended demo flags from the README. Dispatch name "brodia": the selector and `chert dev --agent brodia` target it.
CMD ["python", "-m", "facetime.worker", "--voice", "gemini", "--agent-name", "brodia", "--perception", "off", "--avatar", "--mirror", "--vision-notes", "start"]

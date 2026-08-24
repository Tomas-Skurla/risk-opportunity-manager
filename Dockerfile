# syntax=docker/dockerfile:1

# Keep the readable tag and pin the multi-platform image index by digest.
# Dependabot updates this direct FROM reference via .github/dependabot.yml.
FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS test

ENV QT_QPA_PLATFORM=offscreen

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        bash \
        libdbus-1-3 \
        libegl1 \
        libfontconfig1 \
        libgl1 \
        libglib2.0-0 \
        libx11-xcb1 \
        libxkbcommon-x11-0 \
        libxcb-cursor0 \
        libxcb-icccm4 \
        libxcb-image0 \
        libxcb-keysyms1 \
        libxcb-randr0 \
        libxcb-render-util0 \
        libxcb-shape0 \
        libxcb-shm0 \
        libxcb-sync1 \
        libxcb-xfixes0 \
        libxcb-xinerama0 \
        libxcb-xkb1 \
        libxcb1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY server/requirements.lock /tmp/server-requirements.lock
COPY client/requirements.lock /tmp/client-requirements.lock
COPY requirements-dev.txt /tmp/requirements-dev.txt

RUN python -m pip install --no-cache-dir \
        --requirement /tmp/server-requirements.lock \
        --requirement /tmp/client-requirements.lock \
        --requirement /tmp/requirements-dev.txt

COPY pyproject.toml alembic.ini ./
COPY server ./server
COPY client ./client
COPY tests ./tests
COPY scripts ./scripts

RUN bash scripts/check_project.sh

FROM base AS server

WORKDIR /app

COPY server/requirements.lock /tmp/server-requirements.lock
RUN python -m pip install --no-cache-dir \
        --requirement /tmp/server-requirements.lock

COPY server ./server

RUN groupadd --gid 1000 riskapp \
    && useradd --create-home --uid 1000 --gid 1000 riskapp \
    && install -d -o riskapp -g riskapp /data

# Only non-sensitive operational defaults are baked into the image.
#
# ENV, ALLOW_INSECURE_DEFAULT_SECRET, INITIAL_SUPERUSER_* and AUTO_CREATE_SCHEMA
# are deliberately NOT set here. ARCHITECTURE.md states that production startup
# rejects default secrets; baking ALLOW_INSECURE_DEFAULT_SECRET=1 into the
# runtime image would disable exactly that check for every consumer of the
# image. The image now fails closed: it will not start without real config.
# Development values live in compose.yaml, which is not what gets deployed.
#
# RISKAPP_HOST=0.0.0.0 is correct *inside* the container -- the process must
# listen on the container's interface. Restricting exposure is the publisher's
# job, which compose.yaml does by binding to 127.0.0.1 on the host.
ENV DATABASE_URL=sqlite+pysqlite:////data/riskapp.db \
    RISKAPP_HOST=0.0.0.0 \
    RISKAPP_PORT=8000 \
    RISKAPP_RELOAD=0

USER riskapp
WORKDIR /app/server

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"]

CMD ["python", "-m", "riskapp_server"]
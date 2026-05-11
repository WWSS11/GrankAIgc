ARG DOCKER_IMAGE_PREFIX=docker.m.daocloud.io/
ARG DOCKER_COMPOSE_VERSION=v2.29.7

FROM ${DOCKER_IMAGE_PREFIX}library/node:20-bookworm-slim AS frontend-builder

WORKDIR /app/package/frontend
COPY package/frontend/package*.json ./
RUN npm ci
COPY package/frontend/ ./
RUN npm run build

FROM ${DOCKER_IMAGE_PREFIX}library/python:3.11-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/package

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git docker.io \
    && mkdir -p /app/config /usr/local/lib/docker/cli-plugins \
    && arch="$(uname -m)" \
    && case "$arch" in \
        x86_64) compose_arch="x86_64" ;; \
        aarch64|arm64) compose_arch="aarch64" ;; \
        *) echo "unsupported architecture for Docker Compose: $arch" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-linux-${compose_arch}" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
    && docker compose version \
    && rm -rf /var/lib/apt/lists/*

COPY package/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY package/ ./
COPY --from=frontend-builder /app/package/frontend/dist ./static

EXPOSE 9800

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:9800/health || exit 1

CMD ["python", "main.py"]

# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS web
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    STATIC_DIR=/app/static \
    PORT=8787 \
    HOME=/home/appuser \
    XDG_CACHE_HOME=/data/cache \
    DENO_DIR=/data/cache/deno

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        gosu \
        tini \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp needs a JavaScript runtime for YouTube. Deno is the one enabled by default.
ARG DENO_VERSION=2.9.8
RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
         amd64) deno_target="x86_64-unknown-linux-gnu" ;; \
         arm64) deno_target="aarch64-unknown-linux-gnu" ;; \
         *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
       esac \
    && curl -fsSL "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-${deno_target}.zip" -o /tmp/deno.zip \
    && unzip -d /usr/local/bin /tmp/deno.zip \
    && chmod 755 /usr/local/bin/deno \
    && rm /tmp/deno.zip \
    && deno --version

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir -U "yt-dlp[default,curl-cffi]"

COPY app /app/app
COPY docker/entrypoint.sh /entrypoint.sh
COPY --from=web /src/dist /app/static

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser \
    && chmod 755 /entrypoint.sh \
    && mkdir -p /data/downloads /data/cookies /data/db /data/cache \
    && chown -R appuser:appuser /data /app

EXPOSE 8787
VOLUME ["/data"]
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
CMD ["sh", "-c", "if [ \"${PROXY_HEADERS:-1}\" = \"1\" ]; then exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8787} --proxy-headers --forwarded-allow-ips='*'; else exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8787}; fi"]

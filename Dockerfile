# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS frontend
WORKDIR /src/frontend
ENV HUSKY=0
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ARG VERSION=1.6.2-fork
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BAZARR_VERSION=${VERSION} \
    BAZARR_CONFIG_DIR=/config \
    BAZARR_REQUIRE_IMDB=ambiguous
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates ffmpeg mediainfo unrar-free unzip tini \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY bazarr.py LICENSE ./
COPY bazarr/ bazarr/
COPY custom_libs/ custom_libs/
COPY libs/ libs/
COPY migrations/ migrations/
COPY tests/test_strict_imdb_standalone.py tests/test_ambiguity_standalone.py tests/scan_ambiguity.py tests/
COPY --from=frontend /src/frontend/build/ frontend/build/
COPY docker/entrypoint.sh /usr/local/bin/bazarr-entrypoint
RUN chmod 755 /usr/local/bin/bazarr-entrypoint \
    && mkdir -p /config /app/bin \
    && chown 1000:1000 /config /app/bin \
    && python tests/test_strict_imdb_standalone.py \
    && python tests/test_ambiguity_standalone.py
USER 1000:1000
EXPOSE 6767
STOPSIGNAL SIGINT
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6767/', timeout=4).read(1)"
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/bazarr-entrypoint"]
CMD ["serve"]

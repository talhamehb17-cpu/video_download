# Lumora API: FastAPI + yt-dlp + FFmpeg in one long-running container.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ENVIRONMENT=production \
    STORAGE_DIR=/var/tmp/lumora-media \
    PORT=8000

# ffmpeg: merging, container fixes and subtitle conversion.
# tini:   a real init process, so finished FFmpeg children are always reaped.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tini \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin lumora \
    && mkdir -p /var/tmp/lumora-media \
    && chown lumora:lumora /var/tmp/lumora-media

WORKDIR /srv/app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
# Every analysis and download starts a fresh worker process. Compiled files make
# that start cheaper, which matters on instances with a fraction of a CPU core.
RUN python -m compileall -q app

USER lumora
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health',timeout=4)"

ENTRYPOINT ["tini", "--"]
# One process on purpose: jobs, their progress and their files belong to the
# process that started them. Scale by adding instances behind sticky routing, or
# move job state to Redis and files to object storage (see README).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --timeout-graceful-shutdown 20"]

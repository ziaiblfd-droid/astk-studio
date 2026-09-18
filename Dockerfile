FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ONLY_BINARY=:all:

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-backend.txt /opt/astk-studio/requirements-backend.txt
RUN python3 -m pip install --prefix=/install --upgrade pip \
    && python3 -m pip install --prefix=/install -r /opt/astk-studio/requirements-backend.txt

FROM python:3.12-slim-bookworm

ENV PATH="/usr/local/bin:$PATH"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ASTK_HOST=0.0.0.0 \
    ASTK_PORT=4173 \
    ASTK_EXECUTION_MODE=command \
    ASTK_RUNNER_COMMAND="/opt/astk-studio/scripts/run-astk-job.sh {job_dir}" \
    ASTK_WORKERS=1 \
    ASTK_MAX_UPLOAD_BYTES=536870912 \
    PYTHONPATH=/opt/astk-studio

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgomp1 \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install/bin /usr/local/bin
COPY --from=builder /install/lib /usr/local/lib

WORKDIR /opt/astk-studio

COPY . /opt/astk-studio
RUN chmod +x /opt/astk-studio/scripts/run-astk-job.sh

EXPOSE 4173
ENTRYPOINT []
CMD ["python3", "backend/server.py"]

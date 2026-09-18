FROM --platform=linux/amd64 huangshing/astk

USER root
WORKDIR /opt/astk-studio

COPY . /opt/astk-studio
RUN chmod +x /opt/astk-studio/scripts/run-astk-job.sh

ENV ASTK_HOST=0.0.0.0 \
    ASTK_PORT=4173 \
    ASTK_EXECUTION_MODE=command \
    ASTK_RUNNER_COMMAND="/opt/astk-studio/scripts/run-astk-job.sh {job_dir}" \
    ASTK_WORKERS=1 \
    ASTK_MAX_UPLOAD_BYTES=536870912 \
    PYTHONPATH=/opt/astk-studio

EXPOSE 4173
ENTRYPOINT []
CMD ["python3", "backend/server.py"]

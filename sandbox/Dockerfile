FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/codeforge
COPY config.py ./
COPY sandbox ./sandbox
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SANDBOX_BACKEND=process PYTHONPATH=/opt/codeforge
USER 65534:65534
ENTRYPOINT ["python", "-B", "-m", "sandbox.container_entry"]

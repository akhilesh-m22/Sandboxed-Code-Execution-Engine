FROM docker:27-cli AS docker-cli
FROM python:3.12-slim AS api
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home codeforge \
    && mkdir /data && chown codeforge:codeforge /data
COPY config.py database.py ./
COPY api ./api
COPY sandbox ./sandbox
COPY worker ./worker
COPY frontend ./frontend
COPY docs ./docs
USER 10001:10001
EXPOSE 5000
CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--threads=8", "--max-request-body-size=8388608", "api.app:app"]

FROM api AS worker
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
CMD ["python", "-m", "worker.pool"]

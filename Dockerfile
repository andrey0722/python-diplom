FROM python:3.14-slim

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        # Healthcheck
        curl \
    ; \
    rm -rf /var/lib/apt/lists/*;

WORKDIR /project
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY manage.py .
COPY project project
COPY api api

ENV UVICORN_HOST=0.0.0.0
ENV UVICORN_PORT=8000

HEALTHCHECK --interval=5s --timeout=5s --retries=5 \
    CMD curl --silent --fail localhost:${UVICORN_PORT}/health-check || exit 1

EXPOSE ${UVICORN_PORT}
CMD ["uvicorn", "project.asgi:application", "--no-access-log"]

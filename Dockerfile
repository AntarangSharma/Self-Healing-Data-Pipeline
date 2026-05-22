# syntax=docker/dockerfile:1.7
# Minimal runtime image for the shdpa agent. Built by docker-compose.
#
# Multi-stage to keep the final image lean: builder has hatchling + dev
# headers, runtime has only what `shdpa serve` needs.

FROM python:3.11-slim AS builder
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[anthropic,openai,serve]"

FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SHDPA_STORAGE_PATH=/data/shdpa.db
RUN useradd --create-home --shell /bin/bash shdpa && \
    mkdir -p /data && chown shdpa:shdpa /data
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
USER shdpa
WORKDIR /home/shdpa
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/healthz').status==200 else 1)"
CMD ["shdpa", "serve", "--host", "0.0.0.0", "--port", "8080"]

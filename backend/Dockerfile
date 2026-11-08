FROM docker:27-cli AS docker-cli

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 factoryos
COPY backend ./backend
COPY fixtures ./fixtures
# The repair verifier runs these independent acceptance tests at runtime.
COPY tests ./tests
COPY hardware ./hardware
RUN mkdir -p /app/artifacts/modernization /app/data \
    && chown -R factoryos:factoryos /app/artifacts /app/data
ENV FACTORYOS_NOTIFICATION_LEDGER=/app/data/notifications.sqlite3
USER factoryos
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

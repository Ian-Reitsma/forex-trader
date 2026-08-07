FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FOREX_PROVIDER=simulation \
    FOREX_MODE=shadow \
    FOREX_DATABASE_PATH=/data/forex_trader.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && addgroup --system forex \
    && adduser --system --ingroup forex --home /app forex \
    && mkdir -p /data \
    && chown -R forex:forex /app /data

USER forex
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" || exit 1
CMD ["forex-trader", "serve", "--host", "0.0.0.0", "--port", "8000"]

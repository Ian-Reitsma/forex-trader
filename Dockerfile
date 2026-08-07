FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FOREX_PROVIDER=simulation \
    FOREX_MODE=shadow \
    FOREX_DATABASE_PATH=/data/forex_trader.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

VOLUME ["/data"]
EXPOSE 8000
CMD ["forex-trader", "serve", "--host", "0.0.0.0", "--port", "8000"]

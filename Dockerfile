FROM python:3.11-slim

WORKDIR /app

# psycopg2 needs libpq; gcc for any C-extension wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: API server. Override `command` in docker-compose for the worker.
# Shell form so $PORT expands — PaaS platforms (Railway, Render, Heroku)
# inject PORT and probe that port; local runs fall back to 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

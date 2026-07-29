FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WRU_DATA_DIR=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

RUN mkdir -p /data/uploads

EXPOSE 8000

CMD ["sh", "-c", "python -c 'from app.migrate import run_migrations; run_migrations()' && python scripts/seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

# syntax=docker/dockerfile:1.6
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    PORT=5001 \
    GCS_BUCKET_NAME="meu-bucket-pi" \
    GCS_BLOB_NAME="VENDAS.xlsx"

RUN apt-get update && apt-get install -y --no-install-recommends \
      libfreetype6 libjpeg62-turbo libpng16-16 libglib2.0-0 tzdata ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . /app

RUN useradd -u 10001 -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5001
CMD ["gunicorn", "-b", "0.0.0.0:5001", "app:app"]

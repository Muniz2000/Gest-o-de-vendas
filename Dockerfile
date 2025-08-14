# syntax=docker/dockerfile:1.6
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    PORT=5001 \
    PLANILHA_PATH=/data/VENDAS.xlsx \
    GOOGLE_APPLICATION_CREDENTIALS=/app/credenciais.json

RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 libjpeg62-turbo libpng16-16 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ⚠️ GERA O ARQUIVO DENTRO DA IMAGEM (INSEGURO)
RUN cat > /app/credenciais.json <<'JSON'
{
  "type": "service_account",
  "project_id": "enhanced-hawk-469011-k5",
  "private_key_id": "505b7cd5d684cbad1331c6ebfad840419b7aed8a",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkq...==\n-----END PRIVATE KEY-----\n",
  "client_email": "atividadefacukl-159@enhanced-hawk-469011-k5.iam.gserviceaccount.com",
  "client_id": "112295919845739078433",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/atividadefacukl-159%40enhanced-hawk-469011-k5.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}
JSON

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app

EXPOSE 5001
CMD ["gunicorn", "-b", "0.0.0.0:5001", "app:app"]

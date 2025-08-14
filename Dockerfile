# Imagem base leve com Python 3.13
FROM python:3.13-slim

# Variáveis de ambiente para evitar criar .pyc, forçar flush de stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Backend sem interface gráfica para o Matplotlib
    MPLBACKEND=Agg \
    # Porta padrão do seu app (você usa 5001)
    PORT=5001 \
    # Caminho default da planilha dentro do container (ajuste se quiser)
    PLANILHA_PATH=/data/VENDAS.xlsx

# Instala libs de sistema necessárias em runtime para matplotlib/pillow
# (sem toolchain de build para manter a imagem pequena)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 \
    libjpeg62-turbo \
    libpng16-16 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Cria diretório de trabalho
WORKDIR /app

# Copia e instala dependências
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do projeto
COPY . /app

# Se seu app Flask é exposto como "app = Flask(__name__)" dentro de app.py,
# o entrypoint via gunicorn fica app:app
EXPOSE 5001

# Comando de execução (produção) com gunicorn
# -b 0.0.0.0:$PORT para escutar em todas as interfaces dentro do container
CMD ["gunicorn", "-b", "0.0.0.0:5001", "app:app"]

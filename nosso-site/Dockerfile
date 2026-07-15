FROM python:3.12-slim

WORKDIR /app

# Dependências primeiro (melhor cache de build)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código do site
COPY . .

# Caminho do banco no disco persistente (montado em /data no Render)
ENV DB_PATH=/data/pedidos.db

# O Render injeta $PORT; localmente cai para 8000
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]

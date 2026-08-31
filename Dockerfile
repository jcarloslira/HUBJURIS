FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# O WeasyPrint (que renderiza o HTML das peças em PDF) depende de libs de sistema.
# As fontes são as mesmas dos relatórios já aprovados pelo escritório: DejaVu Serif
# no corpo, Nimbus Sans nos rótulos e Liberation como reserva.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libgdk-pixbuf-2.0-0 \
        fonts-dejavu-core \
        fonts-urw-base35 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app/ app/

EXPOSE 8000

# Forma shell para expandir ${PORT} injetado pelo Render (8000 como padrão local).
CMD uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

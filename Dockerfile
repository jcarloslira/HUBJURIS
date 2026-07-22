FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app/ app/

EXPOSE 8000

# Forma shell para expandir ${PORT} injetado pelo Render (8000 como padrão local).
CMD uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

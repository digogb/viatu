# Stage 1: build do frontend React
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: imagem final Python + Playwright
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml alembic.ini ./
RUN uv sync --no-dev

COPY app/ ./app/
COPY alembic/ ./alembic/

# Copia build estático do frontend
COPY --from=frontend-builder /frontend/dist ./frontend/dist

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
COPY --from=frontend /frontend/dist ./frontend/dist
RUN uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH"

# build-time only: collectstatic needs settings to import, not a database
RUN DJANGO_SECRET_KEY=build-only-not-a-secret python manage.py collectstatic --noinput

RUN useradd --create-home app && mkdir -p /home/app/.cache/huggingface && chown -R app /app /home/app
USER app

CMD ["gunicorn", "-c", "gunicorn.conf.py", "config.wsgi:application"]

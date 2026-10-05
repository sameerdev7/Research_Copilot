.PHONY: dev test lint build e2e

# Django on :8000 and the Vite dev server on :5173 (run the Celery worker separately)
dev:
	uv run python manage.py runserver & npm --prefix frontend run dev

test:
	uv run pytest -q
	npm --prefix frontend test

lint:
	uv run ruff check .
	npm --prefix frontend run lint
	npm --prefix frontend run typecheck

build:
	npm --prefix frontend run build

# browser smoke test in demo mode (no API tokens)
e2e:
	./scripts/e2e.sh

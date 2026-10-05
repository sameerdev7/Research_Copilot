#!/usr/bin/env bash
# Browser smoke test in demo mode: scratch database, no API keys, no tokens.
set -euo pipefail
cd "$(dirname "$0")/.."

DB=research_copilot_e2e
drop_db() { docker compose exec -T postgres psql -U research_copilot -d postgres -c "DROP DATABASE IF EXISTS $DB" >/dev/null; }
trap drop_db EXIT
docker compose up -d postgres
until docker compose exec -T postgres pg_isready -U research_copilot >/dev/null 2>&1; do sleep 1; done
docker compose exec -T postgres psql -U research_copilot -d postgres -c "DROP DATABASE IF EXISTS $DB" -c "CREATE DATABASE $DB"

export POSTGRES_DB=$DB LLM_PROVIDER=demo DJANGO_DEBUG=true GEMINI_API_KEY= GROQ_API_KEY=
uv run python manage.py migrate --noinput
uv run python manage.py seed_demo

cd frontend
npm run build
npx playwright test

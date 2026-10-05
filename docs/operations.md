# Operations

## Deploying

Assumes one host running `docker compose` behind a TLS-terminating reverse proxy (Caddy or nginx).

1. Copy `.env.example` to `.env` and set at least:
   - `DJANGO_SECRET_KEY` (generate one; the app refuses to start in production with the placeholder)
   - `DJANGO_DEBUG=false`
   - `DJANGO_ALLOWED_HOSTS=your.domain`
   - `DJANGO_CSRF_TRUSTED_ORIGINS=https://your.domain`
   - `POSTGRES_PASSWORD` (compose refuses to start without it)
   - `GEMINI_API_KEY` and/or `GROQ_API_KEY`
2. `docker compose up -d --build`. A one-shot `migrate` service runs first; `web` and `worker` wait for it.
3. Point the proxy at `127.0.0.1:8000` and have it send `X-Forwarded-Proto: https`. Postgres, Redis and the app only listen on `127.0.0.1`.
4. Create an admin if you want `/admin/`: `docker compose exec web python manage.py createsuperuser`.

`GET /healthz` is the unauthenticated liveness check (process up, database answers). The detailed `/api/health/` needs a login and powers the Diagnostics panel.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | placeholder | Required when `DJANGO_DEBUG=false` |
| `DJANGO_DEBUG` | `false` | `true` for local dev only |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | Comma-separated `https://` origins |
| `DJANGO_SSL_REDIRECT` | `true` | Redirect HTTP to HTTPS (when not debug) |
| `ALLOW_REGISTRATION` | `true` | `false` closes public sign-up |
| `POSTGRES_*` | see `.env.example` | Database connection |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` | Task queue |
| `LLM_PROVIDER` | `auto` | `demo` = offline canned answers |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | empty, `gemini-3.8-flash` | Primary provider |
| `GROQ_API_KEY`, `GROQ_MODEL` | empty, `openai/gpt-oss-120b` | Fallback provider |
| `DAILY_QUESTION_QUOTA` | `50` | Questions per user per day |
| `WEB_CONCURRENCY`, `WEB_THREADS` | `2`, `8` | Gunicorn processes and threads |
| `SENTRY_DSN` | empty | Enables error tracking |

Rate limits are `10/min` for login and sign-up per IP, `20/min` for questions and for arXiv searches per user. They are counted per web process.

## Backup and restore

The database holds everything (users, papers, chunks and embeddings, chats).

```bash
docker compose exec -T postgres pg_dump -U research_copilot -Fc research_copilot > backup.dump
```
```bash
docker compose exec -T postgres pg_restore -U research_copilot -d research_copilot --clean --if-exists < backup.dump
```

Run the dump on a schedule (cron) and copy it off the host. The `huggingface_cache` volume only caches the embedding model and can be rebuilt.

## Runbook: error codes

Every failure shows a code and a reference id. Search the server log for the reference id (logs are JSON in production and include `request_id`).

| Code | Meaning | Fix |
|---|---|---|
| `llm_not_configured` | No API key set | Set `GEMINI_API_KEY` or `GROQ_API_KEY`, restart |
| `llm_rate_limited` | Both providers are rate-limited | Wait, or add the second provider's key |
| `llm_auth_failed` | A key was rejected | Check the keys in `.env` |
| `llm_model_unavailable` | Model name retired | Update `GEMINI_MODEL` / `GROQ_MODEL` |
| `llm_network_error` | Providers unreachable | Check outbound network |
| `database_error` | Postgres not answering | `docker compose ps`, check the postgres logs |
| `embedding_failed` | Embedding model unavailable | First run needs internet to download it |
| `papers_processing` | Papers still ingesting | Check the Worker line in Diagnostics |
| `no_papers` | Workspace has no papers | Add papers on the Papers tab |
| `quota_exceeded` | Daily limit reached | Resets next day, or raise `DAILY_QUESTION_QUOTA` |
| `arxiv_unavailable` | arXiv down or rate-limiting | Retry shortly |
| `throttled` | Too many requests | Wait the stated number of seconds |
| `internal_error` | Unexpected bug | Find the reference id in the log; it has the traceback |

Papers stuck in "Processing" are failed automatically after 30 minutes (the worker runs a sweep every 10 minutes); use the retry button on the paper afterwards. Provider failures and internal errors do not count against a user's daily quota.

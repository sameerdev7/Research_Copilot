# Research Copilot

A multi-agent research assistant: give it a topic or arXiv ID, it ingests the papers,
and it answers questions about them with inline citations — rejecting its own draft
and retrying when a claim isn't backed by a retrieved chunk.

Django is the plumbing (auth, async jobs, admin, persistence) behind a JSON API; a React
app is the UI. LangGraph drives the rewrite → retrieval → synthesis → critique loop;
LangChain handles chunking. Full design
rationale, the data model, and two real bugs that only showed up in the browser: see
[`docs/architecture.md`](docs/architecture.md). Test strategy and how to run the
suite: [`docs/testing.md`](docs/testing.md).

## Stack

Django + DRF · LangGraph · LangChain · Postgres + pgvector · Celery + Redis ·
sentence-transformers (local embeddings) · Groq / Gemini (free-tier LLMs) · React + Vite

## Quickstart

```bash
cp .env.example .env          # fill in GROQ_API_KEY or GEMINI_API_KEY to use chat
docker compose up -d postgres redis
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

Build the frontend once (Django serves it from `frontend/dist`), or run the Vite dev
server for hot reload:

```bash
cd frontend && npm install
npm run build        # then open http://localhost:8000
npm run dev          # or: http://localhost:5173, proxies /api to Django
```

Create an account from the sign-in page (or `createsuperuser` for `/admin/`).

In a second terminal, start the Celery worker (paper ingestion runs here):

```bash
uv run celery -A config worker --loglevel=info
```

Or run the whole stack, including the app and worker, in containers:

```bash
docker compose up --build
```

## Using it

1. Sign in, create a workspace.
2. Under **Papers**, search a topic (e.g. "retrieval augmented generation") or paste
   an arXiv ID, check the papers you want, and ingest them. Status polls from
   `pending` → `ready` as the Celery worker downloads, chunks, and embeds each PDF.
3. Under **Chat**, ask a question. A live progress indicator shows each stage (search,
   draft, fact-check). The answer comes back with clickable citations to the exact
   passage each claim is based on; if a claim couldn't be verified after a few
   revision attempts, that's surfaced as a visible warning rather than presented as fact.
4. Follow-ups remember the conversation, and every chat is kept in the sidebar.
5. If something breaks, the error says what and how to fix it, and the **Diagnostics**
   button in the sidebar checks Postgres, Redis, the Celery worker, the embedding model
   and your API keys.

Example, after ingesting *Attention Is All You Need* (arXiv `1706.03762`):

> **Q: What does the Transformer use instead of recurrence?**
>
> The Transformer relies entirely on a self-attention mechanism to compute
> representations of its input and output. [1]
>
> *Sources: [1] Attention Is All You Need*

Everything runs at $0: embeddings are local, and both configured LLM providers have
free tiers.

## Production

See [`docs/operations.md`](docs/operations.md): environment variables, deploying behind a TLS proxy,
backups, and a runbook that maps every error code to its fix.

## Tests

```bash
uv run pytest -q
npm --prefix frontend test
make e2e        # browser smoke test in demo mode, uses no tokens
```

100 backend tests plus 8 frontend tests, no live API keys needed — see [`docs/testing.md`](docs/testing.md) for what's
covered and why.

To try the UI without spending any LLM tokens, start Django with `LLM_PROVIDER=demo`:
answers are then canned from the top retrieved passage (see
[`docs/testing.md`](docs/testing.md)).

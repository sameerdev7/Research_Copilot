# Research Copilot

A multi-agent research assistant: give it a topic or arXiv ID, it ingests the papers,
and it answers questions about them with inline citations — rejecting its own draft
and retrying when a claim isn't backed by a retrieved chunk.

Django is the plumbing (auth, async jobs, admin, persistence). LangGraph drives the
retrieval → synthesis → critique loop; LangChain handles chunking. Full design
rationale, the data model, and two real bugs that only showed up in the browser: see
[`docs/architecture.md`](docs/architecture.md). Test strategy and how to run the
suite: [`docs/testing.md`](docs/testing.md).

## Stack

Django + DRF · LangGraph · LangChain · Postgres + pgvector · Celery + Redis ·
sentence-transformers (local embeddings) · Groq / Gemini (free-tier LLMs) · HTMX

## Quickstart

```bash
cp .env.example .env          # fill in GROQ_API_KEY or GEMINI_API_KEY to use chat
docker compose up -d postgres redis
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

In a second terminal, start the Celery worker (paper ingestion runs here):

```bash
uv run celery -A config worker --loglevel=info
```

Or run the whole stack, including the app and worker, in containers:

```bash
docker compose up --build
```

## Using it

1. Log in, create a workspace.
2. Under **Papers**, search a topic (e.g. "retrieval augmented generation") or paste
   an arXiv ID, check the papers you want, and ingest them. Status polls from
   `pending` → `ready` as the Celery worker downloads, chunks, and embeds each PDF.
3. Under **Chat**, ask a question. The answer comes back with citations to the
   specific paper/chunk each claim is based on; if a claim couldn't be verified
   against any retrieved chunk after a few revision attempts, that's surfaced as a
   visible warning rather than presented as fact.

Example, after ingesting *Attention Is All You Need* (arXiv `1706.03762`):

> **Q: What does the Transformer use instead of recurrence?**
>
> The Transformer relies entirely on a self-attention mechanism to compute
> representations of its input and output. [1]
>
> *Sources: paper 1 / chunk 19*

Everything runs at $0: embeddings are local, and both configured LLM providers have
free tiers.

## Tests

```bash
uv run pytest -q
```

20 tests, no live API keys needed — see [`docs/testing.md`](docs/testing.md) for what's
covered and why.

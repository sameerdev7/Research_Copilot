# Architecture

Research Copilot is a research assistant: give it a topic or arXiv ID, it ingests the
papers, and it answers questions about them with inline citations to the actual
retrieved text — rejecting its own answer and retrying when a claim isn't backed by a
retrieved chunk.

Django is the plumbing (auth, persistence, async jobs, admin). It is not the product.
The product is the ingestion pipeline and the self-correcting RAG loop described below.

## System diagram

```
                    ┌─────────────────────────────────────────────┐
                    │                  Django (web)                │
                    │                                               │
  user ──React SPA──▶  JSON API (api/): auth, papers, chat          │
                    │        │              │                       │
                    │        │              ▼                       │
                    │        │      agent.query_graph.run_query()   │
                    │        │      (retrieve → synthesize → ◀┐     │
                    │        │       critique, LangGraph)     │loop │
                    │        │              │  ▲──────────────┘     │
                    │        ▼              ▼                       │
                    │   Paper / Chunk    agent.llm (Gemini / Groq)  │
                    └────────┼─────────────────────────────────────┘
                             │ Paper(status=pending) created
                             ▼
                    ┌─────────────────────┐
                    │   Celery (worker)    │
                    │  tasks.ingest_paper  │
                    │  fetch → parse →     │
                    │  chunk → embed       │
                    └──────────┬────────────┘
                               │
                 ┌─────────────┼──────────────┐
                 ▼             ▼              ▼
           arXiv API     sentence-      Postgres + pgvector
           (search,      transformers   (Paper, Chunk.embedding,
            PDF fetch)   (local, free)   Conversation, Message, …)
                               ▲
                               │ broker/result backend
                             Redis
```

Two independent paths share the same database:

- **Ingestion** (async, via Celery): search arXiv → download a PDF → extract text →
  split into chunks → embed locally → store. Runs once per paper.
- **Query** (sync, streamed to the browser as it progresses): rewrite a follow-up into a
  standalone query → hybrid retrieval (pgvector + full-text, fused) → LLM drafts an
  answer → LLM-judge critique → loop or return. Runs once per chat message.

They are deliberately *not* modeled as one LangGraph graph — ingestion is a linear
Celery pipeline with no need for cycles or an LLM in the loop, while the query path is
a real state machine with a conditional retry edge. Forcing both into one graph would
buy nothing and would make the interesting part (the critique cycle) harder to read.

## The self-correcting RAG loop

This is the one part of the project that's a genuine LangGraph cycle rather than a
linear chain, and the concrete answer to "how do you stop this thing from
hallucinating": [`agent/query_graph.py`](../agent/query_graph.py).

```
 rewrite_node ──▶ retrieve_node ──▶ synthesize_node ──▶ critique_node ──▶ finished? ──▶ done
                                          ▲                                  │
                                          └──────────────── no, retry ────────┘
                                             (critique_notes appended to the
                                              next synthesize prompt)
```

**`rewrite_node`** — conversation memory for retrieval. A follow-up like "how does it
scale?" is meaningless to a vector search on its own, so when the conversation has prior
turns one cheap LLM call rewrites it into a standalone query ("how does the Transformer
scale with sequence length?"). No history means no call. If the rewrite fails or comes
back unusable, retrieval falls back to the raw question rather than failing the turn.

**`retrieve_node`** — hybrid search in [`agent/retrieval.py`](../agent/retrieval.py),
scoped to the workspace and to papers with `status="ready"`. Two retrievers each return
their top `RAG_CANDIDATES` (24): pgvector cosine distance on the locally computed
embedding (`sentence-transformers/all-MiniLM-L6-v2`, 384-dim), and Postgres full-text
search (`to_tsvector('english', text)` with the question's words OR-ed together, served
by a GIN index). Vector search finds paraphrases but misses exact terms like model
names and acronyms; keyword search is the opposite. Their rankings are merged with
reciprocal rank fusion (`1/(60+rank)` per list), then capped at
`RAG_MAX_CHUNKS_PER_PAPER` (3) so one paper can't crowd out the rest, and cut to
`RAG_RETRIEVAL_K` (8). If nothing is retrieved the graph ends there with a plain "couldn't
find anything" answer and no LLM call.

**`synthesize_node`** — prompts the LLM (`agent/prompts.py`) with the question and the
numbered retrieved chunks, and requires one claim per line, each ending in a `[N]` tag
naming the chunk it's based on. The response is parsed line-by-line
(`CITATION_LINE_RE`, which captures a whole trailing `[1][3]` cluster) into `draft_answer` plus a `Citation` list — one entry per line
whose `[N]` actually falls inside the retrieved set, mapped to that chunk's real
`paper_id`/`chunk_id`. On a retry, the prior `critique_notes` are appended to the
prompt as concrete revision instructions. Earlier turns of the conversation are included
as context for what the question refers to, but every claim must still cite a chunk.

**`critique_node`** — checks every line of the draft:
- a line citing a chunk number outside the retrieved set is flagged directly, no LLM
  call needed (`Line N cites chunk [M], which was not retrieved`);
- lines that do cite a real chunk are sent to the LLM as a second, cheap "fact-check"
  call (`build_critique_messages`), which returns which line numbers aren't actually
  supported by their cited chunk (`UNSUPPORTED: 2,4` or `UNSUPPORTED: none`).

If there are unsupported lines and `retries < max_retries` (default 3, `RAG_MAX_RETRIES`),
the graph routes back to `synthesize_node` with those notes. Otherwise it terminates
with `finished=True` — either because the answer is clean, or because retries were
exhausted and the answer is returned *with* its `critique_notes` still attached, so the
caller can label it as imperfect rather than silently presenting it as fact. The chat
UI renders any leftover `critique_notes` as a visible warning under the answer
(`frontend/src/components/AnswerMessage.tsx`).

## State shape

`agent/state.py`:

```python
class Citation(TypedDict):
    paper_id: int
    chunk_id: int
    quoted_text: str

class QueryState(TypedDict):
    workspace_id: int
    question: str
    history: list[Turn]        # earlier question/answer pairs, oldest first
    search_query: str          # the standalone rewrite actually used for retrieval
    retrieved_chunks: list[RetrievedChunk]
    draft_answer: str | None
    citations: list[Citation]
    critique_notes: list[str]
    retries: int
    max_retries: int
    finished: bool
    timings: dict[str, float]  # seconds per node, for diagnosis
```

## LLM adapters

`agent/llm/` is a small provider-agnostic layer, reused from the same pattern as the
author's separate Coding Agent project (a `LLMClient` Protocol + concrete clients),
adapted here for plain chat completion instead of tool-calling:

- `LLMClient` (`base.py`) — `complete(messages: list[dict]) -> str`.
- `GeminiClient` — primary, `gemini-3.8-flash`, via the current `google-genai` SDK
  (not the deprecated `google-generativeai`), with retry/backoff on rate limits.
- `GroqClient` — fallback, `openai/gpt-oss-120b`, generous free tier, also with
  retry/backoff on rate limits (its free-tier tokens-per-minute cap is easy to hit
  when a question pulls in several large retrieved chunks across two LLM calls per
  turn — synthesize + critique).
- `FakeLLMClient` — returns pre-scripted responses in order; used by the whole
  `agent/tests/test_query_graph.py` suite so the critique/retry cycle is tested with
  zero API calls and zero cost.
- `FallbackLLMClient` — wraps an ordered list of clients; tries each in turn and falls
  through to the next on *any* failure (bad key, rate limit, outage), raising the last
  error only if every client fails. Covered by `agent/tests/test_fallback_client.py`.
- `DemoLLMClient` — offline stand-in selected with `LLM_PROVIDER=demo`; echoes the top
  retrieved passage with a citation. For exercising the UI and the graph end to end
  without keys or tokens (the diagnostics panel flags demo mode).
- `errors.py` — `LLMNotConfigured` (no keys) and `LLMUnavailable`, which carries every
  provider's error so the failure can be diagnosed instead of reporting only the last one.
- `factory.get_default_client()` — builds `[GeminiClient, GroqClient]` from whichever
  of `GEMINI_API_KEY`/`GROQ_API_KEY` are set (Gemini first) and wraps them in a
  `FallbackLLMClient`, so a Gemini outage or rate limit transparently falls through to
  Groq mid-request rather than failing the turn. If neither key is set, raises
  `LLMNotConfigured`; if every provider fails, `LLMUnavailable`. Both are turned into a
  diagnosed chat message by [`api/chat.py`](../api/chat.py) — see
  [Diagnostics](#diagnostics).

## Ingestion pipeline (Celery)

`papers/tasks.py::ingest_paper`, one task per paper:

1. `papers/services/arxiv_client.py` — keyless wrapper around arXiv's Atom API
   (`export.arxiv.org/api/query`), used synchronously in the search view (fast enough
   not to need Celery) and again inside the ingest task to re-fetch metadata by ID
   (see [Data correctness notes](#data-correctness-notes) below for why it re-fetches
   rather than trusting the browser's form submission).
2. `papers/services/pdf_extract.py` — downloads the PDF, extracts text with `pypdf`,
   and strips any NUL bytes from the result (garbled PDF extraction can produce them,
   and PostgreSQL's `text` columns reject them outright — see
   [Data correctness notes](#data-correctness-notes)).
3. `langchain_text_splitters.RecursiveCharacterTextSplitter` (`chunk_size=800`,
   `chunk_overlap=120`, ~180 tokens, under the embedding model's 256-token window) — the one direct LangChain usage in the project.
4. `agent/embeddings.py::embed_texts` — batch-embeds all chunks locally, no API call.
5. Old `Chunk` rows for the paper are cleared and the new ones `bulk_create`d, then
   `Paper.status` flips to `ready` (or `failed`, with `failure_reason` set, on any
   exception — verified by ingesting a paper with no extractable text).

## Data model

```
Workspace(user, name)
  └─ Paper(workspace, arxiv_id, title, authors[], abstract, pdf_url, status)
       ├─ Chunk(paper, chunk_index, text, token_count, embedding vector(384))
       └─ IngestionJob(paper, status, error_message, started_at, finished_at)
  └─ Conversation(workspace, title, updated_at)
       └─ Message(conversation, role, content, citations[], critique_notes[],
                  sources[], diagnostics{})
UsageRecord(user, date, requests_made, tokens_used)   # one row per user per day
```

`Message.sources` snapshots every chunk retrieved for an answer (with its paper title
and arXiv id) so `[N]` tags stay resolvable after the paper is re-ingested or removed;
`Message.diagnostics` holds the rewritten query, retry count, per-stage timings and
request id — or, for a failed turn, the structured `error`.

`Chunk.embedding` is a `pgvector.django.VectorField(dimensions=384)` with an
`HnswIndex` (`vector_cosine_ops`) so the similarity search stays fast as
the corpus grows. The `vector` extension is enabled by a `VectorExtension()` migration
operation (`papers/migrations/0001_initial.py`), and a `GinIndex` on
`to_tsvector('english', text)` serves the keyword half of hybrid search, so a fresh `migrate` sets it up —
no manual `CREATE EXTENSION` step needed.

## Multi-tenancy and cost control

- Every `Paper`, `Conversation`, and `Chunk` (transitively, via `Paper`) is scoped to a
  `Workspace`, which is scoped to a `user`. Every API view resolves the workspace (or
  conversation) through `owned_workspace()` and returns `404` — not `403`, so ids can't
  be probed — if it belongs to someone else
  (`api/tests/test_auth_and_workspaces.py::test_other_users_workspace_is_404`).
- `usage/quotas.py::check_and_increment` enforces a per-user daily cap
  (`DAILY_QUESTION_QUOTA`, default 50) on questions asked, using
  `select_for_update()` so concurrent requests can't race past the limit. Going over
  quota degrades to a diagnosed chat message rather than an error page, same pattern
  as an LLM failure. Refusals that cost nothing (no papers yet) don't use up quota.
- Embeddings are local and free (`sentence-transformers`); the only metered calls are
  the LLM calls per question (synthesize + critique, plus a rewrite on follow-ups), and only on the free tiers
  of Gemini/Groq by default.

## Data correctness notes

Two bugs were caught only by driving the real UI in a browser — not by the unit test
suite — and are worth calling out because they're the kind of thing that's easy to
miss in code review:

1. **Metadata mismatch on ingest.** The paper-ingest form originally paired each
   *checked* `arxiv_id` checkbox with the *first* candidate's hidden
   `title`/`authors`/`abstract`/`pdf_url` fields by list position
   (`zip(getlist("arxiv_id"), getlist("title"), ...)`). HTML only submits *checked*
   checkboxes but submits *all* sibling hidden inputs regardless — so checking the
   5th candidate silently ingested it under the 1st candidate's title and abstract.
   Fixed by having the view re-fetch metadata from arXiv by the selected IDs
   (`api/papers.py::paper_ingest`, which now takes a plain list of IDs) instead of trusting the paired form fields —
   which also means a tampered hidden field can't be used to attach the wrong
   abstract to a paper. Covered by
   `api/tests/test_papers.py::test_ingest_stores_refetched_metadata_and_enqueues`.
2. **NUL bytes from PDF extraction.** A real paper's PDF extracted to text containing
   a `\x00` byte, which `psycopg`/PostgreSQL reject on insert
   (`DataError: PostgreSQL text fields cannot contain NUL (0x00) bytes`), crashing the
   whole ingestion task. Fixed in `pdf_extract.extract_text` by stripping NUL bytes
   before the text is chunked and stored. Covered by
   `papers/tests/test_pdf_extract.py::test_extract_text_strips_nul_bytes`.

A third bug — the chat view's `messages` context variable colliding with Django's
flash-messages context processor — disappeared along with the server-rendered templates
when the frontend moved to React.

## Memory

Conversations are first-class and persisted: a workspace has many `Conversation`s, each
with its own `Message` history, listed in the sidebar (most recently active first,
renameable, deletable; the first question becomes the title). Each new question is
answered with the last `RAG_HISTORY_MESSAGES` (6) *successfully answered* turns as
context — `[N]` tags are stripped from earlier answers (they index a different chunk
list), and failed turns are skipped. The history feeds both `rewrite_node` and the
synthesize prompt.

## API and streaming

The UI is a React + TypeScript single-page app in [`frontend/`](../frontend), talking to a
JSON API in [`api/`](../api) built with DRF function views and session auth (CSRF token
echoed from a cookie). Errors from every endpoint share one shape,
`{"error": {"code", "message", "hint", "request_id"}}`, via a custom DRF exception handler.

`POST /api/conversations/<id>/messages/` streams newline-delimited JSON instead of
returning one response, so the UI can show real progress: `user` (the saved question),
`stage` (`rewrite` / `retrieve` / `synthesize` / `critique`, with the attempt number when
the critique loop retries), then a final `message` — the answer or, on failure, a stored
error message. `agent.query_graph.stream_query` drives this by iterating the compiled
graph with `stream_mode="updates"`. If the client disconnects mid-answer, the turn is
recorded as `interrupted` rather than leaving a question with no reply.

## Diagnostics

Failures should say what broke and how to fix it, not "something went wrong":

- [`api/diagnostics.py`](../api/diagnostics.py) classifies exceptions — with the graph
  stage that was running — into codes such as `llm_not_configured`, `llm_rate_limited`,
  `llm_auth_failed`, `llm_model_unavailable`, `database_error`, `embedding_failed`,
  `quota_exceeded`, `no_papers`, `papers_processing`, each with a hint ("Check
  GEMINI_MODEL — the model may have been retired"). Every failure gets a short request
  id, logged server-side with the traceback, so a screenshot of the error is enough to
  find it. Raw exception text is only sent to the browser when `DEBUG` is on.
- Failed turns are stored on the message (`diagnostics.error`), so they survive a reload,
  and are excluded from conversation history.
- `GET /api/health/` ([`api/health.py`](../api/health.py)) checks Postgres + pgvector,
  Redis, whether a Celery worker answers a ping, the embedding model, and which LLM
  providers have keys — without calling any provider. The sidebar shows its status and
  opens a panel with a fix for each failing check.
- Ingestion failures are visible too: a broker outage marks the paper `failed` with the
  reason instead of leaving it `pending` forever, and failed papers can be retried.

## UI

Vite + React 18 + TypeScript, plain CSS, `react-router` for routing, `lucide-react` for
icons. `frontend/src/api.ts` is the only place that talks HTTP (CSRF, error
normalisation, the stream reader); pages are `ChatPage` and `PapersPage` inside a `Shell`
that owns the sidebar and the data both pages share. While an answer generates, the
`Thinking` component renders the server's stage events live. Answers render one claim
per line with clickable `[N]` chips that expand the exact source passage, plus a
verified / "couldn't be verified" badge driven by `critique_notes`.

Django admin is wired up for `Paper`, `Chunk` (read-only — it has a lot of rows),
`Workspace`, `Conversation`/`Message`, and `UsageRecord` and serves as the ops
dashboard; nothing custom was built on top of it.

## Deployment

Production settings, rate limits, health checks and the runbook are in
[`operations.md`](operations.md).

The `Dockerfile` builds the frontend in a Node stage and copies `frontend/dist` into the
Python image; Django serves `index.html` for any non-API path and WhiteNoise serves the
hashed assets under `/static/`. In development, run `npm run dev` in `frontend/`
(port 5173, proxies `/api` to Django on 8000) instead.

`docker-compose.yml` defines four services: `postgres` (`pgvector/pgvector:pg16`),
`redis`, `web` (`gunicorn`, runs migrations + `collectstatic` on start), and `worker`
(`celery -A config worker`). `web` and `worker` share a `huggingface_cache` volume so
the embedding model is downloaded once, not once per container. Host ports for
`postgres`/`redis` are overridable via `POSTGRES_PORT`/`REDIS_HOST_PORT` in `.env` to
avoid clashing with services already running on the host.

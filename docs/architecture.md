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
  user ──HTTP/HTMX──▶  workspaces / papers / chat views             │
                    │        │              │                       │
                    │        │              ▼                       │
                    │        │      agent.query_graph.run_query()   │
                    │        │      (retrieve → synthesize → ◀┐     │
                    │        │       critique, LangGraph)     │loop │
                    │        │              │  ▲──────────────┘     │
                    │        ▼              ▼                       │
                    │   Paper / Chunk    agent.llm (Groq / Gemini)  │
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
- **Query** (sync, in the request/response cycle): embed the question → pgvector
  similarity search → LLM drafts an answer → LLM-judge critique → loop or return. Runs
  once per chat message.

They are deliberately *not* modeled as one LangGraph graph — ingestion is a linear
Celery pipeline with no need for cycles or an LLM in the loop, while the query path is
a real state machine with a conditional retry edge. Forcing both into one graph would
buy nothing and would make the interesting part (the critique cycle) harder to read.

## The self-correcting RAG loop

This is the one part of the project that's a genuine LangGraph cycle rather than a
linear chain, and the concrete answer to "how do you stop this thing from
hallucinating": [`agent/query_graph.py`](../agent/query_graph.py).

```
 retrieve_node ──▶ synthesize_node ──▶ critique_node ──▶ finished? ──▶ done
                          ▲                                  │
                          └──────────────── no, retry ────────┘
                             (critique_notes appended to the
                              next synthesize prompt)
```

**`retrieve_node`** — embeds the question locally (`agent/embeddings.py`,
`sentence-transformers/all-MiniLM-L6-v2`, 384-dim, normalized), then does a pgvector
cosine-distance search (`CosineDistance` from `pgvector.django`) over `Chunk` rows
scoped to the workspace and to papers with `status="ready"`, top-`k` (`RAG_RETRIEVAL_K`,
default 8).

**`synthesize_node`** — prompts the LLM (`agent/prompts.py`) with the question and the
numbered retrieved chunks, and requires one claim per line, each ending in a `[N]` tag
naming the chunk it's based on. The response is parsed line-by-line
(`CITATION_LINE_RE`) into `draft_answer` plus a `Citation` list — one entry per line
whose `[N]` actually falls inside the retrieved set, mapped to that chunk's real
`paper_id`/`chunk_id`. On a retry, the prior `critique_notes` are appended to the
prompt as concrete revision instructions.

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
(`templates/chat/_messages.html`).

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
    retrieved_chunks: list[RetrievedChunk]
    draft_answer: str | None
    citations: list[Citation]
    critique_notes: list[str]
    retries: int
    max_retries: int
    finished: bool
```

## LLM adapters

`agent/llm/` is a small provider-agnostic layer, reused from the same pattern as the
author's separate Coding Agent project (a `LLMClient` Protocol + concrete clients),
adapted here for plain chat completion instead of tool-calling:

- `LLMClient` (`base.py`) — `complete(messages: list[dict]) -> str`.
- `GroqClient` — default, `llama-3.3-70b-versatile`, generous free tier.
- `GeminiClient` — fallback, `gemini-2.0-flash`, via the current `google-genai` SDK
  (not the deprecated `google-generativeai`), with retry/backoff on rate limits.
- `FakeLLMClient` — returns pre-scripted responses in order; used by the whole
  `agent/tests/test_query_graph.py` suite so the critique/retry cycle is tested with
  zero API calls and zero cost.
- `factory.get_default_client()` — Groq if `GROQ_API_KEY` is set, else Gemini if
  `GEMINI_API_KEY` is set, else raises. `chat/views.py` treats that (and any other LLM
  failure — bad key, rate limit, network error) as an external-boundary failure: it's
  caught, logged, and degraded to a chat message instead of a 500. See
  [`chat/views.py`](../chat/views.py).

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
3. `langchain_text_splitters.RecursiveCharacterTextSplitter` (`chunk_size=500`,
   `chunk_overlap=50`) — the one direct LangChain usage in the project.
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
  └─ Conversation(workspace)
       └─ Message(conversation, role, content, citations[], critique_notes[])
UsageRecord(user, date, requests_made, tokens_used)   # one row per user per day
```

`Chunk.embedding` is a `pgvector.django.VectorField(dimensions=384)` with an
`HnswIndex` (`vector_cosine_ops`) so `retrieve_node`'s similarity search stays fast as
the corpus grows. The `vector` extension is enabled by a `VectorExtension()` migration
operation (`papers/migrations/0001_initial.py`), so a fresh `migrate` sets it up —
no manual `CREATE EXTENSION` step needed.

## Multi-tenancy and cost control

- Every `Paper`, `Conversation`, and `Chunk` (transitively, via `Paper`) is scoped to a
  `Workspace`, which is scoped to a `user`. Every view resolves the workspace through
  `_get_owned_workspace()` and returns `403` if it belongs to someone else
  (`workspaces/tests/test_views.py::test_cannot_view_another_users_workspace`).
- `usage/quotas.py::check_and_increment` enforces a per-user daily cap
  (`DAILY_QUESTION_QUOTA`, default 50) on questions asked, using
  `select_for_update()` so concurrent requests can't race past the limit. Going over
  quota degrades to a chat message rather than an error page, same pattern as an LLM
  failure.
- Embeddings are local and free (`sentence-transformers`); the only metered calls are
  the two-per-question LLM calls (synthesize + critique), and only on the free tiers
  of Groq/Gemini by default.

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
   (`papers/views.py::ingest_papers`) instead of trusting the paired form fields —
   which also means a tampered hidden field can't be used to attach the wrong
   abstract to a paper. Covered by
   `papers/tests/test_views.py::test_ingesting_only_the_checked_candidate_does_not_mix_up_metadata`.
2. **NUL bytes from PDF extraction.** A real paper's PDF extracted to text containing
   a `\x00` byte, which `psycopg`/PostgreSQL reject on insert
   (`DataError: PostgreSQL text fields cannot contain NUL (0x00) bytes`), crashing the
   whole ingestion task. Fixed in `pdf_extract.extract_text` by stripping NUL bytes
   before the text is chunked and stored. Covered by
   `papers/tests/test_pdf_extract.py::test_extract_text_strips_nul_bytes`.

A third bug was a template/view issue rather than a data one: the chat view's
`messages` context variable collided with Django's built-in flash-messages context
processor (also named `messages`), which `base/base.html` renders as banner alerts —
so every chat message double-rendered as an ugly banner using the model's raw
`__str__`. Fixed by renaming the chat context key to `chat_messages`.

## UI

Server-rendered Django templates plus HTMX for the two places that need a partial
swap without a full page reload: posting a chat message
(`templates/chat/conversation.html`, `hx-swap="beforeend"`) and polling paper
ingestion status (`templates/papers/_paper_status.html`, `hx-trigger="every 3s"`,
only while at least one paper is `pending`). No SPA framework, no custom JS beyond
what HTMX needs.

Django admin is wired up for `Paper`, `Chunk` (read-only — it has a lot of rows),
`Workspace`, `Conversation`/`Message`, and `UsageRecord` and serves as the ops
dashboard; nothing custom was built on top of it.

## Deployment

`docker-compose.yml` defines four services: `postgres` (`pgvector/pgvector:pg16`),
`redis`, `web` (`gunicorn`, runs migrations + `collectstatic` on start), and `worker`
(`celery -A config worker`). `web` and `worker` share a `huggingface_cache` volume so
the embedding model is downloaded once, not once per container. Host ports for
`postgres`/`redis` are overridable via `POSTGRES_PORT`/`REDIS_HOST_PORT` in `.env` to
avoid clashing with services already running on the host.

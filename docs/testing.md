# Testing

## Running the suite

```bash
uv run pytest -q
```

100 backend tests (plus 8 frontend tests with `npm test`, and a Playwright smoke test via `make e2e`), no live API keys or network access required (`papers/tests/test_arxiv_client.py`
mocks `requests.get`; everything LLM-related uses `FakeLLMClient`, and a root `conftest.py` blanks the API keys
for every test so nothing can reach a real provider by accident). Needs a running
Postgres with the `vector` extension available — `pytest-django` creates and migrates a
throwaway `test_<POSTGRES_DB>` database against whatever `POSTGRES_HOST`/`POSTGRES_PORT`
are in `.env`, and the `VectorExtension()` migration operation enables `vector` in that
database automatically, so no manual setup beyond having the `postgres` container (or
any pgvector-enabled Postgres) reachable.

Embeddings are computed for real (locally, via `sentence-transformers`) rather than
mocked in `papers/tests/test_tasks.py` — it's free, fast, and testing that a `Chunk`
actually gets a real 384-dim vector is the point.

## Layout and philosophy

Tests live in a `tests/` package per app, mirroring the source layout:

```
papers/tests/
  test_arxiv_client.py   # arXiv API wrapper, mocked HTTP
  test_pdf_extract.py    # PDF text extraction, including the NUL-byte regression
  test_tasks.py          # the Celery ingestion task, mocked download + real embedding
  fixtures/
    arxiv_response.xml    # a saved Atom API response
    sample.pdf             # a minimal hand-built PDF with known text content
agent/tests/
  test_query_graph.py    # critique/retry cycle, rewrite, stage events, FakeLLMClient
  test_retrieval.py      # RRF + per-paper cap (pure), hybrid search against real pgvector/FTS
  test_fallback_client.py
api/tests/
  test_auth_and_workspaces.py  # login/register, cross-user 404 isolation
  test_papers.py               # search/ingest/retry, broker-outage handling
  test_chat.py                 # NDJSON stream, history, quota, diagnosed failures, disconnects
  test_diagnostics_and_health.py
```

Each layer is tested at the boundary that makes sense for it, deliberately not
end-to-end for every case:

- **External services are mocked or faked**, never hit for real in the automated
  suite: `requests.get` for arXiv, `Celery.delay()`, `FakeLLMClient` for the LLM. Real
  calls to arXiv/Groq/Gemini/a live Celery worker only happen in manual smoke-testing
  (see below), never in CI.
- **The critique/retry cycle is tested as a real compiled LangGraph graph**, not by
  manually chaining function calls — see the "why a graph, not a chain" note below.
- **API views are tested with DRF's `APIClient`**, asserting on database state and
  response content, with the one real dependency they have on other layers (Celery,
  the query graph, arXiv) mocked out — those layers have their own tests.

## The query graph tests, in detail

(The streaming/stage tests and the rewrite tests in the same file run the *full* graph
with `hybrid_search` stubbed; the retrieval tests in `test_retrieval.py` cover the real
SQL, with `embed_text` patched to return hand-built vectors so no model loads.)

`agent/tests/test_query_graph.py` builds a *second*, smaller compiled graph that
starts at `synthesize` instead of `retrieve`:

```python
def _build_test_graph(llm):
    graph = StateGraph(QueryState)
    graph.add_node("synthesize", lambda s: synthesize_node(s, llm=llm))
    graph.add_node("critique", lambda s: critique_node(s, llm=llm))
    graph.set_entry_point("synthesize")
    graph.add_edge("synthesize", "critique")
    graph.add_conditional_edges("critique", _route_after_critique, {"synthesize": "synthesize", END: END})
    return graph.compile()
```

This reuses the actual production nodes and the actual conditional-routing function
(`_route_after_critique`) from `agent/query_graph.py` — so a wiring bug in the real
retry edge would fail this test — while skipping `retrieve_node`, which is a pure
pgvector lookup with nothing graph-specific about it and would otherwise force every
one of these tests to depend on the database and a populated corpus. This is why the
tests need no `@pytest.mark.django_db` mark at all: none of `synthesize_node`,
`critique_node`, or the conditional edge touch the database.

Three scenarios, each scripting the exact sequence of LLM responses the loop should
produce:

1. **`test_unsupported_claim_triggers_one_retry_then_clean_finish`** — first draft has
   one claim citing a real chunk that doesn't support it; critique flags it; the
   revised draft is clean. Asserts `retries == 1`, `critique_notes == []`, and the
   final `citations` map to the right `paper_id`/`chunk_id`.
2. **`test_max_retries_cutoff_terminates_instead_of_looping_forever`** — every attempt
   is flagged as unsupported. Asserts the loop stops at exactly `max_retries` (doesn't
   run forever) and still returns the last draft with its `critique_notes` intact,
   rather than silently presenting an unverified answer as clean.
3. **`test_citation_to_unretrieved_chunk_is_caught_without_an_extra_llm_call`** — a
   draft cites a chunk number outside the retrieved set. Asserts this is caught by
   `critique_node`'s own range check and does **not** trigger a critique LLM call for
   that line — the fake client would raise `IndexError` (out of scripted responses) if
   it did, so this failure mode is enforced by the test setup itself, not just an
   assertion.

## Manual / real-API smoke testing

Not part of the automated suite (needs live credentials and/or a running worker), but
worth re-running by hand after touching the ingestion or query path:

```bash
# arXiv search against the real API
uv run python manage.py shell -c "
from papers.services import arxiv_client
print(arxiv_client.search('retrieval augmented generation', max_results=3))
"

# Full ingestion against a real paper (downloads the PDF, embeds for real)
uv run python manage.py shell -c "
from papers.tasks import ingest_paper
from papers.models import Paper
paper = Paper.objects.get(arxiv_id='1706.03762v7')
ingest_paper(paper.id)
paper.refresh_from_db()
print(paper.status, paper.chunks.count())
"
```

The query graph against real ingested data, with a scripted `FakeLLMClient` so it
still needs no API key:

```python
from agent.llm.fake_client import FakeLLMClient
from agent.query_graph import run_query

fake = FakeLLMClient(responses=[
    "The Transformer uses self-attention instead of recurrence. [1]\nIt was trained on Mars in 1823. [2]",
    "UNSUPPORTED: 2",
    "The Transformer uses self-attention instead of recurrence. [1]",
    "UNSUPPORTED: none",
])
result = run_query(workspace_id=1, question="What architecture does the Transformer use?", llm=fake)
```

For a full browser pass without spending tokens, start Django with `LLM_PROVIDER=demo`
(and ideally a scratch `POSTGRES_DB`): the demo client answers from the top retrieved
chunk, so the loader, citations, history and error cards can all be exercised. With real
`GROQ_API_KEY`/`GEMINI_API_KEY` in `.env` and `LLM_PROVIDER=auto`, the same flow
exercises the real adapters.

## What caught real bugs (and what didn't)

The three bugs described in [`architecture.md`](architecture.md#data-correctness-notes)
were all found by driving the actual browser against a running dev server + Celery
worker + Postgres — not by the unit suite, which was green the whole time. Two lessons
baked into the current tests as a result:

- `api/tests/test_papers.py::test_ingest_stores_refetched_metadata_and_enqueues`
  descends from a test that exists specifically because the *first* version of the ingest test
  only ever submitted a single candidate, which can't expose a positional-mismatch bug
  between multiple candidates — a reminder that a Django `Client()` test with only one
  of something in the form data doesn't exercise the same code path as the real
  multi-candidate form.
- `papers/tests/test_pdf_extract.py::test_extract_text_strips_nul_bytes` exists
  because the hand-built `sample.pdf` fixture (plain ASCII text, no NUL bytes) could
  never have surfaced the bug — only a real arXiv PDF's extracted text did. The
  regression test fakes `PdfReader` to return a NUL byte directly rather than trying
  to reproduce the specific PDF that triggered it.

For UI-affecting or storage-affecting changes to the ingestion or chat flow, treat a
real browser pass (search → select → ingest → wait for `ready` → ask a question) as
part of the change, not optional polish.

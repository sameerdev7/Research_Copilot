# Testing

## Running the suite

```bash
uv run pytest -q
```

20 tests, no live API keys or network access required (`papers/tests/test_arxiv_client.py`
mocks `requests.get`; everything LLM-related uses `FakeLLMClient`). Needs a running
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
  test_views.py          # search/ingest views, mocked arxiv_client + Celery .delay()
  fixtures/
    arxiv_response.xml    # a saved Atom API response
    sample.pdf             # a minimal hand-built PDF with known text content
agent/tests/
  test_query_graph.py    # the critique/retry cycle, FakeLLMClient, no DB access
chat/tests/
  test_views.py          # chat view: quota, LLM-failure degradation, message creation
workspaces/tests/
  test_views.py          # workspace CRUD + cross-user 403 isolation
```

Each layer is tested at the boundary that makes sense for it, deliberately not
end-to-end for every case:

- **External services are mocked or faked**, never hit for real in the automated
  suite: `requests.get` for arXiv, `Celery.delay()`, `FakeLLMClient` for the LLM. Real
  calls to arXiv/Groq/Gemini/a live Celery worker only happen in manual smoke-testing
  (see below), never in CI.
- **The critique/retry cycle is tested as a real compiled LangGraph graph**, not by
  manually chaining function calls — see the "why a graph, not a chain" note below.
- **Django views are tested with `Client()`**, asserting on database state and
  response content, with the one real dependency they have on other layers (Celery,
  the query graph, arXiv) mocked out — those layers have their own tests.

## The query graph tests, in detail

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

With a real `GROQ_API_KEY`/`GEMINI_API_KEY` in `.env`, drop the `llm=fake` argument to
exercise the real adapters end-to-end through the chat UI.

## What caught real bugs (and what didn't)

The three bugs described in [`architecture.md`](architecture.md#data-correctness-notes)
were all found by driving the actual browser against a running dev server + Celery
worker + Postgres — not by the unit suite, which was green the whole time. Two lessons
baked into the current tests as a result:

- `papers/tests/test_views.py::test_ingesting_only_the_checked_candidate_does_not_mix_up_metadata`
  exists specifically because the *first* version of `test_ingest_papers_creates_paper_and_enqueues_celery_task`
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

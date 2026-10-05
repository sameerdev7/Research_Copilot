import { CircleCheck, Menu, RotateCw, Search, Trash2, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, toErrorInfo } from "../api";
import ErrorNotice from "../components/ErrorNotice";
import { useShell } from "../components/shellContext";
import type { Candidate, ErrorInfo, Paper } from "../types";

const POLL_MS = 3000;

function StatusPill({ paper }: { paper: Paper }) {
  if (paper.status === "ready") return <span className="pill ok"><CircleCheck size={13} /> Ready</span>;
  if (paper.status === "failed") return <span className="pill error"><TriangleAlert size={13} /> Failed</span>;
  return <span className="pill pending"><span className="spinner tiny" /> Processing</span>;
}

export default function PapersPage() {
  const { workspace, refreshWorkspaces, openDiagnostics, toggleSidebar } = useShell();

  const [papers, setPapers] = useState<Paper[]>([]);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<ErrorInfo | null>(null);

  const load = useCallback(async () => {
    const list = await api.papers(workspace.id);
    setPapers(list);
    return list;
  }, [workspace.id]);

  useEffect(() => {
    setCandidates(null);
    setSelected([]);
    load().catch((err) => setError(toErrorInfo(err)));
  }, [load]);

  // poll while papers are ingesting and refresh sidebar counts as they finish
  const hasPending = papers.some((p) => p.status === "pending");
  const finishedCount = useRef(0);
  useEffect(() => {
    finishedCount.current = papers.filter((p) => p.status !== "pending").length;
  }, [papers]);
  useEffect(() => {
    if (!hasPending) return;
    const timer = setInterval(() => {
      load()
        .then((list) => {
          const finished = list.filter((p) => p.status !== "pending").length;
          if (finished !== finishedCount.current) return refreshWorkspaces();
        })
        .catch(() => {});
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [hasPending, load, refreshWorkspaces]);

  async function search(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSearching(true);
    try {
      setCandidates(await api.searchPapers(workspace.id, query));
      setSelected([]);
    } catch (err) {
      setError(toErrorInfo(err));
    } finally {
      setSearching(false);
    }
  }

  async function addSelected() {
    setError(null);
    setAdding(true);
    try {
      await api.ingestPapers(workspace.id, selected);
      setCandidates(null);
      setSelected([]);
      await Promise.all([load(), refreshWorkspaces()]);
    } catch (err) {
      setError(toErrorInfo(err));
    } finally {
      setAdding(false);
    }
  }

  async function act(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await Promise.all([load(), refreshWorkspaces()]);
    } catch (err) {
      setError(toErrorInfo(err));
    }
  }

  const toggle = (id: string) =>
    setSelected((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]));

  return (
    <div className="page papers-page">
      <header className="page-header">
        <button className="icon-button menu-button" onClick={toggleSidebar} aria-label="Menu"><Menu size={20} /></button>
        <h1>Papers</h1>
        <span className="muted">{workspace.name}</span>
      </header>

      <div className="page-body">
        <form className="search-form" onSubmit={search}>
          <Search size={16} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search arXiv by topic, or paste arXiv IDs (e.g. 1706.03762)"
          />
          <button className="primary" disabled={searching || !query.trim()}>
            {searching ? <span className="spinner small" /> : "Search"}
          </button>
        </form>

        {error && <ErrorNotice error={error} onDiagnose={openDiagnostics} />}

        {candidates && (
          <section className="card">
            <h2>Results</h2>
            {candidates.length === 0 && <p className="muted">No papers found for "{query}".</p>}
            <ul className="paper-list">
              {candidates.map((c) => (
                <li key={c.arxiv_id}>
                  <label>
                    <input
                      type="checkbox"
                      checked={c.already_added || selected.includes(c.arxiv_id)}
                      disabled={c.already_added}
                      onChange={() => toggle(c.arxiv_id)}
                    />
                    <div>
                      <strong>{c.title}</strong>
                      <span className="muted">{c.authors.slice(0, 4).join(", ")}{c.authors.length > 4 ? " et al." : ""} · {c.arxiv_id}</span>
                      {c.already_added && <span className="muted">Already in this workspace</span>}
                    </div>
                  </label>
                </li>
              ))}
            </ul>
            {selected.length > 0 && (
              <button className="primary" onClick={addSelected} disabled={adding}>
                {adding ? <span className="spinner small" /> : `Add ${selected.length} paper${selected.length > 1 ? "s" : ""}`}
              </button>
            )}
          </section>
        )}

        <section>
          <h2>Library <span className="muted">({papers.length})</span></h2>
          {papers.length === 0 && <p className="muted">Nothing here yet. Search above to add your first paper.</p>}
          <ul className="paper-list library">
            {papers.map((paper) => (
              <li key={paper.id}>
                <div className="paper-main">
                  <strong>{paper.title}</strong>
                  <span className="muted">{paper.authors.slice(0, 4).join(", ")}{paper.authors.length > 4 ? " et al." : ""} · {paper.arxiv_id}</span>
                  {paper.status === "failed" && <span className="failure">{paper.failure_reason || "Ingestion failed."}</span>}
                </div>
                <StatusPill paper={paper} />
                {paper.status === "failed" && (
                  <button className="icon-button" title="Retry" onClick={() => act(() => api.retryPaper(workspace.id, paper.id))}>
                    <RotateCw size={15} />
                  </button>
                )}
                <button
                  className="icon-button"
                  title="Remove"
                  onClick={() => confirm(`Remove "${paper.title}"?`) && act(() => api.deletePaper(workspace.id, paper.id))}
                >
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
          </ul>
          {hasPending && (
            <p className="muted">
              Papers stay "Processing" until the Celery worker finishes them.{" "}
              <button className="link" onClick={openDiagnostics}>Stuck? Run diagnostics</button>
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

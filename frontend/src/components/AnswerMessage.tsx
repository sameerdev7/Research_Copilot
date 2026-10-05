import { ChevronDown, CircleCheck, ExternalLink, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { parseAnswer } from "../answer";
import type { Message, Source } from "../types";
import ErrorNotice from "./ErrorNotice";

function SourceCard({ source }: { source: Source }) {
  return (
    <div className="source-card">
      <div className="source-head">
        <span className="chip static">{source.n}</span>
        <a href={`https://arxiv.org/abs/${source.arxiv_id}`} target="_blank" rel="noreferrer">
          {source.paper_title} <ExternalLink size={12} />
        </a>
        <span className="muted">{Math.round(source.score * 100)}% match</span>
      </div>
      <p>{source.text}</p>
    </div>
  );
}

interface Props {
  message: Message;
  onRetry?: () => void;
  onDiagnose: () => void;
}

export default function AnswerMessage({ message, onRetry, onDiagnose }: Props) {
  const [openSources, setOpenSources] = useState<number[]>([]);
  const [showNotes, setShowNotes] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  const error = message.diagnostics.error;
  if (error) {
    return (
      <div className="message assistant">
        <ErrorNotice error={error} onRetry={onRetry} onDiagnose={onDiagnose} />
      </div>
    );
  }

  const lines = parseAnswer(message.content);
  const sources = new Map(message.sources.map((s) => [s.n, s]));
  const cited = [...new Set(lines.flatMap((l) => l.refs))].filter((n) => sources.has(n)).sort((a, b) => a - b);
  const toggle = (n: number) =>
    setOpenSources((open) => (open.includes(n) ? open.filter((x) => x !== n) : [...open, n]));

  const notes = message.critique_notes;
  const { search_query, retries, timings, request_id } = message.diagnostics;

  return (
    <div className="message assistant">
      <div className="answer">
        {lines.map((line, i) => (
          <p key={i}>
            {line.text}
            {line.refs.map((n) => (
              <button
                key={n}
                className={`chip ${openSources.includes(n) ? "active" : ""}`}
                onClick={() => toggle(n)}
                disabled={!sources.has(n)}
                title={sources.get(n)?.paper_title}
              >
                {n}
              </button>
            ))}
          </p>
        ))}
      </div>

      {cited.some((n) => openSources.includes(n)) && (
        <div className="source-list">
          {cited.filter((n) => openSources.includes(n)).map((n) => <SourceCard key={n} source={sources.get(n)!} />)}
        </div>
      )}

      <div className="answer-meta">
        {notes.length === 0 ? (
          <span className="verdict ok"><CircleCheck size={14} /> Every claim checked against its source</span>
        ) : (
          <button className="verdict warn" onClick={() => setShowNotes(!showNotes)}>
            <TriangleAlert size={14} /> {notes.length} claim{notes.length > 1 ? "s" : ""} couldn't be verified
            <ChevronDown size={14} />
          </button>
        )}
        {cited.length > 0 && (
          <button className="link" onClick={() => setOpenSources(openSources.length ? [] : cited)}>
            {openSources.length ? "Hide sources" : `Show ${cited.length} source${cited.length > 1 ? "s" : ""}`}
          </button>
        )}
        <button className="link" onClick={() => setShowDetails(!showDetails)}>Details</button>
      </div>

      {showNotes && (
        <ul className="notes">
          {notes.map((note, i) => <li key={i}>{note}</li>)}
        </ul>
      )}
      {showDetails && (
        <dl className="details">
          {search_query && <><dt>Searched for</dt><dd>{search_query}</dd></>}
          {retries !== undefined && <><dt>Revisions</dt><dd>{retries}</dd></>}
          {timings && (
            <>
              <dt>Timings</dt>
              <dd>{Object.entries(timings).map(([stage, s]) => `${stage} ${s.toFixed(1)}s`).join(" · ")}</dd>
            </>
          )}
          {request_id && <><dt>Reference</dt><dd><code>{request_id}</code></dd></>}
        </dl>
      )}
    </div>
  );
}

import { CircleAlert, CircleCheck, TriangleAlert, X } from "lucide-react";
import type { Health } from "../types";

const ICONS = {
  ok: <CircleCheck size={18} className="status-ok" />,
  warn: <TriangleAlert size={18} className="status-warn" />,
  error: <CircleAlert size={18} className="status-error" />,
};

interface Props {
  health: Health | null;
  failed: boolean;
  onRefresh: () => void;
  onClose: () => void;
}

export default function HealthPanel({ health, failed, onRefresh, onClose }: Props) {
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="System diagnostics">
        <div className="modal-head">
          <h2>System diagnostics</h2>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        {failed && (
          <p className="muted">Couldn't reach the backend at all - check that Django is running on port 8000.</p>
        )}
        {!health && !failed && <span className="spinner" />}
        <ul className="health-list">
          {health?.checks.map((check) => (
            <li key={check.name}>
              {ICONS[check.status]}
              <div>
                <strong>{check.name}</strong>
                <p>{check.message}</p>
                {check.hint && <p className="muted">{check.hint}</p>}
              </div>
            </li>
          ))}
        </ul>
        <button onClick={onRefresh}>Run checks again</button>
      </div>
    </div>
  );
}

import { TriangleAlert } from "lucide-react";
import type { ErrorInfo } from "../types";

interface Props {
  error: ErrorInfo;
  onRetry?: () => void;
  onDiagnose?: () => void;
}

// shows what failed, how to fix it, and a log reference id
export default function ErrorNotice({ error, onRetry, onDiagnose }: Props) {
  return (
    <div className="error-notice" role="alert">
      <TriangleAlert size={18} className="error-icon" />
      <div className="error-body">
        <strong>{error.message}</strong>
        {error.hint && <p>{error.hint}</p>}
        {error.detail && <pre className="error-detail">{error.detail}</pre>}
        <div className="error-meta">
          <code>{error.code}</code>
          {error.stage && <code>stage: {error.stage}</code>}
          {error.request_id && <code>ref {error.request_id}</code>}
        </div>
        {(onRetry || onDiagnose) && (
          <div className="error-actions">
            {onRetry && <button onClick={onRetry}>Try again</button>}
            {onDiagnose && <button onClick={onDiagnose}>Run diagnostics</button>}
          </div>
        )}
      </div>
    </div>
  );
}

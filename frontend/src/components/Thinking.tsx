import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import type { Stage, StageEvent } from "../types";

const LABELS: Record<Stage, string> = {
  rewrite: "Understanding your question",
  retrieve: "Searching your papers",
  synthesize: "Drafting an answer",
  critique: "Fact-checking every claim",
};

function label(event: StageEvent): string {
  if (event.stage === "synthesize" && event.attempt > 1) return `Revising after fact-check (attempt ${event.attempt})`;
  return LABELS[event.stage];
}

// live progress from the server's stage events
export default function Thinking({ stages }: { stages: StageEvent[] }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  const current = stages[stages.length - 1];

  return (
    <div className="message assistant">
      <div className="thinking" role="status" aria-live="polite">
        <ul>
          {stages.slice(0, -1).map((event, i) => (
            <li key={i} className="done"><Check size={14} /> {label(event)}</li>
          ))}
          <li className="active">
            <span className="spinner small" /> {current ? label(current) : "Starting"}
            <span className="dots"><i>.</i><i>.</i><i>.</i></span>
          </li>
        </ul>
        <span className="elapsed">{seconds}s</span>
      </div>
    </div>
  );
}

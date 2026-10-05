import { Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, toErrorInfo } from "../api";
import type { ErrorInfo, Workspace } from "../types";
import ErrorNotice from "./ErrorNotice";

export function NewWorkspaceForm({ autoFocus, onDone }: { autoFocus?: boolean; onDone?: () => void }) {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [error, setError] = useState<ErrorInfo | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const workspace = await api.createWorkspace(name);
      onDone?.();
      navigate(`/w/${workspace.id}`);
    } catch (err) {
      setError(toErrorInfo(err));
    }
  }

  return (
    <form className="inline-form" onSubmit={submit}>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Workspace name"
        autoFocus={autoFocus}
        maxLength={200}
      />
      <button className="primary" disabled={!name.trim()}>Create</button>
      {error && <ErrorNotice error={error} />}
    </form>
  );
}

interface Props {
  workspaces: Workspace[];
  current: Workspace;
  onDelete: () => void;
}

export default function WorkspaceSwitcher({ workspaces, current, onDelete }: Props) {
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);

  function remove() {
    if (confirm(`Delete "${current.name}" with all its papers and chats? This can't be undone.`)) onDelete();
  }

  return (
    <div className="workspace-switcher">
      <div className="switcher-row">
        <select value={current.id} onChange={(e) => navigate(`/w/${e.target.value}`)} aria-label="Workspace">
          {workspaces.map((w) => (
            <option key={w.id} value={w.id}>{w.name}</option>
          ))}
        </select>
        <button className="icon-button" title="New workspace" onClick={() => setCreating(!creating)}>
          <Plus size={16} />
        </button>
        <button className="icon-button" title="Delete workspace" onClick={remove}>
          <Trash2 size={15} />
        </button>
      </div>
      {creating && <NewWorkspaceForm autoFocus onDone={() => setCreating(false)} />}
    </div>
  );
}

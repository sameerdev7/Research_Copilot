import { Check, FileText, Pencil, Plus, Stethoscope, Trash2, LogOut } from "lucide-react";
import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import type { Conversation, Health, User, Workspace } from "../types";
import Logo from "./Logo";
import WorkspaceSwitcher from "./WorkspaceSwitcher";

interface Props {
  user: User;
  workspaces: Workspace[];
  workspace: Workspace;
  conversations: Conversation[];
  health: Health | null;
  open: boolean;
  onRename: (id: number, title: string) => void;
  onDelete: (id: number) => void;
  onWorkspaceDelete: () => void;
  onDiagnostics: () => void;
  onLogout: () => void;
  onNavigate: () => void;
}

function ConversationItem({
  conversation,
  basePath,
  onRename,
  onDelete,
  onNavigate,
}: {
  conversation: Conversation;
  basePath: string;
  onRename: Props["onRename"];
  onDelete: Props["onDelete"];
  onNavigate: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(conversation.title);
  const label = conversation.title || "New chat";

  function save() {
    setEditing(false);
    if (title.trim() && title !== conversation.title) onRename(conversation.id, title.trim());
  }

  if (editing) {
    return (
      <li className="chat-item editing">
        <input
          value={title}
          autoFocus
          maxLength={120}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") setEditing(false);
          }}
          onBlur={save}
        />
        <Check size={14} />
      </li>
    );
  }

  return (
    <li className="chat-item">
      <NavLink to={`${basePath}/${conversation.id}`} onClick={onNavigate} title={label}>
        {label}
      </NavLink>
      <button className="icon-button" title="Rename" onClick={() => { setTitle(conversation.title); setEditing(true); }}>
        <Pencil size={13} />
      </button>
      <button
        className="icon-button"
        title="Delete"
        onClick={() => confirm(`Delete "${label}"?`) && onDelete(conversation.id)}
      >
        <Trash2 size={13} />
      </button>
    </li>
  );
}

export default function Sidebar(props: Props) {
  const { user, workspaces, workspace, conversations, health, open } = props;
  const navigate = useNavigate();
  const base = `/w/${workspace.id}`;

  return (
    <aside className={open ? "sidebar open" : "sidebar"}>
      <Logo />
      <WorkspaceSwitcher workspaces={workspaces} current={workspace} onDelete={props.onWorkspaceDelete} />

      <button
        className="new-chat"
        onClick={() => {
          navigate(`${base}/chat`);
          props.onNavigate();
        }}
      >
        <Plus size={16} /> New chat
      </button>

      <NavLink to={`${base}/papers`} className="nav-link" onClick={props.onNavigate}>
        <FileText size={16} /> Papers
        <span className="badge">{workspace.ready_count}/{workspace.paper_count}</span>
      </NavLink>

      <div className="section-label">Chats</div>
      <ul className="chat-list">
        {conversations.length === 0 && <li className="muted empty">No chats yet</li>}
        {conversations.map((c) => (
          <ConversationItem
            key={c.id}
            conversation={c}
            basePath={`${base}/chat`}
            onRename={props.onRename}
            onDelete={props.onDelete}
            onNavigate={props.onNavigate}
          />
        ))}
      </ul>

      <div className="sidebar-footer">
        <button className="health-button" onClick={props.onDiagnostics}>
          <span className={`dot ${health?.status ?? "unknown"}`} />
          <Stethoscope size={15} />
          {health === null ? "Diagnostics" : health.status === "ok" ? "All systems ok" : "Needs attention"}
        </button>
        <div className="user-row">
          <span title={user.username}>{user.username}</span>
          <button className="icon-button" title="Sign out" onClick={props.onLogout}>
            <LogOut size={15} />
          </button>
        </div>
      </div>
    </aside>
  );
}

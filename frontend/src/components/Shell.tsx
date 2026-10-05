import { useCallback, useEffect, useState } from "react";
import { Outlet, useMatch, useNavigate, useParams } from "react-router-dom";
import { api, toErrorInfo } from "../api";
import { useAuth } from "../auth";
import { rememberWorkspace } from "../lastWorkspace";
import type { Conversation, ErrorInfo, Health, Workspace } from "../types";
import ErrorNotice from "./ErrorNotice";
import HealthPanel from "./HealthPanel";
import Sidebar from "./Sidebar";
import type { ShellContext } from "./shellContext";

const MOBILE_QUERY = "(max-width: 800px)";
const COLLAPSED_KEY = "sidebarCollapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function saveCollapsed(value: boolean) {
  try {
    localStorage.setItem(COLLAPSED_KEY, value ? "1" : "0");
  } catch {
    // storage unavailable: skip remembering
  }
}

// sidebar and page frame for one workspace; owns the shared data
export default function Shell() {
  const workspaceId = Number(useParams().workspaceId);
  const activeChatId = Number(useMatch("/w/:workspaceId/chat/:conversationId")?.params.conversationId);
  const navigate = useNavigate();
  const { user, setUser } = useAuth();

  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthFailed, setHealthFailed] = useState(false);
  const [healthOpen, setHealthOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false); // small screens: slide-over
  const [collapsed, setCollapsed] = useState(readCollapsed); // wide screens: hidden entirely
  const [notice, setNotice] = useState<ErrorInfo | null>(null);

  const refreshWorkspaces = useCallback(async () => {
    setWorkspaces(await api.workspaces());
  }, []);

  const refreshHealth = useCallback(async () => {
    setHealthFailed(false);
    try {
      setHealth(await api.health());
    } catch {
      setHealth(null);
      setHealthFailed(true);
    }
  }, []);

  useEffect(() => {
    refreshWorkspaces().catch((err) => setNotice(toErrorInfo(err)));
    refreshHealth();
  }, [refreshWorkspaces, refreshHealth]);

  useEffect(() => {
    rememberWorkspace(workspaceId);
    setConversations([]);
    api.conversations(workspaceId).then(setConversations).catch((err) => setNotice(toErrorInfo(err)));
  }, [workspaceId]);

  const workspace = workspaces?.find((w) => w.id === workspaceId);
  useEffect(() => {
    if (workspaces && !workspace) navigate("/", { replace: true });
  }, [workspaces, workspace, navigate]);

  const upsertConversation = useCallback((conversation: Conversation) => {
    setConversations((list) => [conversation, ...list.filter((c) => c.id !== conversation.id)]);
  }, []);

  async function run(action: () => Promise<unknown>) {
    try {
      await action();
    } catch (err) {
      setNotice(toErrorInfo(err));
    }
  }

  const rename = (id: number, title: string) =>
    run(async () => {
      const { conversation } = await api.renameConversation(id, title);
      setConversations((list) => list.map((c) => (c.id === id ? conversation : c)));
    });

  const remove = (id: number) =>
    run(async () => {
      await api.deleteConversation(id);
      setConversations((list) => list.filter((c) => c.id !== id));
      if (id === activeChatId) navigate(`/w/${workspaceId}/chat`);
    });

  if (!workspace || !workspaces || !user) return <div className="center-screen"><span className="spinner" /></div>;

  const context: ShellContext = {
    workspace,
    conversations,
    upsertConversation,
    refreshWorkspaces,
    notify: setNotice,
    toggleSidebar: () => {
      if (window.matchMedia(MOBILE_QUERY).matches) return setSidebarOpen((open) => !open);
      setCollapsed((value) => {
        saveCollapsed(!value);
        return !value;
      });
    },
    openDiagnostics: () => {
      setHealthOpen(true);
      refreshHealth();
    },
  };

  return (
    <div className={collapsed ? "app collapsed" : "app"}>
      <Sidebar
        user={user}
        workspaces={workspaces}
        workspace={workspace}
        conversations={conversations}
        health={health}
        open={sidebarOpen}
        onRename={rename}
        onDelete={remove}
        onWorkspaceDelete={() => run(async () => {
          await api.deleteWorkspace(workspaceId);
          await refreshWorkspaces();
          navigate("/", { replace: true });
        })}
        onDiagnostics={context.openDiagnostics}
        onNavigate={() => setSidebarOpen(false)}
        onLogout={() => run(async () => {
          await api.logout();
          setUser(null);
        })}
      />
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}
      <main>
        <Outlet context={context} />
      </main>
      {notice && (
        <div className="toast">
          <ErrorNotice error={notice} />
          <button className="link" onClick={() => setNotice(null)}>Dismiss</button>
        </div>
      )}
      {healthOpen && (
        <HealthPanel health={health} failed={healthFailed} onRefresh={refreshHealth} onClose={() => setHealthOpen(false)} />
      )}
    </div>
  );
}

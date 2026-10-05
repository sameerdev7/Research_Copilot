import { useOutletContext } from "react-router-dom";
import type { Conversation, ErrorInfo, Workspace } from "../types";

export interface ShellContext {
  workspace: Workspace;
  conversations: Conversation[];
  // adds or updates a conversation in the sidebar
  upsertConversation: (conversation: Conversation) => void;
  refreshWorkspaces: () => Promise<void>;
  openDiagnostics: () => void;
  toggleSidebar: () => void;
  notify: (error: ErrorInfo) => void;
}

export const useShell = () => useOutletContext<ShellContext>();

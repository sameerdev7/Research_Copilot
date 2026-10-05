import type {
  Candidate,
  Conversation,
  ErrorInfo,
  Health,
  Message,
  Paper,
  StreamEvent,
  User,
  Workspace,
} from "./types";

export class ApiError extends Error {
  constructor(
    public info: ErrorInfo,
    public status: number,
  ) {
    super(info.message);
  }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

function csrfToken(): string {
  return globalThis.document?.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] ?? "";
}

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    if (body?.error) return new ApiError(body.error, res.status);
  } catch {
    // not JSON: a proxy answered instead of Django
  }
  const unreachable = res.status === 502 || res.status === 503 || res.status === 504;
  return new ApiError(
    {
      code: unreachable ? "server_unreachable" : "unexpected_response",
      message: unreachable ? "The backend isn't responding." : `Unexpected response (${res.status}).`,
      hint: unreachable ? "Is Django running? Start it with `uv run python manage.py runserver`." : undefined,
    },
    res.status,
  );
}

async function send(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(
      { code: "network_error", message: "Can't reach the server.", hint: "Check that the backend is running." },
      0,
    );
  }
  if (!res.ok) {
    const error = await toApiError(res);
    if (error.info.code === "not_authenticated") onUnauthorized();
    throw error;
  }
  return res;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await send(method, path, body);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

// reads the answer stream, one JSON event per line
export async function* streamMessage(
  conversationId: number,
  question: string,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await send("POST", `/conversations/${conversationId}/messages/`, { question }, signal);
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop()!;
    for (const line of lines) if (line.trim()) yield JSON.parse(line) as StreamEvent;
  }
}

export const api = {
  me: () => request<{ user: User | null }>("GET", "/auth/me/"),
  login: (username: string, password: string) =>
    request<{ user: User }>("POST", "/auth/login/", { username, password }),
  register: (username: string, password: string) =>
    request<{ user: User }>("POST", "/auth/register/", { username, password }),
  logout: () => request<void>("POST", "/auth/logout/"),

  workspaces: () => request<Workspace[]>("GET", "/workspaces/"),
  createWorkspace: (name: string) => request<Workspace>("POST", "/workspaces/", { name }),
  deleteWorkspace: (id: number) => request<void>("DELETE", `/workspaces/${id}/`),

  papers: (workspaceId: number) => request<Paper[]>("GET", `/workspaces/${workspaceId}/papers/`),
  searchPapers: (workspaceId: number, query: string) =>
    request<Candidate[]>("POST", `/workspaces/${workspaceId}/papers/search/`, { query }),
  ingestPapers: (workspaceId: number, arxivIds: string[]) =>
    request<Paper[]>("POST", `/workspaces/${workspaceId}/papers/ingest/`, { arxiv_ids: arxivIds }),
  retryPaper: (workspaceId: number, paperId: number) =>
    request<Paper>("POST", `/workspaces/${workspaceId}/papers/${paperId}/retry/`),
  deletePaper: (workspaceId: number, paperId: number) =>
    request<void>("DELETE", `/workspaces/${workspaceId}/papers/${paperId}/`),

  conversations: (workspaceId: number) =>
    request<Conversation[]>("GET", `/workspaces/${workspaceId}/conversations/`),
  createConversation: (workspaceId: number) =>
    request<Conversation>("POST", `/workspaces/${workspaceId}/conversations/`),
  conversation: (id: number, before?: number) =>
    request<{ conversation: Conversation; messages: Message[]; has_more: boolean }>(
      "GET",
      `/conversations/${id}/${before ? `?before=${before}` : ""}`,
    ),
  renameConversation: (id: number, title: string) =>
    request<{ conversation: Conversation }>("PATCH", `/conversations/${id}/`, { title }),
  deleteConversation: (id: number) => request<void>("DELETE", `/conversations/${id}/`),

  health: () => request<Health>("GET", "/health/"),
};

// turns anything thrown into an ErrorInfo for the UI
export function toErrorInfo(err: unknown): ErrorInfo {
  if (err instanceof ApiError) return err.info;
  return { code: "unknown", message: err instanceof Error ? err.message : "Something went wrong." };
}

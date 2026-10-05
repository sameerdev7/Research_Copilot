export interface User {
  id: number;
  username: string;
}

export interface Workspace {
  id: number;
  name: string;
  created_at: string;
  paper_count: number;
  ready_count: number;
}

export type PaperStatus = "pending" | "ready" | "failed";

export interface Paper {
  id: number;
  arxiv_id: string;
  title: string;
  authors: string[];
  abstract: string;
  status: PaperStatus;
  failure_reason: string;
  created_at: string;
}

export interface Candidate {
  arxiv_id: string;
  title: string;
  authors: string[];
  abstract: string;
  pdf_url: string;
  already_added: boolean;
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Source {
  n: number;
  paper_id: number;
  chunk_id: number;
  paper_title: string;
  arxiv_id: string;
  text: string;
  score: number;
}

export interface ErrorInfo {
  code: string;
  message: string;
  hint?: string;
  stage?: string;
  request_id?: string;
  detail?: string;
}

export interface Diagnostics {
  error?: ErrorInfo;
  request_id?: string;
  search_query?: string;
  retries?: number;
  timings?: Record<string, number>;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  critique_notes: string[];
  diagnostics: Diagnostics;
  created_at: string;
}

export type Stage = "rewrite" | "retrieve" | "synthesize" | "critique";

export interface StageEvent {
  stage: Stage;
  attempt: number;
}

export type StreamEvent =
  | { type: "user"; message: Message; conversation: Conversation }
  | ({ type: "stage" } & StageEvent)
  | { type: "message"; message: Message; conversation: Conversation }
  | { type: "error"; error: ErrorInfo };

export interface HealthCheck {
  name: string;
  status: "ok" | "warn" | "error";
  message: string;
  hint: string;
}

export interface Health {
  status: "ok" | "warn" | "error";
  checks: HealthCheck[];
}

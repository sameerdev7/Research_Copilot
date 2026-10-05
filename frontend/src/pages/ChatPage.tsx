import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Menu } from "lucide-react";
import { api, streamMessage, toErrorInfo } from "../api";
import AnswerMessage from "../components/AnswerMessage";
import Composer from "../components/Composer";
import ErrorNotice from "../components/ErrorNotice";
import { useShell } from "../components/shellContext";
import Thinking from "../components/Thinking";
import type { ErrorInfo, Message, StageEvent } from "../types";

export default function ChatPage() {
  const { workspace, conversations, upsertConversation, refreshWorkspaces, openDiagnostics, toggleSidebar } =
    useShell();
  const navigate = useNavigate();
  const conversationId = Number(useParams().conversationId) || null;

  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false); // older messages exist on the server
  const [loadingMore, setLoadingMore] = useState(false);
  const [stages, setStages] = useState<StageEvent[] | null>(null); // non-null while an answer is generating
  const [error, setError] = useState<ErrorInfo | null>(null);

  const activeId = useRef(conversationId);
  const justCreated = useRef<number | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const keepScroll = useRef(false); // set while prepending older messages

  // load history when the route changes conversation
  useEffect(() => {
    activeId.current = conversationId;
    setError(null);
    if (conversationId === null) {
      setMessages([]);
      setHasMore(false);
      setStages(null);
      return;
    }
    if (justCreated.current === conversationId) {
      justCreated.current = null; // we're mid-send into this one; its state is already on screen
      return;
    }
    setStages(null);
    setLoading(true);
    api
      .conversation(conversationId)
      .then((data) => {
        if (activeId.current !== conversationId) return;
        setMessages(data.messages);
        setHasMore(data.has_more);
      })
      .catch((err) => activeId.current === conversationId && setError(toErrorInfo(err)))
      .finally(() => setLoading(false));
  }, [conversationId]);

  useEffect(() => {
    if (keepScroll.current) {
      keepScroll.current = false;
      return;
    }
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, stages]);

  async function loadEarlier() {
    const oldest = messages.find((m) => m.id > 0);
    if (!conversationId || !oldest) return;
    setLoadingMore(true);
    try {
      const data = await api.conversation(conversationId, oldest.id);
      keepScroll.current = true;
      setMessages((list) => [...data.messages, ...list]);
      setHasMore(data.has_more);
    } catch (err) {
      setError(toErrorInfo(err));
    } finally {
      setLoadingMore(false);
    }
  }

  async function send(question: string) {
    setError(null);
    let id = conversationId;
    try {
      if (id === null) {
        const created = await api.createConversation(workspace.id);
        id = created.id;
        justCreated.current = id;
        activeId.current = id;
        upsertConversation(created);
        navigate(`/w/${workspace.id}/chat/${id}`, { replace: true });
      }

      // show the question now; the server's copy replaces it later
      const optimistic: Message = {
        id: -Date.now(), role: "user", content: question, sources: [], critique_notes: [],
        diagnostics: {}, created_at: new Date().toISOString(),
      };
      setMessages((list) => [...list, optimistic]);
      setStages([]);

      const stillHere = () => activeId.current === id;
      let received = false;
      for await (const event of streamMessage(id, question)) {
        if (event.type === "user") {
          if (stillHere()) setMessages((list) => list.map((m) => (m.id === optimistic.id ? event.message : m)));
          upsertConversation(event.conversation);
        } else if (event.type === "stage") {
          if (stillHere()) setStages((list) => [...(list ?? []), { stage: event.stage, attempt: event.attempt }]);
        } else if (event.type === "message") {
          received = true;
          if (stillHere()) setMessages((list) => [...list, event.message]);
          upsertConversation(event.conversation);
        } else {
          received = true;
          if (stillHere()) setError(event.error);
        }
      }
      if (!received) {
        throw new Error("The connection dropped before the answer finished. Reload to see whether it was saved.");
      }
    } catch (err) {
      if (activeId.current === id) setError(toErrorInfo(err));
      // drop the unsaved copy of the question
      setMessages((list) => list.filter((m) => m.id > 0));
    } finally {
      if (activeId.current === id) setStages(null);
      refreshWorkspaces().catch(() => {});
    }
  }

  const lastQuestion = [...messages].reverse().find((m) => m.role === "user")?.content;
  const title = conversations.find((c) => c.id === conversationId)?.title || "New chat";
  const generating = stages !== null;
  const noPapers = workspace.ready_count === 0;

  return (
    <div className="page chat-page">
      <header className="page-header">
        <button className="icon-button menu-button" onClick={toggleSidebar} aria-label="Menu"><Menu size={20} /></button>
        <h1>{title}</h1>
        <span className="muted">{workspace.name}</span>
      </header>

      <div className="thread">
        <div className="thread-inner">
          {loading && <span className="spinner" />}
          {hasMore && (
            <button className="link load-earlier" onClick={loadEarlier} disabled={loadingMore}>
              {loadingMore ? "Loading..." : "Load earlier messages"}
            </button>
          )}
          {!loading && messages.length === 0 && !generating && (
            <div className="empty-state">
              <h2>Ask your papers anything</h2>
              {noPapers ? (
                <p className="muted">
                  This workspace has no ready papers yet. <Link to={`/w/${workspace.id}/papers`}>Add some</Link> and
                  come back.
                </p>
              ) : (
                <p className="muted">
                  Answers cite the exact passages they come from, and every claim is fact-checked before you see it.
                  Follow-up questions remember the conversation.
                </p>
              )}
            </div>
          )}

          {messages.map((message, i) =>
            message.role === "user" ? (
              <div key={message.id} className="message user"><p>{message.content}</p></div>
            ) : (
              <AnswerMessage
                key={message.id}
                message={message}
                onRetry={i === messages.length - 1 && lastQuestion && !generating ? () => send(lastQuestion) : undefined}
                onDiagnose={openDiagnostics}
              />
            ),
          )}

          {stages !== null && <Thinking stages={stages} />}
          {error && <ErrorNotice error={error} onDiagnose={openDiagnostics} />}
          <div ref={bottom} />
        </div>
      </div>

      <Composer
        disabled={generating}
        placeholder={noPapers ? "Add papers first, then ask a question" : "Ask a question about your papers"}
        onSend={send}
      />
    </div>
  );
}

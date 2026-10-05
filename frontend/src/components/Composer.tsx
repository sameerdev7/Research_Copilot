import { ArrowUp } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

const MAX_CHARS = 2000;

interface Props {
  disabled: boolean;
  placeholder: string;
  onSend: (question: string) => void;
}

export default function Composer({ disabled, placeholder, onSend }: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // grow with content up to a cap
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  function submit() {
    const question = text.trim();
    if (!question || disabled) return;
    onSend(question);
    setText("");
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="composer">
      <textarea
        ref={ref}
        value={text}
        rows={1}
        maxLength={MAX_CHARS}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        autoFocus
      />
      <button className="send" onClick={submit} disabled={disabled || !text.trim()} aria-label="Send">
        <ArrowUp size={18} />
      </button>
    </div>
  );
}

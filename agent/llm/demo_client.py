import time

from agent.prompts import CRITIQUE_SYSTEM_PROMPT, REWRITE_SYSTEM_PROMPT


# offline stand-in for a real provider (LLM_PROVIDER=demo)
class DemoLLMClient:
    def __init__(self, delay_seconds: float = 0.8):
        self._delay = delay_seconds

    def complete(self, messages: list[dict]) -> str:
        time.sleep(self._delay)
        system = messages[0]["content"]
        user = messages[1]["content"]
        if system == REWRITE_SYSTEM_PROMPT:
            return user.rsplit("Latest question:", 1)[-1].strip()
        if system == CRITIQUE_SYSTEM_PROMPT:
            return "UNSUPPORTED: none"
        chunk = user.split("Source chunks:\n", 1)[-1].split("\n\n[2] ", 1)[0]
        text = chunk.split(") ", 1)[-1]
        snippet = " ".join(text.split())[:200]
        return f"(demo mode) The top retrieved passage says: {snippet} [1]"

from collections.abc import Callable

from .base import LLMClient


# creates the real client lazily and keeps a rough token estimate (~4 chars per token)
class CountingClient:
    def __init__(self, factory: Callable[[], LLMClient]):
        self._factory = factory
        self._client: LLMClient | None = None
        self.estimated_tokens = 0

    def complete(self, messages: list[dict]) -> str:
        if self._client is None:
            self._client = self._factory()
        reply = self._client.complete(messages)
        prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
        self.estimated_tokens += (prompt_chars + len(reply)) // 4
        return reply

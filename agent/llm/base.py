from typing import Protocol


class LLMClient(Protocol):
    def complete(self, messages: list[dict]) -> str:
        """Send a chat-style message list, return the assistant's text reply."""
        ...

from typing import Protocol


class LLMClient(Protocol):
    def complete(self, messages: list[dict]) -> str:
        ...

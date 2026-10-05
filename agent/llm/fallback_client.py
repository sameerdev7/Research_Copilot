import logging

from .base import LLMClient
from .errors import LLMUnavailable

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 300


# tries each client in order, falling through on any failure
class FallbackLLMClient:
    def __init__(self, clients: list[LLMClient]):
        if not clients:
            raise ValueError("FallbackLLMClient needs at least one client")
        self._clients = clients

    def complete(self, messages: list[dict]) -> str:
        attempts: list[tuple[str, str]] = []
        for client in self._clients:
            name = type(client).__name__
            try:
                return client.complete(messages)
            except Exception as exc:  # noqa: BLE001 - any provider failure should fall through to the next
                logger.warning("%s failed, falling back: %s", name, exc)
                attempts.append((name, str(exc)[:MAX_ERROR_CHARS]))
        raise LLMUnavailable(attempts)

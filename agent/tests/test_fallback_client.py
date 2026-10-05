import pytest

from agent.llm.errors import LLMUnavailable
from agent.llm.fallback_client import FallbackLLMClient


class _FailingClient:
    def __init__(self, exc: Exception):
        self._exc = exc

    def complete(self, messages: list[dict]) -> str:
        raise self._exc


class _OkClient:
    def __init__(self, text: str):
        self._text = text

    def complete(self, messages: list[dict]) -> str:
        return self._text


def test_uses_primary_when_it_succeeds():
    client = FallbackLLMClient([_OkClient("primary answer"), _FailingClient(RuntimeError("should not be called"))])

    assert client.complete([]) == "primary answer"


def test_falls_through_to_next_client_on_failure():
    client = FallbackLLMClient([_FailingClient(RuntimeError("primary down")), _OkClient("fallback answer")])

    assert client.complete([]) == "fallback answer"


def test_raises_with_every_providers_error_when_all_clients_fail():
    client = FallbackLLMClient([_FailingClient(RuntimeError("first down")), _FailingClient(RuntimeError("second down"))])

    with pytest.raises(LLMUnavailable, match="second down") as info:
        client.complete([])

    assert [name for name, _ in info.value.attempts] == ["_FailingClient", "_FailingClient"]
    assert "first down" in info.value.attempts[0][1]


def test_requires_at_least_one_client():
    with pytest.raises(ValueError):
        FallbackLLMClient([])

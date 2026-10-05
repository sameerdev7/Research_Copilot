from agent.llm.counting_client import CountingClient
from agent.llm.fake_client import FakeLLMClient


def test_estimates_tokens_across_calls():
    client = CountingClient(lambda: FakeLLMClient(["x" * 40, "y" * 40]))
    messages = [{"role": "user", "content": "z" * 40}]

    client.complete(messages)
    client.complete(messages)

    assert client.estimated_tokens == 40  # (40 + 40) // 4 per call


def test_creates_the_real_client_only_on_first_use():
    created = []
    client = CountingClient(lambda: created.append(1) or FakeLLMClient(["ok"]))

    assert created == []
    client.complete([])
    assert created == [1]

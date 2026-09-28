class FakeLLMClient:
    """Returns pre-scripted text responses in order, ignoring input. For tests only."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._index = 0

    def complete(self, messages: list[dict]) -> str:
        if self._index >= len(self._responses):
            raise IndexError("FakeLLMClient ran out of scripted responses")
        response = self._responses[self._index]
        self._index += 1
        return response

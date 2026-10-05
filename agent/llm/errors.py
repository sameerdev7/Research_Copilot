# no provider API key is set
class LLMNotConfigured(RuntimeError):
    pass


# every provider failed; attempts holds (provider, error) pairs
class LLMUnavailable(RuntimeError):
    def __init__(self, attempts: list[tuple[str, str]]):
        self.attempts = attempts
        summary = "; ".join(f"{provider}: {error}" for provider, error in attempts)
        super().__init__(f"All LLM providers failed - {summary}")

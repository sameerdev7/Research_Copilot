import os

from groq import BadRequestError, Groq

DEFAULT_MODEL = "llama-3.3-70b-versatile"


class GroqClient:
    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None):
        self._client = Groq(api_key=api_key or os.environ["GROQ_API_KEY"])
        self._model = model

    def complete(self, messages: list[dict]) -> str:
        try:
            response = self._client.chat.completions.create(model=self._model, messages=messages)
        except BadRequestError as exc:
            detail = exc.body.get("error", {}).get("message", str(exc)) if isinstance(exc.body, dict) else str(exc)
            raise RuntimeError(f"Groq request failed: {detail}") from exc

        return response.choices[0].message.content or ""

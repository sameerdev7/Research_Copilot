import os
import re
import time

from groq import BadRequestError, Groq, RateLimitError

DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 20
REQUEST_TIMEOUT_SECONDS = 60.0


def _retry_delay_seconds(exc: RateLimitError) -> float | None:
    # parse Groq's "try again in 14.9s" hint
    match = re.search(r"try again in ([\d.]+)s", str(exc))
    return float(match.group(1)) if match else None


class GroqClient:
    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None):
        self._client = Groq(api_key=api_key or os.environ["GROQ_API_KEY"], timeout=REQUEST_TIMEOUT_SECONDS)
        self._model = model

    def complete(self, messages: list[dict]) -> str:
        response = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._client.chat.completions.create(model=self._model, messages=messages)
                break
            except BadRequestError as exc:
                detail = (
                    exc.body.get("error", {}).get("message", str(exc)) if isinstance(exc.body, dict) else str(exc)
                )
                raise RuntimeError(f"Groq request failed: {detail}") from exc
            except RateLimitError as exc:
                if attempt == MAX_RETRIES:
                    raise
                wait = _retry_delay_seconds(exc) or DEFAULT_BACKOFF_SECONDS
                time.sleep(wait)

        return response.choices[0].message.content or ""

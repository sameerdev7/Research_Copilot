import re
import time

from google import genai
from google.genai.errors import ClientError

DEFAULT_MODEL = "gemini-2.0-flash"
MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 20


def _to_gemini_contents(messages: list[dict]) -> tuple[str | None, list[dict]]:
    system_instruction = None
    contents = []
    for msg in messages:
        role = msg["role"]
        if role == "system":
            system_instruction = msg["content"]
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": msg.get("content") or ""}]})
        else:
            contents.append({"role": "user", "parts": [{"text": str(msg.get("content", ""))}]})
    return system_instruction, contents


def _retry_delay_seconds(exc: ClientError) -> float | None:
    match = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", str(exc))
    return float(match.group(1)) if match else None


def _is_rate_limited(exc: ClientError) -> bool:
    return getattr(exc, "code", None) == 429


class GeminiClient:
    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None):
        self._client = genai.Client(api_key=api_key)
        self._model_name = model

    def complete(self, messages: list[dict]) -> str:
        system_instruction, contents = _to_gemini_contents(messages)
        config = {"system_instruction": system_instruction} if system_instruction else None

        response = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._model_name, contents=contents, config=config
                )
                break
            except ClientError as exc:
                if not _is_rate_limited(exc) or attempt == MAX_RETRIES:
                    raise
                wait = _retry_delay_seconds(exc) or DEFAULT_BACKOFF_SECONDS
                time.sleep(wait)

        return response.text

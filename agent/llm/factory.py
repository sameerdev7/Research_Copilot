from django.conf import settings

from .base import LLMClient
from .gemini_client import GeminiClient
from .groq_client import GroqClient


def get_default_client() -> LLMClient:
    """Groq is the default (fast, generous free tier); fall back to Gemini."""
    if settings.GROQ_API_KEY:
        return GroqClient(model=settings.GROQ_MODEL, api_key=settings.GROQ_API_KEY)
    if settings.GEMINI_API_KEY:
        return GeminiClient(model=settings.GEMINI_MODEL, api_key=settings.GEMINI_API_KEY)
    raise RuntimeError("No LLM API key configured: set GROQ_API_KEY or GEMINI_API_KEY")

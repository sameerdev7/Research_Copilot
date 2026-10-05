from django.conf import settings

from .base import LLMClient
from .demo_client import DemoLLMClient
from .errors import LLMNotConfigured
from .fallback_client import FallbackLLMClient
from .gemini_client import GeminiClient
from .groq_client import GroqClient


# Gemini first, Groq as the fallback
def get_default_client() -> LLMClient:
    if settings.LLM_PROVIDER == "demo":
        return DemoLLMClient()

    clients: list[LLMClient] = []
    if settings.GEMINI_API_KEY:
        clients.append(GeminiClient(model=settings.GEMINI_MODEL, api_key=settings.GEMINI_API_KEY))
    if settings.GROQ_API_KEY:
        clients.append(GroqClient(model=settings.GROQ_MODEL, api_key=settings.GROQ_API_KEY))

    if not clients:
        raise LLMNotConfigured("No LLM API key configured: set GEMINI_API_KEY or GROQ_API_KEY")

    return FallbackLLMClient(clients)

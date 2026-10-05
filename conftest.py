import pytest
from django.core.cache import cache


# blank API keys so tests can never call a real provider
@pytest.fixture(autouse=True)
def never_call_a_real_llm(settings):
    settings.GEMINI_API_KEY = ""
    settings.GROQ_API_KEY = ""
    settings.LLM_PROVIDER = "auto"


# throttle counters live in the cache, so reset them between tests
@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()

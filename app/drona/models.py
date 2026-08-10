import os
from openai import OpenAI, AsyncOpenAI

# R1 — Non-negotiable Model Strings
MODEL_PLANNER = "deepseek-v4-pro"
MODEL_SCOPING = "deepseek-v4-flash"
MODEL_TUTOR = "deepseek-v4-flash"

# Per-call timeout budgets, in seconds.
#
# The `openai` package is the HTTP client for DeepSeek as well as for OpenAI
# (same SDK, different base_url), and it defaults to 600s. Unset, a slow
# DeepSeek response hangs a live turn for ten minutes while the heartbeat keeps
# the socket open and the student sees nothing happen.
#
# Budgets differ by service: a tutor turn must feel live, whereas plan authoring
# measurably takes 103-124s and must not be cut off mid-JSON.
TUTOR_TIMEOUT_S = 60.0
SCOPING_TIMEOUT_S = 30.0
PLANNER_TIMEOUT_S = 240.0
# Backstop applied to the client itself, so no future call site can silently
# inherit the SDK's 600s default by forgetting to pass a timeout.
DEFAULT_TIMEOUT_S = 90.0


def get_drona_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY or OPENAI_API_KEY is missing from environment")

    # Client-level default so a call site that forgets to pass `timeout=` still
    # cannot inherit the SDK's 600s. Individual calls override this with their
    # own budget (planner needs longer, tutor needs shorter) — this is only the
    # backstop for anything added later.
    if os.getenv("DEEPSEEK_API_KEY"):
        return OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
            timeout=DEFAULT_TIMEOUT_S,
            max_retries=1,
        )

    # Fallback to OpenAI endpoint if DeepSeek API key not present
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=DEFAULT_TIMEOUT_S, max_retries=1)


def get_drona_async_client() -> AsyncOpenAI:
    """Async twin of get_drona_client(), for turns that stream the completion
    instead of blocking the event loop for the full call duration."""
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY or OPENAI_API_KEY is missing from environment")

    if os.getenv("DEEPSEEK_API_KEY"):
        return AsyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
            timeout=DEFAULT_TIMEOUT_S,
            max_retries=1,
        )

    return AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=DEFAULT_TIMEOUT_S, max_retries=1)

def get_model_name(service: str) -> str:
    """Returns the non-negotiable model string for each Drona service (R1)."""
    # Allow environment override if specific provider requires alias mapping
    if service == "planner":
        return os.getenv("DEEPSEEK_PLANNER_MODEL", MODEL_PLANNER)
    elif service in ("scoping", "tutor"):
        return os.getenv("DEEPSEEK_FLASH_MODEL", MODEL_SCOPING)
    return MODEL_TUTOR

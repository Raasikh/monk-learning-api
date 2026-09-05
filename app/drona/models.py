import os
from openai import OpenAI, AsyncOpenAI

# R1 — Non-negotiable Model Strings
MODEL_PLANNER = "deepseek-v4-pro"
MODEL_SCOPING = "deepseek-v4-flash"
MODEL_TUTOR = "deepseek-v4-flash"

# Segment authoring, split out from the planner 2026-08-15.
#
# The outline is one call and genuinely wants the stronger model: it decides how
# a subtopic is broken into segments, and everything downstream inherits that
# judgement. Segment authoring is the other 6-9 calls per plan, and it does not
# make that judgement - it fills in a structure the outline already fixed, from
# a stub naming the title, objective and teaching notes, into a hard-specified
# output shape (9-12 board items; checkpoint with question, model_answer,
# rubric). Those calls are ~85-90% of plan-authoring spend.
#
# Reversible in one environment variable, with no deploy:
#     DEEPSEEK_SEGMENT_MODEL=deepseek-v4-pro
#
# and measurable against the 115 plans already authored on Pro. _author_segment
# validates every segment and retries on failure, so a weaker model surfaces as
# retries in llm_calls rather than as quietly worse lessons.
MODEL_SEGMENT = "deepseek-v4-flash"

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
        # base_url is overridable. It was hardcoded, which meant a network that
        # cannot reach api.deepseek.com could not run the planner AT ALL --
        # not a model problem, a transport one: TCP connects and the TLS
        # handshake is reset by peer, while api.openai.com and openrouter.ai
        # negotiate fine from the same machine seconds apart.
        #
        # The default is unchanged, so production behaviour is identical.
        # Setting DEEPSEEK_BASE_URL (with DEEPSEEK_PLANNER_MODEL /
        # DEEPSEEK_SEGMENT_MODEL for the gateway's model naming) runs the same
        # weights through another gateway. Anything measured that way has an
        # extra network hop and its LATENCY is not comparable to production;
        # token counts and outputs are.
        return OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
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

def thinking_off() -> dict:
    """Body fragment that disables the model's reasoning pass.

    ONE definition, because there were two and they drifted. DeepSeek direct
    takes {"thinking": {"type": "disabled"}}; OpenRouter ignores that key and
    needs {"reasoning": {"enabled": false}}. diagram_author.py carried its own
    DeepSeek-only copy, so through a gateway its reasoning stayed ON, max_tokens
    was consumed by reasoning, and every call returned EMPTY content -- which
    surfaced as "does not start with <svg" and cost an entire chapter its
    diagrams while looking like a string-parsing bug.

    Both keys are sent; each gateway ignores the other's.
    """
    return {"thinking": {"type": "disabled"}, "reasoning": {"enabled": False}}


def get_model_name(service: str) -> str:
    """Returns the non-negotiable model string for each Drona service (R1)."""
    # Allow environment override if specific provider requires alias mapping
    if service == "planner":
        return os.getenv("DEEPSEEK_PLANNER_MODEL", MODEL_PLANNER)
    elif service == "segment":
        return os.getenv("DEEPSEEK_SEGMENT_MODEL", MODEL_SEGMENT)
    elif service in ("scoping", "tutor"):
        return os.getenv("DEEPSEEK_FLASH_MODEL", MODEL_SCOPING)
    return MODEL_TUTOR

import os
from openai import OpenAI

# R1 — Non-negotiable Model Strings
MODEL_PLANNER = "deepseek-v4-flash"
MODEL_SCOPING = "deepseek-v4-flash"
MODEL_TUTOR = "deepseek-v4-flash"

def get_drona_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY or OPENAI_API_KEY is missing from environment")

    # If DEEPSEEK_API_KEY is present, use DeepSeek base URL
    if os.getenv("DEEPSEEK_API_KEY"):
        return OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
    
    # Fallback to OpenAI endpoint if DeepSeek API key not present
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_model_name(service: str) -> str:
    """Returns the non-negotiable model string for each Drona service (R1)."""
    # Allow environment override if specific provider requires alias mapping
    if service == "planner":
        return os.getenv("DEEPSEEK_PLANNER_MODEL", MODEL_PLANNER)
    elif service in ("scoping", "tutor"):
        return os.getenv("DEEPSEEK_FLASH_MODEL", MODEL_SCOPING)
    return MODEL_TUTOR

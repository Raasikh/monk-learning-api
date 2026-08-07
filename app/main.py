import time
import asyncio
import logging
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.auth import get_current_user_id
from app.routers import practice

# Set up logger
logger = logging.getLogger("monk_api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(
    title="Monk Learning API",
    description="FastAPI backend service for Monk Learning practice questions & auth",
    version="0.1.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"] + settings.allowed_origins_list,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def verify_models_on_startup():
    logger.info("✅ [STARTUP] FastAPI application startup complete. Server ready.")


@app.middleware("http")
async def log_request_latency(request: Request, call_next):
    start_time = time.time()

    # Extract user identity hint from Authorization header if present
    auth_header = request.headers.get("authorization", "")
    user_hint = "authenticated" if auth_header.startswith("Bearer ") else "anonymous"

    response = await call_next(request)

    latency_ms = round((time.time() - start_time) * 1000, 2)
    logger.info(
        f"endpoint={request.url.path} method={request.method} status={response.status_code} "
        f"latency={latency_ms}ms user_hint={user_hint}"
    )

    return response


# Register routers
app.include_router(practice.router)

from app.routers.drona import router as drona_http_router
app.include_router(drona_http_router)

from app.drona.live_session_ws import router as drona_ws_router
app.include_router(drona_ws_router)



import os

@app.on_event("startup")
def validate_environment_startup():
    missing_always = []
    
    # Always required
    always_vars = [
        "ALLOWED_ORIGINS",
        "SUPABASE_URL",
        "SUPABASE_SECRET_KEY",
        "SUPABASE_JWKS_URL",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
    ]
    for var in always_vars:
        if not os.getenv(var, "").strip():
            missing_always.append(var)

    # Voice mode required (if VOICE_ENABLED == "true")
    missing_voice = []
    if os.getenv("VOICE_ENABLED", "").lower() == "true":
        voice_vars = ["SARVAM_API_KEY", "SARVAM_STT_ENDPOINT", "RUMIK_API_KEY", "RUMIK_TTS_ENDPOINT"]
        for var in voice_vars:
            if not os.getenv(var, "").strip():
                missing_voice.append(var)

    total_missing = missing_always + missing_voice
    if total_missing:
        error_msg = f"CRITICAL BUILD/DEPLOY FAILURE: Missing environment variables on Railway startup: {', '.join(total_missing)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    logger.info("Startup environment validation passed successfully.")

@app.get("/version", tags=["version"])
def version():
    return {"commit": os.getenv("RAILWAY_GIT_COMMIT_SHA", "unknown")}


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.get("/me", tags=["auth"])
def me(user_id: str = Depends(get_current_user_id)):
    return {"user_id": user_id}

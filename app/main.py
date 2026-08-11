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

# Silence noisy HTTP & platform libraries (§2.1)
for noisy_logger in ["httpx", "httpcore", "postgrest", "supabase", "gunicorn.access", "uvicorn.access"]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

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
    # Filler audio is NOT pre-warmed here any more. It only plays when Rumik
    # rate-limits or the connection pool is exhausted — rare enough that
    # synthesizing 12 clips on every boot cost more than it saved: ~20-45s of
    # Rumik connections competing with whoever was already in class on a
    # redeploy. FillerAudioCache now synthesizes lazily, in the background,
    # the first time a filler is actually asked for (that first occurrence
    # falls back to a brief silence).
    asyncio.create_task(platform_metrics_sampler_loop())


async def platform_metrics_sampler_loop():
    """Samples real provider load every 30s.

    This is the evidence behind any request to raise a provider's limits, so
    every field has to mean what its name says. Three did not:

    - active_sessions counted drona_sessions rows still in phase 'teaching',
      which includes every session ever abandoned mid-lesson (143 of them,
      against at most one live student). Now counts live WebSocket
      connections.
    - rumik_requests_last_60s counted connection OPENS, not synthesis
      requests — roughly a 4x undercount, since one connection carries a
      turn's several sentences. Now counts actual sends.
    - sarvam_requests_last_60s was assigned the session count, measuring
      nothing about Sarvam at all. Now counts real STT calls.
    """
    from app.drona.voice_proxy import RumikConnectionPool, stt_requests_last_60s
    from app.drona.live_session_ws import ACTIVE_SESSION_CONNECTIONS
    from app.db import supabase
    pool = RumikConnectionPool.get_instance()
    sample_counter = 0
    while True:
        await asyncio.sleep(30.0)
        sample_counter += 1
        try:
            live_sessions = sum(
                1 for rec in list(ACTIVE_SESSION_CONNECTIONS.values())
                if rec["state"].is_active
            )
            open_conns = len(pool.active_leases)
            opens_60s, sends_60s = pool.get_rate_usage()
            stt_60s = stt_requests_last_60s()

            if live_sessions > 0 or open_conns > 0 or sends_60s > 0:
                recent_waits = pool.acquisition_wait_times[-50:] if pool.acquisition_wait_times else [0]
                recent_waits_sorted = sorted(recent_waits)
                p95_idx = min(int(len(recent_waits_sorted) * 0.95), len(recent_waits_sorted) - 1)
                p95_wait = int(recent_waits_sorted[p95_idx])

                supabase.table("drona_platform_metrics").insert([{
                    "active_sessions": live_sessions,
                    "rumik_connections_open": open_conns,
                    "rumik_requests_last_60s": sends_60s,
                    "sarvam_requests_last_60s": stt_60s,
                    "p95_lease_acquisition_ms": p95_wait
                }]).execute()

                # Log summary ONLY once every 20 samples (10 minutes)
                if sample_counter % 20 == 0:
                    logger.info(
                        f"📊 [PLATFORM METRICS 10m] live_sessions={live_sessions} | rumik_conns_open={open_conns} "
                        f"| rumik_sends_60s={sends_60s} | rumik_opens_60s={opens_60s} | stt_60s={stt_60s} "
                        f"| p95_lease_wait={p95_wait}ms"
                    )
        except Exception as err:
            logger.warning(f"Platform metrics sampler non-fatal error: {err}")


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

from app.routers.notes import router as notes_router
app.include_router(notes_router)

from app.routers.doubts import router as doubts_router
app.include_router(doubts_router)



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

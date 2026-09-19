import time
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

# Must run before any app.* import below — several modules (e.g.
# app/drona/retrieval.py) construct an OpenAI client at IMPORT time from
# os.getenv(...), which raises immediately if the key isn't already in the
# process environment. Railway injects real env vars directly so this is a
# no-op there (load_dotenv never overrides an existing var), but a local
# process launcher that can't source .env itself — e.g. a dev-server tool
# spawning uvicorn directly — had no other way to get these vars in.
# Path-based rather than bare load_dotenv() so it finds the right .env
# regardless of the launching process's working directory.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import gzip as _gzip

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers, MutableHeaders
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

class GZipCompleteResponses:
    """gzip for whole responses only — never for a stream.

    Starlette's own GZipMiddleware compresses streaming bodies too, and gzip's
    internal buffering holds a small chunk back until enough bytes accumulate
    to emit a block. On an SSE endpoint that means audio frames and snap
    question events arrive late or in batches — exactly the latency the rest of
    this codebase spends its effort removing. (See the note on /speak-stream:
    the first sentence is meant to play at ~4s.)

    So the rule is narrow and checkable rather than clever: if the response
    arrives as more than one body chunk, it is a stream and passes through
    untouched. Only a complete, single-chunk body is ever compressed — which is
    every JSON endpoint, including the ones that actually hurt: /drona/catalogue
    (1,144 concepts), /progress (~130KB of chapter tree) and /doubts.
    """

    def __init__(self, app, minimum_size: int = 1024, compresslevel: int = 6):
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if "gzip" not in Headers(scope=scope).get("accept-encoding", "").lower():
            await self.app(scope, receive, send)
            return

        # The response.start message is held until the first body chunk tells us
        # whether this is a stream; nothing can be decided before then.
        held_start = None
        passthrough = False

        async def send_wrapper(message):
            nonlocal held_start, passthrough
            if passthrough:
                await send(message)
                return

            if message["type"] == "http.response.start":
                held_start = message
                return
            if message["type"] != "http.response.body":
                await send(message)
                return

            body = message.get("body", b"")

            async def release_uncompressed():
                nonlocal passthrough
                passthrough = True
                await send(held_start)
                await send(message)

            if message.get("more_body", False):
                await release_uncompressed()   # a stream: hands off for good
                return

            headers = MutableHeaders(raw=held_start["headers"])
            if len(body) < self.minimum_size or "content-encoding" in headers:
                await release_uncompressed()
                return

            compressed = _gzip.compress(body, compresslevel=self.compresslevel)
            if len(compressed) >= len(body):
                await release_uncompressed()   # already-compact bytes, e.g. a JPEG
                return

            headers["Content-Encoding"] = "gzip"
            headers["Content-Length"] = str(len(compressed))
            headers.add_vary_header("Accept-Encoding")
            passthrough = True
            await send(held_start)
            await send({"type": "http.response.body", "body": compressed,
                        "more_body": False})

        await self.app(scope, receive, send_wrapper)


app.add_middleware(GZipCompleteResponses, minimum_size=1024)

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
    # Filler audio is NOT pre-warmed here, for either surface.
    #
    # The classroom's was removed for cost: 12 clips on every boot cost
    # ~20-45s of Rumik connections competing with whoever was already in
    # class on a redeploy, and it only plays when Rumik rate-limits anyway.
    #
    # The follow-up's was built and then removed for a different reason — it
    # sounded wrong. A cached line cannot know what was asked, so it is
    # generic by construction, and a generic line in front of a specific
    # answer reads as a stall rather than as a teacher thinking. Rumik also
    # paces identical text differently between calls (0.061 vs 0.103 s/char on
    # the same sentence), so a cached clip's delivery never quite matches the
    # live sentence behind it. Auditioning the take fixed the dragging and not
    # the mismatch.
    #
    # So the follow-up simply starts when its first sentence is ready: 1.9-3.8s
    # measured, median 2.5s, of which most is Rumik's own first-byte time.
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
    from app.db import supabase, aexec
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

                fields = {
                    "active_sessions": live_sessions,
                    "rumik_connections_open": open_conns,
                    "rumik_requests_last_60s": sends_60s,
                    "sarvam_requests_last_60s": stt_60s,
                    "p95_lease_acquisition_ms": p95_wait,
                }

                # Multi-worker: each worker reports its own 30s sample, ONE
                # worker holds the leader lock and writes the summed row —
                # otherwise N workers write N partial rows and every column
                # stops meaning what its name says. Without Redis this worker
                # is the only one, and it writes its own numbers as ever.
                from app import redis_store
                row = fields
                if await redis_store.metrics_report(fields):
                    total = await redis_store.metrics_aggregate_if_leader()
                    if total is None:
                        continue  # another worker is the leader this cycle
                    row = {k: total.get(k, fields[k]) for k in fields}

                # Threaded: this sampler runs every 30s for the life of the
                # process, and a blocking insert here stalls the event loop —
                # and therefore every live class — to write a metrics row.
                await aexec(lambda: supabase.table("drona_platform_metrics")
                            .insert([row]).execute())

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

from app.routers.progress import router as progress_router
app.include_router(progress_router)

from app.routers.doubt_of_day import router as doubt_of_day_router
app.include_router(doubt_of_day_router)

# The founders' dashboard. Every /admin/api/* route answers 404 unless the
# caller's email is on ADMIN_EMAILS — see require_admin in app/auth.py.
from app.routers.admin import router as admin_router
app.include_router(admin_router)



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

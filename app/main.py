import time
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
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


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


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.get("/me", tags=["auth"])
def me(user_id: str = Depends(get_current_user_id)):
    return {"user_id": user_id}

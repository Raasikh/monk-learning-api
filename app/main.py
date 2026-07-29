from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.auth import get_current_user_id
from app.routers import practice

app = FastAPI(
    title="Monk Learning API",
    description="FastAPI service for Monk Learning practice questions & auth",
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

# Register routers
app.include_router(practice.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.get("/me", tags=["auth"])
def me(user_id: str = Depends(get_current_user_id)):
    return {"user_id": user_id}

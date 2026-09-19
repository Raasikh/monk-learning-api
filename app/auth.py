import logging

import jwt
from jwt import PyJWKClient
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.config import settings

logger = logging.getLogger("monk_api")

security = HTTPBearer(auto_error=False)

# Shared PyJWKClient instance with key caching enabled.
# PyJWKClient matches token 'kid', caches keys, and automatically refetches on unknown 'kid'.
_jwk_client: Optional[PyJWKClient] = None


def get_jwk_client() -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        if not settings.SUPABASE_JWKS_URL:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server authentication misconfiguration (SUPABASE_JWKS_URL not set)",
            )
        _jwk_client = PyJWKClient(settings.SUPABASE_JWKS_URL, cache_keys=True)
    return _jwk_client


def decode_supabase_jwt(token: str) -> str:
    """Verifies a Supabase access token and returns its user_id ('sub').

    Shared by the REST dependency below and the WebSocket handshake in
    live_session_ws.py — a WebSocket has no Authorization header to hang a
    Depends() off, so it calls this directly on the token it pulls from
    ?token= and translates the raised jwt exceptions into a close code
    itself. Raises the same jwt.* exceptions get_current_user_id catches;
    callers must handle jwt.ExpiredSignatureError / jwt.PyJWKClientError /
    jwt.InvalidTokenError (or let them propagate, for REST).
    """
    jwk_client = get_jwk_client()
    signing_key = jwk_client.get_signing_key_from_jwt(token)
    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256", "HS256", "RS256"],
        options={"verify_aud": False}  # Supabase tokens carry aud='authenticated'
    )

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise jwt.InvalidTokenError("Token payload missing user_id ('sub')")
    return user_id


def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> str:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return decode_supabase_jwt(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (jwt.PyJWKClientError, jwt.InvalidTokenError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authorization token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Admin access — the founders' dashboard at /admin, and nothing else.
# ─────────────────────────────────────────────────────────────────────────────

def decode_supabase_claims(token: str) -> dict:
    """Same verification as decode_supabase_jwt, but returns the whole payload.

    The dashboard gates on `email`, not `sub`: a UUID allowlist means pasting
    two opaque strings into Railway and re-reading them from the auth schema
    every time you wonder who has access. The email claim is only present on
    a verified email sign-in, which is the only kind this product issues
    (see the note at the top of lib/auth.ts in the mobile app).
    """
    jwk_client = get_jwk_client()
    signing_key = jwk_client.get_signing_key_from_jwt(token)
    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256", "HS256", "RS256"],
        options={"verify_aud": False},
    )
    if not payload.get("sub"):
        raise jwt.InvalidTokenError("Token payload missing user_id ('sub')")
    return payload


class AdminIdentity:
    __slots__ = ("user_id", "email")

    def __init__(self, user_id: str, email: str):
        self.user_id = user_id
        self.email = email


def require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> AdminIdentity:
    """Admin-or-404.

    Every failure — no token, bad token, good token belonging to a student —
    answers 404, not 401/403. A 403 confirms the route exists and that the
    caller merely lacks a role, which tells someone probing the API exactly
    where to keep pushing. To anyone not on the allowlist, /admin is simply
    not a thing this server has.

    An empty ADMIN_EMAILS closes the door rather than opening it: an env var
    that gets dropped in a Railway redeploy must not silently expose every
    student's row to any signed-in account.
    """
    allow = settings.admin_emails_set
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    if not allow:
        logger.warning("[admin] rejected: ADMIN_EMAILS is unset, dashboard is closed")
        raise not_found
    if not credentials or not credentials.credentials:
        raise not_found

    try:
        claims = decode_supabase_claims(credentials.credentials)
    except (jwt.ExpiredSignatureError, jwt.PyJWKClientError, jwt.InvalidTokenError):
        raise not_found

    email = (claims.get("email") or "").strip().lower()
    if not email or email not in allow:
        # Logged because on a two-person allowlist, a miss is either one of
        # you on the wrong account or someone who should not be here at all.
        logger.warning(
            "[admin] rejected: user_id=%s email=%s not on allowlist",
            claims.get("sub"), email or "<none>",
        )
        raise not_found

    return AdminIdentity(user_id=claims["sub"], email=email)

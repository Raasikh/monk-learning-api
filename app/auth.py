import jwt
from jwt import PyJWKClient
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.config import settings

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

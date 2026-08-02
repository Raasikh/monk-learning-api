from typing import Optional
from supabase import create_client, Client
from app.config import settings

_supabase_client: Optional[Client] = None


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SECRET_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set in environment variables")
        _supabase_client = create_client(
            supabase_url=settings.SUPABASE_URL,
            supabase_key=settings.SUPABASE_SECRET_KEY
        )
    return _supabase_client


# Module-level property proxy or lazy getter for backward compatibility
class LazySupabase:
    def __getattr__(self, name):
        return getattr(get_supabase(), name)


supabase = LazySupabase()

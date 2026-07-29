from supabase import create_client, Client
from app.config import settings

# Single shared Supabase client instance created with the SECRET key (bypasses RLS)
supabase: Client = create_client(
    supabase_url=settings.SUPABASE_URL,
    supabase_key=settings.SUPABASE_SECRET_KEY
)

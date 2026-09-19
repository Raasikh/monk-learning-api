import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SUPABASE_URL: str = ""
    SUPABASE_SECRET_KEY: str = ""
    SUPABASE_JWKS_URL: str = ""
    ALLOWED_ORIGINS: str = ""

    # The anon/publishable key — the same one the mobile app ships
    # (EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY). Public by design: it is inlined
    # into every app bundle already. The API needs it only to hand to the
    # /admin sign-in page, which authenticates with the same email OTP
    # students use rather than inventing a second password system.
    SUPABASE_PUBLISHABLE_KEY: str = ""

    # Comma-separated email allowlist for /admin. Empty means the dashboard is
    # closed to everyone — a missing env var must not fail open.
    ADMIN_EMAILS: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def allowed_origins_list(self) -> List[str]:
        if not self.ALLOWED_ORIGINS:
            return []
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def admin_emails_set(self) -> set:
        """Lowercased, so the allowlist can't be defeated by capitalisation.

        Supabase stores addresses lowercased and the `email` claim comes back
        the same way, but the env var is typed by a human.
        """
        return {
            e.strip().lower()
            for e in self.ADMIN_EMAILS.split(",")
            if e.strip()
        }


settings = Settings()

# Monk Learning API

FastAPI backend service for Monk Learning practice questions & auth verification.

## Repository Structure

```
monk-learning-api/
  app/
    main.py            FastAPI app, CORS, router registration
    config.py          env var loading (pydantic-settings)
    auth.py            Supabase JWT verification dependency (JWKS / ES256)
    db.py              Supabase client using the SECRET key
    routers/
      practice.py      Practice questions & submission endpoints
  requirements.txt
  Procfile
  railway.toml
  README.md
  .gitignore           (.env ignored)
```

## Environment Variables

- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_SECRET_KEY`: Supabase service role / secret key (bypasses RLS)
- `SUPABASE_JWKS_URL`: JWKS endpoint URL (`https://tgbknrmnjwiokraddurx.supabase.co/auth/v1/.well-known/jwks.json`)
- `ALLOWED_ORIGINS`: Comma-separated list of allowed CORS origins

## Running Locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

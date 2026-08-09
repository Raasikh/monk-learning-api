# 📦 `app/` — FastAPI Core Application

The `app/` directory houses the complete backend application source code for **Monk Learning API**. It powers the REST HTTP endpoints, Supabase database connections, authentication middleware, and Drona AI Tutoring Engine.

---

## 📂 Subdirectory Architecture

```text
app/
 ├── routers/             # FastAPI HTTP REST endpoint controllers
 ├── drona/               # Core Drona AI Tutor engine (LLM, Voice, WS, Pacing)
 ├── auth.py              # Supabase JWT authentication middleware
 ├── config.py            # Environment configurations & model settings
 ├── db.py                # Supabase PostgreSQL client initialization
 └── main.py              # Application entrypoint & platform telemetry sampler
```

---

## 🛠️ Module Overview

### 1. `main.py`
- Initializes the FastAPI application instance.
- Configures CORS middleware for Vercel production domains.
- Launches background telemetry tasks (`platform_metrics_sampler_loop`) and pre-warms filler voice audio cache on boot.
- **Log Noise Reduction**: Silences noisy HTTP libraries (`httpx`, `supabase`, `uvicorn.access`) to `WARNING` level.

### 2. `auth.py`
- Handles Supabase JWT token verification (`get_current_user_id`).
- Secures REST API routes and enforces user ownership checks.

### 3. `db.py`
- Instantiates the Supabase PostgreSQL client using system environment keys (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`).

### 4. `config.py`
- Centralized configuration settings loader parsing environment variables.

---

> [!NOTE]
> All core AI tutoring logic, WebSocket handlers, and voice synthesis connection pools reside inside [`app/drona/`](file:///Users/raasikhnaveed/Desktop/monk-learning-api/app/drona/README.md).

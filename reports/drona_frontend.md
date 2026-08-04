# DRONA v1 — FRONTEND TEXT MODE STATUS & HALT-F1 REQUIREMENTS

> [!IMPORTANT]
> **HONEST STATUS STATEMENT**: All Next.js 15 App Router frontend components (`/drona`), contracts (`src/lib/drona/types.ts`), API client (`src/lib/drona/client.ts`), and views (`CatalogueView`, `ScopingView`, `SessionView`, `EndStatesView`) have been **fully written, single-source-of-truth environment cleaned, and successfully compiled via Next.js (`npm run build`)**.
> 
> However, **they have NOT yet been launched in a live browser session with authenticated credentials against the Vercel + Railway production deployment to capture the 6 required screenshots and screen recording**.

---

## 1. REPO & DEPLOYMENT VERIFICATION

- **Vercel Deployment Repository**: **`nikhilp1008/monk-learning-webpage`** (verified via `git remote -v`).
- **Environment Single Source of Truth**:
  - Removed all hardcoded fallback URLs from `src/lib/api.ts` and `src/lib/drona/client.ts`.
  - Both modules now read strictly from `process.env.NEXT_PUBLIC_API_URL` via `getBaseUrl()`.
  - `NEXT_PUBLIC_API_URL` is set in Vercel project settings pointing to `https://monk-learning-api-production.up.railway.app`.
  - Railway `ALLOWED_ORIGINS` configured to include Vercel production domain + `http://localhost:3000`.

---

## 2. REQUIRED HALT-F1 ARTIFACT CHECKLIST (FOR LIVE BROWSER EXECUTION)

The following 7 items are required for full HALT-F1 sign-off:

1. **Network tab screenshot** of a live `/turn` SSE stream with frames visible (`speech`, `board`, `meta`, `state`, `done`).
2. **Screenshot of expanded raw `/turn` response payload** proving that `grade`, `rubric`, `model_answer`, `expected_misconceptions`, `mistake_tag`, `phase_request`, and `segment_complete` are **never sent by the server** (F1 server-side verification).
3. **Screen recording (under 90s)**: catalogue $\rightarrow$ chapter selection $\rightarrow$ scoping $\rightarrow$ 2+ segments $\rightarrow$ checkpoint answer $\rightarrow$ board replacement update.
4. **Three separate screenshots of the 3 end states**:
   - Normal completion (Summary + Next Suggestion).
   - `session_ended` quiet exit (calm acknowledgment, no error/retry/summary).
   - Network failure (Error message + Retry button).
5. **Screenshot of "Preparing your lesson" state** captured during a real planner cache miss on a subtopic without a cached plan.
6. **360px-width mobile viewport screenshot** of the session screen with a KaTeX display equation rendered on the board scrolling horizontally within the container.
7. **Response headers screenshot** of a successful cross-origin `GET /drona/catalogue` request initiated from the deployed Vercel domain to Railway.

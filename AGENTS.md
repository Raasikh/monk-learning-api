# AGENTS.md — conventions for AI agents working in this repo

## Model choice: prefer Claude/Opus agents over DeepSeek API calls

**Default to Claude (Opus) subagents for any authoring, generation, analysis, or
review task done during development.** Do not reach for a DeepSeek API call
just because `app/drona/models.py` makes one easy.

DeepSeek is the **product's runtime model** — it serves live student traffic
(tutor turns, scoping, planner, snap solver) because it is cheap and fast at
that scale. It is not the right tool for development-time work, where quality
matters more than per-call cost.

**Use a Claude/Opus agent for:**
- Generating or curating content — subtopics, concept taxonomies, question
  banks, lesson plan drafts, seed data
- Auditing or reviewing existing content for correctness
- Code review, refactors, multi-file analysis
- Anything whose output a human will read, ship, or store permanently

**Use a DeepSeek call only when:**
- You are testing the live product path itself and need the *actual* model the
  student will hit — e.g. `tests/drona/test_guardrails.py`, which must validate
  `prompts/tutor.md` against the real runtime model, not a stand-in. Validating
  a prompt against a model that never serves it proves nothing.
- You are measuring latency, cost, or token usage of the production pipeline

When adding a script that calls an LLM, state in a comment which of the two it
is and why. A dev-time script quietly using DeepSeek to save pennies is the
failure mode this rule exists to prevent.

## Runtime model wiring (for reference)

`app/drona/models.py` is the single source of truth for the production models:

| Service | Model |
|---|---|
| planner | `deepseek-v4-pro` |
| scoping, tutor | `deepseek-v4-flash` |

Always go through `get_drona_client()` / `get_model_name(...)` rather than
constructing an `OpenAI()` client inline — a hand-rolled client that forgets
`base_url` silently talks to OpenAI with a DeepSeek model string and 404s.

## Secrets and local runs

`app/main.py` calls `load_dotenv()` before importing anything under `app.*`,
because several modules build API clients at import time from `os.getenv`.
Local servers therefore start without a pre-sourced shell. Do not move that
call below the `app.*` imports.

## Two-repo contract

The API (this repo) and `monk-learning-web` share a WebSocket/SSE contract.
Changing an event's shape means changing both repos in the same pass — see
`app/drona/live_session_ws.py` and `src/lib/drona/voice.ts`.

Keys in `FORBIDDEN_SSE_KEYS` / the WS equivalent must never reach the client:
they are the answer key, rubric, and grading internals. Adding a new
teacher-only field means adding it to that set in the same change.

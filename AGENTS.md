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

## Diagram-question pipeline (data/nta_raw)

The raw diagram-question corpus is built by ordered passes; later passes
overwrite earlier row-level edits, so **re-running a pass means re-running
everything after it**:

1. `extract_nta_papers.py` (harvest → probe → extract) → paper artifacts in
   `data/nta_raw/papers/`
2. `extract_diagram_questions.py` (scan → **materialize**) →
   `data/nta_raw/diagram_questions.jsonl` (regenerated from scratch)
3. `merge_diagram_regions.py` (same-text multi-region merge)
4. `apply_classification.py` (chapter/concept/difficulty from
   `scratch/classify_results/`, produced by subagent classification of
   `scratch/classify_batches/`)
5. tiny-crop quarantine + `upload_diagram_assets.py` (R2 `diagram` arrays)
6. `repair_directive4_pass1.py` (terminal: option-leak/ExamSIDE-chrome strip,
   option-figure detection + `option_figures` concept, residue quarantines)
7. `enforce_pending_gate_eligibility.py` (terminal: `pending_gate` only if the
   row could pass `is_quality_question` — 4 covered options (text or option
   image), or numerical with numeric key, else a specific quarantine reason)

Supporting passes (run before materialize to have effect): `stem_hygiene.py`,
`repair_text_fidelity.py`, `repair_options.py`,
`ocr_extract_scanned_papers.py`, `join_nta_answer_keys.py`,
`positional_key_join_2022.py`, `extract_solutions_mined.py`,
`reattribute_figures.py` (span/column/text attribution of figures to
questions — the pipeline's hard-won lesson: NEVER pair figures to questions
by page adjacency), then full-corpus vision verification
(`scratch/vision_batches/` → subagent verdicts in `scratch/vision_results/`,
fails dropped; a fresh >=50-row human-judged sample must pass 95% before any
row ships with a figure).

Proof/lint after any change: `corpus_proof_report.py` (§4 plausibility
numbers — key distribution, self-consistency, funnel, asset integrity, text
fidelity) and `verify_diagram_questions.py` (structural lint).

Hard rules: nothing in `data/nta_raw/*.jsonl` is servable — every row carries
`needs_manual`; never write to the live `questions` or `chapters` tables;
`data/nta_raw/diagram_assets/` stays gitignored (assets live in R2).

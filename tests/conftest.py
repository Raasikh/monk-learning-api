"""Shared test guards.

Accounting must never leave the building during a test run: `record_call`
inserts into the real `llm_calls` table whenever Supabase env is configured
(which it is, on every dev machine with a .env). Left live, the suite pollutes
production accounting with stub calls and adds a network round-trip inside the
solver's thread pool — enough latency to reorder the shared-queue stubs in the
parallel-solve tests.

`from app.drona.usage import record_call` binds the name into each importing
module, so the source module and every known importer are patched.
"""
import sys

import pytest


@pytest.fixture(autouse=True)
def _no_llm_call_recording(monkeypatch):
    def noop(*args, **kwargs):
        return None

    import app.drona.usage as usage
    monkeypatch.setattr(usage, "record_call", noop)
    monkeypatch.setattr(usage, "record_call_bg", noop)
    for mod_name in ("app.snap", "app.drona.planner"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "record_call"):
            monkeypatch.setattr(mod, "record_call", noop)

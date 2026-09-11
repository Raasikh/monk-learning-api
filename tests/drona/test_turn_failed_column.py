"""The failed-turn audit record must actually be insertable.

Found 2026-09-11: `drona_turns` had no `turn_failed` column, and PostgREST
rejects an insert naming an unknown column outright (PGRST204) rather than
ignoring it. Since tutor.py sets that key ONLY when a turn failed, the result
was that every failed turn was absent from the table — successful turns wrote
cleanly, failures wrote nothing, and the insert's try/except logged it at
WARNING where nobody read it. Any failure rate over the table read 0% by
construction, right through an outage that failed every turn for hours.

These tests are schema-shape tests against the live table. They are skipped
when the database is unreachable so a laptop without credentials does not
report a green suite it never ran — a silent skip and a pass are not the same
result, so the skip says why.
"""
import pytest

try:
    from app.db import supabase
    _rows = supabase.table("drona_turns").select("*").limit(1).execute().data
    _reachable = True
    _reason = ""
except Exception as e:  # pragma: no cover - environment dependent
    _rows, _reachable, _reason = [], False, str(e)[:120]

pytestmark = pytest.mark.skipif(
    not _reachable, reason=f"drona_turns unreachable: {_reason}"
)

# A row is needed to read the column set off. An empty table is not a pass:
# it means this file proved nothing, and it should say so rather than be green.
_has_row = bool(_rows)


@pytest.mark.skipif(not _has_row, reason="drona_turns is empty; no shape to read")
def test_turn_failed_column_exists():
    # migrations/0042 adds it. Before that migration is applied this FAILS,
    # which is the point: the failing fixture is the production state.
    assert "turn_failed" in _rows[0], (
        "drona_turns has no turn_failed column — every failed turn is being "
        "rejected wholesale (PGRST204). Apply migrations/0042."
    )


@pytest.mark.skipif(not _has_row, reason="drona_turns is empty; no shape to read")
def test_turn_failed_is_never_null():
    # NOT NULL DEFAULT false, so a row written before 0042 reads false rather
    # than becoming a third state meaning "written by an older build".
    assert _rows[0].get("turn_failed") is not None


def test_a_failed_turn_payload_is_accepted():
    """The exact payload shape tutor.py sends for a failed turn."""
    probe = {
        "session_id": "00000000-0000-0000-0000-000000000000",
        "turn_index": 1,
        "segment_index": 1,
        "phase_in": "teaching",
        "turn_failed": True,
    }
    try:
        supabase.table("drona_turns").insert([probe]).execute()
    except Exception as e:
        msg = str(e)
        if "PGRST204" in msg or "turn_failed" in msg:
            pytest.fail(
                "drona_turns rejected a failed-turn insert on the turn_failed "
                f"column — apply migrations/0042. Server said: {msg[:200]}"
            )
        # Any other rejection (a foreign key on the all-zero session_id, a
        # NOT NULL elsewhere) means the COLUMN was accepted, which is what
        # this test is about. Distinguishing them matters: treating an FK
        # error as failure would make this test unfixable by the migration.
        assert "turn_failed" not in msg
    else:  # pragma: no cover - only when the FK permits the probe row
        supabase.table("drona_turns").delete().eq(
            "session_id", probe["session_id"]
        ).eq("turn_index", 1).execute()

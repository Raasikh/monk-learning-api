"""Turn processor for practice_explain Drona sessions.

A practice_explain session is a disposable, question-scoped "talk to the
teacher" conversation launched from the Practice page after a student answers
a question — not a lesson. The whole turn mechanic lives in
app/drona/scoped_turn.py, shared with doubt_of_day; this module only binds the
four things that are specific to this mode (prompt, seed column, seed label,
log tag).
"""
from typing import Any, AsyncGenerator, Dict

from app.drona.scoped_turn import process_scoped_turn_stream, sanitize_board_events  # noqa: F401


async def process_practice_explain_turn_stream(
    session: Dict[str, Any],
    user_id: str,
    utterance: str | None,
    turn_type: str,
) -> AsyncGenerator[str, None]:
    async for chunk in process_scoped_turn_stream(
        session,
        user_id,
        utterance,
        turn_type,
        mode_label="practice_explain",
        prompt_file="tutor_practice_explain.md",
        seed_key="practice_seed",
        seed_header="PRACTICE QUESTION",
    ):
        yield chunk

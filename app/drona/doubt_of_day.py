"""Turn processor for doubt_of_day Drona sessions.

Launched from the dashboard's doubt-of-the-day card: a two-minute chat about
one curated doubt, where the teacher asks for the student's own guess before
revealing anything, then gives the answer and the mechanism behind it and
lets the session end.

The turn mechanic is shared with practice_explain — see
app/drona/scoped_turn.py. Only two things differ from that mode beyond the
prompt and seed column: the opening turn mounts guess chips instead of
understanding chips (nothing has been explained yet for "that's clear" to
mean anything), and the seed carries a verified `answer`/`explanation` pair
that the prompt treats as ground truth.
"""
from typing import Any, AsyncGenerator, Dict

from app.drona.persona import GUESS_CHIPS
from app.drona.scoped_turn import process_scoped_turn_stream


async def process_doubt_of_day_turn_stream(
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
        mode_label="doubt_of_day",
        prompt_file="tutor_doubt_of_day.md",
        seed_key="doubt_seed",
        seed_header="DOUBT",
        opening_chips=GUESS_CHIPS,
    ):
        yield chunk

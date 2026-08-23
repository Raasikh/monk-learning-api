"""Which exam a student is entitled to, and what that entitles them to see.

The exam is an ENTITLEMENT, not a preference: it is what the student paid for,
written to `profiles.target_exam` at onboarding ('JEE', 'NEET', or 'both').

Progress has resolved it correctly since it was built, but nothing else did —
so the Learn catalogue served every student the whole corpus. A NEET student
was offered all 27 Mathematics chapters, which are not on their syllabus at
all, plus the 316 JEE-only concepts tagged inside the physics and chemistry
chapters they do share. A JEE student was offered the 32 Biology chapters and
350 NEET-only concepts the same way. The tags to prevent that were already on
every one of the 1,144 concept rows; nothing read them.

This module is that reading, in one place, so the catalogue and Progress cannot
drift apart on what a student is entitled to.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SUBJECTS_BY_EXAM: Dict[str, List[str]] = {
    "jee": ["physics", "chemistry", "mathematics"],
    "neet": ["physics", "chemistry", "biology"],
}


def entitlement_of(profile: Optional[Dict[str, Any]]) -> str:
    """'jee', 'neet', or 'both' from a profile row.

    Defaults to 'jee' for a missing or unreadable profile, matching Progress:
    an unknown entitlement shows the larger shared syllabus rather than an
    empty catalogue, so a profile problem does not look like missing content.
    """
    raw = str((profile or {}).get("target_exam") or "").strip().lower()
    if "both" in raw:
        return "both"
    return "neet" if "neet" in raw else "jee"


def allowed_exams(entitlement: str) -> Tuple[str, ...]:
    """The exam views this entitlement may request."""
    return ("jee", "neet") if entitlement == "both" else (entitlement,)


def resolve_exam(profile: Optional[Dict[str, Any]], requested: Optional[str] = None) -> str:
    """The exam view to serve: the request when the student is entitled to it,
    otherwise their entitlement. A 'both' student may switch views with
    ?exam=; everyone else gets what they paid for regardless of what is asked
    for, which is what makes this an entitlement check and not a filter.
    """
    allowed = allowed_exams(entitlement_of(profile))
    req = str(requested or "").strip().lower()
    return req if req in allowed else allowed[0]


def subjects_for(exam: str) -> Sequence[str]:
    """Subject names on this exam's syllabus, lowercased. 'both' gets the union."""
    if exam == "both":
        return ["physics", "chemistry", "mathematics", "biology"]
    return SUBJECTS_BY_EXAM.get(exam, SUBJECTS_BY_EXAM["jee"])


def subject_on_syllabus(subject: Optional[str], exam: str) -> bool:
    return str(subject or "").strip().lower() in set(subjects_for(exam))


def tagged_for_exam(exams_val: Any, exam: str) -> bool:
    """Whether a concept's `exams` tag covers this exam view.

    Untagged content is treated as SHARED, not hidden. All 1,144 concepts are
    tagged today, so this branch is unreachable now — but if a new concept ever
    lands without tags, showing it to everyone is a visible, fixable mistake,
    whereas hiding it looks exactly like a chapter that was never authored.
    That failure mode is the one that costs a day to diagnose.
    """
    if exam == "both" or not exams_val:
        return True
    if isinstance(exams_val, str):
        vals: Iterable[Any] = [exams_val]
    else:
        vals = exams_val
    return any(exam in str(v).strip().lower() for v in vals)

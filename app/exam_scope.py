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

The two surfaces ask DIFFERENT questions of it, and the difference is
deliberate:

  - Progress asks `resolve_exam` — an ENTITLEMENT. A score is always computed
    against the exam the student paid for, and ?exam= only picks a view for a
    'both' student. It is not a thing to be opted out of.

  - The Learn catalogue asks `selected_exam` — a SELECTION. It shows the whole
    corpus until a student actively picks an exam, and narrows only then.
    Unfiltered is the deliberate default while the catalogue is still being
    tested across all four subjects; a filter that hides content by default
    makes "is this chapter broken?" and "is this chapter hidden?" look
    identical, which is the harder question to answer.
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


def selected_exam(requested: Optional[str] = None) -> str:
    """The exam view for a SELECTION-driven surface: the Learn catalogue.

    Returns 'both' — the whole corpus, nothing hidden — unless the caller names
    a specific exam. This is the opposite default from `resolve_exam`, and
    intentionally so: nothing narrows the catalogue until a student picks, so
    the picker itself is the only thing that can hide a chapter.
    """
    req = str(requested or "").strip().lower()
    return req if req in ("jee", "neet") else "both"


def subjects_for(exam: str) -> Sequence[str]:
    """Subject names on this exam's syllabus, lowercased. 'both' gets the union."""
    if exam == "both":
        return ["physics", "chemistry", "mathematics", "biology"]
    return SUBJECTS_BY_EXAM.get(exam, SUBJECTS_BY_EXAM["jee"])


def subject_on_syllabus(subject: Optional[str], exam: str) -> bool:
    return canonical_subject(subject) in set(subjects_for(exam))


# ─── One name per subject ────────────────────────────────────────────────────
#
# The corpus decided this vocabulary long ago: `chapters` and `questions` store
# lowercase physics / chemistry / mathematics / biology across 828 rows, and
# SUBJECTS_BY_EXAM above is written in the same terms. Anything that wants to
# group, join or filter by subject has to speak it.
#
# Snapped doubts did not. The models label accurately and spell freely, so the
# same subject arrived as "Maths", "Mathematics" and "mathematics", and
# "Chemistry" beside "chemistry" — correctly classified rows that an equality
# filter could not see. Normalising per-caller is how that happens twice, so it
# lives here with the vocabulary it has to match.
#
# What a student READS is a separate question from what we store: "mathematics"
# is the key, "Math" is the label.
_SUBJECT_ALIASES = {
    "math": "mathematics", "maths": "mathematics", "mathematics": "mathematics",
    "phys": "physics", "physics": "physics",
    "chem": "chemistry", "chemistry": "chemistry",
    "bio": "biology", "biology": "biology",
}

DISPLAY_LABEL: Dict[str, str] = {
    "physics": "Physics",
    "chemistry": "Chemistry",
    "mathematics": "Math",
    "biology": "Biology",
}


def canonical_subject(raw: Any) -> Optional[str]:
    """The corpus's name for this subject, or None when it is not one.

    None rather than a placeholder: `doubts.subject` already uses NULL for "no
    subject read", which is what an unreadable photo leaves behind.
    """
    value = str(raw or "").strip().lower()
    if not value:
        return None
    if value in _SUBJECT_ALIASES:
        return _SUBJECT_ALIASES[value]
    # Prefix matching, but ONLY on something short enough to be one subject
    # word. A structurer once echoed the schema placeholder
    # "Physics|Chemistry|Maths|Biology|unknown", which starts with "phys" — a
    # loose match files that under Physics, which is a confident wrong answer
    # to "which subject" and worse than admitting we do not know.
    if len(value) > 16 or any(sep in value for sep in "|,/;"):
        return None
    for prefix in ("math", "phys", "chem", "bio"):
        if value.startswith(prefix):
            return _SUBJECT_ALIASES[prefix]
    return None


def display_subject(raw: Any) -> Optional[str]:
    """What a student should see: 'Math', 'Physics', … or None."""
    canon = canonical_subject(raw)
    return DISPLAY_LABEL.get(canon) if canon else None


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

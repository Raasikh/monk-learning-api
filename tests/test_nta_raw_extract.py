"""Tests for the deterministic NTA raw-extraction parsers.

No network, no PDFs: parsers operate on synthetic per-page text layers.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import extract_nta_papers as x  # noqa: E402


SAMPLE_2026 = [
    # page 1 — mirrors the real NTA 2026 layout: boilerplate field lines,
    # "Options :" followed by option-ID lines, section headings for subject.
    "National Testing Agency\n"
    "Question Paper Name : B Tech 2nd Apr 2026 Shift 1\n"
    "Mathematics Section A\n"
    "Question Number : 1 Question Id : 6911201 Question Type : MCQ "
    "Option Shuffling : Yes Display Question Number : Yes\n"
    "Is Question Mandatory : No Single Line Question Option : No "
    "Option Orientation : Vertical\n"
    "A particle moves in a circle of radius 2 m with constant speed 4 m/s. "
    "The magnitude of its centripetal acceleration is\n"
    "Options :\n"
    "69112011. 2 m/s2\n"
    "69112012. 4 m/s2\n"
    "69112013. 8 m/s2\n"
    "69112014. 16 m/s2\n"
    "Question Number : 2 Question Id : 6911202 Question Type : SA "
    "Display Question Number : Yes Keyboard Layout : Inscript\n"
    "Response Type : Numeric\n"
    "Evaluation Required For SA : Yes\n"
    "Show Word Count : Yes\n"
    "Answers Type : Equal\n"
    "Text Areas : PlainText\n"
    "Possible Answers :\n1\n"
    "If the sum of the roots of x^2 - 5x + 6 = 0 is S, then S equals\n",
    # page 2
    "Physics Section A\n"
    "Question Number : 3 Question Id : 6911203 Question Type : MCQ "
    "Option Shuffling : Yes Display Question Number : Yes\n"
    "Is Question Mandatory : No Single Line Question Option : No "
    "Option Orientation : Vertical\n"
    "Which of the following is a noble gas configuration element?\n"
    "Options :\n"
    "69112031. Sodium\n"
    "69112032. Argon\n"
    "69112033. Calcium\n"
    "69112034. Iron\n",
]

SAMPLE_2022 = [
    "Q:1\n"
    "Topic Name:Mathematics-Section A\n"
    "ItemCode:101665\n"
    "Let f(x) = x^2 + 3x + 2. The value of f(1) is equal to\n"
    "(1) 4\n"
    "(2) 5\n"
    "(3) 6\n"
    "(4) 7\n"
    "Q:2\n"
    "Topic Name:Mathematics-Section B\n"
    "ItemCode:101666\n"
    "If the determinant of the matrix A is 5, then the determinant of 2A, "
    "where A is of order 3, is (round off to the nearest integer)\n",
]

SAMPLE_GENERIC = [
    "JEE MAIN 2024 SHIFT 1\n"
    "1. A body of mass 2 kg is thrown vertically upwards with speed 10 m/s. "
    "The maximum height reached is approximately\n"
    "(1) 2 m\n"
    "(2) 5 m\n"
    "(3) 10 m\n"
    "(4) 20 m\n"
    "2. The dimensional formula of Planck's constant is the same as that of\n"
    "(1) force\n"
    "(2) energy\n"
    "(3) angular momentum\n"
    "(4) power\n",
    "Solutions\n"
    "1. (2) Using v^2 = u^2 - 2gh we get h = 5 m\n"
    "2. (3) Angular momentum has dimensions ML2T-1\n",
]


def test_detect_format_2026():
    assert x.detect_format(SAMPLE_2026) == x.FMT_2026


def test_detect_format_2022():
    assert x.detect_format(SAMPLE_2022) == x.FMT_2022


def test_detect_format_generic():
    assert x.detect_format(SAMPLE_GENERIC) == x.FMT_GENERIC


def test_parse_2026():
    out = x.extract_paper(SAMPLE_2026)
    assert out["status"] == "extracted"
    assert out["format"] == x.FMT_2026
    assert out["question_count"] == 3
    q1, q2, q3 = out["questions"]
    assert q1["qno"] == 1
    assert q1["question_id"] == "6911201"
    assert q1["question_type"] == "single_correct"
    assert q1["subject"] == "Mathematics"
    assert q1["section"] == "Section A"
    assert q1["options"]["C"] == "8 m/s2"
    assert len(q1["options"]) == 4
    assert q1["option_ids"] == ["69112011", "69112012", "69112013", "69112014"]
    assert q1["page_start"] == 1
    assert "particle moves in a circle" in q1["text"]
    assert "Shuffling" not in q1["text"]  # boilerplate stripped
    assert q2["question_type"] == "numerical"
    assert q2["options"] is None
    assert "sum of the roots" in q2["text"]
    assert "Possible Answers" not in q2["text"]
    assert q3["page_start"] == 2
    assert q3["subject"] == "Physics"
    # Paper-level facts recovered from the NTA header line.
    meta = out["detected_paper_meta"]
    assert meta["exam_date"] == "2026-04-02"
    assert meta["shift"] == 1
    # No answers anywhere in the raw layer.
    assert all("correct_option" not in q for q in out["questions"])


def test_parse_2026_image_only_stems_flagged():
    pages = [
        "Question Number : 1 Question Id : 6911201 Question Type : MCQ "
        "Option Shuffling : Yes Display Question Number : Yes\n"
        "Is Question Mandatory : No Single Line Question Option : No "
        "Option Orientation : Vertical\n"
        "Options :\n"
        "69112011. \n69112012. \n69112013. \n69112014. \n"
    ]
    out = x.extract_paper(pages)
    q = out["questions"][0]
    assert "stem_image_only" in q["parse_flags"]
    assert "options_image_only" in q["parse_flags"]
    # IDs are still real and key-joinable.
    assert q["question_id"] == "6911201"
    assert q["option_ids"] == ["69112011", "69112012", "69112013", "69112014"]


def test_parse_2022():
    out = x.extract_paper(SAMPLE_2022)
    assert out["status"] == "extracted"
    assert out["question_count"] == 2
    q1, q2 = out["questions"]
    assert q1["question_id"] == "101665"
    assert q1["subject"] == "Mathematics"
    assert q1["section"] == "Section A"
    assert q1["question_type"] == "single_correct"
    assert q1["options"]["D"] == "7"
    assert q2["question_type"] == "numerical"
    assert q2["options"] is None
    assert "rounding" not in " ".join(q2["parse_flags"])


def test_parse_generic_cuts_solutions():
    out = x.extract_paper(SAMPLE_GENERIC)
    assert out["status"] == "extracted"
    assert out["question_count"] == 2
    q1 = out["questions"][0]
    assert q1["options"]["B"] == "5 m"
    # Solution text must not leak into question blocks.
    for q in out["questions"]:
        assert "Using v^2" not in q["text"]
        assert "Using v^2" not in " ".join((q.get("options") or {}).values())


def test_generic_rejects_option_markers_as_questions():
    # Paren-style option markers "(1)" must never be taken as question
    # numbers, and question numbers must form a monotonic run from 1.
    pages = [
        "1. Stem of the first real question here, long enough to be a stem\n"
        "(1) opt one\n"
        "(2) opt two\n"
        "(3) opt three\n"
        "(4) opt four\n"
        "2. Second real question with a decently long stem to parse\n"
        "(1) a\n(2) b\n(3) c\n(4) d\n"
    ]
    out = x.extract_paper(pages)
    assert out["question_count"] == 2
    assert [q["qno"] for q in out["questions"]] == [1, 2]
    assert out["questions"][0]["options"]["A"] == "opt one"


def test_parse_failed_on_empty_text():
    out = x.extract_paper(["", "   "])
    assert out["status"] == "parse_failed"
    assert out["question_count"] == 0


def test_flags_fewer_than_four_options():
    pages = [
        "Question Number : 7 Question Id : 700 Question Type : MCQ\n"
        "A stem that is definitely long enough to not trip the stem flag\n"
        "(1) only one option present\n"
    ]
    out = x.extract_paper(pages)
    q = out["questions"][0]
    assert "options_count_1" in q["parse_flags"]


def test_infer_metadata_from_esaral_style_name():
    meta = x.infer_metadata(
        "https://www.esaral.com/media/uploads/2024/4/10/124243-JEE-Main_Morning-Shift-1_08-04-2024_Student-Copy.pdf",
        "JEE-Main Morning-Shift-1 08-04-2024 Student Copy",
        2024,
    )
    assert meta["year"] == 2024
    assert meta["exam_date"] == "2024-04-08"
    assert meta["session"] == 2
    assert meta["shift"] == 1
    assert meta["paper_type"] == "question_paper"
    assert meta["language"] == "English"


def test_build_tags_for_jee_marks_class_span():
    tags = x.build_tags(
        {"exam": "jee-main", "paper_type": "question_paper"},
        "JEE Main 2025 Shift 1",
    )
    assert tags[0] == "jee-main"
    assert "class-11" in tags
    assert "class-12" in tags
    assert "entrance-exam" in tags


def test_embedded_answer_captured_in_answer_sheet():
    pages = [
        "1. A stem long enough to be parsed as a real question body\n"
        "(1) alpha\n(2) beta\n(3) gamma\n(4) delta\n"
        "Answer (2)\n"
        "Sol. some worked solution that must stay out of the stem\n"
        "2. A second stem long enough to keep the question-number run\n"
        "(1) one\n(2) two\n(3) three\n(4) four\n"
    ]
    out = x.extract_paper(pages)
    q = out["questions"][0]
    assert "embedded_answer_captured" in q["parse_flags"]
    assert "Answer" not in q["text"]
    sheet = out["answer_sheet"]
    assert sheet["status"] == "embedded_unverified"
    assert sheet["validation"] == "not_verified"
    assert sheet["entries"][0]["qno"] == 1
    assert sheet["entries"][0]["answer"]["option"] == "B"


def test_question_colon_memory_based_format():
    pages = [
        "JEE-Main-31-01-2024 (Memory Based)\n[MORNING SHIFT]\nMathematics\n"
        "Question: Solve the differential equation for y given x > 0\n"
        "Options:\n(a) one\n(b) two\n(c) three\n(d) four\n"
        "Answer: (b)\nSolution: worked solution stays out of the stem\n"
        "Question: Compute the definite integral value rounded off\n"
        "Answer: 48.00\nSolution: numerical worked solution\n"
    ]
    out = x.extract_paper(pages)
    assert out["status"] == "extracted"
    assert out["question_count"] == 2
    q1 = out["questions"][0]
    assert q1["options"]["B"] == "two"
    assert "unnumbered_question_colon_format" in q1["parse_flags"]
    assert q1["embedded_answer"]["option"] == "B"
    meta = out["detected_paper_meta"]
    assert meta["exam_date"] == "2024-01-31"
    assert meta["shift"] == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

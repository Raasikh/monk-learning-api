"""Tests for diagram-candidate geometry helpers (no network, no PDFs)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import extract_diagram_questions as d  # noqa: E402


def test_image_candidate_flags_and_context():
    page_dict = {
        "blocks": [
            {"type": 0, "bbox": (10, 10, 200, 30), "lines": [{"spans": [{"text": "Physics Section A"}]}]},
            {"type": 0, "bbox": (10, 40, 200, 60), "lines": [{"spans": [{"text": "1. A ray diagram is shown"}]}]},
            {"type": 1, "bbox": (40, 80, 260, 220)},
            {"type": 1, "bbox": (0, 0, 612, 792)},  # full-page scan
        ]
    }
    cands = d.image_candidates_from_page_dict(page_dict, 612, 792, 3)
    assert len(cands) == 2
    diagram, scan = cands
    assert diagram["page"] == 3
    assert diagram["flags"] == []
    assert "full_page_scan" in scan["flags"]
    ctx = d.question_context_from_text_blocks(page_dict, diagram["bbox"])
    assert ctx["qno"] == 1
    assert ctx["subject"] == "Physics"
    assert ctx["section"] == "Section A"


def test_low_area_image_is_flagged_not_silent():
    page_dict = {"blocks": [{"type": 1, "bbox": (10, 10, 30, 30)}]}
    cands = d.image_candidates_from_page_dict(page_dict, 612, 792, 1)
    assert "tiny_image" in cands[0]["flags"]
    assert "low_area_image" in cands[0]["flags"]


def test_2026_header_context_carries_question_id():
    page_dict = {
        "blocks": [
            {"type": 0, "bbox": (10, 10, 300, 40), "lines": [{"spans": [{"text": "Question Number : 7 Question Id : 6911215 Question Type : MCQ"}]}]},
            {"type": 1, "bbox": (50, 80, 250, 200)},
        ]
    }
    cand = d.image_candidates_from_page_dict(page_dict, 612, 792, 1)[0]
    ctx = d.question_context_from_text_blocks(page_dict, cand["bbox"])
    assert ctx["qno"] == 7
    assert ctx["question_id"] == "6911215"


def test_diagram_confirmation_requires_real_signal():
    artifact = {"questions": [{"qno": 1, "question_id": None,
                               "parse_flags": ["references_figure_not_extracted"],
                               "page_start": 1, "page_end": 1}]}
    assert d.diagram_confirmation({"method": "mathpix_line_data"}, artifact) == "mathpix_line_data"
    assert d.diagram_confirmation({"method": "pymupdf_image_block", "flags": [],
                                   "context": {"qno": 1}, "page": 1}, artifact) == "figure_flag_plus_image_block"
    assert d.diagram_confirmation({"method": "pymupdf_image_block", "flags": ["tiny_image"],
                                   "context": {"qno": 1}, "page": 1}, artifact) is None


def test_find_matching_question_prefers_question_id():
    artifact = {"questions": [{"qno": 1, "question_id": "111"}, {"qno": 2, "question_id": "222"}]}
    row = {"context": {"question_id": "222", "qno": 1}, "page": 1}
    assert d.find_matching_question(artifact, row)["question_id"] == "222"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

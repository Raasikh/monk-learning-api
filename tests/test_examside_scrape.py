"""Pure helper tests for the ExamSIDE scraper (no network)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import scrape_examside_chapters as s  # noqa: E402


def test_exam_from_url_and_tags():
    assert s.exam_from_url("https://questions.examside.com/past-years/medical/neet/biology") == "neet-ug"
    assert s.exam_from_url("https://questions.examside.com/past-years/jee/jee-main/physics") == "jee-main"
    assert s.exam_from_url("https://questions.examside.com/past-years/jee/jee-advanced/chemistry") == "jee-advanced"
    assert "class-11" in s.tags_for("jee-advanced")
    assert "entrance-exam" in s.tags_for("neet-ug")


def test_strip_html_handles_breaks_and_entities():
    assert s.strip_html("A &ndash; B<br>C") == "A – B C"


def test_question_regex_finds_image_question():
    html = (
        '<a class="cp-q svelte-x" href="/past-years/medical/question/foo">'
        '<span class="cp-q-index">73</span>'
        '<div class="cp-q-preview"><!-- HTML_TAG_START -->Select the organelle in the diagram'
        '<img src="https://neetcare-image.cdn.examgoal.net/x.png" />'
        '<!-- HTML_TAG_END --></div>'
        '<span class="cp-q-paper">NEET 2013 (Karnataka)</span>'
        "</a>"
    )
    m = s.QUESTION_RE.search(html)
    assert m
    href, body = m.group(1), m.group(2)
    assert href.endswith("/foo")
    assert s.IMG_RE.findall(body) == ["https://neetcare-image.cdn.examgoal.net/x.png"]
    assert "diagram" in s.strip_html(body)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

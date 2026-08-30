"""Tests for the Snap a Doubt pipeline (app/snap.py).

The rules these protect:

  - GPT-4o mini transcribes only; DeepSeek solves only and never sees the image.
  - An illegible question is never sent to the solver.
  - Unparseable JSON gets exactly one retry, then a visible error — never a
    canned answer (AGENTS.md Rule 4).
  - Max 2 questions per submission, enforced server-side and not only in the
    prompt.
  - The served model string is asserted (Rule 5).

These stub the model calls. They do NOT prove the models behave — they prove
what we do with what comes back.

Runs under pytest, or standalone:  python3 tests/test_snap_solver.py
"""
import json
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")

import pytest  # noqa: E402

import app.snap as snap  # noqa: E402
from app.snap import (  # noqa: E402
    MAX_QUESTIONS,
    MODEL_SOLVE,
    MODEL_TRANSCRIBE,
    SnapError,
    _assert_model,
    _validate_solution,
    iter_snapped_questions,
    solve_question,
    solve_snapped_image,
    transcribe_questions,
)


# --- stubs ------------------------------------------------------------------

class _Response:
    def __init__(self, content, model):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]
        self.model = model


class _Client:
    """Returns each queued response in turn, so retries can be exercised.

    `contents` may instead be a {marker: [responses]} mapping, which routes on
    what the prompt actually contains rather than on call order. Questions are
    solved concurrently in a ThreadPoolExecutor, so a positional queue hands
    each thread whatever happens to be at the head of the list when it gets
    there — the ordering a test writes is not the ordering it gets. Any test
    that needs question A to fail and question B to succeed must key on the
    questions themselves; only same-question retry sequences are ordered.
    """

    def __init__(self, contents, model):
        self._routed = isinstance(contents, dict)
        if self._routed:
            self._contents = {k: list(v) for k, v in contents.items()}
        else:
            self._contents = list(contents)
        self._model = model
        self.calls = 0
        self._lock = threading.Lock()
        outer = self

        class _Completions:
            def create(self, **kwargs):
                with outer._lock:
                    outer.calls += 1
                    content = outer._next(json.dumps(kwargs.get("messages", "")))
                return _Response(content, outer._model)

        self.chat = type("Chat", (), {"completions": _Completions()})()

    def _next(self, prompt: str):
        if not self._routed:
            return self._contents.pop(0) if self._contents else self._contents
        for marker, queue in self._contents.items():
            if marker in prompt and queue:
                return queue.pop(0) if len(queue) > 1 else queue[0]
        raise AssertionError(
            f"stubbed solver got a prompt matching no marker in "
            f"{sorted(self._contents)}: {prompt[:200]}"
        )


@pytest.fixture(autouse=True)
def stub_mathpix_ocr(monkeypatch):
    """Mathpix now reads the page before the structuring model sees it.

    These tests exercise what we do with the structured result, so the OCR is
    stubbed to a confident read. The gate itself is tested explicitly below.
    """
    # The page text must CONTAIN the options the tests structure out of it —
    # the fidelity gate (rightly) refuses options that are not on the page.
    page_text = (
        "OCR TEXT OF THE PAGE\n"
        "Extra pure $N_2$ can be obtained by heating\n"
        "(A) NH_3 with CuO (B) NH_4NO_3 (C) (NH_4)_2Cr_2O_7 (D) Ba(N_3)_2\n"
        "first second third\n"
        "octahedral, tetrahedral and square planar; "
        "tetrahedral, square planar and octahedral; "
        "square planar, tetrahedral and octahedral; "
        "octahedral, square planar and octahedral"
    )
    monkeypatch.setattr(
        snap.mathpix, "read_page",
        lambda *_a, **_k: {"text": page_text, "confidence": 0.9},
    )


def stub_transcriber(monkeypatch, contents, model=MODEL_TRANSCRIBE):
    # dict = routed by prompt content (see _Client), list = ordered queue,
    # bare string = a single response reused for every call.
    client = _Client(contents if isinstance(contents, (list, dict)) else [contents], model)
    monkeypatch.setattr(snap, "_openai_client", lambda: client)
    return client


def stub_matcher(monkeypatch, labels, equivalent=True):
    """Stubs pass 3. A blind solve derives, then this decides which option it equals."""
    return stub_transcriber(monkeypatch, json.dumps(
        {"option_labels": labels, "equivalent": equivalent}))


def stub_solver(monkeypatch, contents, model=MODEL_SOLVE):
    # dict = routed by prompt content (see _Client), list = ordered queue,
    # bare string = a single response reused for every call.
    client = _Client(contents if isinstance(contents, (list, dict)) else [contents], model)
    monkeypatch.setattr(snap, "_deepseek_client", lambda: client)
    return client


def transcription(*questions, note=None):
    body = {"questions": list(questions)}
    if note:
        body["note"] = note
    return json.dumps(body)


def question(text="Find the acceleration when $F = 10$ N and $m = 2$ kg.",
             subject="Physics", topic="Laws of Motion", legible=True, note=None,
             options=None, question_type=None, printed_answer=None):
    if question_type is None:
        question_type = "single_correct" if options else "subjective"
    q = {"text": text, "subject": subject, "topic": topic, "legible": legible,
         "question_type": question_type, "options": options or [],
         "printed_answer": printed_answer}
    if note:
        q["note"] = note
    return q


MCQ_OPTIONS = [
    {"label": "A", "text": "NH_3 with CuO"},
    {"label": "B", "text": "NH_4NO_3"},
    {"label": "C", "text": "(NH_4)_2Cr_2O_7"},
    {"label": "D", "text": "Ba(N_3)_2"},
]


def mcq_transcription(options=MCQ_OPTIONS, printed_answer=None, legible=True,
                      question_type="single_correct", **extra):
    q = {"text": "Extra pure $N_2$ can be obtained by heating",
         "question_type": question_type, "options": options,
         "subject": "Chemistry", "topic": "p-Block", "legible": legible}
    if printed_answer:
        q["printed_answer"] = printed_answer
    q.update(extra)
    return json.dumps({"questions": [q]})


GOOD_SOLUTION = json.dumps({
    "answer": "$a = 5$ m s$^{-2}$",
    "steps": [
        {"n": 1, "text": "Newton's second law gives $F = ma$."},
        {"n": 2, "text": "Rearrange to $a = \\\\dfrac{F}{m}$."},
        {"n": 3, "text": "Substitute: $a = \\\\dfrac{10}{2} = 5$ m s$^{-2}$."},
    ],
    "key_idea": "Only the net force matters — resolve before dividing.",
    "subject": "Physics",
    "topic": "Laws of Motion",
})


# --- Rule 5: model strings are asserted -------------------------------------

def test_versioned_model_string_is_accepted():
    _assert_model("gpt-4o-mini-2024-07-18", MODEL_TRANSCRIBE, "transcribe")
    print("  accepted gpt-4o-mini-2024-07-18")


def test_legacy_alias_is_refused():
    """deepseek-chat served in place of v4-flash is the Rule 5 failure."""
    with pytest.raises(SnapError) as err:
        _assert_model("deepseek-chat", MODEL_SOLVE, "solve")
    print(f"  refused deepseek-chat: {err.value}")


def test_solver_refuses_when_provider_serves_another_model(monkeypatch):
    stub_solver(monkeypatch, [GOOD_SOLUTION, GOOD_SOLUTION], model="deepseek-reasoner")
    with pytest.raises(SnapError) as err:
        solve_question(question(), "d1")
    print(f"  refused: {err.value} (stage={err.value.stage})")


# --- the solver never sees the image, the transcriber never solves ----------

def test_solver_receives_only_the_transcribed_json(monkeypatch):
    """The payload handed to the solver carries text/subject/topic — no image."""
    sent = {}

    class _Capturing:
        def __init__(self):
            outer = self

            class _Completions:
                def create(self, **kwargs):
                    sent.update(kwargs)
                    return _Response(GOOD_SOLUTION, MODEL_SOLVE)

            self.chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(snap, "_deepseek_client", lambda: _Capturing())
    solve_question(question(), "d1")

    user_msg = sent["messages"][-1]["content"]
    print(f"  solver user message: {user_msg[:90]}…")
    assert "image_url" not in json.dumps(sent["messages"])
    assert "base64" not in json.dumps(sent["messages"])
    assert sent["extra_body"] == {"thinking": {"type": snap.SOLVE_THINKING}}
    print(f"  no image reached the solver; thinking={snap.SOLVE_THINKING}")


def test_illegible_question_is_never_solved(monkeypatch):
    stub_solver(monkeypatch, [GOOD_SOLUTION])
    with pytest.raises(SnapError) as err:
        solve_question(question(legible=False, note="The bottom line is cut off."), "d1")
    print(f"  refused before any solve call: {err.value}")


def test_pipeline_skips_illegible_and_solves_the_rest(monkeypatch):
    stub_transcriber(monkeypatch, transcription(
        question(text="Legible one."),
        question(text="", legible=False, note="Too blurry to read."),
    ))
    solver = stub_solver(monkeypatch, [GOOD_SOLUTION])

    out = solve_snapped_image(b"img", "image/jpeg", "d1")
    print(f"  solved {out['solved_count']} of {len(out['questions'])}; "
          f"solver called {solver.calls}x")
    assert out["solved_count"] == 1
    assert solver.calls == 1
    assert "solution" not in out["questions"][1]


# --- questions solve concurrently, not one after another --------------------

def test_questions_solve_concurrently(monkeypatch):
    """Every legible question's solve starts at once, not after the previous
    one finishes. A page of solves that each block until released must all be
    mid-flight together, or this would hang until the timeout."""
    releases = {1: threading.Event(), 2: threading.Event()}
    entered = {1: threading.Event(), 2: threading.Event()}

    monkeypatch.setattr(snap, "transcribe_questions", lambda *a, **k: {
        "questions": [
            {"n": 1, "text": "q1", "legible": True, "options": [], "question_type": "subjective"},
            {"n": 2, "text": "q2", "legible": True, "options": [], "question_type": "subjective"},
        ],
        "note": None, "ocr_confidence": 0.99,
    })

    def fake_solve_question(question, doubt_id="-", usage_acc=None, on_event=None):
        n = question["n"]
        entered[n].set()
        assert releases[n].wait(timeout=5), f"q{n} was never released"
        return {"answer": f"a{n}", "option_labels": [], "steps": [{"n": 1, "text": "x"}],
                "key_idea": None, "subject": None, "topic": None}

    monkeypatch.setattr(snap, "solve_question", fake_solve_question)

    result_holder = {}

    def run():
        result_holder["out"] = solve_snapped_image(b"img", "image/jpeg", "d1", 2)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    assert entered[1].wait(timeout=3), "q1 never started"
    assert entered[2].wait(timeout=3), "q2 never started while q1 was still blocked"
    releases[1].set()
    releases[2].set()
    t.join(timeout=5)
    assert not t.is_alive(), "solve_snapped_image did not finish"
    out = result_holder["out"]
    print(f"  solved_count={out['solved_count']}")
    assert out["solved_count"] == 2


def test_text_is_rebuilt_from_stem_and_options(monkeypatch):
    """The structurer no longer emits `text`; code joins stem + options.

    `text` was stem-and-options concatenated -- the same content the model had
    already written into `stem` and `options`, measured at 47% of everything it
    emitted on a real 3-question page. Output tokens are what the ~10s
    structuring call spends its time on, so it stopped being asked for.
    """
    page = ("Q65. A vessel at 1000 K contains gas, then Kp is :\n"
            "(1) 1.8 atm (2) 0.3 atm (3) 3 atm (4) 0.18 atm\n")
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": page, "confidence": 0.98,
                                           "diagram_regions": 0, "ocr_ms": 50})
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "stem": "Q65. A vessel at 1000 K contains gas, then Kp is :",
        "question_type": "single_correct", "legible": True,
        "options": [{"label": "1", "text": "1.8 atm"}, {"label": "2", "text": "0.3 atm"},
                    {"label": "3", "text": "3 atm"}, {"label": "4", "text": "0.18 atm"}],
    }]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1", None, 1)["questions"][0]
    print(f"  stem={q['stem'][:50]!r}")
    print(f"  text={q['text'][:80]!r}")
    assert q["stem"] == "Q65. A vessel at 1000 K contains gas, then Kp is :"
    # Options must NOT be inside the stem -- that is what the solver reasons
    # from, and seeing them is the back-fitting failure blind solving prevents.
    assert "1.8 atm" not in q["stem"]
    # ...but the display/search form still carries every option.
    for opt in ("1.8 atm", "0.3 atm", "3 atm", "0.18 atm"):
        assert opt in q["text"], f"{opt} missing from the rebuilt text"
    assert q["text"].startswith(q["stem"])


def test_legacy_text_only_response_still_reads(monkeypatch):
    """A response in the OLD shape (`text`, no `stem`) must still work.

    The prompt and the code deploy separately, and a stale prompt returning
    `text` must not break the read.
    """
    stub_transcriber(monkeypatch, mcq_transcription())
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  legacy stem={q['stem'][:60]!r}")
    assert q["stem"]
    assert q["options"]


def test_low_page_confidence_does_not_warn_the_student(monkeypatch):
    """A low page_confidence must NOT be reported as a half-read page.

    It looked like the partial-read signal — a real submission scored 0.0313
    while finding one question out of six — so a warning was built on it. Then
    it was measured: pages rendered with the tiled watermarks a coaching PDF
    carries score 0.15 while reading PERFECTLY (all six questions, 2,016
    chars). The warning would have told students to re-crop photos that had
    been read correctly, and a student who deliberately snapped ONE question
    off a watermarked paper would get it every time.

    page_confidence stays logged, and stays out of the student's way.
    """
    monkeypatch.setattr(snap.mathpix, "read_page", lambda *_a, **_k: {
        "text": "Q56. Given below are two statements :\n(1) a (2) b (3) c (4) d\n",
        "confidence": 0.9122, "page_confidence": 0.0313,
        "diagram_regions": 0, "ocr_ms": 2905,
    })
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "stem": "Q56. Given below are two statements :",
        "question_type": "single_correct", "legible": True,
        "options": [{"label": "1", "text": "a"}, {"label": "2", "text": "b"},
                    {"label": "3", "text": "c"}, {"label": "4", "text": "d"}],
    }]}))
    read = transcribe_questions(b"img", "image/jpeg", "d1", None, 3)
    print(f"  one question, page_confidence 0.0313 -> note={read['note']!r}")
    assert not read["note"], (
        "a low page_confidence must not manufacture a student-facing warning; "
        f"got {read['note']!r}"
    )


def test_crop_never_loses_the_image(monkeypatch):
    """Preprocessing must never be why a snap fails.

    crop_to_content runs before anything reads the photo, so every bad input
    it can be handed — an unopenable file, a solid colour, something tiny —
    has to come back as the original bytes rather than raising or returning
    something Mathpix cannot read.
    """
    from app.image_prep import crop_to_content
    from PIL import Image
    import io as _io

    def as_png(img):
        b = _io.BytesIO(); img.save(b, format="PNG"); return b.getvalue()

    cases = {
        "not an image at all": b"this is not a picture",
        "empty bytes": b"",
        "solid white": as_png(Image.new("RGB", (900, 700), "white")),
        "solid black": as_png(Image.new("RGB", (900, 700), "black")),
        "tiny": as_png(Image.new("RGB", (12, 12), "white")),
    }
    for label, data in cases.items():
        out, note = crop_to_content(data, "d1")
        print(f"  {label:22} -> {'unchanged' if out is data else 'cropped'} note={note}")
        # Every one of these is a case with nothing to crop. The contract is
        # pass-through: the SAME bytes back, not a re-encode and not a raise.
        # (Identity, not truthiness — empty in must give empty out, and the
        # router rejects an empty upload long before this runs.)
        assert out is data, f"{label} should have been passed through untouched"
        assert note is None, f"{label} should report no crop, got {note!r}"


def test_page_question_numbers_are_read_in_order():
    """The page's printed numbers drive selection, so they must be read right."""
    ocr = (
        "Q62. Which statement is not true for radioactive decay?\n"
        "(1) Decay constant increases\n"
        "Q63. The products formed are :\n"
        "Q64. How many stereoisomers? <smiles>CC=CC(C)O</smiles>\n"
        "(1) 1.660 g (2) 0.336 g\n"
        "Q65. A vessel at 1000 K contains $CO_2$\n"
    )
    nums = snap._question_numbers_in(ocr)
    print(f"  numbers={nums}")
    assert nums == [62, 63, 64, 65]
    # Option labels and stray figures must NOT be mistaken for question numbers.
    assert 1 not in nums and 2 not in nums


def test_unnumbered_page_yields_no_numbers():
    """An unnumbered page falls back to 'the first N' rather than inventing
    numbers — a wrong number list would chase questions that do not exist."""
    nums = snap._question_numbers_in(
        "Find the acceleration when $F = 10$ N.\n(1) 5\n(2) 2\n"
    )
    print(f"  numbers={nums}")
    assert nums == []


def test_structurer_skipping_ahead_is_corrected(monkeypatch):
    """Naming the exact questions is checked, and a skip is corrected once.

    Real failures, twice: a page of Q11-Q19 came back as Q16-Q18, and a page of
    Q62-Q66 came back as Q64-Q66. The student framed the top of the page and
    got its middle, which also breaks "reframe to the next three".
    """
    page_text = (
        "Q62. Which statement is not true for radioactive decay?\n"
        "(1) alpha (2) beta (3) gamma (4) delta\n"
        "Q63. The products formed in the sequence are :\n"
        "(1) one (2) two (3) three (4) four\n"
        "Q64. How many stereoisomers are possible?\n"
        "(1) 2 (2) 1 (3) 4 (4) 3\n"
        "Q65. A vessel at 1000 K contains gas.\n"
        "(1) 1.8 atm (2) 0.3 atm (3) 3 atm (4) 0.18 atm\n"
    )
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": page_text, "confidence": 0.98,
                                           "diagram_regions": 0, "ocr_ms": 100})

    def q(n, opts):
        return {"text": f"Q{n}. stem {n}", "stem": f"Q{n}. stem {n}",
                "question_type": "single_correct", "legible": True,
                "options": [{"label": str(i + 1), "text": t}
                            for i, t in enumerate(opts)]}

    # Forces the WHOLE-PAGE path, which is where a skip is still possible: the
    # per-question parallel path hands each call one question's slice and names
    # it, so there is nothing left to skip to. This pins the fallback's
    # correction, which is what runs on an unnumbered or unsplittable page.
    monkeypatch.setattr(snap, "_slice_by_question", lambda *_a, **_k: {})

    # First response skips ahead (the bug); the correction returns the right ones.
    wrong = json.dumps({"questions": [q(64, ["2", "1", "4", "3"]),
                                      q(65, ["1.8 atm", "0.3 atm", "3 atm", "0.18 atm"])]})
    right = json.dumps({"questions": [q(62, ["alpha", "beta", "gamma", "delta"]),
                                      q(63, ["one", "two", "three", "four"])]})
    client = stub_transcriber(monkeypatch, [wrong, right])

    read = transcribe_questions(b"img", "image/jpeg", "d1", None, 2)
    got = [qq["stem"].split(".")[0] for qq in read["questions"]]
    print(f"  structurer calls={client.calls} -> served {got}")
    assert client.calls == 2, "the skip should have triggered exactly one correction"
    assert got == ["Q62", "Q63"], f"served the wrong questions: {got}"


def test_a_numerical_question_is_not_refused_for_having_no_options(monkeypatch):
    """"No options" is only evidence against a CHOICE question.

    A JEE numerical prints a blank -- "the value of alpha is ____" -- so it has
    no options by design. The structurer read one correctly as `numerical` with
    `options: []`, then set `legible: false` because the options were
    "missing", in a note that literally began "The question is legible, but".
    A page of three came back solved 0/3 and the student was told to retake a
    photo that had been read perfectly.
    """
    page = ("Q4. When 300 J of heat is given to an ideal gas at constant "
            "volume its temperature rises from 20 C to 50 C. What is 100n?\n")
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": page, "confidence": 0.99,
                                           "page_confidence": 0.9,
                                           "diagram_regions": 0, "ocr_ms": 10})
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "number": 4, "question_type": "numerical", "options": [],
        "legible": False, "note": "The question is legible but lacks options.",
        "stem": ("When 300 J of heat is given to an ideal gas at constant volume "
                 "its temperature rises from 20 C to 50 C. What is 100n?"),
    }]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1", None, 3)["questions"][0]
    print(f"  type={q['question_type']} options={len(q['options'])} legible={q['legible']}")
    assert q["legible"] is True, "a numerical question was refused for having no options"


def test_a_choice_question_with_no_options_is_still_refused(monkeypatch):
    """The override above must not reach the refusal that matters.

    A multiple-choice question without its choices reached the solver once and
    it invented an answer that was not among them. That gate stands.
    """
    page = "Q7. Extra pure nitrogen can be obtained by heating\n(A) NH_3 with CuO\n"
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": page, "confidence": 0.99,
                                           "page_confidence": 0.9,
                                           "diagram_regions": 0, "ocr_ms": 10})
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "number": 7, "question_type": "single_correct", "legible": True,
        "stem": "Extra pure nitrogen can be obtained by heating",
        "options": [{"label": "A", "text": "NH_3 with CuO"}],
    }]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1", None, 3)["questions"][0]
    print(f"  options={len(q['options'])} legible={q['legible']} reason={q['reason']}")
    assert q["legible"] is False
    assert q["reason"] == "options_unreadable"


def test_options_that_are_figures_are_read_not_refused(monkeypatch):
    """"Which of these curves…" printed as four graphs must not be refused.

    There is no text for the OCR to read, so the structurer returns a choice
    question with zero options and the gate fired: "the options could not be
    read. Retake the photo with all the choices in frame." That advice cannot
    work — no photograph of a graph turns it into text. Several figures inside
    one question's span is the signal that its options are drawn.
    """
    page = _page_with_geometry(
        text="Q45. Which resistivity vs temperature curve suits standard resistors?",
        diagram_spans=[{"top": 91, "bottom": 266}, {"top": 95, "bottom": 266},
                       {"top": 405, "bottom": 586}, {"top": 412, "bottom": 586}],
        text_lines=[{"top": 28, "bottom": 52,
                     "text": "Q45. Which resistivity vs temperature curve suits standard resistors?"}],
    )
    monkeypatch.setattr(snap.mathpix, "read_page", lambda *_a, **_k: page)
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "number": 45, "question_type": "single_correct", "options": [],
        "legible": True, "requires_diagram": False,
        "stem": "Which resistivity vs temperature curve suits standard resistors?",
    }]}))
    q = transcribe_questions(b"img", "image/png", "d1", None, 3)["questions"][0]
    print(f"  legible={q['legible']} options_are_drawn={q['options_are_drawn']} "
          f"reason={q.get('reason')}")
    assert q["legible"] is True, "a question whose options are drawn was refused"
    assert q["options_are_drawn"] is True


def test_drawn_options_survive_a_page_with_no_usable_numbering(monkeypatch):
    """The same page, refused once and read once, because of attribution.

    Real pair of runs on one photo of four circuits. The first attributed four
    figures to the question's span and read them. The second produced no
    per-question attribution at all — so every question reported zero figures,
    the gate saw none, and a circuit question was refused for "unreadable
    options" with the four circuits sitting in the frame unlooked-at.

    Attribution is a preference, not a precondition. A choice question with no
    readable options, on a page that HAS figures, is exactly the shape the
    reading pass exists for; whether they can be told apart is that pass's
    judgement to make, not this gate's.
    """
    page = _page_with_geometry(
        text="Which of the following circuits is reverse - biased ?",
        diagram_spans=[{"top": 498, "bottom": 589}, {"top": 508, "bottom": 745},
                       {"top": 769, "bottom": 982}, {"top": 773, "bottom": 857}],
        # No line carries a question number, so nothing can be sliced per
        # question — which is precisely the run that failed.
        text_lines=[{"top": 460, "bottom": 486,
                     "text": "Which of the following circuits is reverse - biased ?"}],
    )
    monkeypatch.setattr(snap.mathpix, "read_page", lambda *_a, **_k: page)
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "number": 19, "question_type": "single_correct", "options": [],
        "options_complete": False, "legible": True, "requires_diagram": True,
        "stem": "Which of the following circuits is reverse - biased ?",
    }]}))
    q = transcribe_questions(b"img", "image/png", "d1", None, 3)["questions"][0]
    print(f"  legible={q['legible']} options_are_drawn={q['options_are_drawn']} "
          f"reason={q.get('reason')}")
    assert q["options_are_drawn"] is True, "four figures on the page, none looked at"
    assert q["legible"] is True, "refused for unreadable options with the options in frame"


def test_a_page_with_no_figures_at_all_still_refuses(monkeypatch):
    """The fallback is to the page's figures, not to trusting every question.

    A choice question with no options on a page carrying no figures has
    genuinely lost its options, and a retake is the right advice.
    """
    page = _page_with_geometry(
        text="Q7. The value of the integral is",
        diagram_spans=[],
        text_lines=[{"top": 28, "bottom": 52, "text": "Q7. The value of the integral is"}],
    )
    monkeypatch.setattr(snap.mathpix, "read_page", lambda *_a, **_k: page)
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "number": 7, "question_type": "single_correct", "options": [],
        "legible": True, "requires_diagram": False,
        "stem": "The value of the integral is",
    }]}))
    q = transcribe_questions(b"img", "image/png", "d1", None, 3)["questions"][0]
    print(f"  legible={q['legible']} reason={q.get('reason')}")
    assert q["legible"] is False
    assert q["options_are_drawn"] is False


def test_one_figure_does_not_make_the_options_drawn(monkeypatch):
    """A question WITH a figure but genuinely missing options is still refused.

    One figure is the question's own diagram. It takes several inside the span
    to mean "the options are pictures" — otherwise a normal figure question
    with its choices cut off would be waved through, and a choice question
    without its choices reached the solver once and it invented an answer.
    """
    page = _page_with_geometry(
        text="Q3. The gas undergoes the process shown. Which is correct?",
        diagram_spans=[{"top": 111, "bottom": 350}],
        text_lines=[{"top": 30, "bottom": 54,
                     "text": "Q3. The gas undergoes the process shown. Which is correct?"}],
    )
    monkeypatch.setattr(snap.mathpix, "read_page", lambda *_a, **_k: page)
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "number": 3, "question_type": "single_correct", "options": [],
        "legible": True, "requires_diagram": True,
        "stem": "The gas undergoes the process shown. Which is correct?",
    }]}))
    q = transcribe_questions(b"img", "image/png", "d1", None, 3)["questions"][0]
    print(f"  legible={q['legible']} reason={q.get('reason')}")
    assert q["legible"] is False
    assert q["reason"] == "options_unreadable"


def test_drawn_options_skip_the_ocr_fidelity_gate(monkeypatch):
    """Described options were never IN the OCR text, so they cannot be checked
    against it. Running that gate on them would refuse every one."""
    page = _page_with_geometry(
        text="Q45. Which curve?",
        diagram_spans=[{"top": 91, "bottom": 266}, {"top": 95, "bottom": 266},
                       {"top": 405, "bottom": 586}, {"top": 412, "bottom": 586}],
        text_lines=[{"top": 28, "bottom": 52, "text": "Q45. Which curve?"}],
    )
    monkeypatch.setattr(snap.mathpix, "read_page", lambda *_a, **_k: page)
    # The structurer returns options that are NOT in the OCR text at all.
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "number": 45, "question_type": "single_correct", "legible": True,
        "stem": "Which curve?",
        "options": [{"label": "1", "text": "resistivity falls steeply"},
                    {"label": "2", "text": "resistivity is constant"}],
    }]}))
    q = transcribe_questions(b"img", "image/png", "d1", None, 3)["questions"][0]
    print(f"  legible={q['legible']} reason={q.get('reason')}")
    # Two options WERE returned, so options_are_drawn is False and the fidelity
    # gate applies normally — this pins that the gate is still live for text
    # options that do not match the page.
    assert q["legible"] is False
    assert q["reason"] == "options_fidelity"


def test_answers_arrive_as_they_finish_not_in_page_order(monkeypatch):
    """A slow question must not hold finished answers behind it.

    Delivery used to walk the page in order, so it blocked on q1's queue before
    looking at q2. On a real submission q5 was ready at 8.9s and q4 at 23.5s,
    and the student saw neither until q3 -- which had wedged -- gave up at
    2m13s. All three then appeared at once, two minutes late.

    The page keeps its own order regardless: cards are rendered from the
    question list sent before any solving and fill in as answers land, so
    out-of-order delivery is invisible.
    """
    delays = {1: 0.9, 2: 0.3, 3: 0.05}      # q1 slowest, q3 fastest
    monkeypatch.setattr(snap, "crop_to_content", lambda b, d="-": (b, None))
    monkeypatch.setattr(snap, "transcribe_questions", lambda *a, **k: {
        "questions": [{"n": i, "text": f"q{i}", "stem": f"q{i}", "legible": True,
                       "options": [], "question_type": "numerical",
                       "requires_diagram": False} for i in (1, 2, 3)],
        "note": None, "ocr_confidence": 0.99, "ocr_ms": 0, "structure_ms": 0})

    def fake_solve(q, doubt_id="-", usage_acc=None, on_event=None):
        time.sleep(delays[q["n"]])
        return {"answer": f"a{q['n']}", "option_labels": [],
                "steps": [{"n": 1, "text": "x"}], "key_idea": None,
                "subject": None, "topic": None}
    monkeypatch.setattr(snap, "solve_question", fake_solve)

    order = [item["n"] for kind, item
             in snap.iter_snapped_questions(b"x", "image/png", "d1", 3)
             if kind == "question"]
    print(f"  delivered in order: {order}  (page order would be [1, 2, 3])")
    assert order == [3, 2, 1], (
        f"answers should arrive fastest-first, got {order}")


def test_every_question_is_delivered_exactly_once(monkeypatch):
    """Out-of-order delivery must not drop or duplicate a question.

    Mixed legible and illegible: the illegible ones have no solve to wait for
    and go out immediately, the rest as they finish -- and every one arrives,
    once.
    """
    monkeypatch.setattr(snap, "crop_to_content", lambda b, d="-": (b, None))
    monkeypatch.setattr(snap, "transcribe_questions", lambda *a, **k: {
        "questions": [
            {"n": 1, "text": "q1", "stem": "q1", "legible": True, "options": [],
             "question_type": "numerical", "requires_diagram": False},
            {"n": 2, "text": "", "stem": "", "legible": False, "options": [],
             "question_type": "numerical", "requires_diagram": False,
             "note": "too blurry"},
            {"n": 3, "text": "q3", "stem": "q3", "legible": True, "options": [],
             "question_type": "numerical", "requires_diagram": False},
        ], "note": None, "ocr_confidence": 0.99, "ocr_ms": 0, "structure_ms": 0})
    monkeypatch.setattr(snap, "solve_question",
                        lambda q, doubt_id="-", usage_acc=None, on_event=None: {
                            "answer": "a", "option_labels": [],
                            "steps": [{"n": 1, "text": "x"}], "key_idea": None,
                            "subject": None, "topic": None})

    delivered = [item["n"] for kind, item
                 in snap.iter_snapped_questions(b"x", "image/png", "d1", 3)
                 if kind == "question"]
    print(f"  delivered: {delivered}")
    assert sorted(delivered) == [1, 2, 3], f"lost or duplicated: {delivered}"
    assert len(delivered) == len(set(delivered)), "a question was delivered twice"


def test_a_wedged_solve_retries_without_thinking(monkeypatch):
    """An attempt that answered nothing is retried — but not identically.

    Measured: a diagram question spent 2m13s returning an empty response
    because reasoning spends the SAME token allowance as the answer, so the
    model thought until the allowance was gone and had none left to write with.
    Repeating that call verbatim wedges verbatim, and the student waits on the
    slowest question of the page.

    So the retry changes the one variable that causes it. Thinking off cannot
    fail the same way and returns fast, which is what makes a second attempt
    affordable at all.
    """
    attempts = []

    def make_kwargs():
        class _Slow:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        attempts.append(kw)
                        # Burn most of the budget, then return nothing at all.
                        time.sleep(snap.SOLVE_TIMEOUT_S * 0.7)
                        return iter(())
        return dict(model=MODEL_SOLVE, messages=[{"role": "user", "content": "x"}],
                    timeout=snap.SOLVE_TIMEOUT_S, _client=_Slow(),
                    extra_body={"thinking": {"type": "enabled"}}, max_tokens=16000)

    monkeypatch.setattr(snap, "SOLVE_TIMEOUT_S", 1.0)
    with pytest.raises(SnapError):
        snap._streamed_solve(make_kwargs, lambda *_a: None, "d1", None)
    print(f"  attempts made: {len(attempts)}")
    assert len(attempts) == 2, "a wedge is worth exactly one different retry"
    assert attempts[0]["extra_body"]["thinking"]["type"] == "enabled"
    assert attempts[1]["extra_body"]["thinking"]["type"] == "disabled", (
        "the retry must change the thing that wedged, not repeat it"
    )
    assert attempts[1]["max_tokens"] < attempts[0]["max_tokens"], (
        "without thinking the big allowance is not needed"
    )


def test_a_slow_attempt_that_said_something_is_not_retried(monkeypatch):
    """Partial content is a slow success, not a wedge.

    The difference matters: an attempt that produced working but unparseable
    JSON has already spent the student's time on something real, and a second
    full attempt would spend it again. Only an attempt that answered NOTHING
    earns the thinking-off retry.
    """
    attempts = []

    def make_kwargs():
        class _Chunk:
            def __init__(self, text):
                self.usage = None
                self.choices = [type("C", (), {"delta": type("D", (), {
                    "content": text, "reasoning_content": None})()})()]

        class _Slow:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        attempts.append(kw)
                        time.sleep(snap.SOLVE_TIMEOUT_S * 0.7)
                        # Says something, but never valid JSON.
                        return iter([_Chunk("{not json")])
        return dict(model=MODEL_SOLVE, messages=[{"role": "user", "content": "x"}],
                    timeout=snap.SOLVE_TIMEOUT_S, _client=_Slow(),
                    extra_body={"thinking": {"type": "enabled"}}, max_tokens=16000)

    monkeypatch.setattr(snap, "SOLVE_TIMEOUT_S", 1.0)
    with pytest.raises(SnapError):
        snap._streamed_solve(make_kwargs, lambda *_a: None, "d2", None)
    print(f"  attempts made: {len(attempts)}")
    assert len(attempts) == 1, "a slow attempt that produced content is not retried"


def test_a_fast_failure_is_still_retried(monkeypatch):
    """The no-retry rule must not swallow the retry that earns its keep.

    Unparseable JSON that comes back QUICKLY is the case the retry exists for —
    a rambling step broke its own escaping twice, and the corrective fixed it.
    """
    attempts = {"n": 0}

    def make_kwargs():
        class _Fast:
            class chat:
                class completions:
                    @staticmethod
                    def create(**_kw):
                        attempts["n"] += 1
                        return iter(())          # fails immediately, no delay
        return dict(model=MODEL_SOLVE, messages=[{"role": "user", "content": "x"}],
                    timeout=snap.SOLVE_TIMEOUT_S, _client=_Fast())

    with pytest.raises(SnapError):
        snap._streamed_solve(make_kwargs, lambda *_a: None, "d1", None)
    print(f"  attempts made: {attempts['n']}")
    assert attempts["n"] == 2, "a fast failure should still get its one retry"


def _page_with_geometry(**over):
    """A Mathpix result carrying line geometry: Q3 owns a figure, Q4/Q5 do not."""
    page = {
        "text": "Q3. gas process\nQ4. heat at constant volume\nQ5. insulated cylinder",
        "confidence": 0.99, "page_confidence": 0.9, "diagram_regions": 1, "ocr_ms": 10,
        "diagram_spans": [{"top": 111, "bottom": 350}],
        "text_lines": [
            {"top": 30, "bottom": 54, "text": "Q3. gas process shown in the figure"},
            {"top": 370, "bottom": 392, "text": "(1) 21 (2) 15 (3) 28 (4) 24"},
            {"top": 470, "bottom": 494, "text": "Q4. heat at constant volume"},
            {"top": 600, "bottom": 624, "text": "Q5. insulated cylinder"},
        ],
    }
    page.update(over)
    return page


def test_a_figure_belongs_to_the_question_it_sits_inside():
    """Geometry, not wording, decides which question owns a figure.

    The page-level count cannot: OR-ing it onto every question refused a
    thermodynamics question because a bob-on-a-string question shared the page.
    """
    counts = snap.figures_by_question(_page_with_geometry(), [3, 4, 5])
    print(f"  {counts}")
    assert counts == {3: 1, 4: 0, 5: 0}


def test_geometry_overrides_the_text_model_both_ways(monkeypatch):
    """A figure the wording missed is added; one it imagined is dropped.

    The text model never sees the page — it infers a figure from prose, and has
    been wrong in both directions: it missed one whose stem said "two
    arrangements of wires" without "as shown", and flagged another that had no
    figure at all.
    """
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: _page_with_geometry())
    # Q3 really has the figure and is reported as not needing one; Q4 has none
    # and is reported as needing one.
    stub_transcriber(monkeypatch, json.dumps({"questions": [
        {"number": 3, "question_type": "numerical", "options": [], "legible": True,
         "requires_diagram": False, "stem": "gas process shown in the figure, find alpha"},
        {"number": 4, "question_type": "numerical", "options": [], "legible": True,
         "requires_diagram": True, "stem": "heat at constant volume, find 100n"},
    ]}))
    qs = transcribe_questions(b"img", "image/png", "d1", None, 2)["questions"]
    print(f"  q3 requires_diagram={qs[0]['requires_diagram']} (model said False)")
    print(f"  q4 requires_diagram={qs[1]['requires_diagram']} (model said True)")
    assert qs[0]["requires_diagram"] is True, "a real figure was not picked up"
    assert qs[1]["requires_diagram"] is False, "an imagined figure was not dropped"


def test_no_geometry_leaves_the_text_model_in_charge(monkeypatch):
    """No coordinates means NO OPINION, never "there is no figure".

    Reading an absent signal as "no figure" would silently stop describing
    figures on any page whose OCR returns no geometry — the same class of
    failure as the gate that skipped the describing pass entirely.
    """
    bare = _page_with_geometry(diagram_spans=[], text_lines=[])
    assert snap.figures_by_question(bare, [3, 4]) == {}

    monkeypatch.setattr(snap.mathpix, "read_page", lambda *_a, **_k: bare)
    stub_transcriber(monkeypatch, json.dumps({"questions": [
        {"number": 3, "question_type": "numerical", "options": [], "legible": True,
         "requires_diagram": True, "stem": "the arrangement shown in the figure"},
    ]}))
    q = transcribe_questions(b"img", "image/png", "d1", None, 1)["questions"][0]
    print(f"  requires_diagram={q['requires_diagram']} (kept the model's judgement)")
    assert q["requires_diagram"] is True


def test_a_figure_question_reaches_the_describing_pass(monkeypatch):
    """A question is not refused here for needing its figure.

    The describing pass runs only on legible questions, so a P-V graph question
    returned as `requires_diagram: true` AND `legible: false` -- its note citing
    "the reference to the figure" -- was refused for the exact reason that pass
    exists to handle, and the figure was never looked at. Whether a figure can
    be worked from is that pass's call; it refuses honestly when it cannot.
    """
    # The options must appear in the OCR text, or the fidelity gate refuses
    # first and this tests the wrong thing. The ONLY reason for illegibility
    # here is the model's own note about the figure.
    page = ("Q3. 10 mole of an ideal gas undergoes the process shown in the figure.\n"
            "(1) 21 (2) 15 (3) 28 (4) 24\n")
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": page, "confidence": 0.99,
                                           "page_confidence": 0.9,
                                           "diagram_regions": 1, "ocr_ms": 10})
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "number": 3, "question_type": "single_correct", "requires_diagram": True,
        "legible": False, "note": "unreadable: the reference to the figure",
        "stem": "10 mole of an ideal gas undergoes the process shown in the figure.",
        "options": [{"label": "1", "text": "21"}, {"label": "2", "text": "15"},
                    {"label": "3", "text": "28"}, {"label": "4", "text": "24"}],
    }]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1", None, 3)["questions"][0]
    print(f"  requires_diagram={q['requires_diagram']} legible={q['legible']}")
    assert q["requires_diagram"] is True
    assert q["legible"] is True, "refused before its figure was ever described"


def test_a_schema_placeholder_is_not_filed_as_a_subject():
    """The subject chip and the /doubts filter take only real subjects.

    A per-question structuring call echoed the schema's own placeholder, so
    "Physics|Chemistry|Maths|Biology|unknown" was about to be stored as the
    subject. It also starts with "Phys", so a loose prefix match filed it under
    Physics — a confident wrong answer to "which subject", which is worse than
    admitting we do not know.
    """
    from app.exam_scope import canonical_subject, display_subject

    # Stored values use the corpus's vocabulary -- `chapters` and `questions`
    # have said lowercase "mathematics" across 828 rows since long before
    # doubts existed, so that is the name everything groups on. "Math" is the
    # label a student reads, which is a separate question from what is stored.
    cases = {
        "Physics|Chemistry|Maths|Biology|unknown": None,
        "Physics, Chemistry": None,
        "Astrology": None,
        "": None,
        None: None,
        "Chemistry": "chemistry",
        "physics": "physics",
        "Mathematics": "mathematics",
        "Maths": "mathematics",
        "math": "mathematics",
        "  Maths  ": "mathematics",
    }
    for raw, want in cases.items():
        got = canonical_subject(raw)
        print(f"  {str(raw)[:44]:46} -> {got}  (shown as {display_subject(raw)})")
        assert got == want, f"{raw!r} became {got!r}, wanted {want!r}"

    # Every spelling a model has produced lands on the same key AND the same
    # label, which is the whole point -- an equality filter has to see them all.
    assert len({canonical_subject(s) for s in ("Maths", "Mathematics", "math", "MATHS")}) == 1
    assert display_subject("Maths") == "Math"


def test_numbered_page_structures_each_question_in_parallel(monkeypatch):
    """A numbered multi-question page gets one call PER QUESTION, concurrently.

    The whole-page call is dominated by how many output tokens it must
    generate -- 10.5s for three questions on a real submission -- and that work
    divides: each slice between two printed question numbers holds exactly one
    question and its options. Also removes the skip-ahead failure mode by
    construction, since a call handed one question cannot return a later one.
    """
    page_text = (
        "Q62. First question here?\n(1) a (2) b (3) c (4) d\n"
        "Q63. Second question here?\n(1) e (2) f (3) g (4) h\n"
        "Q64. Third question here?\n(1) i (2) j (3) k (4) l\n"
    )
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": page_text, "confidence": 0.98,
                                           "diagram_regions": 0, "ocr_ms": 100})

    seen = []

    class _PerQuestion:
        def __init__(self):
            outer = self
            self.calls = 0

            class _Completions:
                def create(self, **kw):
                    outer.calls += 1
                    body = kw["messages"][-1]["content"]
                    num = int(re.search(r"Q(\d+)", body).group(1))
                    seen.append(num)
                    # Each call must be given ONLY its own question's text.
                    for other in (62, 63, 64):
                        if other != num:
                            assert f"Q{other}." not in body, (
                                f"call for Q{num} was shown Q{other}'s text")
                    return _Response(json.dumps({"questions": [{
                        "number": num, "stem": f"stem {num}",
                        "question_type": "single_correct", "legible": True,
                        "options": [{"label": "1", "text": "a"},
                                    {"label": "2", "text": "b"}],
                    }]}), MODEL_TRANSCRIBE)
            self.chat = type("Chat", (), {"completions": _Completions()})()

    client = _PerQuestion()
    monkeypatch.setattr(snap, "_openai_client", lambda: client)

    read = transcribe_questions(b"img", "image/jpeg", "d1", None, 3)
    print(f"  calls={client.calls} for numbers {sorted(seen)}")
    assert client.calls == 3, "expected one call per question"
    assert sorted(seen) == [62, 63, 64]
    # Merged back in PAGE order, whichever order the calls finished in.
    assert [q["stem"] for q in read["questions"]] == ["stem 62", "stem 63", "stem 64"]


def test_unsplittable_page_falls_back_to_one_call(monkeypatch):
    """An unnumbered page keeps the single whole-page call -- there is no safe
    way to slice it, and half a question is worse than a slow one."""
    monkeypatch.setattr(snap.mathpix, "read_page", lambda *_a, **_k: {
        "text": "Find the acceleration when F = 10 N and m = 2 kg.\n(1) 5 (2) 2\n",
        "confidence": 0.98, "diagram_regions": 0, "ocr_ms": 100})
    client = stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "stem": "Find the acceleration when F = 10 N and m = 2 kg.",
        "question_type": "single_correct", "legible": True,
        "options": [{"label": "1", "text": "5"}, {"label": "2", "text": "2"}]}]}))
    transcribe_questions(b"img", "image/jpeg", "d1", None, 3)
    print(f"  calls={client.calls} (unnumbered page)")
    assert client.calls == 1


def test_correct_selection_costs_no_extra_call(monkeypatch):
    """When the model complies, verification is free — no second call."""
    page_text = ("Q62. First question here?\n(1) a (2) b (3) c (4) d\n"
                 "Q63. Second question here?\n(1) e (2) f (3) g (4) h\n")
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": page_text, "confidence": 0.98,
                                           "diagram_regions": 0, "ocr_ms": 100})
    good = json.dumps({"questions": [
        {"text": "Q62. First question here?", "stem": "Q62. First question here?",
         "question_type": "single_correct", "legible": True,
         "options": [{"label": "1", "text": "a"}, {"label": "2", "text": "b"},
                     {"label": "3", "text": "c"}, {"label": "4", "text": "d"}]},
    ]})
    client = stub_transcriber(monkeypatch, [good])
    transcribe_questions(b"img", "image/jpeg", "d1", None, 1)
    print(f"  structurer calls={client.calls}")
    assert client.calls == 1


def test_questions_are_sent_before_any_solving(monkeypatch):
    """The question reaches the student before the first solve starts.

    The page used to have nothing to show for the whole ~20-30s solve, then
    painted question and answer together at the end. The transcribed question
    is known the moment OCR/structuring finishes, so it goes out then — with
    no answer attached, which is what makes it safe to send early.
    """
    monkeypatch.setattr(snap, "transcribe_questions", lambda *a, **k: {
        "questions": [
            {"n": 1, "text": "q1 full", "stem": "q1 stem", "legible": True,
             "options": [{"label": "A", "text": "opt"}],
             "question_type": "single_correct", "subject": "Maths", "topic": "Algebra"},
        ],
        "note": None, "ocr_confidence": 0.99,
    })

    solve_started = threading.Event()

    def fake_solve_question(question, doubt_id="-", usage_acc=None, on_event=None):
        solve_started.set()
        return {"answer": "a", "option_labels": [], "steps": [{"n": 1, "text": "x"}],
                "key_idea": None, "subject": None, "topic": None}

    monkeypatch.setattr(snap, "solve_question", fake_solve_question)

    gen = snap.iter_snapped_questions(b"img", "image/jpeg", "d1", 1)
    kinds = []
    payload = None
    for kind, item in gen:
        kinds.append(kind)
        if kind == "questions_read":
            payload = item
            # Nothing may have been solved yet at this point — that is the
            # whole guarantee this test exists for.
            assert not solve_started.is_set(), \
                "a solve had already started before the question was sent"
            break

    print(f"  events up to questions_read: {kinds}")
    assert kinds == ["meta", "questions_read"]
    q = payload["questions"][0]
    print(f"  payload: stem={q['stem']!r} options={q['options']} chapter={q['chapter']!r}")
    assert q["stem"] == "q1 stem"
    assert q["options"] == [{"label": "A", "text": "opt"}]
    assert q["chapter"] == "Algebra"
    # No answer may ride along early, under any key.
    assert not ({"answer", "steps", "key_idea", "option_labels", "status"} & set(q)), \
        f"an answer field leaked into the pre-solve payload: {sorted(q)}"
    gen.close()


def test_background_question_already_done_skips_replay(monkeypatch):
    """A question solving in the background can finish before its turn comes.

    Its queued step events must not replay all at once when it becomes
    "front" — that reads as a glitch, not as fast. Q2 finishes (and queues its
    own step event) while Q1 is still working; Q1's step must stream, but
    Q2's must never appear as a "step" event at all — its card should just
    appear once Q1 is done.
    """
    monkeypatch.setattr(snap, "transcribe_questions", lambda *a, **k: {
        "questions": [
            {"n": 1, "text": "q1", "legible": True, "options": [], "question_type": "subjective"},
            {"n": 2, "text": "q2", "legible": True, "options": [], "question_type": "subjective"},
        ],
        "note": None, "ocr_confidence": 0.99,
    })

    q2_done = threading.Event()

    def fake_solve_question(question, doubt_id="-", usage_acc=None, on_event=None):
        n = question["n"]
        if n == 1:
            if on_event:
                on_event("step", {"n": 1, "text": "q1 step"})
            # Block until q2 has genuinely finished in the background, so its
            # events are sitting in its queue — unread — once q1 ends.
            assert q2_done.wait(timeout=5), "q2 never finished"
        else:
            if on_event:
                on_event("step", {"n": 1, "text": "q2 step"})
            q2_done.set()
        return {"answer": f"a{n}", "option_labels": [], "steps": [{"n": 1, "text": "x"}],
                "key_idea": None, "subject": None, "topic": None}

    monkeypatch.setattr(snap, "solve_question", fake_solve_question)

    events = [(kind, data.get("question_index"))
              for kind, data in iter_snapped_questions(b"img", "image/jpeg", "d1", 2)]
    print(f"  events: {events}")
    assert ("step", 1) in events
    assert ("step", 2) not in events, "q2's stale step was replayed instead of skipped"


# --- max 2 questions, enforced server-side ----------------------------------

def test_more_than_the_cap_is_truncated(monkeypatch):
    """The cap is MAX_QUESTIONS per photo, enforced in code not just the prompt."""
    over = MAX_QUESTIONS + 2
    stub_transcriber(monkeypatch, transcription(
        *[question(text=f"Q{i}.") for i in range(over)]))
    read = transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  kept {len(read['questions'])} of {over}; note={read['note']!r}")
    assert len(read["questions"]) == MAX_QUESTIONS
    assert read["note"]


def test_transcriber_note_is_preserved(monkeypatch):
    stub_transcriber(monkeypatch, transcription(
        question(), note="Third question was cut off at the edge."
    ))
    read = transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  note={read['note']!r}")
    assert "cut off" in read["note"]


def test_empty_text_is_treated_as_illegible(monkeypatch):
    """A question with no text is not legible, whatever the flag claims."""
    stub_transcriber(monkeypatch, transcription(question(text="   ", legible=True)))
    read = transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  legible={read['questions'][0]['legible']} for empty text")
    assert read["questions"][0]["legible"] is False


# --- one retry, then a visible error ----------------------------------------

def test_unparseable_transcription_retries_once_then_fails(monkeypatch):
    client = stub_transcriber(monkeypatch, ["{not json", "still not json"])
    with pytest.raises(SnapError) as err:
        transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  {client.calls} attempts, then: {err.value}")
    assert client.calls == 2


def test_retry_succeeds_on_the_second_attempt(monkeypatch):
    client = stub_transcriber(monkeypatch, ["{broken", transcription(question())])
    read = transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  recovered on attempt {client.calls}: {len(read['questions'])} question(s)")
    assert client.calls == 2
    assert len(read["questions"]) == 1


def test_unparseable_solution_retries_once_then_fails(monkeypatch):
    client = stub_solver(monkeypatch, ["{broken", "{still broken"])
    with pytest.raises(SnapError) as err:
        solve_question(question(), "d1")
    print(f"  {client.calls} attempts, then: {err.value}")
    assert client.calls == 2


def test_fenced_json_is_recovered(monkeypatch):
    stub_solver(monkeypatch, [f"```json\n{GOOD_SOLUTION}\n```"])
    out = solve_question(question(), "d1")
    print(f"  recovered {len(out['steps'])} steps from a fenced response")
    assert len(out["steps"]) == 3


# --- a solution without an answer or steps is not a solution ----------------

def test_solution_without_an_answer_is_refused():
    with pytest.raises(SnapError) as err:
        _validate_solution({"steps": [{"n": 1, "text": "A step."}]})
    print(f"  refused: {err.value}")


def test_solution_without_steps_is_refused():
    with pytest.raises(SnapError) as err:
        _validate_solution({"answer": "42"})
    print(f"  refused: {err.value}")


def test_empty_steps_list_is_refused():
    with pytest.raises(SnapError) as err:
        _validate_solution({"answer": "42", "steps": []})
    print(f"  refused: {err.value}")


def test_string_steps_are_accepted_and_numbered():
    out = _validate_solution({"answer": "42", "steps": ["First move.", "Second move."]})
    print(f"  normalised: {out['steps']}")
    assert out["steps"] == [{"n": 1, "text": "First move."}, {"n": 2, "text": "Second move."}]


def test_key_idea_is_optional():
    out = _validate_solution({"answer": "42", "steps": [{"n": 1, "text": "A step."}]})
    print(f"  key_idea={out['key_idea']!r}")
    assert out["key_idea"] is None


# --- whole-pipeline failures are visible, never canned ----------------------

def test_pipeline_raises_when_nothing_could_be_solved(monkeypatch):
    stub_transcriber(monkeypatch, transcription(
        question(text="", legible=False, note="The page is out of focus.")
    ))
    with pytest.raises(SnapError) as err:
        solve_snapped_image(b"img", "image/jpeg", "d1")
    print(f"  refused: {err.value} (stage={err.value.stage})")
    assert "focus" in str(err.value)


def test_one_failed_solve_does_not_lose_the_other_question(monkeypatch):
    stub_transcriber(monkeypatch, transcription(
        question(text="One."), question(text="Two."),
    ))
    # Routed by question text, not call order: the two solves run concurrently
    # in a ThreadPoolExecutor, so a positional queue made this test flaky —
    # whichever thread reached the stub first took the head of the list, and
    # the failure landed on question 2 about as often as on question 1.
    stub_solver(monkeypatch, {"One.": ["{broken", "{broken"], "Two.": [GOOD_SOLUTION]})
    out = solve_snapped_image(b"img", "image/jpeg", "d1")
    print(f"  solved {out['solved_count']} of 2; "
          f"q1 error={out['questions'][0].get('solve_error')!r}")
    assert out["solved_count"] == 1
    assert out["questions"][0]["solve_error"]
    assert out["questions"][1]["solution"]


def test_no_questions_array_is_refused(monkeypatch):
    stub_transcriber(monkeypatch, ['{"questions": []}', '{"questions": []}'])
    with pytest.raises(SnapError) as err:
        transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  refused: {err.value}")


def test_missing_openai_key_is_a_config_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SnapError) as err:
        snap._openai_client()
    print(f"  refused: {err.value} (stage={err.value.stage})")
    assert err.value.stage == "config"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))


# --- MCQ gates: the regression this file exists for -------------------------
#
# A cropped photo produced a bare stem with no options. The solver answered
# "Sodium azide (NaN3)" — not one of the four choices — and it was stored as
# `solved`. Each test below closes one step of that path.

def test_mcq_without_options_is_marked_illegible(monkeypatch):
    """A stem with no choices never reaches the solver."""
    stub_transcriber(monkeypatch, mcq_transcription(options=[]))
    read = transcribe_questions(b"img", "image/jpeg", "d1")
    q = read["questions"][0]
    print(f"  legible={q['legible']} note={q['note']!r}")
    assert q["legible"] is False
    assert "options" in (q["note"] or "")


def test_mcq_with_one_option_is_marked_illegible(monkeypatch):
    """Partially-read choices are as unusable as none."""
    stub_transcriber(monkeypatch, mcq_transcription(options=MCQ_OPTIONS[:1]))
    read = transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  legible={read['questions'][0]['legible']} with 1 option")
    assert read["questions"][0]["legible"] is False


def test_options_present_stays_legible(monkeypatch):
    stub_transcriber(monkeypatch, mcq_transcription())
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  legible={q['legible']} options={[o['label'] for o in q['options']]}")
    assert q["legible"] is True
    assert len(q["options"]) == 4


def test_bare_string_options_are_labelled(monkeypatch):
    """Some responses return plain strings; they get A, B, C, D in order."""
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "text": "Pick one", "question_type": "single_correct",
        "options": ["first", "second", "third"], "legible": True}]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  {[(o['label'], o['text']) for o in q['options']]}")
    assert [o["label"] for o in q["options"]] == ["A", "B", "C"]


def test_options_imply_a_choice_question(monkeypatch):
    """Two or more options make it a choice question even with no type given."""
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "text": "Pick one", "options": MCQ_OPTIONS, "legible": True}]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  question_type={q['question_type']}")
    assert q["question_type"] == "single_correct"


def test_answer_outside_the_options_is_flagged(monkeypatch):
    """THE regression, updated: an answer on no option is flagged, not invented.

    It used to be refused outright, which threw away a correct derivation
    whenever the OCR had mangled an option. Now the working is shown and the
    mismatch is stated.
    """
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "Sodium azide (NaN_3)",
        "steps": [{"n": 1, "text": "Azides decompose to nitrogen."},
                  {"n": 2, "text": "So sodium azide gives pure $N_2$."}],
        "key_idea": "Azide decomposition."})])
    stub_matcher(monkeypatch, [], equivalent=False)
    out = solve_question(question(options=MCQ_OPTIONS), "d1")
    print(f"  unmatched={out['unmatched']} labels={out['option_labels']}")
    assert out["unmatched"] is True
    assert out["option_labels"] == []
    # Never silently promoted to one of the real options.
    assert out["answer"] not in [o["text"] for o in MCQ_OPTIONS]



def test_answer_matching_an_option_label_is_accepted(monkeypatch):
    stub_solver(monkeypatch, [json.dumps({
        "answer": "Barium azide", "option_labels": ["D"],
        "steps": [{"n": 1, "text": "Ba azide decomposes cleanly."},
                  {"n": 2, "text": "It leaves only $N_2$."}],
        "key_idea": "No gaseous by-products."})])
    out = solve_question(question(options=MCQ_OPTIONS), "d1")
    print(f"  option_label={out['option_labels']} answer={out['answer']!r}")
    assert out["option_labels"] == ["D"]
    # The stored answer is the option's own text, not the model's paraphrase.
    assert out["answer"] == "Ba(N_3)_2"


def test_answer_matching_option_text_without_a_label_is_accepted(monkeypatch):
    stub_solver(monkeypatch, [json.dumps({
        "answer": "Ba(N_3)_2", "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}],
        "key_idea": "k"})])
    out = solve_question(question(options=MCQ_OPTIONS), "d1")
    print(f"  matched by text -> option_label={out['option_labels']}")
    assert out["option_labels"] == ["D"]


def test_non_mcq_answer_is_not_constrained(monkeypatch):
    stub_solver(monkeypatch, [GOOD_SOLUTION])
    out = solve_question(question(), "d1")
    print(f"  free-form answer accepted: {out['answer']!r}")
    assert out["option_labels"] == []


# --- the printed answer key is withheld, then used as a check ---------------

def test_printed_answer_never_reaches_the_solver(monkeypatch):
    sent = {}

    class _Capturing:
        def __init__(self):
            class _Completions:
                def create(self, **kwargs):
                    sent.update(kwargs)
                    return _Response(json.dumps({
                        "answer": "Ba(N_3)_2", "option_labels": ["D"],
                        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}],
                        "key_idea": "k"}), MODEL_SOLVE)
            self.chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(snap, "_deepseek_client", lambda: _Capturing())
    solve_question(question(options=MCQ_OPTIONS, printed_answer="D"), "d1")

    blob = json.dumps(sent["messages"])
    print(f"  solver payload: {sent['messages'][-1]['content'][:110]}…")
    assert "printed_answer" not in blob
    print("  printed answer withheld from the solver")


def test_agreement_with_the_printed_key_is_recorded(monkeypatch):
    stub_solver(monkeypatch, [json.dumps({
        "answer": "Ba(N_3)_2", "option_labels": ["D"],
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    out = solve_question(question(options=MCQ_OPTIONS, printed_answer="D"), "d1")
    print(f"  printed=D solver=D -> agrees={out['agrees_with_printed_answer']}")
    assert out["agrees_with_printed_answer"] is True


def test_disagreement_with_the_printed_key_is_recorded(monkeypatch):
    stub_solver(monkeypatch, [json.dumps({
        "answer": "NH_4NO_3", "option_labels": ["B"],
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    out = solve_question(question(options=MCQ_OPTIONS, printed_answer="D"), "d1")
    print(f"  printed=D solver=B -> agrees={out['agrees_with_printed_answer']}")
    assert out["agrees_with_printed_answer"] is False


def test_pipeline_refuses_a_bare_mcq_stem_end_to_end(monkeypatch):
    """The whole path: cropped photo -> no options -> nothing solved."""
    stub_transcriber(monkeypatch, mcq_transcription(options=[]))
    solver = stub_solver(monkeypatch, [GOOD_SOLUTION])
    with pytest.raises(SnapError) as err:
        solve_snapped_image(b"img", "image/jpeg", "d1")
    print(f"  solver called {solver.calls}x; refused: {str(err.value)[:80]}")
    assert solver.calls == 0


# --- printed answer keys are stripped in CODE, not just asked for -----------

def test_printed_answer_is_stripped_from_the_transcription(monkeypatch):
    """The prompt asks for this; a real exam page ignored it. Code enforces it."""
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "text": "1. Extra pure $N_2$ is obtained by heating\n(A) a (B) b\n(C) c (D) d\n\nANSWER : D",
        "question_type": "single_correct", "options": MCQ_OPTIONS, "legible": True}]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  text tail={q['text'].splitlines()[-1]!r}")
    print(f"  printed_answer={q['printed_answer']!r}")
    assert "ANSWER" not in q["text"].upper()
    assert q["printed_answer"] == "D"


def test_stripped_key_beats_the_models_own_field(monkeypatch):
    """What the code removed is authoritative over what the model reported."""
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "text": "Q?\n(A) a (B) b\nAns. (B)", "is_multiple_choice": True,
        "options": MCQ_OPTIONS, "printed_answer": "A", "legible": True}]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  model said A, page said B -> {q['printed_answer']!r}")
    assert q["printed_answer"] == "B"


def test_prose_containing_the_word_answer_is_not_stripped(monkeypatch):
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "text": "Explain why the answer depends on temperature.", "legible": True}]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  text={q['text']!r} printed_answer={q['printed_answer']!r}")
    assert q["text"].endswith("temperature.")
    assert q["printed_answer"] is None


# --- "incomplete question" is not a solved doubt ---------------------------

def test_unanswerable_is_refused_not_stored_as_solved(monkeypatch):
    """A cropped stem produced 'the question is incomplete' stored as solved."""
    stub_solver(monkeypatch, [json.dumps({
        "answerable": False,
        "answer": "The question is incomplete; it does not say what is heated.",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}],
        "key_idea": "k"})] * 2)
    with pytest.raises(SnapError) as err:
        solve_question(question(), "d1")
    print(f"  refused: {err.value}")
    assert "incomplete" in str(err.value)


def test_answerable_true_still_solves(monkeypatch):
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "$a = 5$",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    out = solve_question(question(), "d1")
    print(f"  solved: {out['answer']!r}")
    assert out["answer"] == "$a = 5$"


def test_unanswerable_marks_the_row_failed_not_solved(monkeypatch):
    """End to end: nothing is solved, so the pipeline raises rather than store."""
    stub_transcriber(monkeypatch, transcription(question(text="A bare stem.")))
    stub_solver(monkeypatch, [json.dumps({
        "answerable": False, "answer": "Incomplete question.",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})] * 2)
    with pytest.raises(SnapError) as err:
        solve_snapped_image(b"img", "image/jpeg", "d1")
    print(f"  pipeline refused: {str(err.value)[:70]}")


# --- new gates: diagrams, truncated options, multi-correct, numerical -------
#
# Each closes a failure measured on a real page:
#   Q3 magnetic field — options flattened, a 4th invented, diagram ignored.
#   Q1 hydrogen       — reasoning said n=1, answer picked the n=3 option.

def test_diagram_dependent_question_is_refused(monkeypatch):
    """The solver never sees the image, so a figure question cannot be solved."""
    stub_transcriber(monkeypatch, mcq_transcription(requires_diagram=True))
    solver = stub_solver(monkeypatch, [GOOD_SOLUTION])
    with pytest.raises(SnapError) as err:
        solve_snapped_image(b"img", "image/jpeg", "d1")
    print(f"  solver called {solver.calls}x; {str(err.value)[:70]}")
    assert solver.calls == 0


def test_truncated_option_list_is_refused(monkeypatch):
    """Three options read, a fourth cut off — do not let the solver choose."""
    stub_transcriber(monkeypatch, mcq_transcription(
        options=MCQ_OPTIONS[:3], options_complete=False))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  legible={q['legible']} note={(q['note'] or '')[:60]!r}")
    assert q["legible"] is False


def test_complete_option_list_is_kept(monkeypatch):
    stub_transcriber(monkeypatch, mcq_transcription(options_complete=True))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  legible={q['legible']} with a complete list")
    assert q["legible"] is True


def test_multi_correct_accepts_several_labels(monkeypatch):
    """Blind solve, then the matcher may return more than one label."""
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "NH_3 with CuO and (NH_4)_2Cr_2O_7",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    stub_matcher(monkeypatch, ["A", "C"])
    out = solve_question(question(options=MCQ_OPTIONS,
                                  question_type="multi_correct"), "d1")
    print(f"  option_labels={out['option_labels']} answer={out['answer']!r}")
    assert out["option_labels"] == ["A", "C"]


def test_single_correct_keeps_only_one_label(monkeypatch):
    """Blind solve, then the matcher; single_correct keeps one label."""
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "NH_3 with CuO",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    stub_matcher(monkeypatch, ["A", "C"])
    out = solve_question(question(options=MCQ_OPTIONS,
                                  question_type="single_correct"), "d1")
    print(f"  matcher said A,C -> narrowed to {out['option_labels']}")
    assert out["option_labels"] == ["A"]


def test_numerical_question_needs_no_options(monkeypatch):
    """NAT: a value answer, no options, and no option gate applied."""
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "text": "Find the value of $x$ to two decimal places.",
        "question_type": "numerical", "options": [], "legible": True}]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  legible={q['legible']} type={q['question_type']}")
    assert q["legible"] is True

    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "3.14", "option_labels": [],
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    out = solve_question(q, "d1")
    print(f"  answer={out['answer']!r} labels={out['option_labels']}")
    assert out["answer"] == "3.14"


def test_subjective_question_needs_no_options(monkeypatch):
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "text": "Derive the expression for escape velocity.",
        "question_type": "subjective", "options": [], "legible": True}]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  legible={q['legible']} type={q['question_type']}")
    assert q["legible"] is True


def test_shared_fragment_does_not_count_as_a_match(monkeypatch):
    """(pi+2)/pi must NOT be matched to the option `pi + 2`.

    A shared numerator is not equality; that near-miss is what produced a
    confident wrong answer on a real page.
    """
    options = [{"label": "A", "text": "$\\pi + 2$"},
               {"label": "B", "text": "$\\pi + 1$"}]
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "$\\dfrac{\\pi + 2}{\\pi}$",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    stub_matcher(monkeypatch, [], equivalent=False)
    out = solve_question(question(options=options), "d1")
    print(f"  labels={out['option_labels']} unmatched={out['unmatched']}")
    assert out["option_labels"] == []
    assert out["unmatched"] is True


def test_option_naming_the_quantity_still_matches_a_bare_value(monkeypatch):
    """Option "r = 2a_0" must match the answer "$2a_0$".

    The mirror of the restated-equation bug below, and it slipped through
    because that fix stripped the "<name> =" prefix from the ANSWER only. Here
    the paper carries it instead: the solver derived the value, every option
    restates it as "r = ...", and a correct answer was shown to the student as
    "matches no option" with option (2) sitting right there on the page.

    The LLM matcher is stubbed to refuse, so a pass proves the exact path
    caught it without spending a call.
    """
    options = [{"label": "1", "text": "r = 4a_0"}, {"label": "2", "text": "r = 2a_0"},
               {"label": "3", "text": "r = a_0/2"}, {"label": "4", "text": "r = a_0/4"}]
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "$2a_0$",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    matcher = stub_matcher(monkeypatch, [], equivalent=False)
    out = solve_question(question(options=options), "d1")
    print(f"  labels={out['option_labels']} answer={out['answer']!r} "
          f"matcher_calls={matcher.calls}")
    assert out["option_labels"] == ["2"]
    assert not out.get("unmatched")
    assert matcher.calls == 0


def test_a_selection_question_is_solved_with_its_options(monkeypatch):
    """"Identify the quantity that CANNOT be measured" needs the four choices.

    Real page, real failure: asked blind, v4 answered "Mass". True — a
    spherometer cannot measure mass — and useless, because "Mass" is not one of
    the four things printed on the paper, so it matched nothing and the answer
    was withheld. The answer to a selection question is not a quantity, it is
    one of the options.
    """
    options = [
        {"label": "1", "text": "Radius of curvature of concave surface"},
        {"label": "2", "text": "Specific rotation of liquids"},
        {"label": "3", "text": "Thickness of thin plates"},
        {"label": "4", "text": "Radius of curvature of convex surface"},
    ]
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "Specific rotation of liquids",
        "option_labels": ["2"],
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    # An option-shown solve cross-checks that its steps conclude the same
    # option, which is a second model call. The cross-check itself is covered
    # by its own tests; here it only has to agree.
    monkeypatch.setattr(snap, "_steps_support_label", lambda *_a, **_kw: ["2"])
    q = question(options=options)
    q["stem"] = "Identify the physical quantity that cannot be measured using spherometer :"
    q["question_type"] = "single_correct"
    out = solve_question(q, "d1")
    print(f"  labels={out['option_labels']} unmatched={out.get('unmatched')}")
    assert out["option_labels"] == ["2"], "the option the paper prints, not a free-text quantity"
    assert not out.get("unmatched")


def test_a_computational_mcq_still_solves_blind(monkeypatch):
    """Showing the options is for SELECTION questions only.

    "The value of 15C13 is" has an answer of its own, and handing over the
    choices only invites reasoning backwards from them. It derives, then
    matches, as it always did.
    """
    options = [{"label": "1", "text": "105"}, {"label": "2", "text": "195"}]
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "105",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    stub_matcher(monkeypatch, ["1"], equivalent=True)
    q = question(options=options)
    q["stem"] = "The value of $^{15}C_{13}$ is"
    out = solve_question(q, "d1")
    print(f"  labels={out['option_labels']}")
    assert out["option_labels"] == ["1"], "matched from a blind derivation"


def test_a_genuinely_absent_answer_still_refuses(monkeypatch):
    """Stripping "<name> =" must not turn near-misses into matches.

    The whole point of exact-ish matching is that a wrong answer is reported as
    unmatched rather than snapped to the closest option.
    """
    options = [{"label": "1", "text": "r = 4a_0"}, {"label": "2", "text": "r = 2a_0"}]
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "$7a_0$",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    stub_matcher(monkeypatch, [], equivalent=False)
    out = solve_question(question(options=options), "d1")
    print(f"  labels={out['option_labels']} unmatched={out.get('unmatched')}")
    assert out["option_labels"] == []
    assert out["unmatched"] is True


def test_restated_equation_still_matches_its_option(monkeypatch):
    """`$x(1/2)=3-e$` must match the option `3 - e` — real bug, real page.

    The prompt asks for the value alone, but the solver restated the equation
    it satisfies. The normalised full string ("x123e") does not equal the
    option's ("3e"), so this fell through to the LLM matcher — which also
    missed it, flagging a correct answer as unmatched. The fix tries the text
    after the LAST '=' too. The matcher is stubbed to refuse the match (a
    trap): if this test passes, the exact path caught it and the matcher was
    never even called.
    """
    options = [{"label": "1", "text": "1/2 + e"}, {"label": "2", "text": "3 + e"},
               {"label": "3", "text": "3 - e"}, {"label": "4", "text": "3/2 + e"}]
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "$x(1/2)=3-e$",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    matcher = stub_matcher(monkeypatch, [], equivalent=False)
    out = solve_question(question(options=options), "d1")
    print(f"  labels={out['option_labels']} answer={out['answer']!r} "
          f"matcher_calls={matcher.calls}")
    assert out["option_labels"] == ["3"]
    assert out["answer"] == "3 - e"
    assert matcher.calls == 0


# --- Mathpix OCR gate -------------------------------------------------------

def test_low_ocr_confidence_proceeds_with_a_warning(monkeypatch):
    """The confidence floor is gone: a watermarked scan scored 0.8177 while
    reading perfectly, so the floor refused good pages. Low scores are logged
    and the downstream gates judge the read instead."""
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": "watermarked scan", "confidence": 0.62})
    structurer = stub_transcriber(monkeypatch, mcq_transcription())
    read = transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  0.62 proceeded -> {len(read['questions'])} question(s), "
          f"structurer called {structurer.calls}x")
    assert structurer.calls == 1
    assert len(read["questions"]) == 1


def test_usable_confidence_proceeds(monkeypatch):
    """0.9697 was a hand-checked perfect read; it must not be refused."""
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": "clean", "confidence": 0.9697})
    stub_transcriber(monkeypatch, mcq_transcription())
    read = transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  confidence 0.67 accepted -> {len(read['questions'])} question(s)")
    assert len(read["questions"]) == 1


def test_missing_confidence_is_not_a_refusal(monkeypatch):
    """Mathpix omits the score on some responses; that is not evidence of a bad read."""
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": "clean", "confidence": None})
    stub_transcriber(monkeypatch, mcq_transcription())
    read = transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  no confidence reported -> proceeded with {len(read['questions'])}")
    assert len(read["questions"]) == 1


def test_ocr_failure_is_a_transcribe_error(monkeypatch):
    def _boom(*_a, **_k):
        raise snap.mathpix.MathpixError("Mathpix returned HTTP 500")
    monkeypatch.setattr(snap.mathpix, "read_page", _boom)
    with pytest.raises(SnapError) as err:
        transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  stage={err.value.stage}: {err.value}")
    assert err.value.stage == "transcribe"


def test_structuring_model_never_receives_the_image(monkeypatch):
    """The whole point of OCR-first: no pixels reach the structuring model."""
    sent = {}

    class _Capturing:
        def __init__(self):
            class _Completions:
                def create(self, **kwargs):
                    sent.update(kwargs)
                    return _Response(mcq_transcription(), MODEL_TRANSCRIBE)
            self.chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(snap, "_openai_client", lambda: _Capturing())
    transcribe_questions(b"img", "image/jpeg", "d1")
    blob = json.dumps(sent["messages"])
    print(f"  structuring input: {sent['messages'][-1]['content'][:70]}…")
    assert "image_url" not in blob and "base64" not in blob
    print("  no image reached the structuring model")


def test_max_questions_is_per_call_overridable(monkeypatch):
    """The daily quota shrinks one submission by passing max_questions."""
    stub_transcriber(monkeypatch, transcription(
        question(text="One."), question(text="Two."), question(text="Three.")))
    read = transcribe_questions(b"img", "image/jpeg", "d1", None, max_questions=1)
    print(f"  capped to {len(read['questions'])}; note={read['note']!r}")
    assert len(read["questions"]) == 1
    assert read["note"]


def test_json_eaten_latex_backslashes_are_restored():
    """`"\\text{e}"` written as `"\text{e}"` parses to TAB+"ext{e}" — valid JSON,
    broken LaTeX. Measured on a real page as `$3-<TAB>ext{e}$`, which KaTeX
    cannot render, and which the existing repair path never saw because the
    JSON itself was well-formed."""
    from app.snap import _repair_latex
    assert _repair_latex("$3-\text{e}$") == "$3-\\text{e}$"
    assert _repair_latex("$\frac{1}{y}$") == "$\\frac{1}{y}$"
    assert _repair_latex("$\bigg($") == "$\\bigg($"
    assert _repair_latex("$\times \theta$") == "$\\times \\theta$"
    # Real newlines separate options and must survive.
    assert _repair_latex("(1) a\n(2) b") == "(1) a\n(2) b"
    print("  control chars restored to LaTeX commands, newlines untouched")


def test_repair_reaches_nested_structures():
    from app.snap import _repair_latex
    out = _repair_latex({"options": [{"text": "$\frac{1}{2}$"}]})
    print(f"  {out}")
    assert out["options"][0]["text"] == "$\\frac{1}{2}$"


def test_perfect_reads_from_real_pages_are_not_refused():
    """Every hand-checked-perfect page must clear the floor.

    A confidence_rate gate set snugly above the single known-bad sample would
    refuse real students' photos; these are the measured good ones.
    """
    from app.mathpix import confidence_is_usable
    for label, rate in [("JEE Q11-Q18", 0.9936), ("JEE Q1-Q8", 0.9975),
                        ("chemistry", 0.9697), ("magnetic field", 0.9982),
                        ("wave equation", 0.9936), ("stem-only crop", 0.9997)]:
        ok = confidence_is_usable(rate)
        print(f"  {label:16} rate={rate} -> {'accepted' if ok else 'REFUSED'}")
        assert ok, f"{label} was a perfect read and must not be refused"


# --- refusals must say what the student can actually DO -------------------
#
# "Upload a better photo" is right for some refusals and actively wrong for
# others. Two JEE questions were refused on a page Mathpix read at
# confidence_rate 0.9936 — telling that student to retake sends them round a
# loop they cannot win, and (before this) charged them quota each time.

def test_unclear_photo_says_retake(monkeypatch):
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": "blurry", "confidence": 0.62})
    with pytest.raises(SnapError) as err:
        transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  reason={err.value.reason} remedy={err.value.remedy}")
    assert err.value.remedy == snap.REMEDY_RETAKE


def test_diagram_question_is_flagged_not_refused(monkeypatch):
    """Figure questions go to the describing pass rather than being refused."""
    stub_transcriber(monkeypatch, mcq_transcription(requires_diagram=True))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  legible={q['legible']} requires_diagram={q['requires_diagram']}")
    assert q["legible"] is True
    assert q["requires_diagram"] is True


def test_cut_off_options_say_retake(monkeypatch):
    stub_transcriber(monkeypatch, mcq_transcription(
        options=MCQ_OPTIONS[:3], options_complete=False))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  reason={q['reason']} remedy={q['remedy']}")
    assert q["remedy"] == snap.REMEDY_RETAKE


def test_unmatched_answer_is_flagged_not_thrown_away(monkeypatch):
    """A derived answer that is on no option is SHOWN, flagged — not refused.

    Refusing threw away a correct derivation whenever the OCR mangled an option,
    and left the student with nothing to judge.
    """
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "$\\dfrac{\\pi+2}{\\pi}$",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    stub_matcher(monkeypatch, [], equivalent=False)
    out = solve_question(question(options=MCQ_OPTIONS), "d1")
    print(f"  unmatched={out['unmatched']} labels={out['option_labels']}")
    print(f"  note: {out['unmatched_note'][:88]}…")
    assert out["unmatched"] is True
    assert out["option_labels"] == []
    # The derived answer survives, so the student can see what it got.
    assert "pi+2" in out["answer"].replace("\\\\", "")


def test_model_failure_is_our_side(monkeypatch):
    stub_solver(monkeypatch, ["{broken", "{still broken"])
    with pytest.raises(SnapError) as err:
        solve_question(question(), "d1")
    print(f"  reason={err.value.reason} remedy={err.value.remedy}")
    assert err.value.remedy == snap.REMEDY_OUR_SIDE
    assert "Monk's end" in str(err.value)


# --- figures: describe them, and only refuse when that fails ---------------

DIAGRAM_JSON = json.dumps({
    "has_diagram": True, "sufficient": True,
    "description": ("A semicircular arc of radius $R$ carrying current $I$, with "
                    "two straight semi-infinite wires entering along the diameter "
                    "from opposite sides, meeting at the centre $C_1$."),
})


def test_diagram_is_described_and_reaches_the_solver(monkeypatch):
    """The description goes to the solver; the IMAGE still does not."""
    stub_transcriber(monkeypatch, [mcq_transcription(requires_diagram=True),
                                   DIAGRAM_JSON])
    sent = {}

    class _Capturing:
        def __init__(self):
            class _Completions:
                def create(self, **kwargs):
                    sent.update(kwargs)
                    return _Response(json.dumps({
                        "answerable": True, "answer": "Ba(N_3)_2",
                        "option_labels": ["D"],
                        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}],
                        "key_idea": "k"}), MODEL_SOLVE)
            self.chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(snap, "_deepseek_client", lambda: _Capturing())
    out = solve_snapped_image(b"img", "image/jpeg", "d1")

    payload = sent["messages"][-1]["content"]
    print(f"  solver payload includes diagram: {'diagram_description' in payload}")
    assert "diagram_description" in payload
    assert "semicircular arc" in payload
    # The image itself must still never reach the solver.
    blob = json.dumps(sent["messages"])
    assert "image_url" not in blob and "base64" not in blob
    assert out["solved_count"] == 1
    print("  described, solved, and no pixels reached the solver")


def test_unreadable_figure_is_refused_honestly(monkeypatch):
    """When the figure cannot be made out, say THAT — not 'bad photo'."""
    stub_transcriber(monkeypatch, [
        mcq_transcription(requires_diagram=True),
        json.dumps({"has_diagram": True, "sufficient": False,
                    "note": "The current direction is not visible."}),
    ])
    solver = stub_solver(monkeypatch, [GOOD_SOLUTION])
    with pytest.raises(SnapError) as err:
        solve_snapped_image(b"img", "image/jpeg", "d1")
    print(f"  solver called {solver.calls}x; {str(err.value)[:90]}…")
    assert solver.calls == 0
    assert "figure" in str(err.value)


def test_thin_description_is_not_solved_from(monkeypatch):
    """'A curvy wire shape' is not something to solve a physics question from."""
    stub_transcriber(monkeypatch, [
        mcq_transcription(requires_diagram=True),
        json.dumps({"has_diagram": True, "sufficient": True,
                    "description": "Some wires."}),
    ])
    solver = stub_solver(monkeypatch, [GOOD_SOLUTION])
    with pytest.raises(SnapError):
        solve_snapped_image(b"img", "image/jpeg", "d1")
    print(f"  solver called {solver.calls}x on a 11-char description")
    assert solver.calls == 0


# --- back-fitting is now structurally impossible -----------------------------
#
# Measured failure this closes: shown the options, the solver derived
# pi/(pi+1), wrote "that is not among options", changed its assumption, and
# picked (pi+2)/(pi+1) because it matched. It cannot do that if it never sees
# the options.

def test_solver_is_not_shown_the_options(monkeypatch):
    """A self-contained choice question is solved blind, from the stem only."""
    sent = {}

    class _Capturing:
        def __init__(self):
            class _Completions:
                def create(self, **kwargs):
                    sent.update(kwargs)
                    return _Response(json.dumps({
                        "answerable": True, "answer": "Ba(N_3)_2",
                        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}],
                        "key_idea": "k"}), MODEL_SOLVE)
            self.chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(snap, "_deepseek_client", lambda: _Capturing())
    stub_matcher(monkeypatch, ["D"])
    q = question(options=MCQ_OPTIONS)
    q["stem"] = "Extra pure $N_2$ is obtained by heating"
    out = solve_question(q, "d1")

    payload = sent["messages"][-1]["content"]
    print(f"  solver saw: {payload[:96]}…")
    assert '"options": []' in payload
    for opt in MCQ_OPTIONS:
        assert opt["text"] not in payload, f"{opt['text']} leaked to the solver"
    print("  no option text reached the solver; matcher assigned", out["option_labels"])
    assert out["option_labels"] == ["D"]


def test_statement_questions_still_see_their_options(monkeypatch):
    """"Which of the following is NOT true" IS its options -- withholding them
    would make it unanswerable."""
    sent = {}

    class _Capturing:
        def __init__(self):
            class _Completions:
                def create(self, **kwargs):
                    sent.update(kwargs)
                    return _Response(json.dumps({
                        "answerable": True, "answer": "NH_4NO_3",
                        "option_labels": ["B"],
                        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}],
                        "key_idea": "k"}), MODEL_SOLVE)
            self.chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(snap, "_deepseek_client", lambda: _Capturing())
    q = question(options=MCQ_OPTIONS)
    q["self_contained"] = False
    out = solve_question(q, "d1")
    payload = sent["messages"][-1]["content"]
    print(f"  options supplied: {'NH_4NO_3' in payload}")
    assert "NH_4NO_3" in payload
    assert out["option_labels"] == ["B"]


def test_answer_becomes_the_option_text_after_matching(monkeypatch):
    """The stored answer reads as the printed choice, not the solver's phrasing."""
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "barium azide",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    stub_matcher(monkeypatch, ["D"])
    out = solve_question(question(options=MCQ_OPTIONS), "d1")
    print(f"  {out['option_labels']} -> {out['answer']!r}")
    assert out["answer"] == "Ba(N_3)_2"


# --- steps must be readable by a student, not a record of thinking ---------

def test_long_steps_are_flagged():
    from app.snap import _step_problems, MAX_STEP_CHARS
    problems = _step_problems([{"n": 1, "text": "x" * (MAX_STEP_CHARS + 50)}])
    print(f"  {problems}")
    assert problems and "characters" in problems[0]


def test_deliberation_in_steps_is_flagged():
    """The measured failure: a step that argued with itself and named the options."""
    from app.snap import _step_problems
    problems = _step_problems([{"n": 5, "text":
        "The ratio is 1/2. However, that is not among the options. "
        "Re-evaluating: perhaps the wires also contribute."}])
    print(f"  {problems}")
    assert problems and "thinks out loud" in problems[0]


def test_too_many_steps_are_flagged():
    from app.snap import _step_problems, MAX_STEPS
    problems = _step_problems([{"n": i, "text": "clean"} for i in range(MAX_STEPS + 2)])
    print(f"  {problems}")
    assert problems and "steps" in problems[0]


def test_clean_steps_pass():
    from app.snap import _step_problems
    problems = _step_problems([
        {"n": 1, "text": "Newton's second law gives $F = ma$."},
        {"n": 2, "text": "Rearranging, $a = F/m = 10/2 = 5$ m s$^{-2}$."},
    ])
    print(f"  problems: {problems or 'none'}")
    assert problems == []


def test_rambling_steps_earn_one_rewrite(monkeypatch):
    """A poor first answer is rewritten, not discarded — the answer was fine."""
    rambling = json.dumps({
        "answerable": True, "answer": "$a = 5$",
        "steps": [{"n": 1, "text": "First. However, re-evaluating: " + "x" * 500}],
        "key_idea": "k"})
    clean = json.dumps({
        "answerable": True, "answer": "$a = 5$",
        "steps": [{"n": 1, "text": "Newton's second law gives $F = ma$."},
                  {"n": 2, "text": "So $a = 10/2 = 5$ m s$^{-2}$."}],
        "key_idea": "k"})
    client = stub_solver(monkeypatch, [rambling, clean])
    out = solve_question(question(), "d1")
    print(f"  {client.calls} solve calls; final steps: {len(out['steps'])}")
    for st in out["steps"]:
        print(f"    {st['n']}. [{len(st['text'])} chars] {st['text'][:60]}")
    assert client.calls == 2
    assert len(out["steps"]) == 2


# --- self-consistency: an unstable answer is flagged, not asserted ----------
#
# Measured need: an identical photo produced 13 on one run and 14 on the next
# at temperature 0. A single sample asserts a coin flip as fact.

def _solution(ans, answerable=True):
    return json.dumps({
        "answerable": answerable, "answer": ans,
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})


def test_majority_vote_picks_the_stable_answer(monkeypatch):
    """2 of 3 samples say 14 -> 14 wins, the 13 is outvoted."""
    monkeypatch.setattr(snap, "SOLVE_SAMPLES", 3)
    stub_solver(monkeypatch, [_solution("13"), _solution("14"), _solution("14")])
    out = solve_question(question(), "d1")
    print(f"  votes={out.get('consensus_votes')} -> {out['answer']!r}")
    assert out["answer"] == "14"
    assert out.get("no_consensus") is None


def test_three_way_split_is_flagged_not_asserted(monkeypatch):
    monkeypatch.setattr(snap, "SOLVE_SAMPLES", 3)
    stub_solver(monkeypatch, [_solution("13"), _solution("14"), _solution("15")])
    out = solve_question(question(), "d1")
    print(f"  votes={out.get('consensus_votes')} no_consensus={out.get('no_consensus')}")
    assert out.get("no_consensus") is True
    assert "different" in out["consensus_note"]


def test_unanimous_is_clean(monkeypatch):
    monkeypatch.setattr(snap, "SOLVE_SAMPLES", 3)
    stub_solver(monkeypatch, [_solution("42")] * 3)
    out = solve_question(question(), "d1")
    print(f"  votes={out.get('consensus_votes')}")
    assert out["answer"] == "42"
    assert out.get("no_consensus") is None


def test_one_sample_keeps_the_old_behaviour(monkeypatch):
    monkeypatch.setattr(snap, "SOLVE_SAMPLES", 1)
    client = stub_solver(monkeypatch, [_solution("42")])
    out = solve_question(question(), "d1")
    print(f"  {client.calls} call(s), votes={out.get('consensus_votes')}")
    assert client.calls == 1
    assert "consensus_votes" not in out


def test_failed_samples_do_not_sink_the_vote(monkeypatch):
    """One sample dies (bad JSON twice); the other two still decide."""
    monkeypatch.setattr(snap, "SOLVE_SAMPLES", 3)
    stub_solver(monkeypatch, ["{broken", "{broken", _solution("7"), _solution("7")])
    out = solve_question(question(), "d1")
    print(f"  votes={out.get('consensus_votes')} -> {out['answer']!r}")
    assert out["answer"] == "7"


# --- extraction fidelity: options must exist on the page --------------------

OCR_PAGE = ("Q2. Let $x=x(y)$ solve the equation. If $x(1)=1$, then:\n"
            "(1) $\\frac{1}{2}+e$\n(2) $3+e$\n(3) $3-e$\n(4) $\\frac{3}{2}+e$")


def test_invented_option_is_caught(monkeypatch):
    """An option the structuring model made up is not on the page -> refused."""
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": OCR_PAGE, "confidence": 0.99})
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "text": "…", "stem": "…", "question_type": "single_correct", "legible": True,
        "options": [{"label": "1", "text": "$\\frac{1}{2}+e$"},
                    {"label": "2", "text": "$3+e$"},
                    {"label": "3", "text": "$3-e$"},
                    {"label": "4", "text": "$\\pi + 4$"}]}]}))   # invented
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  legible={q['legible']} reason={q['reason']}")
    assert q["legible"] is False and q["reason"] == "options_fidelity"


def test_sign_flip_is_caught(monkeypatch):
    """The measured mutation: page says 3-e, structure says 3+e twice."""
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": OCR_PAGE.replace("(2) $3+e$", "(2) $1+e$"),
                                           "confidence": 0.99})
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "text": "…", "stem": "…", "question_type": "single_correct", "legible": True,
        "options": [{"label": "1", "text": "$\\frac{1}{2}+e$"},
                    {"label": "2", "text": "$3+e$"},        # page says 1+e
                    {"label": "3", "text": "$3-e$"},
                    {"label": "4", "text": "$\\frac{3}{2}+e$"}]}]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  legible={q['legible']} reason={q['reason']}")
    assert q["legible"] is False


def test_faithful_options_pass(monkeypatch):
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": OCR_PAGE, "confidence": 0.99})
    stub_transcriber(monkeypatch, json.dumps({"questions": [{
        "text": "…", "stem": "…", "question_type": "single_correct", "legible": True,
        "options": [{"label": "1", "text": "$\\frac{1}{2}+\\mathrm{e}$"},
                    {"label": "2", "text": "$3+e$"},
                    {"label": "3", "text": "$3-e$"},
                    {"label": "4", "text": "$\\frac{3}{2}+e$"}]}]}))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  legible={q['legible']} (LaTeX-wrapper differences tolerated)")
    assert q["legible"] is True


def test_answer_contradicting_its_own_steps_is_corrected(monkeypatch):
    """Solver saw options, steps derived B, answer said D -> derivation wins."""
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True,
        "answer": "octahedral, square planar and octahedral",
        "option_labels": ["D"],
        "steps": [{"n": 1, "text": "Cl gives tetrahedral."},
                  {"n": 2, "text": "CN gives square planar."},
                  {"n": 3, "text": "H2O gives octahedral."}],
        "key_idea": "k"})])
    stub_transcriber(monkeypatch, json.dumps({"option_labels": ["B"], "clear": True}))
    opts = [{"label": "A", "text": "octahedral, tetrahedral and square planar"},
            {"label": "B", "text": "tetrahedral, square planar and octahedral"},
            {"label": "C", "text": "square planar, tetrahedral and octahedral"},
            {"label": "D", "text": "octahedral, square planar and octahedral"}]
    q = question(options=opts)
    q["self_contained"] = False
    out = solve_question(q, "d1")
    print(f"  corrected to {out['option_labels']} ({out['answer'][:44]!r})")
    assert out["option_labels"] == ["B"]
    assert out.get("answer_from_steps") is True


# ── The shapes a JEE / NEET paper actually prints ────────────────────────────
#
# Built after a run of one-shape-at-a-time bugs: numerical questions refused for
# having no options, figure questions refused before their figure was read,
# options that are graphs refused as unreadable. Each of those was a shape
# nobody had walked through. This walks all of them.
#
# The structuring MODEL is stubbed per shape with what it actually returned for
# that shape on the live API, so this pins OUR handling — the gates, the
# overrides, the refusals — rather than re-testing gpt-4o.

def _shape(monkeypatch, ocr, structured, **page_over):
    page = {"text": ocr, "confidence": 0.99, "page_confidence": 0.9,
            "diagram_regions": 0, "ocr_ms": 0,
            "diagram_spans": [], "text_lines": []}
    page.update(page_over)
    monkeypatch.setattr(snap.mathpix, "read_page", lambda *_a, **_k: page)
    stub_transcriber(monkeypatch, json.dumps({"questions": [structured]}))
    return transcribe_questions(b"x", "image/png", "d1", None, 1)["questions"][0]


def test_shape_assertion_reason(monkeypatch):
    """Statement I / Statement II. The options describe which statement holds,
    so the stem cannot be answered without them — self_contained must be False
    or the solver derives blind and has nothing to match against."""
    ocr = ("Q5. Statement I: one mole of propyne gives half a mole of H2.\n"
           "Statement II: four g of propyne gives NH3 occupying 224 mL at STP.\n"
           "(1) I incorrect II correct (2) Both correct\n"
           "(3) I correct II incorrect (4) Both incorrect\n")
    q = _shape(monkeypatch, ocr, {
        "number": 5, "question_type": "single_correct", "legible": True,
        "self_contained": False, "stem": "Statement I ... Statement II ...",
        "options": [{"label": "1", "text": "I incorrect II correct"},
                    {"label": "2", "text": "Both correct"},
                    {"label": "3", "text": "I correct II incorrect"},
                    {"label": "4", "text": "Both incorrect"}]})
    print(f"  legible={q['legible']} self_contained={q['self_contained']}")
    assert q["legible"] is True
    assert q["self_contained"] is False


def test_shape_match_the_column(monkeypatch):
    """List-I against List-II, options are pairings. Same rule: the options are
    the answer space, so the solver must see them."""
    ocr = ("Q7. Match List-I with List-II.\n"
           "(A) Ammeter (B) Voltmeter (C) Galvanometer (D) Ohmmeter\n"
           "(I) low shunt (II) high series (III) small current (IV) resistance\n"
           "(1) A-I, B-II, C-III, D-IV (2) A-II, B-I, C-III, D-IV\n"
           "(3) A-I, B-III, C-II, D-IV (4) A-IV, B-II, C-III, D-I\n")
    q = _shape(monkeypatch, ocr, {
        "number": 7, "question_type": "multi_correct", "legible": True,
        "self_contained": False, "stem": "Match List-I with List-II.",
        "options": [{"label": "1", "text": "A-I, B-II, C-III, D-IV"},
                    {"label": "2", "text": "A-II, B-I, C-III, D-IV"},
                    {"label": "3", "text": "A-I, B-III, C-II, D-IV"},
                    {"label": "4", "text": "A-IV, B-II, C-III, D-I"}]})
    print(f"  legible={q['legible']} opts={len(q['options'])}")
    assert q["legible"] is True
    assert len(q["options"]) == 4


def test_shape_printed_answer_key_is_stripped(monkeypatch):
    """A page that prints its own key must not hand it to the solver.

    Solving becomes copying, and a wrong solve becomes indistinguishable from a
    right one. The key is kept aside to CHECK the answer afterwards.
    """
    ocr = ("Q9. The SI unit of magnetic flux is:\n"
           "(1) tesla (2) weber (3) henry (4) gauss\nANSWER : B\n")
    q = _shape(monkeypatch, ocr, {
        "number": 9, "question_type": "single_correct", "legible": True,
        "stem": "The SI unit of magnetic flux is:\nANSWER : B",
        "options": [{"label": "1", "text": "tesla"}, {"label": "2", "text": "weber"},
                    {"label": "3", "text": "henry"}, {"label": "4", "text": "gauss"}]})
    print(f"  printed_answer={q['printed_answer']!r} stem={q['stem']!r}")
    assert q["printed_answer"] == "B"
    assert "ANSWER" not in q["stem"], "the key was left in what the solver reads"


def test_shape_short_option_list_is_refused(monkeypatch):
    """Two options where the paper prints four means the rest were cropped.

    `options_complete` is set optimistically by the model — a 4-option question
    cropped to 2 came back "complete" — so the count is checked in code.
    """
    ocr = "Q10. Which is a strong electrolyte?\n(1) CH3COOH (2) NH4OH\n"
    q = _shape(monkeypatch, ocr, {
        "number": 10, "question_type": "single_correct", "legible": True,
        "options_complete": True, "stem": "Which is a strong electrolyte?",
        "options": [{"label": "1", "text": "CH3COOH"},
                    {"label": "2", "text": "NH4OH"}]})
    print(f"  legible={q['legible']} reason={q.get('reason')}")
    assert q["legible"] is False
    assert q["reason"] == "options_cut_off"


def test_shape_comprehension_passage_reaches_every_question():
    """A shared passage sits ABOVE the first question of its set.

    Slicing from the question number dropped it, so each question arrived as
    "The time period of revolution is proportional to:" with nothing to reason
    from. Every question in the set needs it.
    """
    ocr = ("Comprehension (Q31 to Q33):\n"
           "A particle of mass m moves in a circular path of radius R under a "
           "central force F = -k/r^2. The total energy is E and angular "
           "momentum is L.\n\n"
           "Q31. The time period of revolution is proportional to:\n"
           "(1) R^{3/2} (2) R^2 (3) R (4) R^{1/2}\n"
           "Q32. The kinetic energy of the particle is:\n"
           "(1) k/2R (2) k/R (3) 2k/R (4) k/4R\n")
    slices = snap._slice_by_question(ocr, [31, 32])
    for n in (31, 32):
        print(f"  Q{n}: passage carried={'central force' in slices[n]}")
        assert "central force" in slices[n], f"Q{n} lost its passage"
    assert "time period" in slices[31] and "kinetic energy" in slices[32]


def test_shape_a_page_header_is_not_carried_as_context():
    """The passage rule must not drag a running header into every slice —
    that is tokens on every question for no benefit."""
    ocr = ("JEE Main 2026 (24 January Shift 2)\n"
           "Q3. Find the acceleration of the block on the incline.\n"
           "(1) 2.5 m/s2 (2) 5 m/s2 (3) 7.5 m/s2 (4) 10 m/s2\n"
           "Q4. Find the tension in the string connecting the blocks.\n"
           "(1) 10 N (2) 20 N (3) 30 N (4) 40 N\n")
    slices = snap._slice_by_question(ocr, [3, 4])
    carried = [n for n, s in slices.items() if "SHARED CONTEXT" in s]
    print(f"  slices carrying the header: {carried}")
    assert not carried, "a short page header should not be treated as a passage"


def test_option_figures_pair_in_reading_order():
    """A 2x2 grid of options pairs down the rows, then across each row.

    Real geometry from a page of four circuits: the y spans OVERLAP in pairs
    (498-589 beside 508-745, 769-982 beside 773-857), so sorting by `top`
    alone interleaves the two rows and hands option 2 the picture of option 3.
    """
    options = [{"label": str(i), "text": f"circuit {i}"} for i in (1, 2, 3, 4)]
    spans = [
        {"top": 769, "bottom": 982, "left": 40, "right": 300},    # bottom-left
        {"top": 498, "bottom": 589, "left": 380, "right": 640},   # top-right
        {"top": 508, "bottom": 745, "left": 40, "right": 300},    # top-left
        {"top": 773, "bottom": 857, "left": 380, "right": 640},   # bottom-right
    ]
    paired = snap.pair_figures(options, spans, "d1")
    order = [(s["top"], s["left"]) for s in paired]
    print(f"  reading order: {order}")
    assert order == [(498, 380), (508, 40), (769, 40), (773, 380)] or \
           order == [(508, 40), (498, 380), (769, 40), (773, 380)], order
    # Whatever the row grouping, the top row must come before the bottom one
    # and each row must run left to right.
    assert order[0][0] < order[2][0] and order[0][1] < order[1][1]
    assert order[2][1] < order[3][1]


def test_a_mismatched_count_is_not_paired():
    """Three figures against four options is a guess, and a guess renames an answer.

    This module already refuses to guess a label-to-option pairing for TEXT,
    because a mislabelled option silently renames the answer. A mislabelled
    picture does the same thing more convincingly.
    """
    options = [{"label": str(i), "text": f"c{i}"} for i in (1, 2, 3, 4)]
    spans = [{"top": 10 * i, "bottom": 10 * i + 5, "left": 0, "right": 50}
             for i in range(3)]
    print(f"  paired: {snap.pair_figures(options, spans, 'd1')}")
    assert snap.pair_figures(options, spans, "d1") is None


def test_figures_without_horizontal_extent_are_not_paired():
    """Older geometry carried only y, and a y-only box cannot separate a row."""
    options = [{"label": "1", "text": "a"}, {"label": "2", "text": "b"}]
    spans = [{"top": 10, "bottom": 40}, {"top": 12, "bottom": 44}]
    assert snap.pair_figures(options, spans, "d1") is None

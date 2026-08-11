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
import sys

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
    """Returns each queued response in turn, so retries can be exercised."""

    def __init__(self, contents, model):
        self._contents = list(contents)
        self._model = model
        self.calls = 0
        outer = self

        class _Completions:
            def create(self, **_kwargs):
                outer.calls += 1
                content = outer._contents.pop(0) if outer._contents else outer._contents
                return _Response(content, outer._model)

        self.chat = type("Chat", (), {"completions": _Completions()})()


@pytest.fixture(autouse=True)
def stub_mathpix_ocr(monkeypatch):
    """Mathpix now reads the page before the structuring model sees it.

    These tests exercise what we do with the structured result, so the OCR is
    stubbed to a confident read. The gate itself is tested explicitly below.
    """
    monkeypatch.setattr(
        snap.mathpix, "read_page",
        lambda *_a, **_k: {"text": "OCR TEXT OF THE PAGE", "confidence": 0.9},
    )


def stub_transcriber(monkeypatch, contents, model=MODEL_TRANSCRIBE):
    client = _Client(contents if isinstance(contents, list) else [contents], model)
    monkeypatch.setattr(snap, "_openai_client", lambda: client)
    return client


def stub_solver(monkeypatch, contents, model=MODEL_SOLVE):
    client = _Client(contents if isinstance(contents, list) else [contents], model)
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
    assert sent["extra_body"] == {"thinking": {"type": "disabled"}}
    print("  no image reached the solver; thinking disabled")


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
    # First question's solve fails both attempts; second succeeds.
    stub_solver(monkeypatch, ["{broken", "{broken", GOOD_SOLUTION])
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


def test_answer_outside_the_options_is_refused(monkeypatch):
    """THE regression: an invented answer must not be stored as solved."""
    stub_solver(monkeypatch, [json.dumps({
        "answer": "Sodium azide (NaN_3)", "option_labels": [],
        "steps": [{"n": 1, "text": "Azides decompose to nitrogen."},
                  {"n": 2, "text": "So sodium azide gives pure $N_2$."}],
        "key_idea": "Azide decomposition."})] * 2)
    with pytest.raises(SnapError) as err:
        solve_question(question(options=MCQ_OPTIONS), "d1")
    print(f"  refused: {err.value}")


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
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "A and C", "option_labels": ["A", "C"],
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    out = solve_question(question(options=MCQ_OPTIONS,
                                  question_type="multi_correct"), "d1")
    print(f"  option_labels={out['option_labels']} answer={out['answer']!r}")
    assert out["option_labels"] == ["A", "C"]


def test_single_correct_keeps_only_one_label(monkeypatch):
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "A and C", "option_labels": ["A", "C"],
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})])
    out = solve_question(question(options=MCQ_OPTIONS,
                                  question_type="single_correct"), "d1")
    print(f"  narrowed to {out['option_labels']}")
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
    """(pi+2)/pi must NOT match the option `pi + 2`. The exact Q3 failure."""
    options = [{"label": "A", "text": "$\\pi + 2$"},
               {"label": "B", "text": "$\\pi + 1$"}]
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "$\\dfrac{\\pi + 2}{\\pi}$",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})] * 2)
    with pytest.raises(SnapError) as err:
        solve_question(question(options=options), "d1")
    print(f"  refused: {str(err.value)[:80]}")


# --- Mathpix OCR gate -------------------------------------------------------

def test_low_ocr_confidence_is_refused(monkeypatch):
    """A read the OCR itself doubts must not be reasoned on.

    Gated on confidence_rate, not confidence: perfect reads scored 0.43-0.94 on
    `confidence`, so it separates nothing. See app/mathpix.py for the table.
    """
    monkeypatch.setattr(snap.mathpix, "read_page",
                        lambda *_a, **_k: {"text": "blurry", "confidence": 0.62})
    structurer = stub_transcriber(monkeypatch, mcq_transcription())
    with pytest.raises(SnapError) as err:
        transcribe_questions(b"img", "image/jpeg", "d1")
    print(f"  structuring model called {structurer.calls}x; {str(err.value)[:64]}")
    assert structurer.calls == 0


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


def test_diagram_question_does_not_blame_the_photo(monkeypatch):
    """A perfect photo of a figure question is still unanswerable."""
    stub_transcriber(monkeypatch, mcq_transcription(requires_diagram=True))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  reason={q['reason']} remedy={q['remedy']}")
    print(f"  note={q['note'][:72]}…")
    assert q["remedy"] == snap.REMEDY_NOT_PHOTO
    assert "will not help" in q["note"]


def test_cut_off_options_say_retake(monkeypatch):
    stub_transcriber(monkeypatch, mcq_transcription(
        options=MCQ_OPTIONS[:3], options_complete=False))
    q = transcribe_questions(b"img", "image/jpeg", "d1")["questions"][0]
    print(f"  reason={q['reason']} remedy={q['remedy']}")
    assert q["remedy"] == snap.REMEDY_RETAKE


def test_no_matching_option_is_our_side_not_theirs(monkeypatch):
    """THE case: page read perfectly, solver could not land on an option."""
    stub_solver(monkeypatch, [json.dumps({
        "answerable": True, "answer": "$\\dfrac{\\pi+2}{\\pi}$",
        "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}], "key_idea": "k"})] * 2)
    with pytest.raises(SnapError) as err:
        solve_question(question(options=MCQ_OPTIONS), "d1")
    print(f"  reason={err.value.reason} remedy={err.value.remedy}")
    print(f"  message: {str(err.value)[:96]}…")
    assert err.value.remedy == snap.REMEDY_OUR_SIDE
    assert "will not change this" in str(err.value)


def test_model_failure_is_our_side(monkeypatch):
    stub_solver(monkeypatch, ["{broken", "{still broken"])
    with pytest.raises(SnapError) as err:
        solve_question(question(), "d1")
    print(f"  reason={err.value.reason} remedy={err.value.remedy}")
    assert err.value.remedy == snap.REMEDY_OUR_SIDE
    assert "Monk's end" in str(err.value)

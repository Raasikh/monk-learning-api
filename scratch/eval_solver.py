"""Solver accuracy eval — the number that decides what ships.

Runs real question photos through the REAL pipeline (Mathpix -> structure ->
blind solve), several rounds per question, and scores against hand-verified
answers. Reports accuracy AND stability, because both failure modes were
measured on real pages:

  - Q3 flipped 13/14 across identical runs (instability)
  - Q64 answered a stable, confidently wrong "3" (systematic error)

Usage:
    python scratch/eval_solver.py --rounds 3 --samples 1     # baseline
    python scratch/eval_solver.py --rounds 3 --samples 3     # consensus voting

Every question prints its own line (AGENTS.md rule 2). Transcription runs once
per image and is shared across rounds, so the eval isolates the SOLVER.
"""
import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.snap as snap  # noqa: E402
from app.snap import SnapError, solve_question, transcribe_questions  # noqa: E402

SCRATCH = ("/private/tmp/claude-501/-Users-raasikhnaveed-Desktop-monk-learning-api/"
           "466d52f7-d267-4106-b6a8-59b66e7e90f7/scratchpad/")

# Hand-verified ground truth, in question order per image. None = no key for
# that question (it is reported but not scored).
GROUND_TRUTH = {
    "jee.png": ["784", "3-e", "14", "e^{8/5}", "22"],
    "question.png": ["Ba(N3)2", "tetrahedral, square planar and octahedral"],
    "q64.png": ["4"],
    "cand_29875.png": ["300 m/s"],
}


def canon(text: str) -> str:
    """Comparison form: LaTeX wrappers off, signs and structure kept.

    Deliberately NOT snap._norm — that strips '+'/'-', which would score the
    measured wrong answer $3+e$ as a match for the correct $3-e$.
    """
    t = (text or "").lower()
    t = t.replace("\\text", "").replace("\\mathrm", "").replace("\\dfrac", "\\frac")
    t = t.replace("\\left", "").replace("\\right", "")
    t = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"\1/\2", t)
    t = re.sub(r"[${}\\ ,_]", "", t)
    return t


def matches(expected: str, got: str) -> bool:
    e, g = canon(expected), canon(got)
    return bool(e) and bool(g) and (e == g or e in g or g in e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--samples", type=int, default=1,
                    help="solver samples per solve (1=single, 3=majority vote)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    snap.SOLVE_SAMPLES = args.samples
    print(f"solver={snap.MODEL_SOLVE}  samples/solve={args.samples}  "
          f"rounds={args.rounds}\n")

    # 1. Transcribe each image once; collect (question, expected) pairs.
    tasks = []
    for image, expected_list in GROUND_TRUTH.items():
        path = SCRATCH + image
        if not os.path.exists(path):
            print(f"SKIP {image}: not on disk")
            continue
        mime = "image/png" if image.endswith(".png") else "image/jpeg"
        with open(path, "rb") as fh:
            blob = fh.read()
        try:
            read = transcribe_questions(blob, mime, image[:6])
        except SnapError as err:
            print(f"SKIP {image}: transcribe refused — {err}")
            continue
        for idx, q in enumerate(read["questions"]):
            expected = expected_list[idx] if idx < len(expected_list) else None
            if not q["legible"]:
                print(f"  {image} q{q['n']}: not solvable ({(q.get('note') or '')[:60]})")
                continue
            if expected is None:
                continue
            tasks.append((image, q, expected))

    print(f"\n{len(tasks)} scoreable questions x {args.rounds} rounds "
          f"= {len(tasks) * args.rounds} solves\n")

    # 2. Solve each question `rounds` times.
    def run_round(job):
        image, q, expected, rnd = job
        try:
            sol = solve_question(dict(q), f"{image[:4]}r{rnd}")
            return (image, q["n"], expected, sol.get("answer") or "",
                    bool(sol.get("no_consensus")), None)
        except SnapError as err:
            return (image, q["n"], expected, None, False, str(err)[:70])

    jobs = [(img, q, exp, r) for (img, q, exp) in tasks
            for r in range(args.rounds)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_round, jobs))

    # 3. Score.
    by_q = {}
    for image, qn, expected, answer, flagged, err in results:
        by_q.setdefault((image, qn, expected), []).append((answer, flagged, err))

    total = correct_all = correct_any = stable = flagged_qs = 0
    print(f"{'question':22} {'expected':16} {'answers over rounds':66} verdict")
    print("-" * 118)
    for (image, qn, expected), rounds in sorted(by_q.items()):
        total += 1
        answers = [a if a is not None else f"REFUSED({e})" for a, f, e in rounds]
        oks = [a is not None and matches(expected, a) for a, f, e in rounds]
        distinct = len({canon(a) if a else f"__refused{i}" for i, (a, f, e) in enumerate(rounds)})
        is_stable = distinct == 1
        any_flag = any(f for a, f, e in rounds)
        if all(oks):
            verdict = "OK"
            correct_all += 1
        elif any(oks):
            verdict = "UNSTABLE(right sometimes)"
        else:
            verdict = "WRONG"
        if any(oks):
            correct_any += 1
        if is_stable:
            stable += 1
        if any_flag:
            flagged_qs += 1
            verdict += " +flagged-unsure"
        print(f"{image[:14]+' q'+str(qn):22} {expected[:16]:16} "
              f"{' | '.join(a[:20] for a in answers):66} {verdict}")

    print("-" * 118)
    print(f"questions            : {total}")
    print(f"correct EVERY round  : {correct_all}/{total}"
          f"  ({100 * correct_all / max(1, total):.0f}%)")
    print(f"correct ANY round    : {correct_any}/{total}")
    print(f"stable across rounds : {stable}/{total}")
    print(f"flagged unsure       : {flagged_qs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

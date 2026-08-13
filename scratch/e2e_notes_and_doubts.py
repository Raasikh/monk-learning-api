"""STALE — predates streaming, remedies, quota and per-question rows.
Trust scratch/eval_solver.py and the /doubts/stream smoke instead; the /notes
assertions here are still valid.

End-to-end exercise of the Notes / Snap a Doubt / My Doubts HTTP surface.

AGENTS.md Rule 2: calling backend functions directly proves nothing about the
app. This drives the real HTTP endpoints with a real Supabase JWT, exactly as
the browser does.

Every assertion prints its own line, so a failure names itself.

Usage:
    # against a locally running uvicorn
    python scratch/e2e_notes_and_doubts.py --base http://localhost:8000

    # against Railway
    python scratch/e2e_notes_and_doubts.py --base https://<railway-host>

    # include the paid Snap pipeline (uploads a real photo, spends model calls)
    python scratch/e2e_notes_and_doubts.py --base ... --image path/to/question.jpg

The JWT comes from scratch/mint_jwt.py if present, or --token.
"""
import argparse
import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = "") -> bool:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}" + (f" — {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))
    return condition


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="API base URL")
    ap.add_argument("--token", help="Supabase access token (JWT)")
    ap.add_argument("--image", help="Path to a question photo; enables the Snap test")
    ap.add_argument("--session-id", help="A finished drona_sessions.id to save as a note")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    token = args.token or os.getenv("E2E_JWT")
    if not token:
        print("No token. Pass --token, set E2E_JWT, or mint one with scratch/mint_jwt.py")
        return 2

    h = {"Authorization": f"Bearer {token}"}
    print(f"Base: {base}")
    print(f"Token: {token[:12]}…\n")

    # ── auth reaches the API at all ─────────────────────────────────────────
    print("--- Auth ---")
    r = requests.get(f"{base}/me", headers=h, timeout=30)
    check("GET /me returns 200", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
    user_id = (r.json() or {}).get("user_id") if r.status_code == 200 else None
    print(f"        user_id={user_id}")

    # ── notes ───────────────────────────────────────────────────────────────
    print("\n--- Notes ---")
    r = requests.get(f"{base}/notes", headers=h, timeout=30)
    check("GET /notes returns 200", r.status_code == 200, f"HTTP {r.status_code} {r.text[:160]}")
    if r.status_code == 200:
        body = r.json()
        check("GET /notes has notes/count/subjects",
              all(k in body for k in ("notes", "count", "subjects")),
              f"keys={list(body)}")
        print(f"        {body.get('count')} note(s), subjects={body.get('subjects')}")

    r = requests.get(f"{base}/notes?q=zzz-nothing-matches", headers=h, timeout=30)
    check("GET /notes?q= filters", r.status_code == 200 and r.json().get("count") == 0,
          f"HTTP {r.status_code}, count={r.json().get('count') if r.ok else '?'}")

    r = requests.get(f"{base}/notes/00000000-0000-0000-0000-000000000000",
                     headers=h, timeout=30)
    check("GET /notes/{unknown} returns 404", r.status_code == 404, f"HTTP {r.status_code}")

    r = requests.post(f"{base}/notes", headers=h, timeout=60,
                      json={"session_id": "00000000-0000-0000-0000-000000000000"})
    check("POST /notes on an unknown session refuses (422)", r.status_code == 422,
          f"HTTP {r.status_code} {r.text[:160]}")

    note_id = None
    if args.session_id:
        r = requests.post(f"{base}/notes", headers=h, timeout=60,
                          json={"session_id": args.session_id})
        ok = check("POST /notes saves a real session", r.status_code == 201,
                   f"HTTP {r.status_code} {r.text[:200]}")
        if ok:
            saved = r.json()
            note_id = saved["id"]
            print(f"        {json.dumps(saved, indent=8)[:400]}")

            r2_ = requests.post(f"{base}/notes", headers=h, timeout=60,
                                json={"session_id": args.session_id})
            check("POST /notes twice does not duplicate",
                  r2_.status_code == 201 and r2_.json().get("already_saved") is True,
                  f"already_saved={r2_.json().get('already_saved') if r2_.ok else '?'}")

            r3 = requests.get(f"{base}/notes/{note_id}", headers=h, timeout=30)
            if check("GET /notes/{id} returns the board", r3.status_code == 200,
                     f"HTTP {r3.status_code}"):
                detail = r3.json()
                segs = detail.get("board_items") or []
                items = sum(len(s.get("items", [])) for s in segs)
                check("saved board is non-empty", items > 0, f"{items} items in {len(segs)} segment(s)")
                check("board never exceeds the plan",
                      detail["segments_covered"] <= detail["total_segments"],
                      f"{detail['segments_covered']}/{detail['total_segments']} segments")
    else:
        print("  SKIP  POST /notes round trip — pass --session-id <finished session>")

    # ── doubts ──────────────────────────────────────────────────────────────
    print("\n--- My Doubts ---")
    r = requests.get(f"{base}/doubts", headers=h, timeout=30)
    check("GET /doubts returns 200", r.status_code == 200, f"HTTP {r.status_code} {r.text[:160]}")
    if r.status_code == 200:
        body = r.json()
        check("GET /doubts has doubts/count/subjects",
              all(k in body for k in ("doubts", "count", "subjects")),
              f"keys={list(body)}")
        print(f"        {body.get('count')} doubt(s), subjects={body.get('subjects')}")

    r = requests.get(f"{base}/doubts/00000000-0000-0000-0000-000000000000",
                     headers=h, timeout=30)
    check("GET /doubts/{unknown} returns 404", r.status_code == 404, f"HTTP {r.status_code}")

    # A non-image upload must be refused before any model call is spent.
    r = requests.post(f"{base}/doubts", headers=h, timeout=60,
                      files={"file": ("notes.txt", b"not an image", "text/plain")})
    check("POST /doubts rejects a non-image (415)", r.status_code == 415,
          f"HTTP {r.status_code} {r.text[:160]}")

    # ── snap, only when a real photo is supplied ────────────────────────────
    print("\n--- Snap a Doubt (real pipeline) ---")
    if not args.image:
        print("  SKIP  pass --image path/to/question.jpg to exercise the models and R2")
    elif not os.path.exists(args.image):
        check("image exists", False, args.image)
    else:
        mime = ("image/png" if args.image.lower().endswith(".png")
                else "image/webp" if args.image.lower().endswith(".webp")
                else "image/jpeg")
        with open(args.image, "rb") as fh:
            blob = fh.read()
        print(f"        uploading {os.path.basename(args.image)} "
              f"({len(blob)} bytes, {mime})")
        r = requests.post(f"{base}/doubts", headers=h, timeout=300,
                          files={"file": (os.path.basename(args.image), blob, mime)})
        print(f"        HTTP {r.status_code}")
        print(f"        {r.text[:1200]}")

        if r.status_code == 201:
            body = r.json()
            check("snap returned questions", bool(body.get("questions")),
                  f"{len(body.get('questions', []))} question(s)")
            check("no more than 2 questions", len(body.get("questions", [])) <= 2)
            solved = [q for q in body.get("questions", []) if q["status"] == "solved"]
            check("at least one question solved", bool(solved),
                  f"{body.get('solved_count')} solved")
            for q in solved:
                check(f"q{q['question_index']} has an answer", bool(q.get("answer")),
                      str(q.get("answer"))[:80])
                check(f"q{q['question_index']} has 3-6 steps",
                      3 <= len(q.get("steps") or []) <= 6,
                      f"{len(q.get('steps') or [])} steps")
                check(f"q{q['question_index']} has a key_idea", bool(q.get("key_idea")),
                      str(q.get("key_idea"))[:80])
                check(f"q{q['question_index']} transcription is not empty",
                      bool(q.get("question_text")))

                d = requests.get(f"{base}/doubts/{q['id']}", headers=h, timeout=30)
                if check(f"GET /doubts/{q['id'][:8]} returns 200", d.status_code == 200,
                         f"HTTP {d.status_code}"):
                    detail = d.json()
                    check("detail exposes a signed image_url, not a key",
                          bool(detail.get("image_url")) and "image_key" not in detail,
                          str(detail.get("image_url"))[:80])

                rep = requests.post(f"{base}/doubts/{q['id']}/report", headers=h,
                                    timeout=30, json={"comment": "e2e smoke test"})
                check("POST /doubts/{id}/report returns 200", rep.status_code == 200,
                      f"HTTP {rep.status_code} {rep.text[:120]}")
        elif r.status_code == 422:
            print("        (422 = the photo was refused; that is a valid honest outcome)")
        elif r.status_code == 503:
            check("R2 configured", False, "503 — R2_* env vars are not set on this server")

    print(f"\n{'=' * 60}")
    print(f"RESULT: {passed} passed, {failed} failed")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

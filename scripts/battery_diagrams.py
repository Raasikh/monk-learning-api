"""Diagram-dependent questions through the FULL production pipeline.

Companion to battery_solve.py, drawing from data/nta_raw: real NTA figures
whose attribution passed vision review, composed into printed pages with
plain-text options, snapped through production under a throwaway account,
graded against the embedded (unverified) NTA keys.

Calibration runs, 2026-09-19:
  - fair harness: 7/9 correct, 0 wrong, 2 honest refusals
  - a deliberately degraded harness (LaTeX-stripped options, downscaled
    figures) scored 3/12 — and the pipeline REFUSED or withheld on every
    degraded item rather than answer wrong. The gates are the story.
  - hand-verified reference remains 63/64 (this week's NTA grading pass).

    python3 scripts/battery_diagrams.py            # ~9-12 questions, ~$1

Requires scratch/vision_results + scratch/vision_batches* + data/nta_raw
on this machine, and the mobile repo's .env for the anon key.
"""
import concurrent.futures as cf
import glob
import io
import json
import os
import random
import sys
import textwrap
import time

import requests
from PIL import Image, ImageDraw, ImageFont
from supabase import create_client

sys.path.insert(0, ".")

API = os.environ.get("BATTERY_API", "https://monk-learning-api-production.up.railway.app")
FONT_PATH = "/System/Library/Fonts/Supplemental/Times New Roman.ttf"


def load_battery(size=12, per_subject=5, seed=11):
    passing = set()
    for f in glob.glob("scratch/vision_results/*.jsonl"):
        for line in open(f):
            try:
                r = json.loads(line)
                if r.get("verdict") == "pass":
                    passing.add(r["id"])
            except json.JSONDecodeError:
                pass
    assets = {}
    for f in (glob.glob("scratch/vision_batches/*.jsonl")
              + glob.glob("scratch/vision_batches_examside/*.jsonl")):
        for line in open(f):
            try:
                r = json.loads(line)
                if r.get("asset_path"):
                    assets[r["id"]] = r["asset_path"]
            except json.JSONDecodeError:
                pass

    def plain(t):
        return t and "\\" not in t and "$" not in t and len(t) < 90

    cands = []
    for line in open("data/nta_raw/diagram_questions.jsonl"):
        r = json.loads(line)
        qid = r.get("diagram_question_id")
        sheet = r.get("answer_sheet") or {}
        if qid not in passing or qid not in assets or not os.path.exists(assets[qid]):
            continue
        key = None
        for e in (sheet.get("entries") or []):
            a = e.get("answer") or {}
            if a.get("option") in ("A", "B", "C", "D"):
                key = a["option"]
        opts = r.get("options") or {}
        stem = r.get("question_text") or ""
        if (not key or set(opts) != set("ABCD")
                or not all(plain(v) for v in opts.values())
                or "\\" in stem or "$" in stem or len(stem) > 380):
            continue
        try:
            if Image.open(assets[qid]).width < 260:
                continue
        except Exception:
            continue
        paper = r.get("paper_id") or ""
        subj = ("physics" if "physics" in paper else
                "chemistry" if "chemistry" in paper else
                "math" if "math" in paper else "other")
        cands.append((qid, subj, stem, opts, key, assets[qid]))
    random.seed(seed)
    random.shuffle(cands)
    battery, per = [], {}
    for c in cands:
        if per.get(c[1], 0) < per_subject and len(battery) < size:
            battery.append(c)
            per[c[1]] = per.get(c[1], 0) + 1
    return battery


def compose(stem, opts, fig_path):
    font = ImageFont.truetype(FONT_PATH, 30)
    fig = Image.open(fig_path).convert("RGB")
    if fig.width > 1100:
        fig = fig.resize((1100, int(fig.height * 1100 / fig.width)))
    lines = [f"1.   {c}" if i == 0 else "      " + c
             for i, c in enumerate(textwrap.wrap(stem, 76))]
    opt_lines = [f"      ({L}) {opts[L]}" for L in "ABCD"]
    H = 60 + 44 * len(lines) + 40 + fig.height + 40 + 44 * len(opt_lines) + 40
    img = Image.new("RGB", (1400, H), "white")
    d = ImageDraw.Draw(img)
    y = 30
    for ln in lines:
        d.text((60, y), ln, fill="black", font=font)
        y += 44
    y += 30
    img.paste(fig, (120, y))
    y += fig.height + 30
    for ln in opt_lines:
        d.text((60, y), ln, fill="black", font=font)
        y += 44
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def main() -> int:
    battery = load_battery()
    print(f"battery of {len(battery)}")
    svc = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    email = f"battery-{int(time.time())}@monk-internal.test"
    password = "battery-" + os.urandom(8).hex()
    user = svc.auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True})
    anon_key = next(
        l.split("=", 1)[1].strip().strip('"') for l in
        open(os.path.expanduser("~/Desktop/monk-learning-mobile/monklearning-mobile/.env"))
        if l.startswith("EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY="))
    anon = create_client(os.environ["SUPABASE_URL"], anon_key)
    token = anon.auth.sign_in_with_password(
        {"email": email, "password": password}).session.access_token

    def snap(item):
        qid, subj, stem, opts, key, fig = item
        try:
            img = compose(stem, opts, fig)
            r = requests.post(f"{API}/doubts",
                              headers={"Authorization": f"Bearer {token}"},
                              files={"file": (f"{qid}.jpg", img, "image/jpeg")},
                              timeout=300)
            if r.status_code != 201:
                try:
                    msg = str((r.json().get("detail") or {}))[:90]
                except Exception:
                    msg = r.text[:90]
                return (qid, subj, key, None, None, None, msg)
            qs = r.json().get("questions") or []
            q = qs[0] if qs else {}
            return (qid, subj, key, q.get("option_labels") or [],
                    (q.get("answer") or "")[:35], q.get("status"),
                    (q.get("failure_reason") or "")[:70])
        except Exception as err:
            return (qid, subj, key, None, None, None, f"EXC {err}")

    try:
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            results = list(ex.map(snap, battery))
        score = wrong = refused = withheld = 0
        for qid, subj, key, labels, ans, status, note in results:
            if labels is None:
                refused += 1
                print(f"RF {subj:9s} {qid[:8]} key={key} -> {note}")
                continue
            ok = labels == [key]
            held = status == "unsure" or not labels
            score += ok
            withheld += (held and not ok)
            wrong += (not ok and not held)
            print(f"{'OK' if ok else ('WH' if held else 'XX')} {subj:9s} "
                  f"{qid[:8]} key={key} -> labels={labels} status={status} ans={ans!r}")
        print(f"\n{score}/{len(results)} correct | {withheld} withheld | "
              f"{refused} refused | {wrong} wrong (keys embedded_unverified)")
        return 0 if wrong == 0 else 1
    finally:
        svc.table("doubts").delete().eq("user_id", user.user.id).execute()
        svc.auth.admin.delete_user(user.user.id)
        print("battery account cleaned up")


if __name__ == "__main__":
    raise SystemExit(main())

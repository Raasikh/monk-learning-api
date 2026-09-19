"""Twelve of the hardest JEE Main / NEET formats, through the FULL pipeline.

Renders real printed pages, snaps them through production — Mathpix OCR,
structuring, solve, stepcheck, matcher, the unsure gate — under a throwaway
account, grades against official answers by content signature, and deletes
the account. First run scored 12/12, including the trap page whose options
are all wrong: the pipeline derived the true value, second-checked it, and
withheld rather than force a pick.

Run it after any change to prompts/snap_*.md or the solve path:

    python3 scripts/battery_solve.py

Costs a few rupees of OCR + solve tokens and one throwaway account.
Question formats covered: assertion-reason, Statement I/II, match-the-
following, respectively-tuples (blind, permutation options), NOT-negation,
ordered ratios, AP-sum / count / kinematics numericals, an sp2-count with a
condensed structure, and the all-options-wrong gate test.
"""
import concurrent.futures as cf
import io
import os
import re
import sys
import textwrap
import time

import requests
from PIL import Image, ImageDraw, ImageFont
from supabase import create_client

sys.path.insert(0, ".")

API = os.environ.get("BATTERY_API", "https://monk-learning-api-production.up.railway.app")
FONT = "/System/Library/Fonts/Supplemental/Times New Roman.ttf"

PAGES = [
 [(1, "Assertion (A): In uniform circular motion, the work done by the centripetal force on the particle is zero.  Reason (R): The centripetal force is always perpendicular to the velocity of the particle.",
   ["(1) Both A and R are true and R is the correct explanation of A",
    "(2) Both A and R are true but R is not the correct explanation of A",
    "(3) A is true but R is false", "(4) A is false but R is true"]),
  (2, "Statement I: The temperature of a gas rises when it is compressed adiabatically.  Statement II: In an adiabatic compression, the work done on the gas increases its internal energy.",
   ["(1) Both Statement I and Statement II are true",
    "(2) Both Statement I and Statement II are false",
    "(3) Statement I is true but Statement II is false",
    "(4) Statement I is false but Statement II is true"]),
  (3, "Match List-I with List-II.  List-I: (A) Ribosome (B) Lysosome (C) Mitochondrion (D) Golgi apparatus.  List-II: (I) ATP synthesis (II) protein synthesis (III) packaging of secretory products (IV) intracellular digestion.  Choose the correct answer:",
   ["(1) A-II, B-IV, C-I, D-III", "(2) A-I, B-II, C-III, D-IV",
    "(3) A-II, B-I, C-IV, D-III", "(4) A-IV, B-II, C-I, D-III"])],
 [(4, "The hybridisation of boron in BF3 and of nitrogen in NH3 respectively are:",
   ["(1) sp2, sp3", "(2) sp3, sp2", "(3) sp2, sp2", "(4) sp3, sp3"]),
  (5, "The sum of the first 20 terms of the arithmetic progression 3, 7, 11, 15, ... is ________.", [])],
 [(6, "Which of the following species is NOT isoelectronic with Na+ ?",
   ["(1) Mg2+", "(2) O2-", "(3) F-", "(4) K+"]),
  (7, "Two resistors of 2 ohm and 2 ohm are connected first in series and then in parallel. The ratio of the effective resistance in series to that in parallel is:",
   ["(1) 4 : 1", "(2) 1 : 4", "(3) 2 : 1", "(4) 1 : 2"]),
  (8, "A projectile is fired at 30 degrees above the horizontal with speed 10 m/s on level ground. Take g = 10 m/s2. The horizontal range is:",
   ["(1) 5 m", "(2) 10 m", "(3) 15 m", "(4) 20 m"])],
 [(9, "The number of sp2 hybridised carbon atoms in phenylacetone, C6H5-CH2-CO-CH3, is ________.", []),
  (10, "A solid sphere rolls without slipping from rest down an incline of vertical height 7 m. Take g = 10 m/s2. The speed of its centre of mass at the bottom, in m/s, is ________.", [])],
 [(11, "Which of the following is a reducing sugar?",
   ["(1) Sucrose", "(2) Maltose", "(3) Starch", "(4) Cellulose"]),
  (12, "Among O2, N2, NO, CO and B2, the number of paramagnetic species is ________.", [])],
]

# (content signature, expected label or numeric string, kind). expected=None
# means every option is wrong and the pipeline must WITHHOLD, not pick.
GRADES = [
    ("assertion",              "1",   "mcq"),
    ("statement i",            "1",   "mcq"),
    ("match list",             "1",   "mcq"),
    ("hybridisation",          "1",   "mcq"),
    ("arithmetic progression", "820", "num"),
    ("isoelectronic",          "4",   "mcq"),
    ("series and then in parallel", "1", "mcq"),
    ("projectile",             None,  "gate"),
    ("phenylacetone",          "7",   "num"),
    ("rolls without slipping", "10",  "num"),
    ("reducing sugar",         "2",   "mcq"),
    ("paramagnetic",           "3",   "num"),
]


def render(page) -> bytes:
    font = ImageFont.truetype(FONT, 30)
    lines = []
    for n, stem, opts in page:
        first = True
        for chunk in textwrap.wrap(stem, 78):
            lines.append((f"{n}.   {chunk}" if first else "      " + chunk))
            first = False
        for o in opts:
            for i, chunk in enumerate(textwrap.wrap(o, 72)):
                lines.append(("      " + chunk) if i == 0 else "          " + chunk)
        lines.append("")
    img = Image.new("RGB", (1400, 60 + 44 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    y = 30
    for ln in lines:
        draw.text((60, y), ln, fill="black", font=font)
        y += 44
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def main() -> int:
    from app.snap import numbers_agree

    svc = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    email = f"battery-{int(time.time())}@monk-internal.test"
    password = "battery-" + os.urandom(8).hex()
    user = svc.auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True})
    anon_key = None
    for line in open(os.path.expanduser(
            "~/Desktop/monk-learning-mobile/monklearning-mobile/.env")):
        if line.startswith("EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY="):
            anon_key = line.split("=", 1)[1].strip().strip('"')
    anon = create_client(os.environ["SUPABASE_URL"], anon_key)
    token = anon.auth.sign_in_with_password(
        {"email": email, "password": password}).session.access_token
    print(f"battery account: {email}")

    questions = []
    try:
        def snap(page):
            r = requests.post(f"{API}/doubts",
                              headers={"Authorization": f"Bearer {token}"},
                              files={"file": ("page.jpg", render(page), "image/jpeg")},
                              timeout=300)
            r.raise_for_status()
            return r.json().get("questions", [])

        with cf.ThreadPoolExecutor(max_workers=5) as ex:
            for qs in ex.map(snap, PAGES):
                questions.extend(qs)

        score = 0
        for signature, expect, kind in GRADES:
            q = next((x for x in questions
                      if signature in (x.get("question_text") or "").lower()), None)
            if q is None:
                print(f"XX {signature:28s} NEVER CAME BACK from structuring")
                continue
            labels = q.get("option_labels") or []
            ans = (q.get("answer") or "").strip()
            status = q.get("status")
            if kind == "gate":
                ok = status != "solved" or not labels
                note = f"status={status} (must withhold)"
            elif kind == "mcq":
                ok = labels == [expect]
                note = f"labels={labels} ans={ans[:35]!r}"
            else:
                ok = bool(numbers_agree(expect, ans)) or expect in ans
                note = f"ans={ans[:35]!r}"
            score += ok
            print(f"{'OK' if ok else 'XX'} {signature:28s} expect={expect} -> {note}")
        print(f"\nSCORE {score}/{len(GRADES)}")
        return 0 if score == len(GRADES) else 1
    finally:
        svc.table("doubts").delete().eq("user_id", user.user.id).execute()
        svc.auth.admin.delete_user(user.user.id)
        print("battery account cleaned up")


if __name__ == "__main__":
    raise SystemExit(main())

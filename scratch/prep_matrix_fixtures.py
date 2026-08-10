"""Prepares fixtures for the Playwright persona/language matrix.

Writes /tmp/drona_matrix_fixtures.json containing, per subject:
  - chapter name + subtopic title (as they appear in the picker UI)
  - the authored checkpoint model_answer for each segment

The model answers let the browser harness type a genuinely correct answer at a
checkpoint. It cannot read them from the UI by design — grade, rubric and
model_answer never reach the client — so a test harness has to source them
server-side.

Also mints a real Supabase ES256 JWT (admin magiclink -> verify) so the browser
authenticates the way a student does. No auth bypass is added anywhere.
"""
import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.db import supabase  # noqa: E402

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SECRET = os.getenv("SUPABASE_SECRET_KEY") or ""
TEST_EMAIL = os.getenv("E2E_TEST_EMAIL", "raasikh.naveed@gmail.com")


def mint_real_jwt():
    headers = {"apikey": SECRET, "Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"}
    gen = requests.post(
        f"{SUPABASE_URL}/auth/v1/admin/generate_link",
        json={"type": "magiclink", "email": TEST_EMAIL},
        headers=headers, timeout=20,
    )
    if gen.status_code != 200:
        sys.exit(f"generate_link failed: {gen.status_code} {gen.text[:300]}")
    otp = gen.json().get("email_otp")
    ver = requests.post(
        f"{SUPABASE_URL}/auth/v1/verify",
        json={"type": "magiclink", "token": otp, "email": TEST_EMAIL},
        headers=headers, timeout=20,
    )
    if ver.status_code != 200:
        sys.exit(f"verify failed: {ver.status_code} {ver.text[:300]}")
    body = ver.json()
    print(f"  minted real JWT for {TEST_EMAIL}: {body['access_token'][:28]}...")
    return body


def main():
    targets = json.load(open("/tmp/drona_matrix_targets.json"))
    chapters = {c["id"]: c for c in (supabase.table("chapters").select("id,name,subject,class_level").execute().data or [])}

    fixtures = {}
    for subject, t in targets.items():
        plan = supabase.table("lesson_plans").select("plan_json") \
            .eq("chapter_id", t["chapter_id"]).eq("subtopic_key", t["subtopic_key"]).limit(1).execute().data
        if not plan:
            print(f"  !! no plan for {subject}, skipping")
            continue
        segs = plan[0]["plan_json"]["segments"]
        ch = chapters.get(t["chapter_id"], {})
        fixtures[subject] = {
            "chapter_name": t["chapter_name"],
            "class_level": ch.get("class_level"),
            "subtopic": t["subtopic"],
            "segment_count": len(segs),
            "model_answers": [(s.get("checkpoint") or {}).get("model_answer") or "" for s in segs],
            "checkpoint_questions": [(s.get("checkpoint") or {}).get("question") or "" for s in segs],
        }
        print(f"  {subject:<12} {t['chapter_name'][:30]:<30} class={ch.get('class_level')} segs={len(segs)}")

    session = mint_real_jwt()
    out = {
        "supabase_url": SUPABASE_URL,
        "project_ref": SUPABASE_URL.split("//")[1].split(".")[0],
        "session": {
            "access_token": session["access_token"],
            "refresh_token": session.get("refresh_token"),
            "expires_at": session.get("expires_at"),
            "expires_in": session.get("expires_in", 3600),
            "token_type": session.get("token_type", "bearer"),
            "user": session.get("user"),
        },
        "fixtures": fixtures,
    }
    with open("/tmp/drona_matrix_fixtures.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nwrote /tmp/drona_matrix_fixtures.json  ({len(fixtures)} subjects)")


if __name__ == "__main__":
    main()

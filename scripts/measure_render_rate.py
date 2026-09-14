"""How many STORED widget payloads would actually draw, per subject per widget.

This is the F5 number, and it is deliberately measured the same way the device
measures it: every payload goes through the client's own `validate()` via
`scripts/validate-payload.mjs`, not through any server-side idea of validity.
A payload that passes `sanitize_widget_payload` and fails here is exactly the
class of defect that left `data_table_trend` at 0/14 while every one of its
payloads looked fine from this side.

A stored payload that cannot draw is worse than no payload: slot 1 outranks
every fallback in `resolve_board_slot`, so it wins precedence and then renders
a blank board. That is why the rate has to be 100%, not merely high.
"""
import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import fetch_all                      # noqa: E402
from app.drona.planner import WIDGET_PAYLOAD_KEY  # noqa: E402

CLI = (Path(__file__).resolve().parent.parent.parent
       / "monk-learning-mobile/monklearning-mobile/scripts/validate-payload.mjs")


def collect(subject: str, class_level: int | None):
    all_chs = fetch_all("chapters", "id,name,subject,class_level")
    known = sorted({c["subject"] for c in all_chs})
    if subject not in known:
        # A misspelled subject used to return "no stored payloads", which reads
        # as a clean result and is the project's recurring defect: a check that
        # PASSES on absent information. `--subject maths` reported maths clear
        # while the table spells it `mathematics`.
        raise SystemExit(f"no subject {subject!r} in chapters; known: {known}")
    chs = [c for c in all_chs
           if c["subject"] == subject
           and (class_level is None or c["class_level"] == class_level)]
    by_id = {c["id"]: c for c in chs}
    out = {}
    for p in fetch_all("lesson_plans", "id,subtopic_key,chapter_id,plan_json"):
        ch = by_id.get(p["chapter_id"])
        if not ch:
            continue
        for i, seg in enumerate((p["plan_json"] or {}).get("segments") or [], 1):
            pay = seg.get(WIDGET_PAYLOAD_KEY)
            if isinstance(pay, dict) and pay.get("widget"):
                out[f"{ch['name']}|{p['subtopic_key']}|seg{i}"] = pay
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", required=True)
    ap.add_argument("--class-level", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    payloads = collect(args.subject, args.class_level)
    if not payloads:
        print(f"{args.subject}: no stored payloads")
        return 0

    tmp = Path("/tmp/render-rate.json")
    tmp.write_text(json.dumps(payloads))
    res = subprocess.run([ "node", str(CLI), str(tmp), "--many", "--json" ],
                         capture_output=True, text=True, timeout=600)
    if res.returncode == 2:
        print(f"validator could not run: {res.stderr[:300]}", file=sys.stderr)
        return 2
    report = json.loads(res.stdout)

    per = defaultdict(lambda: [0, 0])          # widget -> [draws, total]
    bad = []
    for r in report["results"]:
        w = r["widget"] or "(none)"
        per[w][1] += 1
        if r["ok"] is True:
            per[w][0] += 1
        elif r["ok"] is False:
            bad.append((r["key"], w, "; ".join(r["errors"])[:90]))
        else:
            per[w][0] += 1                     # UNJUDGEABLE counts as drawing

    drew = sum(v[0] for v in per.values())
    tot = sum(v[1] for v in per.values())
    if args.json:
        print(json.dumps({"subject": args.subject, "drew": drew, "total": tot,
                          "per_widget": {k: v for k, v in per.items()},
                          "refused": bad}))
        return 0 if drew == tot else 1

    print(f"\n{args.subject}  {drew}/{tot} stored payloads would draw "
          f"({100 * drew / tot:.0f}%)\n")
    for w in sorted(per):
        d, t = per[w]
        flag = "" if d == t else "   <-- NOT 100%"
        print(f"  {w:22} {d:3}/{t:<3} {100 * d / t:3.0f}%{flag}")
    if bad:
        print(f"\n{len(bad)} refused:")
        for k, w, why in bad:
            print(f"  {k[:58]:58} {w:18} {why}")
    return 0 if drew == tot else 1


if __name__ == "__main__":
    raise SystemExit(main())

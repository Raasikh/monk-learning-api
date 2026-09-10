#!/usr/bin/env python3
"""Render a measure_widget_routing JSONL into the human review sheet.

    python3 scripts/render_routing_sheet.py scripts/routing_phy12_ch1.jsonl \
        > scripts/routing_phy12_ch1_payloads.txt

The sheet is the W8 sign-off artifact: one block per segment with the
objective, what was already on the board (PRIOR), what fired or what the
model did instead, the params verbatim, and a blank SANE line for Raasikh.
The format matches scripts/routing_bio_ch12_v5_payloads.txt, which was
rendered ad hoc and whose renderer was never committed — this commits it.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
    if not rows:
        print("empty jsonl", file=sys.stderr)
        return 2

    chapter = rows[0]["chapter"]
    print(f"ARCHETYPE-BRANCH PAYLOAD DUMP — {chapter}, {len(rows)} segments")
    print("Judge `sane`: does this picture belong beside THIS objective, and is it")
    print("different from what the prior-payload lines say was already drawn?")
    print("`sane` is left blank on purpose. Fill it in.")
    print("=" * 78)

    for r in rows:
        print(f"\n[{r['subtopic_key']}  seg {r['segment_index']}]  {r['segment_title']}")
        print(f"  OBJECTIVE : {r['segment_objective']}")
        # The prior block is the PROMPT text; only its payload lines belong on
        # the sheet — the scaffold sentences around them are the same for
        # every segment and drown the payloads a reviewer needs to compare.
        prior_lines = [ln.strip() for ln in (r.get("prior_payload_block") or "").splitlines()
                       if ln.strip().startswith("segment ")]
        if prior_lines:
            for line in prior_lines:
                print(f"  PRIOR     : {line}")
        else:
            print("  PRIOR     : (none — first payload of this session)")
        if r.get("harness_error"):
            print("  HARNESS   : 💥 turn did not run — see the run log")
        elif r.get("fired"):
            print(f"  FIRED     : {r['widget']} v{r.get('widget_version')} route={r.get('route')}")
            print(f"  CAPTION   : {r.get('caption')}")
            print(f"  NODES     : {r.get('node_list')}")
            print(f"  PARAMS    : {json.dumps(r.get('params'))}")
        else:
            d = r.get("decline") or {}
            print(f"  DECLINED  : {d.get('kind') or 'implicit'}  "
                  f"reason={d.get('reason') or '(none volunteered)'}")
            print(f"  INSTEAD   : {r.get('emitted_instead')}  "
                  f"template cue={r.get('diag_hint')}")
        print("  SANE      : ____")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

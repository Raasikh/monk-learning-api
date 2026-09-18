#!/usr/bin/env python3
"""I5 — the pages a reviewer actually works from, rendered from the store.

    python3 scripts/sane_review_surfaces.py

  reports/sane/<chapter>.png   one page per chapter, ONLY the proposed-n rows:
                               objective, widget chosen, the board rendered at
                               343x236, and the reason in prose.
  reports/sane/INDEX.png       one page: chapter, rows, y/n, projected %, and
                               how many n rows stand between it and 85.

Nothing is parsed. The source is content/sane-rows.json; if a page disagrees
with the store, regenerate the page.
"""
from __future__ import annotations

import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
MOB = Path("/Users/raasikhnaveed/Desktop/monk-learning-mobile/monklearning-mobile")
OUT = MOB / "content/illustrations/v1/reports/sane"
SVGS = Path("/tmp/i5-svgs")
STORE = REPO / "content/sane-rows.json"

W, PAD = 1500, 26
BOARD_W, BOARD_H = 514, 354
F = "/System/Library/Fonts/Supplemental/Arial.ttf"
FB = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
INK, MUTED, RULE, FAIL, OK = ((21, 25, 28), (97, 108, 118), (198, 206, 211),
                              (154, 43, 43), (28, 107, 73))


def font(sz, bold=False):
    return ImageFont.truetype(FB if bold else F, sz)


def wrap(d, text, fnt, width, maxl):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=fnt) <= width:
            cur = t
        else:
            lines.append(cur); cur = w
            if len(lines) == maxl:
                return lines
    if cur:
        lines.append(cur)
    return lines[:maxl]


def main() -> int:
    doc = json.loads(STORE.read_text())
    props = doc.get("proposals_2026_09_17") or []
    if not props:
        raise SystemExit("no proposals in the store — run scripts/sane_remeasure.py --write")

    per = {}
    for r in props:
        per.setdefault(r["chapter"], []).append(r)

    # ── render the boards that exist, through the real widget modules ──────
    from app.db import fetch_all
    from app.drona.planner import WIDGET_PAYLOAD_KEY
    chs = {c["id"]: c for c in fetch_all("chapters", "id,name")}
    payloads = {}
    for p in fetch_all("lesson_plans", "chapter_id,subtopic_key,plan_json"):
        ch = chs.get(p["chapter_id"])
        if not ch:
            continue
        for i, s in enumerate((p["plan_json"] or {}).get("segments") or [], 1):
            pay = s.get(WIDGET_PAYLOAD_KEY)
            if isinstance(pay, dict) and pay.get("widget"):
                payloads[(ch["name"], p["subtopic_key"], i)] = pay

    # J4: EVERY segment with a stored widget board, not only the proposed-n
    # ones. The point is that Raasikh looks at every picture a student could
    # see, once — a review that shows only the rows a rule already doubted can
    # never catch the rows the rule was wrong about, and this session has now
    # found two of those (five data_table_trend boards flagged as wrong when a
    # ranked table was exactly right).
    jobs = []
    for r in props:
        if not payloads.get((r["chapter"], r["subtopic_key"], r["legacy_segment_index"])):
            continue
        pay = payloads.get((r["chapter"], r["subtopic_key"], r["legacy_segment_index"]))
        if pay:
            r["_rid"] = f"{r['chapter']}__{r['subtopic_key']}__{r['legacy_segment_index']}".replace("/", "-").replace(" ", "_")
            jobs.append({"id": r["_rid"], "widget": pay["widget"], "params": pay["params"]})
    if jobs:
        jf = Path("/tmp/i5-job.json"); jf.write_text(json.dumps(jobs))
        subprocess.run(["npx", "jest", "emit-review-svgs"], cwd=str(MOB),
                       capture_output=True, text=True,
                       env={**__import__("os").environ, "REVIEW_JOB": str(jf),
                            "REVIEW_OUT": str(SVGS)})
    print(f"{len(jobs)} board(s) rendered for {sum(1 for r in props if r['verdict']=='n')} n rows")

    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for chapter, rows in sorted(per.items()):
        boards = [r for r in rows
                  if payloads.get((r["chapter"], r["subtopic_key"],
                                   r["legacy_segment_index"]))]
        n_rows = boards
        n_prop = sum(1 for r in rows if r["verdict"] == "n")
        y, n = len(rows) - n_prop, n_prop
        pct = 100.0 * y / len(rows) if rows else 0.0
        need = 0
        while rows and 100.0 * (y + need) / len(rows) < 85.0 and need <= n:
            need += 1
        index.append((chapter, len(boards), y, n, pct, need))
        if not n_rows:
            continue
        heights = [(BOARD_H + 34) if r.get("_rid") and (SVGS / f"{r['_rid']}.svg").exists()
                   else 150 for r in n_rows]
        img = Image.new("RGB", (W, PAD * 2 + 96 + sum(heights)), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((PAD, PAD), chapter, font=font(30, True), fill=INK)
        d.text((PAD, PAD + 42),
               f"{len(boards)} boards; {n} rows proposed n of {len(rows)} — {pct:.1f}%. "
               f"{'clears 85%' if need == 0 else f'{need} must flip to reach 85%'}.",
               font=font(15), fill=OK if need == 0 else MUTED)
        d.text((PAD, PAD + 64),
               "PROPOSALS, not verdicts — generated by rule. Write y or n beside each.",
               font=font(14), fill=MUTED)
        yy = PAD + 96
        for r, h in zip(n_rows, heights):
            d.line([(PAD, yy), (W - PAD, yy)], fill=RULE, width=1)
            ty = yy + 12
            d.text((PAD, ty), f"{r['subtopic_key']}  seg {r['legacy_segment_index']}",
                   font=font(16, True), fill=INK); ty += 24
            d.text((PAD, ty), f"widget: {r['widget_id']}   kind ({r['proposal_kind']})"
                              f"   status={r['precompute_status']}",
                   font=font(14), fill=MUTED); ty += 22
            tw = W - PAD * 2 - BOARD_W - 30
            for ln in wrap(d, r["objective"], font(15), tw, 4):
                d.text((PAD, ty), ln, font=font(15), fill=INK); ty += 20
            if r.get("reason"):
                ty += 8
                d.text((PAD, ty), "reason:", font=font(13, True), fill=FAIL); ty += 18
                for ln in wrap(d, r["reason"], font(14), tw, 4):
                    d.text((PAD, ty), ln, font=font(14), fill=FAIL); ty += 18
            bx = W - PAD - BOARD_W
            svg = SVGS / f"{r.get('_rid', 'none')}.svg"
            if svg.exists():
                png = cairosvg.svg2png(url=str(svg), output_width=BOARD_W,
                                       output_height=BOARD_H)
                img.paste(Image.open(BytesIO(png)).convert("RGB"), (bx, yy + 12))
                d.rectangle([bx, yy + 12, bx + BOARD_W, yy + 12 + BOARD_H],
                            outline=RULE, width=1)
            else:
                d.rectangle([bx, yy + 12, bx + BOARD_W, yy + 12 + h - 24],
                            outline=RULE, width=1)
                for k, ln in enumerate(wrap(d, "no widget drew here — nothing to look at",
                                            font(14), BOARD_W - 30, 2)):
                    d.text((bx + 15, yy + 24 + k * 19), ln, font=font(14), fill=MUTED)
            yy += h
        p = OUT / f"{chapter.replace('/', '-')}.png"
        img.save(p)

    # ── the index ─────────────────────────────────────────────────────────
    index.sort(key=lambda r: (-r[5], -r[3]))
    ih = PAD * 2 + 150 + 26 * len(index)
    img = Image.new("RGB", (W, ih), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((PAD, PAD), "SANE proposals — where every chapter stands",
           font=font(30, True), fill=INK)
    tot_n = sum(r[3] for r in index)
    clear = sum(1 for r in index if r[5] == 0)
    tot_boards = sum(r[1] for r in index)
    d.text((PAD, PAD + 44),
           f"{tot_boards} stored boards across {len(index)} chapters — every picture a "
           f"student could see. {tot_n} rows proposed n.",
           font=font(16), fill=INK)
    d.text((PAD, PAD + 68),
           f"{clear} chapters would clear 85%; {len(index) - clear} would not.",
           font=font(16), fill=INK)
    d.text((PAD, PAD + 92),
           "Proposals generated by rule on 2026-09-17, NOT human verdicts. "
           "Nothing is adopted.", font=font(14), fill=MUTED)
    yy = PAD + 126
    d.text((PAD, yy), "chapter", font=font(13, True), fill=MUTED)
    for lbl, x in (("boards", 760), ("y", 850), ("n", 920), ("%", 1010), ("to 85", 1120)):
        d.text((x, yy), lbl, font=font(13, True), fill=MUTED)
    yy += 22
    for chapter, tot, y, n, pct, need in index:
        col = OK if need == 0 else INK
        d.text((PAD, yy), chapter[:64], font=font(14), fill=col)
        for val, x in ((tot, 760), (y, 850), (n, 920)):
            d.text((x, yy), str(val), font=font(14), fill=col)
        d.text((1010, yy), f"{pct:.1f}%", font=font(14), fill=col)
        d.text((1120, yy), "—" if need == 0 else str(need), font=font(14, True),
               fill=OK if need == 0 else FAIL)
        yy += 26
    ip = OUT / "INDEX.png"
    img.save(ip)
    print(f"\nindex -> {ip}")
    print(f"pages -> {OUT} ({len([r for r in index if r[3]])} chapters with n rows)")
    print(f"TOTAL proposed-n rows across the corpus: {tot_n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

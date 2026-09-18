#!/usr/bin/env python3
"""Replace the master of an EXISTING accepted asset, by byte change on the slug.

    python3 scripts/replace_master.py --slug <asset_slug> --file <master.png>
    python3 scripts/replace_master.py ... --execute

`ingest_asset.py` is the wrong tool for this. It is built for the original
work-order bundle and requires a labelled reference beside every master, which
a replacement drop does not have — pointed at the v1 tree it refuses all 117
rows for a file no board will ever draw.

What a replacement actually needs is narrow: verify the new master, overwrite
the SAME object key, bump `master_sha256` so `setChapterAssets` invalidates on
the client, and re-derive the @2x rendition. The row already exists; nothing
about routing or concepts changes.

It reuses `upload_and_verify` from ingest_asset rather than re-implementing the
put, so the cache policy and the head-check after the put are the same code
that wrote every other object in the bucket.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    from PIL import Image
    from app.db import fetch_all, get_supabase
    from scripts.ingest_asset import upload_and_verify

    rows = [r for r in fetch_all(
        "concept_assets",
        "id,asset_slug,r2_key,width,height,bytes,master_sha256,rendition_2x_sha256,"
        "content_type,manifest_status") if r["asset_slug"] == args.slug]
    if not rows:
        raise SystemExit(f"no concept_assets row for {args.slug!r} — this replaces an "
                         f"existing asset and will not create one")
    row = rows[0]
    if row["manifest_status"] != "accepted":
        raise SystemExit(f"{args.slug} is {row['manifest_status']!r}, not accepted")

    path = Path(args.file)
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size

    if sha == row["master_sha256"]:
        raise SystemExit("the file is byte-identical to what is stored — a replacement "
                         "that changes nothing would bump no hash and invalidate no "
                         "client cache")

    print(f"{args.slug}")
    print(f"  key        {row['r2_key']}")
    print(f"  was        {row['width']}x{row['height']}  {row['bytes']} bytes  "
          f"sha {row['master_sha256'][:16]}")
    print(f"  becomes    {w}x{h}  {len(data)} bytes  sha {sha[:16]}")

    # The @2x rule: any master under 1600px wide gets one, because the client
    # picks it when the frame's device-pixel width exceeds the master width.
    rend_key = rend_sha = None
    rend_bytes = b""
    if w < 1600:
        big = im.resize((w * 2, h * 2), Image.LANCZOS)
        buf = io.BytesIO(); big.save(buf, format="PNG")
        rend_bytes = buf.getvalue()
        rend_sha = hashlib.sha256(rend_bytes).hexdigest()
        rend_key = row["r2_key"].replace(".png", "@2x.png")
        print(f"  rendition  {w*2}x{h*2}  {len(rend_bytes)} bytes  sha {rend_sha[:16]}")

    if not args.execute:
        print("\nDRY RUN — nothing uploaded, no row touched.")
        return 0

    size = upload_and_verify(row["r2_key"], data, "image/png", object_class="art")
    print(f"\n  uploaded master, R2 reports {size} bytes")
    patch = {"master_sha256": sha, "width": w, "height": h, "bytes": len(data)}
    if rend_key:
        rsize = upload_and_verify(rend_key, rend_bytes, "image/png", object_class="art")
        print(f"  uploaded @2x,    R2 reports {rsize} bytes")
        patch["rendition_2x_sha256"] = rend_sha
    get_supabase().table("concept_assets").update(patch).eq("id", row["id"]).execute()
    print("  row updated — master_sha256 bumped, so every running client refetches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

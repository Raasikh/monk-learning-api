#!/usr/bin/env python3
"""Re-copy the client's generated widget manifest into this repo.

    python3 scripts/sync_widget_manifest.py [--mobile-repo PATH]

`app/drona/registry_manifest.json` is a VERBATIM copy of the mobile repo's
`build/registry-manifest.json`, which is itself generated from
`lib/widgets/registry.ts` by `npm run export-registry`. This script is the only
supported way to refresh it — the point is that no human ever types a widget id
or a version number into this repo.

Run it after any registry change on the client, then commit the JSON. If you
forget, `tests/drona/test_widget_registry.py` fails on any machine that has
both checkouts, naming the exact ids and versions that disagree.

Exit codes: 0 changed or already current, 1 could not find the source.
"""
import argparse
import json
import os
import shutil
import sys

API_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(API_ROOT, "app", "drona", "registry_manifest.json")
REL_SOURCE = os.path.join("build", "registry-manifest.json")

# Same candidate list the drift test uses — keep them in step.
CANDIDATES = [
    os.environ.get("MONK_MOBILE_REPO", ""),
    os.path.join(os.path.dirname(API_ROOT), "monk-learning-mobile", "monklearning-mobile"),
    os.path.join(os.path.dirname(API_ROOT), "monklearning-mobile"),
]


def find_source(explicit: str = "") -> str:
    for root in ([explicit] if explicit else []) + CANDIDATES:
        if not root:
            continue
        candidate = os.path.join(root, REL_SOURCE)
        if os.path.isfile(candidate):
            return candidate
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mobile-repo", default="", help="path to the monklearning-mobile checkout")
    args = ap.parse_args()

    source = find_source(args.mobile_repo)
    if not source:
        print(
            "sync_widget_manifest: could not find build/registry-manifest.json.\n"
            "  Pass --mobile-repo PATH, or set MONK_MOBILE_REPO.\n"
            "  If the file is missing inside the checkout, run `npm run export-registry` there first.",
            file=sys.stderr,
        )
        return 1

    before = ""
    if os.path.isfile(DEST):
        with open(DEST, "r", encoding="utf-8") as f:
            before = f.read()
    with open(source, "r", encoding="utf-8") as f:
        after = f.read()

    if before == after:
        print(f"sync_widget_manifest: already current ({source}).")
    else:
        shutil.copyfile(source, DEST)
        print(f"sync_widget_manifest: updated {DEST}\n  from {source}")

    entries = json.loads(after)
    print(f"  {len(entries)} widgets: " + "  ".join(f"{e['id']}@{e['version']}" for e in entries))
    if before and before != after:
        old = {e["id"]: e["version"] for e in json.loads(before)}
        new = {e["id"]: e["version"] for e in entries}
        for wid in sorted(set(old) | set(new)):
            if old.get(wid) != new.get(wid):
                print(f"  CHANGED {wid}: {old.get(wid, '(absent)')} -> {new.get(wid, '(absent)')}")
        print("  Add a WIDGET_SPECS entry in app/drona/widget_registry.py for any NEW id, "
              "or tests/drona/test_widget_registry.py will fail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

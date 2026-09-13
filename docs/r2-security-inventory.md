# Block F — R2 / asset security inventory

**Report only. Nothing in R2 or in any token was changed to produce this.**
Every line below is a live measurement or a grep, taken 2026-09-12, not a
recollection of how it was set up.

---

## 1. CORS

Measured against the public base with an `Origin` header:

    OPTIONS  ->  HTTP/1.1 204
                 Access-Control-Allow-Origin: *
                 Access-Control-Allow-Methods: GET, HEAD
    GET      ->  Access-Control-Allow-Origin: *

**Assessment: correct, and should stay.** The bucket holds public illustration
art that a student's device fetches anonymously; `*` on `GET, HEAD` is the
whole point. There is no credentialed endpoint here to protect and no
`Access-Control-Allow-Credentials`, so `*` costs nothing.

**Recommendation: leave it.** Narrowing to an app origin would be theatre — a
native app sends no `Origin`, and anyone can read these objects by URL anyway.
Revisit only if a write path is ever exposed to a browser, which today it is
not.

---

## 2. Cache-Control, per object class

| class | example | `Cache-Control` | note |
|---|---|---|---|
| master PNG | `concept-assets/<slug>.png` | `public, max-age=31536000, immutable` | set by `upload_and_verify` |
| @2x rendition | `concept-assets/<slug>@2x.png` | `public, max-age=31536000, immutable` | same path |
| label JSON | `concept-assets/<slug>.json` | **none — no object exists yet** | 404; nothing published (C5 blocks all 23 of bio11 ch7) |
| precompute | — | n/a | precompute output is rows in Postgres, not R2 objects |

Two things worth flagging beyond the header itself:

**The label JSON will inherit `immutable` when it is first published**, because
`upload_and_verify` sets that header for everything it writes. For art that is
defensible; for a label set it is actively wrong — label sets are *expected* to
be republished when a reviewer corrects an anchor, and that is the file most
likely to change after first upload. `apply_review.py` uses the same helper, so
today's code would publish a mutable document under an immutable header.

**Content-Type on the 404 probe came back `text/plain;charset=UTF-8`** — that
is the error body, not a stored object. When label sets publish, confirm they
land as `application/json`; `apply_review.py` passes that explicitly.

---

## 3. The fixed-key + `immutable` contradiction

**This is the real finding, and it is already live.**

`immutable` tells every cache that the bytes at a URL will never change for
`max-age` — a year. The object key is fixed (`concept-assets/<slug>.png`) and
the frog heart master was **replaced in place** at that key on 2026-09-12
(`a9490cc`): same key, new bytes, new ETag. The two facts contradict each
other. Any intermediary that honoured the header keeps serving the old plate
for up to a year, with no way to know it is stale.

**Why nothing broke this time, precisely:**

- `r2.dev` is **uncached** — it is Cloudflare's development endpoint and does
  not sit behind the CDN cache, so the replacement propagated immediately.
- The app's own on-disk cache keys on **sha256 in the filename**, so new bytes
  are a new cache key and the old file is orphaned rather than served.
- B0 (`005ccad`) now invalidates the in-memory record when
  `master_sha256` moves, so a running app picks it up without a restart.

So today the only stale copies possible are in **intermediary caches** — a
corporate proxy, an ISP cache, a student's browser if it ever hits the URL
directly. Not zero, but not the app.

**Recommendation — sha-in-key, at the custom-domain swap, not now.**
`asset_object_key` should include a short content hash
(`concept-assets/<slug>.<sha12>.png`), which makes `immutable` true by
construction: a changed file is a changed URL, and no cache anywhere can serve
a stale one. Deliberately **not** done in this block, because the moment a
custom domain goes in front of the bucket the CDN cache becomes real and the
current header becomes a live year-long hazard. Do both in one change:

1. add the hash to the key,
2. move the base URL to the custom domain,
3. keep `immutable` — it is correct once the key is content-addressed.

Doing the domain swap *without* the key change is the dangerous ordering, and
it is the one that will happen by default if this is not written down.

---

## 4. Token scopes in use

Variable **names** only; no values were read or printed.

| variable | used for |
|---|---|
| `R2_ACCESS_KEY_ID` | S3-API credential, `app/storage_r2.py` |
| `R2_SECRET_ACCESS_KEY` | as above |
| `R2_ENDPOINT_URL` | account S3 endpoint |
| `R2_ASSETS_BUCKET_NAME` | `drona-assets` — illustrations |
| `R2_DOUBTS_BUCKET_NAME` | separate bucket for doubt captures |

**What I could not determine, and am not guessing at:** the Cloudflare API
token's actual scope. The S3 credential pair does not carry its permissions in
any readable form, and reading the token's scope needs the Cloudflare
dashboard or an API call with an account token — neither of which I have, and
neither of which I should.

**Recommendation, for Raasikh to check in the dashboard:** the token used by
the ingest should be **Object Read & Write on `drona-assets` only**. Two
specific things to verify, because both are common and neither is visible from
here:

- that it is not an **Admin Read & Write** token (account-wide, and would let
  a leaked key create or delete *buckets*, not just objects);
- that it does not also carry `drona-doubts`. The doubts bucket holds student
  photo captures; the illustration pipeline has no business touching it, and
  one credential for both means a compromise of the ingest is a compromise of
  student images.

---

## 5. What `/version` exposes

    GET https://monk-learning-api-production.up.railway.app/version
    {"commit":"f599a941d5eaf62f24adf537fbc4f0ceffcff23c"}

A bare commit SHA, unauthenticated. **Assessment: acceptable, keep it.** It
leaks that the repo exists and one hash; it does not leak paths, config,
dependency versions or infrastructure. Against that it is the only way to
confirm which code is actually serving — it is what caught the model-echo
outage deploy and what every live-class verification in this project has keyed
off. Removing it would cost real diagnostic ability to hide something a
GitHub repo name already tells you.

**One caveat:** if the repo ever goes private and the SHA is expected to be
secret, this endpoint contradicts that. Decide once, and deliberately.

---

## 6. Every `r2.dev` reference in code and config

For the custom-domain swap, this is the complete list — five places that must
change together, plus documentation that must not be mistaken for config.

**Configuration (must change):**

    monklearning-mobile/eas.json:14   EXPO_PUBLIC_ASSETS_BASE_URL  (development)
    monklearning-mobile/eas.json:23   EXPO_PUBLIC_ASSETS_BASE_URL  (preview)
    monklearning-mobile/eas.json:32   EXPO_PUBLIC_ASSETS_BASE_URL  (production)
    monklearning-mobile/.env          EXPO_PUBLIC_ASSETS_BASE_URL  (fresh-clone default)

**Hard-coded in scripts (must change):**

    monk-learning-api/scripts/apply_review.py:60          R2_PUBLIC
    monk-learning-api/scripts/draft_anchors_pointed.py:92 R2_BASE

**Prose only (must NOT be edited as if it were config):**

    monklearning-mobile/lib/widgets/labelled-figure/r2-figure-resolver.ts:75
      — an error message naming the bucket
    monk-learning-api/scripts/ingest_asset.py:1796
      — a comment recording that r2.dev refuses the default urllib User-Agent

**A second bucket appears in the docs and is NOT this one:**
`pub-1a2e70cb254c42069ccd8c7c9772de82.r2.dev` in
`docs/DIAGRAM_EXTRACTION_DIRECTIVE.md` and the practice-question audit — that
is the **questions** bucket. It has its own base URL and its own lifetime, and
swapping the illustrations domain must not touch it.

**Recommendation:** the two hard-coded script constants should read the same
environment variable the app does rather than each carrying a literal. Three
copies of a URL is three chances to swap two of them.

---

## Summary of recommendations

| # | recommendation | urgency |
|---|---|---|
| 1 | sha-in-key **at the same time as** the custom-domain swap, never after | high — the swap makes the current header dangerous |
| 2 | do not publish label JSON with `immutable`; it is the file most likely to be republished | high — blocks correctly today only because nothing is published |
| 3 | verify the R2 token is Object R/W on `drona-assets` only, not Admin and not also `drona-doubts` | medium — cannot be checked from here |
| 4 | make the two script constants read the env var | low |
| 5 | CORS as-is; `/version` as-is | none |

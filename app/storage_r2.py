"""Cloudflare R2 object storage for snapped doubt images.

R2 speaks the S3 API, so boto3 drives it. Two rules from the directive shape
this module:

  - The database stores the KEY (`doubts/{user_id}/{doubt_id}.jpg`), never a
    public URL. A student's photographed homework must not be publicly
    addressable.
  - Reads go out as short-lived presigned URLs.

Configuration is read lazily, not at import, so the rest of the API still boots
on a deployment where R2 is not configured yet — and says so loudly when a snap
is attempted rather than failing somewhere deep in a request.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger("storage.r2")

# Presigned reads are for a tab that is open now.
SIGNED_URL_TTL_S = 60 * 60

_client = None


class R2NotConfigured(RuntimeError):
    """R2 credentials are absent. Raised instead of silently skipping upload."""


def _env(*names: str) -> str:
    """First non-empty of `names`, so both naming conventions work."""
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def _config() -> dict:
    """Reads the R2 settings.

    Variable names follow the dronav1project convention, which already holds
    working credentials for this Cloudflare account:

        R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME

    Snapped homework is student PII and does not belong beside the public
    diagram assets, so the bucket is read from R2_DOUBTS_BUCKET_NAME first and
    only falls back to R2_BUCKET_NAME when a dedicated bucket has not been
    created yet. R2_ACCOUNT_ID is accepted as an alternative to a full endpoint.
    """
    endpoint = _env("R2_ENDPOINT_URL")
    account_id = _env("R2_ACCOUNT_ID")
    if not endpoint and account_id:
        endpoint = f"https://{account_id}.r2.cloudflarestorage.com"

    cfg = {
        "endpoint_url": endpoint,
        "access_key_id": _env("R2_ACCESS_KEY_ID"),
        "secret_access_key": _env("R2_SECRET_ACCESS_KEY"),
        "bucket": _env("R2_DOUBTS_BUCKET_NAME", "R2_BUCKET_NAME", "R2_BUCKET"),
    }

    missing_labels = {
        "endpoint_url": "R2_ENDPOINT_URL (or R2_ACCOUNT_ID)",
        "access_key_id": "R2_ACCESS_KEY_ID",
        "secret_access_key": "R2_SECRET_ACCESS_KEY",
        "bucket": "R2_DOUBTS_BUCKET_NAME (or R2_BUCKET_NAME)",
    }
    missing = [missing_labels[k] for k, v in cfg.items() if not v]
    if missing:
        raise R2NotConfigured(
            "R2 is not configured on this server. Missing: " + ", ".join(missing)
        )

    if not _env("R2_DOUBTS_BUCKET_NAME"):
        # Falling back to the shared bucket puts photographed homework beside
        # public lesson assets. It works, but it should be a deliberate choice,
        # not something that happens quietly.
        logger.warning(
            "[R2] R2_DOUBTS_BUCKET_NAME is not set — snapped student photos will "
            "be written to the shared bucket '%s'. Create a dedicated private "
            "bucket and set R2_DOUBTS_BUCKET_NAME.",
            cfg["bucket"],
        )
    return cfg


def is_configured() -> bool:
    try:
        _config()
        return True
    except R2NotConfigured:
        return False


def get_client():
    """S3 client pointed at the R2 endpoint. Cached after first use."""
    global _client
    if _client is not None:
        return _client

    cfg = _config()
    try:
        import boto3
        from botocore.config import Config
    except ImportError as err:  # pragma: no cover - dependency is in requirements
        raise R2NotConfigured(f"boto3 is not installed: {err}")

    _client = boto3.client(
        "s3",
        endpoint_url=cfg["endpoint_url"],
        aws_access_key_id=cfg["access_key_id"],
        aws_secret_access_key=cfg["secret_access_key"],
        # R2 ignores regions but the SDK insists on one, and SigV4 is required.
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 2}),
    )
    return _client


def bucket_name() -> str:
    return _config()["bucket"]


def object_key(user_id: str, doubt_id: str, ext: str = "jpg") -> str:
    """`doubts/{user_id}/{doubt_id}.jpg`, exactly as the directive specifies."""
    return f"doubts/{user_id}/{doubt_id}.{ext}"


def upload_image(key: str, data: bytes, content_type: str) -> None:
    """Puts one image. Raises on failure — an unstored photo is not a success."""
    client = get_client()
    client.put_object(
        Bucket=bucket_name(),
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    logger.info("[R2] stored %s (%d bytes)", key, len(data))


def signed_url(key: Optional[str], ttl_s: int = SIGNED_URL_TTL_S) -> Optional[str]:
    """A short-lived GET URL, or None when one cannot be produced.

    Returning None costs the caller a photo, not the whole response — a doubt is
    still readable without its image.
    """
    if not key:
        return None
    try:
        client = get_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name(), "Key": key},
            ExpiresIn=ttl_s,
        )
    except Exception as err:
        logger.warning("[R2] could not sign %s: %s", key, err)
        return None


def delete_image(key: Optional[str]) -> None:
    """Best-effort delete. Logs rather than raising — the row is already gone."""
    if not key:
        return
    try:
        get_client().delete_object(Bucket=bucket_name(), Key=key)
        logger.info("[R2] deleted %s", key)
    except Exception as err:
        logger.warning("[R2] orphaned object %s: %s", key, err)


# ---------------------------------------------------------------------------
# Illustration assets — a SEPARATE BUCKET, not another prefix in this one.
#
# Everything above serves snapped student homework: private, per-user, read
# only through a 1-hour presigned URL. Illustration art is the exact opposite —
# public, immutable, cacheable, and bundled into the app binary so a live class
# renders in airplane mode.
#
# Those two want opposite bucket policies, and bucket policy is the unit R2
# applies access at. A shared bucket with an `illustrations/` prefix works right
# up until somebody enables public read or attaches a custom domain to serve the
# art quickly — at which point every photographed homework page under
# `doubts/{user_id}/` becomes publicly addressable, and the enumeration is
# trivial because the keys are structured. A prefix is a naming convention; it
# is not an access boundary. So: two buckets.
#
# R2_ASSETS_BUCKET_NAME has NO FALLBACK to R2_DOUBTS_BUCKET_NAME. The fallback
# above exists because a doubt that fails to store loses a student's photo; an
# asset that fails to store loses nothing but an ingest run, and writing public
# art into the private bucket is the failure worth refusing.
ASSETS_KEY_PREFIX = "concept-assets/"

_EXT_FOR_CONTENT_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


def assets_bucket_name() -> str:
    """The illustrations bucket. Raises rather than borrowing the doubts one."""
    _config()  # credentials must be present; same account, same client
    bucket = _env("R2_ASSETS_BUCKET_NAME")
    if not bucket:
        raise R2NotConfigured(
            "R2_ASSETS_BUCKET_NAME is not set. Illustration art must not be "
            "written to the doubts bucket — that bucket holds student PII and "
            "is private by policy. Create a separate public-read bucket and "
            "set R2_ASSETS_BUCKET_NAME."
        )
    return bucket


def asset_object_key(asset_slug: str, variant: str, content_type: str) -> str:
    """`concept-assets/{slug}.png` / `concept-assets/{slug}.labelled.png`.

    Deterministic from (slug, variant), and chosen to be BYTE-IDENTICAL to the
    `file_unlabelled` / `file_labelled` columns of illustration-manifest.csv.
    That is not decoration: it makes the join between the work order, the object
    store and the database checkable by eye, and it means a human comparing a
    bucket listing against the manifest does not have to hold a naming
    convention in their head to do it.

    Deterministic is also what makes re-ingest idempotent: the same slug and
    variant overwrite the same object rather than accumulating a second copy.
    The extension comes from the SNIFFED content type, never from the filename,
    so a .png that is really a JPEG lands as .jpg with the right Content-Type.
    """
    ext = _EXT_FOR_CONTENT_TYPE.get(content_type)
    if ext is None:
        raise ValueError(f"no object-key extension for content type {content_type!r}")
    if variant not in ("unlabelled", "labelled"):
        raise ValueError(f"unknown asset variant {variant!r}")
    infix = "" if variant == "unlabelled" else ".labelled"
    return f"{ASSETS_KEY_PREFIX}{asset_slug}{infix}.{ext}"

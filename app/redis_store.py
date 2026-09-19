"""Shared state for running more than one worker.

Three pieces of state kept this API on a single uvicorn worker, and this
module is their new home:

  1. SESSION TAKEOVER — when a student reconnects, the previous socket must
     be retired or they hear two lessons at once. In-process that was a dict
     lookup; across workers it is an epoch counter per session plus a pub/sub
     channel the old holder listens on.
  2. THE RUMIK GATE — the provider tolerates a bounded number of concurrent
     synthesis connections PER ACCOUNT, and a per-process semaphore stops
     protecting the account the moment there are two processes. The global
     gate is a sorted set of leases scored by time: stale entries purge
     themselves, so a crashed worker's leases free on their own.
  3. THE METRICS SAMPLER — per-worker numbers are reported into short-lived
     hashes; one worker at a time holds a leader lock and writes the summed
     row, so the platform-metrics table keeps meaning what its names say.

Everything here degrades to None/no-op when REDIS_URL is unset: a laptop
running one worker behaves exactly as it always did, and the tests exercise
the real logic against fakeredis.
"""
import asyncio
import logging
import os
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("redis_store")

_client = None
_client_checked = False


def get_redis():
    """The shared async client, or None when no REDIS_URL is configured."""
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True
    url = os.getenv("REDIS_URL")
    if not url:
        logger.info("REDIS_URL unset — shared-state features run in-process only")
        return None
    try:
        import redis.asyncio as aioredis
        _client = aioredis.from_url(url, decode_responses=True,
                                    socket_connect_timeout=3,
                                    socket_timeout=5)
        logger.info("Redis configured for shared state")
    except Exception as err:  # noqa: BLE001 — degrade, never block startup
        logger.error("Redis unavailable (%s) — continuing in-process only", err)
        _client = None
    return _client


def _reset_for_tests(client) -> None:
    global _client, _client_checked
    _client = client
    _client_checked = True


# ── 1. session takeover ─────────────────────────────────────────────────────

def _chan(session_id: str) -> str:
    return f"session:{session_id}:takeover"


async def bump_session_epoch(session_id: str) -> Optional[int]:
    """Registers a new connection for the session; returns its epoch.

    Publishing the new epoch is what retires the previous holder on ANY
    worker. None when Redis is absent — the caller keeps the in-process path.
    """
    r = get_redis()
    if r is None:
        return None
    try:
        epoch = await r.incr(f"session:{session_id}:epoch")
        await r.expire(f"session:{session_id}:epoch", 24 * 3600)
        await r.publish(_chan(session_id), str(epoch))
        return int(epoch)
    except Exception as err:  # noqa: BLE001
        logger.warning("epoch bump failed for %s: %s", session_id[:8], err)
        return None


async def watch_session_takeover(session_id: str, my_epoch: int,
                                 on_retire: Callable[[], Awaitable[None]]):
    """Task body: waits for a NEWER epoch on this session's channel.

    The same retire actions the in-process path runs — deactivate, abort the
    live turn — are the callback's job; this only decides WHEN. Returns when
    retired or cancelled.
    """
    r = get_redis()
    if r is None:
        return
    try:
        pubsub = r.pubsub()
        await pubsub.subscribe(_chan(session_id))
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                try:
                    seen = int(msg.get("data"))
                except (TypeError, ValueError):
                    continue
                if seen > my_epoch:
                    logger.info("🔁 [SESSION TAKEOVER via redis] session %s "
                                "epoch %d superseded by %d",
                                session_id[:8], my_epoch, seen)
                    await on_retire()
                    return
        finally:
            try:
                await pubsub.unsubscribe(_chan(session_id))
                await pubsub.aclose()
            except Exception:
                pass
    except asyncio.CancelledError:
        raise
    except Exception as err:  # noqa: BLE001
        logger.warning("takeover watcher for %s stopped: %s", session_id[:8], err)


# ── 2. the global Rumik gate ────────────────────────────────────────────────

RUMIK_GLOBAL_SLOTS = int(os.getenv("RUMIK_GLOBAL_SLOTS", "50"))
# A synthesis older than this is not running any more, whatever happened to
# the worker that started it. 120s comfortably exceeds the longest sentence.
_LEASE_STALE_S = 120.0
_ZKEY = "rumik:leases"


async def rumik_gate_acquire(timeout_s: float = 3.0) -> Optional[str]:
    """A global lease, or None. None means EITHER no Redis (caller proceeds on
    the local semaphore alone, exactly today's behaviour) OR a genuine global
    exhaustion — the string sentinel distinguishes them."""
    r = get_redis()
    if r is None:
        return "local-only"
    deadline = time.monotonic() + timeout_s
    lease = uuid.uuid4().hex
    while True:
        try:
            now = time.time()
            async with r.pipeline(transaction=True) as p:
                p.zremrangebyscore(_ZKEY, 0, now - _LEASE_STALE_S)
                p.zadd(_ZKEY, {lease: now})
                p.zcard(_ZKEY)
                _, _, count = await p.execute()
            if int(count) <= RUMIK_GLOBAL_SLOTS:
                return lease
            await r.zrem(_ZKEY, lease)
        except Exception as err:  # noqa: BLE001 — Redis trouble must not mute the class
            logger.warning("rumik gate degraded to local-only: %s", err)
            return "local-only"
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(0.05)


async def rumik_gate_release(lease: Optional[str]) -> None:
    if not lease or lease == "local-only":
        return
    r = get_redis()
    if r is None:
        return
    try:
        await r.zrem(_ZKEY, lease)
    except Exception:  # noqa: BLE001
        pass  # the stale purge collects it within _LEASE_STALE_S


# ── 3. the metrics sampler ──────────────────────────────────────────────────

_WORKER_ID = f"{os.getpid()}-{uuid.uuid4().hex[:6]}"


async def metrics_report(fields: Dict[str, Any]) -> bool:
    """Publishes this worker's 30s sample. False when Redis is absent —
    the caller then writes its own row exactly as before."""
    r = get_redis()
    if r is None:
        return False
    try:
        key = f"metrics:worker:{_WORKER_ID}"
        await r.hset(key, mapping={k: str(v) for k, v in fields.items()})
        await r.expire(key, 90)
        return True
    except Exception as err:  # noqa: BLE001
        logger.warning("metrics report failed: %s", err)
        return False


async def metrics_aggregate_if_leader() -> Optional[Dict[str, int]]:
    """The summed sample across workers, if THIS worker holds the leader lock.

    The lock has a 45s TTL against a 30s cadence: a dead leader's lock lapses
    before two samples are missed, and SET NX means exactly one writer.
    """
    r = get_redis()
    if r is None:
        return None
    try:
        am_leader = await r.set("metrics:leader", _WORKER_ID, nx=True, ex=45)
        if not am_leader:
            if await r.get("metrics:leader") == _WORKER_ID:
                await r.expire("metrics:leader", 45)
            else:
                return None
        total: Dict[str, int] = {}
        async for key in r.scan_iter("metrics:worker:*"):
            sample = await r.hgetall(key)
            for k, v in sample.items():
                try:
                    n = int(float(v))
                except (TypeError, ValueError):
                    continue
                if k.startswith("p95"):
                    total[k] = max(total.get(k, 0), n)
                else:
                    total[k] = total.get(k, 0) + n
        return total or None
    except Exception as err:  # noqa: BLE001
        logger.warning("metrics aggregation failed: %s", err)
        return None

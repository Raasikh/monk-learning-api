"""The shared-state store, against a real (fake) Redis.

These are the semantics multi-worker safety rests on: takeover epochs are
monotonic and retire exactly the older holder; the Rumik gate never exceeds
its global cap, frees leases on release, and heals leases a dead worker left
behind; the metrics leader is single and its samples sum.
"""
import asyncio

import fakeredis.aioredis
import pytest

import app.redis_store as store


@pytest.fixture()
def redis_client():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store._reset_for_tests(client)
    yield client
    store._reset_for_tests(None)
    store._client_checked = False


def run(coro):
    return asyncio.run(coro)


def test_epochs_are_monotonic_per_session(redis_client):
    async def go():
        a = await store.bump_session_epoch("s1")
        b = await store.bump_session_epoch("s1")
        other = await store.bump_session_epoch("s2")
        return a, b, other
    a, b, other = run(go())
    assert (a, b) == (1, 2)
    assert other == 1


def test_a_newer_epoch_retires_the_older_watcher(redis_client):
    async def go():
        retired = asyncio.Event()

        async def on_retire():
            retired.set()

        epoch = await store.bump_session_epoch("s1")
        watcher = asyncio.create_task(
            store.watch_session_takeover("s1", epoch, on_retire))
        await asyncio.sleep(0.05)
        await store.bump_session_epoch("s1")  # the reconnect
        await asyncio.wait_for(retired.wait(), timeout=2)
        await asyncio.wait_for(watcher, timeout=2)
        return True
    assert run(go())


def test_gate_caps_at_the_global_slot_count(redis_client, monkeypatch):
    monkeypatch.setattr(store, "RUMIK_GLOBAL_SLOTS", 3)

    async def go():
        leases = [await store.rumik_gate_acquire(timeout_s=0.2) for _ in range(3)]
        assert all(l and l != "local-only" for l in leases)
        blocked = await store.rumik_gate_acquire(timeout_s=0.2)
        assert blocked is None
        await store.rumik_gate_release(leases[0])
        freed = await store.rumik_gate_acquire(timeout_s=0.2)
        assert freed and freed != "local-only"
        return True
    assert run(go())


def test_gate_heals_leases_from_a_dead_worker(redis_client, monkeypatch):
    monkeypatch.setattr(store, "RUMIK_GLOBAL_SLOTS", 1)

    async def go():
        # A lease nobody will ever release, planted 10 minutes in the past —
        # the signature of a worker that crashed mid-synthesis.
        await redis_client.zadd(store._ZKEY, {"dead": __import__("time").time() - 600})
        lease = await store.rumik_gate_acquire(timeout_s=0.2)
        return lease
    lease = run(go())
    assert lease and lease != "local-only"


def test_without_redis_everything_degrades_to_local():
    store._reset_for_tests(None)

    async def go():
        assert await store.bump_session_epoch("s1") is None
        lease = await store.rumik_gate_acquire()
        assert lease == "local-only"
        await store.rumik_gate_release(lease)
        assert await store.metrics_report({"x": 1}) is False
        assert await store.metrics_aggregate_if_leader() is None
        return True
    assert run(go())


def test_one_leader_sums_worker_samples(redis_client):
    async def go():
        await store.metrics_report({"active_sessions": 3, "p95_lease_acquisition_ms": 40})
        other = f"metrics:worker:other"
        await redis_client.hset(other, mapping={"active_sessions": "2",
                                                "p95_lease_acquisition_ms": "90"})
        await redis_client.expire(other, 90)
        total = await store.metrics_aggregate_if_leader()
        assert total["active_sessions"] == 5
        assert total["p95_lease_acquisition_ms"] == 90  # p95 takes the worst worker
        # A second aggregator on another "worker" id must be refused.
        store._WORKER_ID_SAVED = store._WORKER_ID
        store._WORKER_ID = "impostor"
        try:
            assert await store.metrics_aggregate_if_leader() is None
        finally:
            store._WORKER_ID = store._WORKER_ID_SAVED
        return True
    assert run(go())

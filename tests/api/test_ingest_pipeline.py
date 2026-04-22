"""Tests for api/services/ingest_pipeline.py (extracted out of the router)."""
from __future__ import annotations

import pytest

from api.services.ingest_pipeline import BeatLike, bucket_beats, ingest_beat_batch, WINDOW_SEC


def _mk(ts: float, ppi: float = 800.0) -> BeatLike:
    return BeatLike(ts=ts, ppi_ms=ppi)


def test_bucket_beats_empty():
    assert bucket_beats([]) == []


def test_bucket_beats_single_window():
    beats = [_mk(0.0), _mk(60.0), _mk(120.0), _mk(WINDOW_SEC - 1)]
    buckets = bucket_beats(beats)
    assert len(buckets) == 1
    assert [b.ts for b in buckets[0]] == [b.ts for b in beats]


def test_bucket_beats_rolls_over_at_window_boundary():
    # Two windows: [0, 299] and [300, 599]
    beats = [_mk(0.0), _mk(299.0), _mk(300.0), _mk(599.0)]
    buckets = bucket_beats(beats)
    assert len(buckets) == 2
    assert [b.ts for b in buckets[0]] == [0.0, 299.0]
    assert [b.ts for b in buckets[1]] == [300.0, 599.0]


class _StubSvc:
    def __init__(self, fail_indexes: set[int] | None = None) -> None:
        self._uid = "stub-uid"
        self.calls: list[tuple[float, float, str]] = []
        self._fail = fail_indexes or set()

    async def ingest_background_window(self, **kw):
        i = len(self.calls)
        self.calls.append((kw["timestamps"][0], kw["timestamps"][-1], kw["context"]))
        if i in self._fail:
            raise RuntimeError("window failed")


@pytest.mark.asyncio
async def test_ingest_beat_batch_normalises_context_and_counts():
    svc = _StubSvc()
    beats = [_mk(0.0), _mk(299.0), _mk(300.0)]
    windows, received = await ingest_beat_batch(svc, beats=beats, context="garbage")
    assert windows == 2
    assert received == 3
    # context is normalised to `background` when an unknown value is passed.
    assert all(call[2] == "background" for call in svc.calls)


@pytest.mark.asyncio
async def test_ingest_beat_batch_continues_through_errors():
    svc = _StubSvc(fail_indexes={0})
    beats = [_mk(0.0), _mk(10.0), _mk(400.0)]
    windows, _received = await ingest_beat_batch(svc, beats=beats, context="sleep")
    # First window failed, second succeeded — count reflects only successes.
    assert windows == 1

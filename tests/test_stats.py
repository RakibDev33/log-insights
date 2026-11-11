from datetime import UTC, datetime, timedelta

import pytest

from log_insights.parser import LogRecord
from log_insights.stats import LogStats, Reservoir

START = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def record(
    path: str = "/", status: int = 200, seconds: int = 0, duration_ms: float | None = 10.0
) -> LogRecord:
    return LogRecord(
        remote_addr="10.0.0.1",
        timestamp=START + timedelta(seconds=seconds),
        method="GET",
        path=path,
        query=None,
        status=status,
        bytes_sent=100,
        referrer=None,
        user_agent=None,
        duration_ms=duration_ms,
    )


def test_aggregates_counts_status_classes_and_error_rate() -> None:
    stats = LogStats().add_all(
        [record(status=200), record(status=201), record(status=404), record(status=503), None]
    )

    assert stats.total == 4
    assert stats.malformed == 1
    assert stats.bytes_sent == 400
    assert stats.status_classes() == {"2xx": 2, "4xx": 1, "5xx": 1}
    assert stats.error_rate == pytest.approx(0.25)


def test_top_paths_are_ordered_by_count_then_path() -> None:
    stats = LogStats().add_all([record("/b"), record("/a"), record("/c"), record("/c"), record("/a")])

    assert stats.top_paths(2) == [("/a", 2), ("/c", 2)]


def test_busiest_minute_prefers_the_earliest_on_ties() -> None:
    stats = LogStats().add_all(
        [record(seconds=5), record(seconds=65), record(seconds=70), record(seconds=125)]
    )

    assert stats.busiest_minute() == (START + timedelta(minutes=1), 2)


def test_time_range_handles_out_of_order_lines() -> None:
    stats = LogStats().add_all([record(seconds=30), record(seconds=10), record(seconds=90)])

    assert stats.first_seen == START + timedelta(seconds=10)
    assert stats.last_seen == START + timedelta(seconds=90)


def test_latency_percentiles_use_nearest_rank() -> None:
    stats = LogStats().add_all([record(duration_ms=float(ms)) for ms in range(1, 101)])

    assert stats.latency_percentiles() == {"p50": 50.0, "p90": 90.0, "p95": 95.0, "p99": 99.0}


def test_records_without_timing_are_excluded_from_latency() -> None:
    stats = LogStats().add_all([record(duration_ms=None), record(duration_ms=7.0)])

    assert stats.latency_percentiles()["p50"] == 7.0
    assert stats.latencies.seen == 1


def test_reservoir_keeps_memory_bounded_and_samples_uniformly() -> None:
    reservoir = Reservoir(capacity=1_000, seed=42)
    for value in range(100_000):
        reservoir.add(float(value))

    assert len(reservoir.values) == 1_000
    assert reservoir.seen == 100_000
    # A uniform sample of 0..99,999 should have a median close to 50,000.
    median = reservoir.percentile(50)
    assert median is not None
    assert 45_000 < median < 55_000


def test_reservoir_rejects_invalid_arguments() -> None:
    with pytest.raises(ValueError):
        Reservoir(capacity=0)
    reservoir = Reservoir()
    reservoir.add(1.0)
    with pytest.raises(ValueError):
        reservoir.percentile(0)


def test_empty_stats_are_safe() -> None:
    stats = LogStats()

    assert stats.error_rate == 0.0
    assert stats.busiest_minute() is None
    assert stats.latency_percentiles()["p99"] is None
    assert stats.to_dict()["busiest_minute"] is None

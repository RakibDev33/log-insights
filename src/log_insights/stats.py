"""Streaming aggregation over parsed log records with bounded memory for latencies."""

import math
import random
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from log_insights.parser import LogRecord

PERCENTILES = (50, 90, 95, 99)


class Reservoir:
    """Uniform random sample of a stream (Vitter's Algorithm R).

    Keeps at most ``capacity`` values, so latency percentiles can be estimated over logs of any size
    with constant memory. While fewer values than ``capacity`` have been seen, the sample is exact.
    """

    def __init__(self, capacity: int = 10_000, seed: int | None = 0) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.seen = 0
        self.values: list[float] = []
        self._random = random.Random(seed)

    def add(self, value: float) -> None:
        self.seen += 1
        if len(self.values) < self.capacity:
            self.values.append(value)
            return
        slot = self._random.randrange(self.seen)
        if slot < self.capacity:
            self.values[slot] = value

    def percentile(self, p: float) -> float | None:
        """Nearest-rank percentile of the sample, or ``None`` when empty."""
        if not self.values:
            return None
        if not 0 < p <= 100:
            raise ValueError("p must be in (0, 100]")
        ordered = sorted(self.values)
        rank = math.ceil(p / 100 * len(ordered))
        return ordered[rank - 1]


@dataclass
class LogStats:
    reservoir_size: int = 10_000
    total: int = 0
    malformed: int = 0
    bytes_sent: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    statuses: Counter[int] = field(default_factory=Counter)
    paths: Counter[str] = field(default_factory=Counter)
    per_minute: Counter[datetime] = field(default_factory=Counter)
    latencies: Reservoir = field(init=False)

    def __post_init__(self) -> None:
        self.latencies = Reservoir(self.reservoir_size)

    def add(self, record: LogRecord) -> None:
        self.total += 1
        self.bytes_sent += record.bytes_sent
        self.statuses[record.status] += 1
        self.paths[record.path] += 1
        self.per_minute[record.timestamp.replace(second=0, microsecond=0)] += 1
        if record.duration_ms is not None:
            self.latencies.add(record.duration_ms)
        if self.first_seen is None or record.timestamp < self.first_seen:
            self.first_seen = record.timestamp
        if self.last_seen is None or record.timestamp > self.last_seen:
            self.last_seen = record.timestamp

    def add_all(self, records: Iterable[LogRecord | None]) -> "LogStats":
        for record in records:
            if record is None:
                self.malformed += 1
            else:
                self.add(record)
        return self

    def status_classes(self) -> dict[str, int]:
        classes: Counter[str] = Counter()
        for status, count in self.statuses.items():
            classes[f"{status // 100}xx"] += count
        return dict(sorted(classes.items()))

    @property
    def error_rate(self) -> float:
        """Share of requests that failed on the server side (5xx), between 0 and 1."""
        if self.total == 0:
            return 0.0
        server_errors = sum(count for status, count in self.statuses.items() if status >= 500)
        return server_errors / self.total

    def top_paths(self, n: int) -> list[tuple[str, int]]:
        # Sort by count, then path, so ties are reported deterministically.
        return sorted(self.paths.items(), key=lambda item: (-item[1], item[0]))[:n]

    def busiest_minute(self) -> tuple[datetime, int] | None:
        if not self.per_minute:
            return None
        return max(self.per_minute.items(), key=lambda item: (item[1], -item[0].timestamp()))

    def latency_percentiles(self) -> dict[str, float | None]:
        return {f"p{p}": self.latencies.percentile(p) for p in PERCENTILES}

    def to_dict(self, top: int = 10) -> dict[str, Any]:
        busiest = self.busiest_minute()
        return {
            "requests": self.total,
            "malformed_lines": self.malformed,
            "bytes_sent": self.bytes_sent,
            "time_range": {
                "start": self.first_seen.isoformat() if self.first_seen else None,
                "end": self.last_seen.isoformat() if self.last_seen else None,
            },
            "status_classes": self.status_classes(),
            "error_rate": round(self.error_rate, 6),
            "latency_ms": {
                **self.latency_percentiles(),
                "samples": len(self.latencies.values),
                "observed": self.latencies.seen,
            },
            "busiest_minute": {"minute": busiest[0].isoformat(), "requests": busiest[1]} if busiest else None,
            "top_paths": [{"path": path, "requests": count} for path, count in self.top_paths(top)],
        }

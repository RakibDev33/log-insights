"""Command line interface: ``log-insights access.log [more.log.gz ...]``."""

import argparse
import gzip
import json
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from log_insights import __version__
from log_insights.parser import parse_line
from log_insights.stats import LogStats

EXIT_OK = 0
EXIT_NO_DATA = 1
EXIT_THRESHOLD_EXCEEDED = 3


@contextmanager
def open_log(source: str) -> Iterator[TextIO]:
    """Opens a plain or gzip-compressed log, or stdin for ``-``. Undecodable bytes are replaced."""
    if source == "-":
        yield sys.stdin
    elif source.endswith(".gz"):
        with gzip.open(source, "rt", encoding="utf-8", errors="replace") as handle:
            yield handle
    else:
        with Path(source).open(encoding="utf-8", errors="replace") as handle:
            yield handle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="log-insights",
        description="Summarise NGINX/Apache access logs: traffic, status codes, top paths and latency.",
    )
    parser.add_argument("sources", nargs="*", default=["-"], help="log files (.gz supported); '-' for stdin")
    parser.add_argument("--top", type=int, default=10, help="number of top paths to show (default: 10)")
    parser.add_argument("--format", choices=["table", "json"], default="table", help="output format")
    parser.add_argument(
        "--fail-on-error-rate",
        type=float,
        metavar="PERCENT",
        help="exit with status 3 if the 5xx rate is above PERCENT (useful in CI and smoke tests)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def collect(sources: Sequence[str]) -> LogStats:
    stats = LogStats()
    for source in sources:
        with open_log(source) as handle:
            stats.add_all(parse_line(line) for line in handle if line.strip())
    return stats


def format_table(stats: LogStats, top: int) -> str:
    lines = [f"Requests        {stats.total:,}   (malformed lines skipped: {stats.malformed:,})"]

    if stats.first_seen and stats.last_seen:
        lines.append(
            f"Time range      {stats.first_seen:%Y-%m-%d %H:%M:%S}Z -> {stats.last_seen:%Y-%m-%d %H:%M:%S}Z"
        )

    classes = " | ".join(
        f"{name} {count:,} ({count / stats.total:.1%})" for name, count in stats.status_classes().items()
    )
    lines.append(f"Status          {classes}")
    lines.append(f"Error rate      {stats.error_rate:.2%} (5xx)")

    percentiles = stats.latency_percentiles()
    if stats.latencies.values:
        latency = " | ".join(
            f"{name} {value:.1f}" for name, value in percentiles.items() if value is not None
        )
        lines.append(f"Latency (ms)    {latency}   ({len(stats.latencies.values):,} samples)")

    busiest = stats.busiest_minute()
    if busiest:
        lines.append(f"Busiest minute  {busiest[0]:%Y-%m-%d %H:%M}Z ({busiest[1]:,} requests)")

    lines.extend(["", "Top paths"])
    width = max((len(path) for path, _ in stats.top_paths(top)), default=0)
    for rank, (path, count) in enumerate(stats.top_paths(top), start=1):
        lines.append(f"  {rank:>2}. {path:<{width}}  {count:>8,}")

    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        stats = collect(args.sources)
    except OSError as error:
        print(f"log-insights: {error}", file=sys.stderr)
        return EXIT_NO_DATA

    if stats.total == 0:
        print("log-insights: no valid log lines found", file=sys.stderr)
        return EXIT_NO_DATA

    if args.format == "json":
        print(json.dumps(stats.to_dict(top=args.top), indent=2))
    else:
        print(format_table(stats, args.top))

    if args.fail_on_error_rate is not None and stats.error_rate * 100 > args.fail_on_error_rate:
        print(
            f"log-insights: 5xx rate {stats.error_rate:.2%} exceeds {args.fail_on_error_rate}%",
            file=sys.stderr,
        )
        return EXIT_THRESHOLD_EXCEEDED

    return EXIT_OK

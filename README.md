# log-insights

![CI](https://github.com/RakibDev33/log-insights/actions/workflows/ci.yml/badge.svg)

A small, dependency-free command line tool that summarises **NGINX/Apache access logs**: traffic, status code mix, 5xx error rate, latency percentiles, the busiest minute and the most requested paths. It streams logs line by line, reads `.gz` rotations directly, and can fail a CI or smoke-test job when the error rate crosses a threshold.

```
$ log-insights /var/log/nginx/access.log --top 5
Requests        20,000   (malformed lines skipped: 1)
Time range      2026-11-10 09:00:00Z -> 2026-11-10 20:39:58Z
Status          2xx 18,563 (92.8%) | 3xx 441 (2.2%) | 4xx 697 (3.5%) | 5xx 299 (1.5%)
Error rate      1.49% (5xx)
Latency (ms)    p50 28.0 | p90 71.0 | p95 95.0 | p99 207.0   (10,000 samples)
Busiest minute  2026-11-10 09:00Z (29 requests)

Top paths
   1. /api/orders        7,965
   2. /api/products      5,001
   3. /health            2,054
   4. /login             1,149
   5. /static/app.js       807
```

## Features

- Parses the `combined` and `common` formats, with an optional trailing `$request_time` for latency
- Query strings are split from paths, so `/api/orders?page=2` counts towards `/api/orders`
- Timestamps with any UTC offset are normalised to UTC; month names are parsed without relying on the locale
- Latency percentiles (p50/p90/p95/p99) from a fixed-size **reservoir sample**, so memory stays constant however large the log is
- Multiple files, gzip-compressed rotations and stdin (`-`) in a single run
- Table output for people, JSON output for scripts and dashboards
- `--fail-on-error-rate PERCENT` returns exit code `3` when the 5xx rate is too high
- Standard library only, fully typed (`mypy --strict`), tested with pytest

## Installation

Requires Python 3.12+.

```bash
pip install git+https://github.com/RakibDev33/log-insights.git
```

## Usage

```bash
log-insights access.log                          # human-readable summary
log-insights access.log access.log.1.gz --top 20 # several files, including rotated archives
kubectl logs deploy/web | log-insights -         # read from stdin
log-insights access.log --format json | jq '.latency_ms'
log-insights access.log --fail-on-error-rate 1   # exit 3 if more than 1% of requests are 5xx
```

| Exit code | Meaning                                        |
| --------- | ---------------------------------------------- |
| `0`       | Summary printed                                |
| `1`       | File could not be read, or no valid log lines  |
| `2`       | Invalid command line arguments                 |
| `3`       | Error rate above `--fail-on-error-rate`        |

To record request times in NGINX, append `$request_time` to the combined format:

```nginx
log_format timed '$remote_addr - $remote_user [$time_local] "$request" '
                 '$status $body_bytes_sent "$http_referer" "$http_user_agent" $request_time';
access_log /var/log/nginx/access.log timed;
```

## Library use

```python
from log_insights import LogStats, parse_line

with open("access.log", encoding="utf-8") as log:
    stats = LogStats().add_all(parse_line(line) for line in log)

print(stats.error_rate, stats.latency_percentiles()["p99"], stats.top_paths(3))
```

## Design notes

- **Streaming with bounded memory for latency.** Exact percentiles need every value, so the tool keeps a uniform random sample of 10,000 request times using Vitter's Algorithm R. Below that size the result is exact; above it, percentiles are estimated from a uniform sample of the whole log. The sampler uses a fixed seed so runs are reproducible.
- **Nearest-rank percentiles.** p95 is the smallest observed value with at least 95% of the samples at or below it, so it is always a real request time rather than an interpolated one.
- **Malformed lines are counted, not fatal.** Real logs contain truncated lines and probes; they are skipped and reported.
- **Deterministic output.** Ties in the top paths are broken by path name and ties for the busiest minute by the earliest minute, so reports are stable across runs.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check . && mypy src tests
```

## License

MIT

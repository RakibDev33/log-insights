from datetime import UTC, datetime

import pytest

from log_insights.parser import parse_line, parse_timestamp

COMBINED = (
    '203.0.113.7 - alice [10/Nov/2026:13:55:36 +0100] "GET /api/orders?page=2 HTTP/1.1" 200 512 '
    '"https://example.com/" "curl/8.5.0" 0.042'
)


def test_parses_a_combined_line_with_request_time() -> None:
    record = parse_line(COMBINED)

    assert record is not None
    assert record.remote_addr == "203.0.113.7"
    assert record.timestamp == datetime(2026, 11, 10, 12, 55, 36, tzinfo=UTC)
    assert record.method == "GET"
    assert record.path == "/api/orders"
    assert record.query == "page=2"
    assert record.status == 200
    assert record.status_class == "2xx"
    assert record.bytes_sent == 512
    assert record.referrer == "https://example.com/"
    assert record.user_agent == "curl/8.5.0"
    assert record.duration_ms == pytest.approx(42.0)


def test_parses_common_format_without_referrer_agent_or_timing() -> None:
    record = parse_line('10.0.0.1 - - [01/Jan/2026:00:00:00 +0000] "POST /login HTTP/2.0" 302 -')

    assert record is not None
    assert record.status == 302
    assert record.bytes_sent == 0
    assert record.referrer is None
    assert record.user_agent is None
    assert record.duration_ms is None


@pytest.mark.parametrize(
    "line",
    [
        "",
        "not a log line",
        '10.0.0.1 - - [01/Jan/2026:00:00:00 +0000] "-" 400 0 "-" "-"',
        '10.0.0.1 - - [32/Foo/2026:00:00:00 +0000] "GET / HTTP/1.1" 200 1',
    ],
)
def test_malformed_lines_return_none(line: str) -> None:
    assert parse_line(line) is None


def test_timestamps_are_normalised_to_utc() -> None:
    assert parse_timestamp("10/Nov/2026:01:30:00 -0530") == datetime(2026, 11, 10, 7, 0, tzinfo=UTC)


def test_invalid_timestamp_raises() -> None:
    with pytest.raises(ValueError, match="Unrecognised timestamp"):
        parse_timestamp("2026-11-10T01:30:00Z")

"""Parser for the NGINX/Apache "combined" log format, with an optional trailing request time.

Example line::

    203.0.113.7 - - [10/Nov/2026:13:55:36 +0000] "GET /api/orders?page=2 HTTP/1.1" 200 512 "-" "curl" 0.042

The trailing request time (seconds, as written by NGINX's ``$request_time``) is optional, as are the
referrer and user agent, so plain "common" format lines parse too.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

_LINE = re.compile(
    r"(?P<remote>\S+) \S+ (?P<user>\S+) \[(?P<time>[^\]]+)\] "
    r'"(?P<method>[A-Z]+) (?P<target>\S+) (?P<protocol>[^"]+)" '
    r"(?P<status>\d{3}) (?P<bytes>\d+|-)"
    r'(?: "(?P<referrer>[^"]*)" "(?P<agent>[^"]*)")?'
    r"(?: (?P<duration>\d+(?:\.\d+)?))?\s*$"
)

_TIME = re.compile(r"(\d{2})/([A-Za-z]{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2})")

# Month names are matched explicitly so parsing does not depend on the process locale (unlike %b).
_MONTHS = {
    name: number
    for number, name in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1
    )
}


@dataclass(frozen=True, slots=True)
class LogRecord:
    remote_addr: str
    timestamp: datetime
    method: str
    path: str
    query: str | None
    status: int
    bytes_sent: int
    referrer: str | None
    user_agent: str | None
    duration_ms: float | None

    @property
    def status_class(self) -> str:
        return f"{self.status // 100}xx"


def parse_timestamp(value: str) -> datetime:
    """Parses ``10/Nov/2026:13:55:36 +0100`` into a timezone-aware UTC datetime."""
    match = _TIME.fullmatch(value)
    if match is None or match.group(2) not in _MONTHS:
        raise ValueError(f"Unrecognised timestamp: {value!r}")

    day, month, year, hour, minute, second, sign, offset_h, offset_m = match.groups()
    offset = timedelta(hours=int(offset_h), minutes=int(offset_m))
    tz = timezone(offset if sign == "+" else -offset)
    local = datetime(int(year), _MONTHS[month], int(day), int(hour), int(minute), int(second), tzinfo=tz)
    return local.astimezone(UTC)


def _optional(value: str | None) -> str | None:
    return None if value in (None, "", "-") else value


def parse_line(line: str) -> LogRecord | None:
    """Returns a record, or ``None`` for lines that are not valid access log entries."""
    match = _LINE.match(line.strip())
    if match is None:
        return None

    try:
        timestamp = parse_timestamp(match["time"])
    except ValueError:
        return None

    path, _, query = match["target"].partition("?")
    duration = match["duration"]
    return LogRecord(
        remote_addr=match["remote"],
        timestamp=timestamp,
        method=match["method"],
        path=path,
        query=query or None,
        status=int(match["status"]),
        bytes_sent=0 if match["bytes"] == "-" else int(match["bytes"]),
        referrer=_optional(match["referrer"]),
        user_agent=_optional(match["agent"]),
        duration_ms=None if duration is None else float(duration) * 1000,
    )

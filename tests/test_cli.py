import gzip
import io
import json
from pathlib import Path

import pytest

from log_insights.cli import EXIT_NO_DATA, EXIT_OK, EXIT_THRESHOLD_EXCEEDED, main

LINES = [
    '10.0.0.1 - - [10/Nov/2026:12:00:01 +0000] "GET /api/orders HTTP/1.1" 200 120 "-" "k6" 0.010',
    '10.0.0.2 - - [10/Nov/2026:12:00:02 +0000] "GET /api/orders?page=2 HTTP/1.1" 200 120 "-" "k6" 0.020',
    '10.0.0.3 - - [10/Nov/2026:12:00:03 +0000] "POST /api/orders HTTP/1.1" 201 80 "-" "k6" 0.030',
    '10.0.0.4 - - [10/Nov/2026:12:01:00 +0000] "GET /health HTTP/1.1" 200 2 "-" "probe" 0.001',
    '10.0.0.5 - - [10/Nov/2026:12:01:30 +0000] "GET /api/orders/9 HTTP/1.1" 503 0 "-" "k6" 1.500',
    "garbage line",
]


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    path = tmp_path / "access.log"
    path.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    return path


def test_json_output_summarises_the_log(log_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(log_file), "--format", "json", "--top", "2"])

    assert exit_code == EXIT_OK
    report = json.loads(capsys.readouterr().out)
    assert report["requests"] == 5
    assert report["malformed_lines"] == 1
    assert report["status_classes"] == {"2xx": 4, "5xx": 1}
    assert report["error_rate"] == pytest.approx(0.2)
    assert report["top_paths"] == [
        {"path": "/api/orders", "requests": 3},
        {"path": "/api/orders/9", "requests": 1},
    ]
    assert report["latency_ms"]["p50"] == pytest.approx(20.0)
    assert report["busiest_minute"] == {"minute": "2026-11-10T12:00:00+00:00", "requests": 3}


def test_table_output_is_human_readable(log_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(log_file)]) == EXIT_OK

    output = capsys.readouterr().out
    assert "Requests        5" in output
    assert "Error rate      20.00% (5xx)" in output
    assert "1. /api/orders" in output


def test_reads_gzip_files_and_combines_multiple_sources(
    tmp_path: Path, log_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "access.log.1.gz"
    with gzip.open(archive, "wt", encoding="utf-8") as handle:
        handle.write(LINES[0] + "\n")

    assert main([str(log_file), str(archive), "--format", "json"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["requests"] == 6


def test_reads_from_stdin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(LINES[:2])))

    assert main(["--format", "json"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["requests"] == 2


def test_error_rate_threshold_sets_a_failing_exit_code(log_file: Path) -> None:
    assert main([str(log_file), "--fail-on-error-rate", "25"]) == EXIT_OK
    assert main([str(log_file), "--fail-on-error-rate", "10"]) == EXIT_THRESHOLD_EXCEEDED


def test_missing_file_or_no_valid_lines_returns_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty.log"
    empty.write_text("not a log line\n", encoding="utf-8")

    assert main([str(tmp_path / "missing.log")]) == EXIT_NO_DATA
    assert main([str(empty)]) == EXIT_NO_DATA
    assert "no valid log lines" in capsys.readouterr().err

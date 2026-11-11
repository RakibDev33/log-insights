"""Summaries of web server access logs."""

from log_insights.parser import LogRecord, parse_line
from log_insights.stats import LogStats

__all__ = ["LogRecord", "LogStats", "parse_line"]
__version__ = "1.0.0"

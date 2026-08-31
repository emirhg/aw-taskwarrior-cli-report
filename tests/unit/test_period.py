"""
Unit tests for period parsing (tw_report.core.period).

Tests verify parse_period correctly handles all period keywords (:today, :week,
etc.) and ISO date formats, producing correct start/end boundaries.
"""

from datetime import datetime, timedelta

import pytest

from tw_report.core.period import parse_period


class TestPeriodKeywords:
    """Test human-readable period keywords."""

    def test_today(self):
        """Period :today should return current day boundaries."""
        start, end = parse_period(":today", day_start_hour=0)
        now = datetime.now().astimezone()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        assert start == today_start
        assert end == today_end

    def test_yesterday(self):
        """Period :yesterday should return previous day boundaries."""
        start, end = parse_period(":yesterday", day_start_hour=0)
        now = datetime.now().astimezone()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today_start - timedelta(days=1)

        assert start == yesterday
        assert end == today_start - timedelta(microseconds=1)

    def test_week(self):
        """Period :week should return Monday to today."""
        start, end = parse_period(":week", day_start_hour=0)
        now = datetime.now().astimezone()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        monday = today_start - timedelta(days=now.weekday())

        assert start == monday
        # End should be today at 23:59:59.999999
        assert start <= end
        assert end.date() == now.date()

    def test_lastweek(self):
        """Period :lastweek should return full previous week (Mon-Sun)."""
        start, end = parse_period(":lastweek", day_start_hour=0)
        now = datetime.now().astimezone()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_last_week = today_start - timedelta(
            days=now.weekday(), weeks=1
        )

        assert start == start_of_last_week
        # End should be 6 days after start (full week)
        assert (end.date() - start.date()).days == 6

    def test_month(self):
        """Period :month should return 1st of current month to today."""
        start, end = parse_period(":month", day_start_hour=0)
        now = datetime.now().astimezone()
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        assert start == first_of_month
        assert end.date() == now.date()

    def test_lastmonth(self):
        """Period :lastmonth should return full previous month."""
        start, end = parse_period(":lastmonth", day_start_hour=0)
        now = datetime.now().astimezone()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_last_month = today_start.replace(day=1) - timedelta(days=1)
        start_of_last_month = end_of_last_month.replace(day=1)

        assert start == start_of_last_month
        assert end.date() == end_of_last_month.date()

    def test_year(self):
        """Period :year should return Jan 1 of current year to today."""
        start, end = parse_period(":year", day_start_hour=0)
        now = datetime.now().astimezone()
        jan_1 = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

        assert start == jan_1
        assert end.date() == now.date()

    def test_lastyear(self):
        """Period :lastyear should return full previous calendar year."""
        start, end = parse_period(":lastyear", day_start_hour=0)
        now = datetime.now().astimezone()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_last_year = today_start.replace(month=1, day=1) - timedelta(days=1)
        start_of_last_year = end_of_last_year.replace(month=1, day=1)

        assert start == start_of_last_year
        assert end.date() == end_of_last_year.date()

    def test_all(self):
        """Period :all should return epoch to now."""
        start, end = parse_period(":all", day_start_hour=0)
        now = datetime.now().astimezone()

        # Start should be epoch (1970-01-01)
        assert start.year == 1970
        assert start.month == 1
        assert start.day == 1
        # End should be approximately now
        assert (now - end).total_seconds() < 1  # Within 1 second of now

    def test_case_insensitive(self):
        """Period keywords should be case-insensitive."""
        start1, end1 = parse_period(":TODAY", day_start_hour=0)
        start2, end2 = parse_period(":today", day_start_hour=0)
        assert start1 == start2
        assert end1 == end2


class TestISODateFormats:
    """Test ISO date and datetime formats."""

    def test_iso_date_single(self):
        """Single ISO date (YYYY-MM-DD) should return day boundaries."""
        start, end = parse_period("2026-06-15", day_start_hour=0)

        # Start should be 00:00:00
        assert start.hour == 0
        assert start.minute == 0
        assert start.second == 0
        # End should be 23:59:59.999999
        assert end.hour == 23
        assert end.minute == 59
        assert end.second == 59

    def test_iso_date_range(self):
        """Two ISO dates should return range from first to second."""
        start, end = parse_period("2026-06-15 2026-06-20", day_start_hour=0)

        # Start should be 2026-06-15 00:00:00
        assert start.date().isoformat() == "2026-06-15"
        # End should be 2026-06-20 23:59:59.999999
        assert end.date().isoformat() == "2026-06-20"

    def test_iso_datetime_single(self):
        """Single ISO datetime uses date part, returns day boundaries."""
        start, end = parse_period("2026-06-15T10:30:45", day_start_hour=0)

        # Single datetime is treated like a single date — returns day boundaries
        assert start.hour == 0
        assert start.minute == 0
        # End should be 23:59:59.999999 of the same day
        assert end.hour == 23
        assert end.minute == 59
        assert end.date() == start.date()

    def test_iso_datetime_range(self):
        """Two ISO datetimes should use exact range."""
        start, end = parse_period("2026-06-15T10:30:45 2026-06-20T15:45:30", day_start_hour=0)

        assert start.hour == 10
        assert start.minute == 30
        assert end.hour == 15
        assert end.minute == 45


class TestInvalidPeriods:
    """Test invalid period formats."""

    def test_invalid_format(self, capsys):
        """Invalid period format should print error and exit."""
        with pytest.raises(SystemExit) as exc_info:
            parse_period("invalid_period")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Invalid period format" in captured.err

    def test_malformed_iso_date(self, capsys):
        """Malformed ISO date should print error and exit."""
        with pytest.raises(SystemExit) as exc_info:
            parse_period("2026-13-45")  # Invalid month and day

        assert exc_info.value.code == 1

    def test_too_many_dates(self, capsys):
        """More than 2 date arguments should error."""
        with pytest.raises(SystemExit) as exc_info:
            parse_period("2026-06-15 2026-06-20 2026-06-25")

        assert exc_info.value.code == 1

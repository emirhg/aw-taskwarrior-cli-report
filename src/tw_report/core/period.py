"""
Period specification parsing for tw-report.

Converts human-readable period strings (:today, :week, ISO dates, etc.) into
start/end datetime tuples for querying activity data.
"""

import sys
from datetime import datetime, timedelta
from typing import Tuple


def parse_period(period_str: str) -> Tuple[datetime, datetime]:
    """
    Convert a human-readable period string into a start and end datetime tuple.

    Supported formats:
    - :today — current day (00:00 to 23:59:59.999999)
    - :yesterday — previous day
    - :week — Monday of current week to today (or Friday if today is weekend)
    - :lastweek — full previous week (Monday-Sunday)
    - :month — 1st of current month to today
    - :lastmonth — full previous month
    - :year — 1st of current year to today
    - :lastyear — full previous calendar year
    - :all — from epoch to now
    - YYYY-MM-DD — specific day
    - YYYY-MM-DD YYYY-MM-DD — date range (inclusive on both ends)
    - YYYY-MM-DDTHH:MM:SS — specific datetime
    - YYYY-MM-DDTHH:MM:SS YYYY-MM-DDTHH:MM:SS — datetime range

    Args:
        period_str: Period specification string (case-insensitive for keywords)

    Returns:
        Tuple of (start, end) datetime objects (timezone-aware)

    Raises:
        SystemExit: If period format is invalid (prints error to stderr and exits)
    """
    now = datetime.now().astimezone()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    period_str = period_str.lower()

    if period_str == ":today":
        start = today_start
        end = today_start + timedelta(days=1) - timedelta(microseconds=1)
    elif period_str == ":yesterday":
        yesterday = today_start - timedelta(days=1)
        start = yesterday
        end = today_start - timedelta(microseconds=1)
    elif period_str == ":week":
        start = today_start - timedelta(days=now.weekday())
        end = today_end
    elif period_str == ":lastweek":
        start_of_last_week = today_start - timedelta(days=now.weekday(), weeks=1)
        end_of_last_week = start_of_last_week + timedelta(days=6)
        start = start_of_last_week
        end = end_of_last_week.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
    elif period_str == ":month":
        start = today_start.replace(day=1)
        end = today_end
    elif period_str == ":lastmonth":
        end_of_last_month = today_start.replace(day=1) - timedelta(days=1)
        start_of_last_month = end_of_last_month.replace(day=1)
        start = start_of_last_month
        end = end_of_last_month.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
    elif period_str == ":year":
        start = today_start.replace(month=1, day=1)
        end = today_end
    elif period_str == ":lastyear":
        end_of_last_year = today_start.replace(month=1, day=1) - timedelta(days=1)
        start_of_last_year = end_of_last_year.replace(month=1, day=1)
        start = start_of_last_year
        end = end_of_last_year.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
    elif period_str == ":all":
        start = datetime(1970, 1, 1, tzinfo=now.tzinfo)
        end = now
    else:
        parts = period_str.split()
        try:
            if len(parts) == 1:
                day = datetime.fromisoformat(parts[0]).astimezone(now.tzinfo)
                start = day.replace(hour=0, minute=0, second=0, microsecond=0)
                end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif len(parts) == 2:
                start = datetime.fromisoformat(parts[0]).astimezone(now.tzinfo)
                end = datetime.fromisoformat(parts[1]).astimezone(now.tzinfo)
            else:
                raise ValueError
        except ValueError:
            print(f"Error: Invalid period format '{period_str}'", file=sys.stderr)
            sys.exit(1)

    return start, end

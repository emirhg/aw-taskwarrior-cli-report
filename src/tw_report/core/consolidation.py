"""
Timeline consolidation helpers.

This module provides utility functions for consolidating timeline data,
such as collapsing task-level rows to project-level summaries.
"""

from datetime import timedelta, date
from typing import Any, Dict, List, Tuple


def collapse_tasks_to_project(rows: List[Dict]) -> List[Dict]:
    """Collapse (period, project, task) rows down to (period, project) totals.

    Sums durations/productivity per project, drops task and categories fields.

    Args:
        rows: List of (period, project, task) rows

    Returns:
        List of (period, project) summary rows
    """
    groups: Dict[Tuple[date, str], List[Dict]] = {}
    for row in rows:
        key = (row["period_start"], row["project"])
        groups.setdefault(key, []).append(row)

    result = []
    for (period_start, project), group_rows in sorted(groups.items()):
        actual_duration = sum(
            (r.get("actual_duration", r["duration"]) for r in group_rows), timedelta(0)
        )
        productive_duration = sum(
            (r.get("productive_duration", timedelta(0)) for r in group_rows), timedelta(0)
        )
        afk_duration = sum(
            (r.get("afk_duration", timedelta(0)) for r in group_rows), timedelta(0)
        )
        offline_extension_duration = sum(
            (r.get("offline_extension_duration", timedelta(0)) for r in group_rows), timedelta(0)
        )
        result.append({
            "period_start": period_start,
            "project": project,
            "duration": actual_duration,
            "actual_duration": actual_duration,
            "productive_duration": productive_duration,
            "afk_duration": afk_duration,
            "offline_extension_duration": offline_extension_duration,
        })

    result.sort(key=lambda r: (r["period_start"], -r["actual_duration"].total_seconds()))
    return result

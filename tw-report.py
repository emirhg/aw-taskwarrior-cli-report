#!/bin/env python
# author: "Emir Herrera González" <emir.herrera@gmail.com>
#
# Generates a timesheet report using data from ActivityWatch buckets.
#
# This script fetches activity data for the specified period, correlates it with
# Taskwarrior tasks, and generates a hierarchical report showing time spent on
# projects, tasks, and specific applications or categories.
#
# By default, it reports on today's activity, excluding time spent away from
# the keyboard (AFK) and only showing activity that occurred during a
# tracked Taskwarrior task.
#
# Features:
# - Human-readable time periods (:today, :week, :month, etc.)
# - Correlation with Taskwarrior projects and tasks.
# - Categorization of activities (e.g., Coding, Communication).
# - Hierarchical, terminal-friendly report format.
# - Customizable through command-line arguments and a categories JSON file.
#
#
# TODO: Add a --resume argument to print only project and task information and supress the app/title output information
# BUG: --exclude-non-project is including non-project data that overlaps with offline data.
# ❯ ${HOME}/Desktop/ianua/work_report/tw-report.py --detail-level=2 --timesheet --consolidate :today --exclude-non-project
"""
    ================================================================================================== Timeline Report ==================================================================================================
Period: :today (2026-06-27 to 2026-06-27)
Active Time: 9:09:03 (2026-06-27 07:25 to 2026-06-27 22:40)
  • AFK time: 0:58:13
  • Project Tracking: 132.6% (10:51:01)
  • Focus time: 6.2% (0:40:22)
  • Untracked productivity: 0.0% (0:00:00)
  • Overall productivity: 8.2% (0:40:22)
  • Overall distracting time: 0.6% (0:03:04)
  • Unscored time: 8.6% (0:42:07)
Current Session: 0:38:08 (22:02 to 22:40)
Last Break: 0:40:07 (21:22 to 22:02)
---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Wk  Date       Day
W26 2026-06-27 Sat
                                                                                                                                                                                  (0:15:21 OFF)
       08:07-08:18  ▶ Organ... > Contabilidad y finanzas ▶▶ Depositar recursos a cuenta inve...                                                                                                  0:11:36  [prod  97%]
                                                                                                                                                                                  (0:48:49 OFF)
       09:08-09:16  ▶ Organ... > Contabilidad y finanzas ▶▶ Depositar recursos a cuenta inve...                                                                                   (0:08:16 AFK)  0:08:44  [prod   5%]
                                                                                                                                                                                  (0:12:08 OFF)
       09:29-09:36  ▶ Organ... > Contabilidad y finanzas ▶▶ Depositar recursos a cuenta inve...                                                                                   (0:03:45 AFK)  0:07:21  [prod  35%]
                                                                                                                                                                                  (0:11:55 OFF)
       09:48-10:40  ▶ Organ... > Contabilidad y finanzas ▶▶ Depositar recursos a cuenta inve...                                                                                   (0:17:42 AFK)  0:51:53  [prod  36%]
       10:42-11:44  ▶ Merca... > Micro1 ▶▶ Aplicación a vacante de Javascript                                                                                                     (0:28:30 AFK)  1:01:22  [prod   7%]
                                                                                                                                                                                  (0:22:42 OFF)
       12:09-20:37  ▶ Ecosi... > Recámara ▶▶ Lavar cortinas                                                                                                                                      8:27:30  [prod   0%]
                                                                                                                                                                                  (0:05:11 OFF)
                                                                                                                                                                                  (0:04:10 OFF)
                                                                                                                                                                                  (0:05:38 OFF)
                                                                                                                                                                                  (0:07:42 OFF)
                                                                                                                                                                                  (0:04:52 OFF)
       14:50-14:50  ▶ No project assigned ▶▶ No task assigned                                                                                                                                    0:00:09  [prod 100%]
                                                                                                                                                                                  (0:12:22 OFF)
       15:32-15:32  ▶ No project assigned ▶▶ No task assigned                                                                                                                                    0:00:08  [prod 100%]
                                                                                                                                                                                  (0:14:27 OFF)
                                                                                                                                                                                  (0:06:56 OFF)
                                                                                                                                                                                  (0:11:56 OFF)
                                                                                                                                                                                  (0:10:48 OFF)
                                                                                                                                                                                  (0:05:52 OFF)
                                                                                                                                                                                  (0:06:59 OFF)
                                                                                                                                                                                  (0:05:45 OFF)
                                                                                                                                                                                  (0:04:21 OFF)
                                                                                                                                                                                  (0:17:25 OFF)
                                                                                                                                                                                  (0:20:07 OFF)
                                                                                                                                                                                  (0:29:22 OFF)
                                                                                                                                                                                  (0:06:24 OFF)
                                                                                                                                                                                  (0:40:07 OFF)
       22:37-22:40  ▶ Organ... > Reporte ▶▶ Corregir el reporte de tiempos consolidados                                                                                                          0:02:32  [prod  99%]
                                                                                                                                                                                               ----------------------
                                                                                                                                                                                   Day total:   10:51:19  [prod   6%]

                                                                                                                                                                                    Total Time: 10:51:19  [prod   6%]
=====================================================================================================================================================================================================================
"""

# FIX: task duration for offline event is not consistent with OFF entries:
"""
  12:09-20:37  ▶ Ecosi... > Recámara ▶▶ Lavar cortinas                                                                                                                                      8:27:30  [prod   0%]
                     - Offline                                                                                                                                                                                8:27:30
                                                                                                                                                                                  (0:05:11 OFF)
                                                                                                                                                                                  (0:04:10 OFF)
                                                                                                                                                                                  (0:05:38 OFF)
                                                                                                                                                                                  (0:07:42 OFF)
                                                                                                                                                                                  (0:04:52 OFF)
       14:50-14
"""

# FIX: Multiple OFF entries on a consolidated report.
# FIX: detail-level=3 of a consolidated report shows some OFF entries that are not consistent with the event duration:
"""
      15:32-15:32  ▶ No project assigned ▶▶ No task assigned                                                                                                                                    0:00:08  [prod 100%]
                     - Work > Programming > Terminal                                                                                                                                                          0:00:08
                                                                                                                                                                                  (0:14:27 OFF)
                                                                                                                                                                                  (0:06:56 OFF)
                                                                                                                                                                                  (0:11:56 OFF)
                                                                                                                                                                                  (0:10:48 OFF)
                                                                                                                                                                                  (0:05:52 OFF)
                                                                                                                                                                                  (0:06:59 OFF)
                                                                                                                                                                                  (0:05:45 OFF)
                                                                                                                                                                                  (0:04:21 OFF)
                                                                                                                                                                                  (0:17:25 OFF)
                                                                                                                                                                                  (0:20:07 OFF)
                                                                                                                                                                                  (0:29:22 OFF)
                                                                                                                                                                                  (0:06:24 OFF)
                                                                                                                                                                                  (0:40:07 OFF)

"""

# FIX: time entries don't look completly consolidated as they show multiple entries for the continuos task
"""
❯ ${HOME}/Desktop/ianua/work_report/tw-report.py --detail-level=3 --timesheet --consolidate :today --ignore-offline
================================================================================================== Timeline Report ==================================================================================================
Period: :today (2026-06-27 to 2026-06-27)
Active Time: 9:54:53 (2026-06-27 07:25 to 2026-06-27 22:51)
  • AFK time: 1:33:08
  • Project Tracking: 131.9% (11:01:35)
  • Focus time: 7.7% (0:50:57)
  • Untracked productivity: 21.3% (1:46:40)
  • Overall productivity: 31.4% (2:37:37)
  • Overall distracting time: 3.7% (0:18:23)
  • Unscored time: 15.2% (1:16:09)
Current Session: 0:49:04 (22:02 to 22:51)
Last Break: 0:40:07 (21:22 to 22:02)
---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Wk  Date       Day
W26 2026-06-27 Sat
       07:25-07:33  ▶ No project assigned ▶▶ No task assigned                                                                                                                                    0:07:54  [prod 100%]
                     - Uncategorized                                                                                                                                                                          0:00:00
                     - Work > Programming > Terminal                                                                                                                                                          0:07:53
       07:49-08:07  ▶ No project assigned ▶▶ No task assigned                                                                                                                     (0:10:30 AFK)  0:18:03  [prod  40%]
                     - Work > Programming > Terminal                                                                                                                                                          0:24:10
                     - Uncategorized                                                                                                                                                                          0:00:24
       08:07-08:18  ▶ Organ... > Contabilidad y finanzas ▶▶ Depositar recursos a cuenta inve...                                                                                                  0:11:36  [prod  97%]
                     - Work > Programming > Terminal                                                                                                                                                          0:11:15
                     - Uncategorized                                                                                                                                                                          0:00:21
       09:08-09:16  ▶ Organ... > Contabilidad y finanzas ▶▶ Depositar recursos a cuenta inve...                                                                                   (0:08:16 AFK)  0:08:44  [prod   5%]
                     - Work > Programming > Terminal                                                                                                                                                          0:08:44
       09:29-09:36  ▶ Organ... > Contabilidad y finanzas ▶▶ Depositar recursos a cuenta inve...                                                                                   (0:03:45 AFK)  0:07:21  [prod  35%]
                     - Work > Programming > Terminal                                                                                                                                                          0:10:01
                     - Uncategorized                                                                                                                                                                          0:01:01
       09:48-10:40  ▶ Organ... > Contabilidad y finanzas ▶▶ Depositar recursos a cuenta inve...                                                                                   (0:17:42 AFK)  0:51:53  [prod  36%]
                     - Uncategorized                                                                                                                                                                          0:13:38
                     - Work > Programming > Terminal                                                                                                                                                          0:32:10
                     - Comms > Documentation                                                                                                                                                                  0:00:02
                     - Finances > Trading                                                                                                                                                                     0:06:54
                     - Comms > Email                                                                                                                                                                          0:00:28
                     - Media > Video                                                                                                                                                                          0:01:39
       10:42-10:42  ▶ No project assigned ▶▶ No task assigned                                                                                                                                    0:00:07  [prod  71%]
                     - Media > Video                                                                                                                                                                          0:00:02
                     - Work > Programming > Terminal                                                                                                                                                          0:00:05

"""

import argparse
import json
import os
import platform
import re
import shutil
import sys
import unicodedata
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Pattern, Tuple

try:
    from aw_client import ActivityWatchClient
    from aw_core.models import Event
    from aw_transform import (
        filter_keyvals,
        filter_period_intersect,
    )
except ImportError:
    print("Error: Required ActivityWatch libraries not found.", file=sys.stderr)
    print("Please install them with: pip install aw-client", file=sys.stderr)
    exit(1)

from report_pipeline import (
    aggregate_hierarchy,
    build_canonical_events,
    build_context,
    compute_metrics,
    merge_overlapping_afk_periods,
)
from report_presenters import HierarchicalReport, TimelineReport

# --- Constants and Configuration ---

DEFAULT_CATEGORIES_FILE = os.path.expanduser(
    "~/.config/activitywatch/aw-server/settings.json"
)

# Sentinel values for unassigned events
NO_PROJECT = "No project assigned"
NO_TASK = "No task assigned"


# --- Argument Parsing ---


def reorder_arguments(argv: List[str]) -> List[str]:
    """Reorder arguments to put all optional arguments before positional ones.

    This allows flexible argument ordering like:
      tw-report :month --timesheet Climb
      tw-report --timesheet Climb :month
    Both get reordered to:
      tw-report --timesheet Climb :month (flags first, then positional)
    """
    if not argv:
        return argv

    optional_args = []
    positional_args = []

    i = 0
    while i < len(argv):
        arg = argv[i]

        # Check if this is an optional argument (starts with -)
        if arg.startswith("-"):
            optional_args.append(arg)
            # Check if the next arg is a value for this flag (not another flag, not a period)
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                # This flag takes a value
                if arg in [
                    "--project",
                    "--task",
                    "--app",
                    "--exclude-project",
                    "--exclude-task",
                    "--exclude-app",
                    "--categories",
                    "--min-score",
                    "--max-score",
                    "--detail-level",
                ]:
                    optional_args.append(argv[i + 1])
                    i += 1
            i += 1
        else:
            # This is a positional argument
            positional_args.append(arg)
            i += 1

    # Return reordered: optional arguments first, then positional arguments
    return optional_args + positional_args


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    # Reorder arguments to put optional args before positional ones
    reordered_argv = reorder_arguments(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Generates a timesheet report from ActivityWatch data."
    )
    parser.add_argument(
        "args",
        nargs="*",
        help="Period (starts with :) and/or search/filter terms. Order doesn't matter. Examples: :today, Climb, :week Climb, Climb :week",
    )
    parser.add_argument(
        "--no-taskwarrior",
        action="store_true",
        help="Do not intersect with Taskwarrior events; report all activity.",
    )
    parser.add_argument(
        "--include-afk", action="store_true", help="Include AFK time in the report."
    )
    parser.add_argument(
        "--exclude-afk",
        action="store_true",
        help="Exclude AFK periods from the timeline report (default: shown as AFK slots).",
    )
    parser.add_argument(
        "--categories",
        type=str,
        default=DEFAULT_CATEGORIES_FILE,
        help=f"Path to categories JSON file (default: {DEFAULT_CATEGORIES_FILE}).",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        help="Filter out and do not display categories with a score below this value.",
    )
    parser.add_argument(
        "--max-score",
        type=float,
        help="Filter out and do not display categories with a score above this value.",
    )
    parser.add_argument(
        "--project",
        type=str,
        action="append",
        metavar="PATTERN",
        help="Filter: show only entries whose project matches PATTERN (partial, repeatable = OR).",
    )
    parser.add_argument(
        "--task",
        type=str,
        action="append",
        metavar="PATTERN",
        help="Filter: show only entries whose task matches PATTERN.",
    )
    parser.add_argument(
        "--app",
        type=str,
        action="append",
        metavar="PATTERN",
        help="Filter: show only entries whose app matches PATTERN.",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Use exact (case-insensitive) matching for --project/--task/--app filters.",
    )
    parser.add_argument(
        "--exclude-project",
        type=str,
        action="append",
        metavar="NAME",
        help="Exclude projects with this exact name (repeatable).",
    )
    parser.add_argument(
        "--exclude-task",
        type=str,
        action="append",
        metavar="NAME",
        help="Exclude tasks with this exact name (repeatable).",
    )
    parser.add_argument(
        "--exclude-app",
        type=str,
        action="append",
        metavar="NAME",
        help="Exclude apps with this exact name (repeatable).",
    )
    parser.add_argument(
        "--detail-level",
        type=int,
        default=2,
        choices=[1, 2, 3, 4, 5],
        metavar="N",
        help="Report depth: 1=Project, 2=+Task (default), 3=+Category, 4=+App, 5=+Title.",
    )
    parser.add_argument(
        "--timesheet",
        action="store_true",
        help="Timeline report: show activity as continuous slots ordered by time.",
    )
    parser.add_argument(
        "--consolidate",
        action="store_true",
        help="Consolidate sessions: merge consecutive sessions of the same task (even with gaps) unless interrupted by another task.",
    )
    parser.add_argument(
        "--exclude-non-project",
        action="store_true",
        help="Exclude events not linked to any project/task (old behavior).",
    )
    parser.add_argument(
        "--exclude-offline",
        action="store_true",
        help="Exclude offline gaps and AFK periods from the timesheet report (default: shown).",
    )
    parser.add_argument(
        "--ignore-offline",
        action="store_true",
        help="With --timesheet --consolidate: merge slots across OFFLINE gaps (default: OFFLINE breaks consolidation).",
    )
    parser.add_argument(
        "--sort-by-duration",
        action="store_true",
        help="Sort categories/projects by duration (descending) instead of by score.",
    )
    parser.add_argument(
        "--sort-alphabetically",
        action="store_true",
        help="Sort categories/projects alphabetically instead of by productivity score (default).",
    )
    parser.add_argument(
        "--deduplicate-categories",
        action="store_true",
        help="Collapse repeated categories within a slot (old behaviour). Default: show categories in timeline order.",
    )
    return parser.parse_args(reordered_argv)


# --- Time Period Utilities ---


def parse_period(period_str: str) -> Tuple[datetime, datetime]:
    """
    Convert a human-readable period string into a start and end datetime tuple.
    """
    now = datetime.now().astimezone()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    period_str = period_str.lower()

    if period_str == ":today":
        start = today_start
        end = today_end
    elif period_str == ":yesterday":
        yesterday = today_start - timedelta(days=1)
        start = yesterday
        end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
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
            exit(1)

    return start, end


# --- Data Loading and Processing ---


def load_categories(filepath: str) -> List[Dict]:
    """Load categorization rules from ActivityWatch settings file."""
    if not os.path.exists(filepath):
        print(f"Warning: Categories file not found at '{filepath}'.", file=sys.stderr)
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            settings = json.load(f)
            return settings.get("classes", [])
    except (json.JSONDecodeError, IOError) as e:
        print(
            f"Warning: Could not load or parse categories from '{filepath}': {e}",
            file=sys.stderr,
        )
        return []


def compile_category_rules(
    category_rules: List[Dict],
) -> Tuple[List[Tuple[List[str], Pattern, float]], Dict[str, float]]:
    """
    Take a list of category rule dictionaries and compile the regex strings.
    Also returns a map of category names to their scores.
    """
    compiled_rules = []
    cat_score_map = {}
    if not category_rules:
        return [], {}

    # First pass: collect all explicit category scores (including parent categories with type: "none")
    explicit_scores = {}  # category path -> score
    for rule_item in category_rules:
        cat_list = rule_item.get("name", ["Unknown"])
        if cat_list:
            full_path = " > ".join(cat_list)
            score_val = rule_item.get("data", {}).get("score")
            # Store all categories (both regex and none types) for inheritance
            explicit_scores[full_path] = (
                float(score_val) if score_val is not None else None
            )
            # If this is a parent category (type: none) with a score, add it to map
            rule = rule_item.get("rule", {})
            if rule.get("type") == "none" and score_val is not None:
                cat_score_map[full_path] = float(score_val)

    # Second pass: compile rules and build score map with inheritance
    for rule_item in category_rules:
        rule = rule_item.get("rule", {})
        if rule.get("type") == "regex" and rule.get("regex"):
            try:
                cat_list = rule_item.get("name", ["Unknown"])
                score_val = rule_item.get("data", {}).get("score")
                score = float(score_val) if score_val is not None else 0.0
                ignore_case = rule.get("ignore_case", True)
                flags = re.IGNORECASE if ignore_case else 0
                pattern = re.compile(rule["regex"], flags)
                compiled_rules.append((cat_list, pattern, score))

                # Store both full path and individual categories in the score map
                # This enables score inheritance: if a specific category has None score,
                # we look up its parent categories
                if cat_list:
                    # Store full path only if it has a non-None score
                    full_path = " > ".join(cat_list)
                    if score_val is not None:
                        cat_score_map[full_path] = score
                        # Also store just the most specific category for backward compatibility
                        cat_score_map[cat_list[-1]] = score

                    # Always store parent paths for inheritance lookup
                    for i in range(len(cat_list) - 1, 0, -1):
                        parent_path = " > ".join(cat_list[:i])
                        # If parent has explicit score, use it; else skip (will default to 0 in lookup)
                        if (
                            parent_path in explicit_scores
                            and explicit_scores[parent_path] is not None
                        ):
                            parent_score = explicit_scores[parent_path]
                            if parent_path not in cat_score_map:
                                cat_score_map[parent_path] = parent_score
            except (re.error, ValueError) as e:
                print(
                    f"Warning: Could not compile regex for rule {rule_item}: {e}",
                    file=sys.stderr,
                )
    return compiled_rules, cat_score_map


def get_category_score(category: str, cat_score_map: Dict[str, float]) -> float:
    """Get score for a category, with inheritance from parent categories.

    If the category itself has no score, tries progressively shorter paths
    to find a parent category score. E.g., for "IM > Messaging > Chat",
    tries: full path, then "IM > Messaging", then "IM", then defaults to 0.
    """
    # Try exact match first
    if category in cat_score_map:
        return cat_score_map[category]

    # Try parent categories if category contains hierarchy separator
    if " > " in category:
        parts = category.split(" > ")
        # Work backwards from most specific to most general
        for i in range(len(parts) - 1, 0, -1):
            parent = " > ".join(parts[:i])
            if parent in cat_score_map:
                return cat_score_map[parent]

    return 0.0


def window_event_max_category_score(
    event: Event, cat_score_map: Dict[str, float]
) -> float:
    """Highest category productivity score assigned to this window event (matches report header logic)."""
    category_list = event.data.get("$category", ["Uncategorized"])
    max_score = None
    for category in category_list:
        score = get_category_score(category, cat_score_map)
        if max_score is None:
            max_score = score
        else:
            max_score = max(max_score, score)
    return float(max_score) if max_score is not None else 0.0


def window_event_productive_duration(
    event: Event, cat_score_map: Dict[str, float]
) -> timedelta:
    """Portion of the event counted as productive (positive category score)."""
    if window_event_max_category_score(event, cat_score_map) > 0:
        return event.duration
    return timedelta(0)


def format_duration_tracked_prod(
    tracked_duration: timedelta, productive_within: timedelta
) -> str:
    """Format duration plus [prod NN%] for tracked-slot totals (weighted productive share).

    Returns fixed-width format with padding to align all labels consistently.
    All values right-aligned: [prod 100%], [prod  53%], [prod   3%]
    """
    base = format_duration(tracked_duration)
    if tracked_duration.total_seconds() <= 0:
        return base
    pct = productive_within.total_seconds() / tracked_duration.total_seconds() * 100
    # Right-align percentage in 3-char field: 100, " 53", "  3"
    label = f"[prod {pct:>3.0f}%]"
    # Format: duration + 2 spaces + label (right-aligned to 11 chars for consistent spacing)
    return f"{base}  {label:>11}"


def format_afk_label(duration: timedelta) -> str:
    """Format AFK duration label with fixed-width padding to match productivity labels.

    Returns format: duration + 2 spaces + [   AFK   ] (11 chars to align with [prod XX%])
    """
    base = format_duration(duration)
    label = "[   AFK   ]"
    return f"{base}  {label:>11}"


def format_offline_label(duration: timedelta) -> str:
    """Format OFFLINE duration label with fixed-width padding to match AFK labels.

    Returns format: duration + 2 spaces + [ OFFLINE ] (11 chars to align with [   AFK   ])
    """
    base = format_duration(duration)
    label = "[ OFFLINE ]"
    return f"{base}  {label:>11}"


def format_duration_with_afk(
    tracked_duration: timedelta,
    productive_within: timedelta,
    afk_duration: Optional[timedelta] = None,
) -> str:
    """Format duration with optional AFK notation for consolidated timesheet display.

    When afk_duration is present (consolidation with AFK breaks), includes:
        (HH:MM:SS AFK)  HH:MM:SS  [prod XX%]
    Otherwise, standard format:
        HH:MM:SS  [prod XX%]
    """
    base_format = format_duration_tracked_prod(tracked_duration, productive_within)

    if afk_duration and afk_duration.total_seconds() > 0:
        afk_str = format_duration(afk_duration)
        # Format: (AFK duration)  tracked duration  [prod XX%]
        # Insert AFK notation before the tracked duration
        return f"({afk_str} AFK)  {base_format}"

    return base_format


def format_duration_with_gaps(
    tracked_duration: timedelta,
    productive_within: timedelta,
    afk_duration: Optional[timedelta] = None,
    offline_extension_duration: Optional[timedelta] = None,
) -> str:
    """Format duration with optional AFK and OFFLINE extension notation.

    When gaps are present (consolidation with breaks), includes:
        (HH:MM:SS AFK, HH:MM:SS OFFLINE)  HH:MM:SS  [prod XX%]
    Otherwise delegates to format_duration_with_afk.
    """
    base_format = format_duration_tracked_prod(tracked_duration, productive_within)

    gap_parts = []
    if afk_duration and afk_duration.total_seconds() > 0:
        gap_parts.append(f"{format_duration(afk_duration)} AFK")
    if offline_extension_duration and offline_extension_duration.total_seconds() > 0:
        gap_parts.append(f"{format_duration(offline_extension_duration)} OFFLINE")

    if gap_parts:
        gaps_str = ", ".join(gap_parts)
        return f"({gaps_str})  {base_format}"

    return base_format


def get_bucket_id(bucket_name: str) -> str:
    """Construct the full bucket ID from its name and the machine's hostname."""
    hostname = platform.node()
    return f"aw-watcher-{bucket_name}_{hostname}"


def get_events(
    client: ActivityWatchClient, bucket_id: str, start: datetime, end: datetime
) -> List[Event]:
    """Fetch events from a specific bucket within a time range."""
    try:
        return client.get_events(bucket_id, start=start, end=end, limit=-1)
    except Exception as e:
        print(
            f"Warning: Could not get events for bucket '{bucket_id}': {e}",
            file=sys.stderr,
        )
        return []


# --- Filtering Utilities ---


def _match(name: str, pattern: str, exact: bool) -> bool:
    """Check if a name matches a pattern (exact or partial)."""
    return name.lower() == pattern.lower() if exact else pattern.lower() in name.lower()


def _matches_any(name: str, patterns: Optional[List[str]], exact: bool) -> bool:
    """Check if name matches any of the patterns. No patterns = match all."""
    return not patterns or any(_match(name, p, exact) for p in patterns)


def _excluded(name: str, exclusions: Optional[List[str]]) -> bool:
    """Check if name is in the exclusion list (exact match, case-insensitive)."""
    return any(name.lower() == e.lower() for e in (exclusions or []))


def apply_filters(
    report_data: Dict,
    args: argparse.Namespace,
    task_based: bool,
) -> Dict:
    """Apply project/task/app filters and exclusions to the report data."""
    if not task_based:
        # No-taskwarrior mode: filter categories and apps only
        filtered = {}
        for cat, c_data in report_data.items():
            if not _matches_any(cat, args.project or args.task or args.app, args.exact):
                continue
            if _excluded(
                cat, args.exclude_project or args.exclude_task or args.exclude_app
            ):
                continue
            filtered_apps = {
                app: a_data
                for app, a_data in c_data.get("apps", {}).items()
                if _matches_any(app, args.app, args.exact)
                and not _excluded(app, args.exclude_app)
            }
            if filtered_apps:
                filtered[cat] = {**c_data, "apps": filtered_apps}
        return filtered

    # Task-based mode: filter projects, tasks, categories, and apps
    search_patterns = ([args.search] if args.search else []) + (args.project or [])
    filtered = {}

    for project, p_data in report_data.items():
        project_match = _matches_any(project, search_patterns, args.exact)

        if not project_match and not args.task and not args.app:
            continue

        if _excluded(project, args.exclude_project):
            continue

        filtered_tasks = {}
        for task, t_data in p_data.get("tasks", {}).items():
            task_patterns = ([args.search] if args.search else []) + (args.task or [])
            task_match = _matches_any(task, task_patterns, args.exact) or project_match

            if not task_match and not args.app:
                continue

            if _excluded(task, args.exclude_task):
                continue

            filtered_cats = {}
            for cat, c_data in t_data.get("categories", {}).items():
                # Only filter apps by specific --app filter; general search matches at project/task level
                filtered_apps = {
                    app: a_data
                    for app, a_data in c_data.get("apps", {}).items()
                    if (not args.app or _matches_any(app, args.app, args.exact))
                    and not _excluded(app, args.exclude_app)
                }
                if filtered_apps:
                    filtered_cats[cat] = {**c_data, "apps": filtered_apps}

            if filtered_cats:
                filtered_tasks[task] = {**t_data, "categories": filtered_cats}

        if filtered_tasks:
            filtered[project] = {**p_data, "tasks": filtered_tasks}

    return filtered


def generate_report_data(
    window_events: List[Event],
    task_events: Optional[List[Event]],
    categories: List[Tuple[List[str], Pattern, float]],
    cat_score_map: Dict[str, float],
    args: argparse.Namespace,
) -> Dict:
    """
    Process window events and structure them into a hierarchical report.
    """
    report: Dict = {}
    # --- 1. Categorize Events ---
    for event in window_events:
        categorize_event(event, categories)

    # --- 2. Filter Events by Score ---
    if args.min_score is not None or args.max_score is not None:
        filtered_events = []
        for event in window_events:
            event_categories = event.data.get("$category")
            # Default score for uncategorized events is 0
            scores = [0]
            if event_categories:
                scores = [
                    get_category_score(cat, cat_score_map) for cat in event_categories
                ]

            # Keep the event if at least one of its categories is within the threshold
            should_keep = any(
                (args.min_score is None or score >= args.min_score)
                and (args.max_score is None or score <= args.max_score)
                for score in scores
            )

            if should_keep:
                filtered_events.append(event)
        window_events = filtered_events

    window_events = sorted(window_events, key=lambda e: e.timestamp)

    def get_app_name(event: Event) -> str:
        return event.data.get("app", "Unknown App")

    def get_title(event: Event) -> str:
        return event.data.get("title", "No Title")

    # --- 3. Aggregate Data ---
    if task_events is not None:
        for event in window_events:
            active_task = find_active_task(event, task_events)
            if active_task:
                task_name, project = get_task_info(active_task)
            else:
                if args.exclude_non_project:
                    continue
                task_name = NO_TASK
                project = NO_PROJECT

            category_list = event.data.get("$category", ["Uncategorized"])
            app_name = get_app_name(event)

            for category in category_list:
                score = get_category_score(category, cat_score_map)
                prod_score = (event.duration.total_seconds() / 3600) * score

                proj_node = report.setdefault(
                    project,
                    {
                        "total_duration": timedelta(0),
                        "tasks": {},
                        "prod_score": 0.0,
                    },
                )
                task_node = proj_node["tasks"].setdefault(
                    task_name,
                    {
                        "total_duration": timedelta(0),
                        "categories": {},
                        "prod_score": 0.0,
                    },
                )
                cat_node = task_node["categories"].setdefault(
                    category,
                    {
                        "total_duration": timedelta(0),
                        "apps": {},
                        "prod_score": 0.0,
                    },
                )
                app_node = cat_node["apps"].setdefault(
                    app_name,
                    {"total_duration": timedelta(0), "prod_score": 0.0},
                )

                proj_node["total_duration"] += event.duration
                proj_node["prod_score"] += prod_score
                task_node["total_duration"] += event.duration
                task_node["prod_score"] += prod_score
                cat_node["total_duration"] += event.duration
                cat_node["prod_score"] += prod_score
                app_node["total_duration"] += event.duration
                app_node["prod_score"] += prod_score

                # Always nest titles under app nodes
                title = get_title(event)
                normalized_title = normalize_title(title)
                title_node = app_node.setdefault("titles", {}).setdefault(
                    normalized_title,
                    {"total_duration": timedelta(0), "prod_score": 0.0},
                )
                title_node["total_duration"] += event.duration
                title_node["prod_score"] += prod_score
    else:
        for event in window_events:
            category_list = event.data.get("$category", ["Uncategorized"])
            app_name = get_app_name(event)

            for category in category_list:
                score = get_category_score(category, cat_score_map)
                prod_score = (event.duration.total_seconds() / 3600) * score

                cat_node = report.setdefault(
                    category,
                    {"total_duration": timedelta(0), "apps": {}, "prod_score": 0.0},
                )
                app_node = cat_node["apps"].setdefault(
                    app_name, {"total_duration": timedelta(0), "prod_score": 0.0}
                )

                cat_node["total_duration"] += event.duration
                cat_node["prod_score"] += prod_score
                app_node["total_duration"] += event.duration
                app_node["prod_score"] += prod_score

                # Always nest titles under app nodes
                title = get_title(event)
                normalized_title = normalize_title(title)
                title_node = app_node.setdefault("titles", {}).setdefault(
                    normalized_title,
                    {"total_duration": timedelta(0), "prod_score": 0.0},
                )
                title_node["total_duration"] += event.duration
                title_node["prod_score"] += prod_score

    return report


# --- Shared Utility Functions (used by both default and timeline reports) ---


def categorize_event(
    event: Event, categories: List[Tuple[List[str], Pattern, float]]
) -> None:
    """Categorize a window event by matching against regex rules.

    Mutates event.data["$category"] in-place with the most specific matching category.
    Used by both generate_report_data() and main() to avoid duplication of regex logic.
    """
    app_name = event.data.get("app", "")
    title = event.data.get("title", "")
    match_strings = [
        app_name + " " + title,
        app_name,
        title,
    ]
    matched_cats = []
    for cat_list, pattern, _ in categories:
        if any(pattern.search(s) for s in match_strings):
            if cat_list:
                full_path = " > ".join(cat_list)
                matched_cats.append((len(cat_list), full_path))
    if matched_cats:
        matched_cats.sort(key=lambda x: (-x[0], x[1]))
        event.data["$category"] = [matched_cats[0][1]]


def find_active_task(event: Event, task_events: List[Event]) -> Optional[Event]:
    """Find the taskwarrior event that overlaps with the given window event.

    Returns the overlapping task event or None if no overlap found.
    Used in generate_report_data(), generate_timeline_data(), and main().
    """
    return next(
        (
            task
            for task in task_events
            if event.timestamp < task.timestamp + task.duration
            and task.timestamp < event.timestamp + event.duration
        ),
        None,
    )


def get_task_info(active_task: Event) -> Tuple[str, str]:
    """Extract task name and project from an active taskwarrior event.

    Returns (task_name, project) tuple. Task name falls back through
    title → label → task → NO_TASK. Project defaults to NO_PROJECT.
    """
    task_name = (
        active_task.data.get("title")
        or active_task.data.get("label")
        or active_task.data.get("task")
        or NO_TASK
    )
    project = active_task.data.get("project", NO_PROJECT)
    return task_name, project


def task_has_offline_tag(task_event: Event) -> bool:
    """Check if a task event has the 'offline' tag (case-insensitive)."""
    raw_tags = task_event.data.get("tags", [])
    tags = [raw_tags] if isinstance(raw_tags, str) else list(raw_tags)
    return "offline" in (t.lower() for t in tags)


def build_offline_category_structure(
    duration: timedelta,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> Dict:
    """Build an Offline category structure for both hierarchical and timeline reports.

    Args:
        duration: Total duration of the offline task
        start_time: Optional start time for timeline reports
        end_time: Optional end time for timeline reports

    Returns:
        A dict representing the Offline category that can be used in both report types
    """
    if start_time is not None and end_time is not None:
        return {
            "category": "Offline",
            "duration": duration,
            "start": start_time,
            "end": end_time,
            "apps": [],
        }
    else:
        return {
            "total_duration": duration,
            "apps": {},
            "prod_score": 0.0,
        }


# --- Report Formatting and Printing ---


def get_terminal_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except OSError:
        return 80


def print_summary_total(
    total_duration: timedelta,
    productive_duration: Optional[timedelta] = None,
    total_score: Optional[float] = None,
) -> None:
    """Print a summary total line with duration and productivity.

    Used by both hierarchical and timeline reports for consistent output.
    Format: Total Time: HH:MM:SS  [prod XX%]
    Right-aligned to terminal width for visual consistency.
    """
    width = get_terminal_width()
    # Use the same formatting as timesheet report for consistency
    summary_line = f"Total Time: {format_duration_tracked_prod(total_duration, productive_duration or timedelta(0))}"
    print(summary_line.rjust(width))


def format_duration(duration: timedelta) -> str:
    total_seconds = int(duration.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{seconds:02}"


def sanitize_title(title: str) -> str:
    """Clean window titles: remove notification counters and emoji.

    Keeps UTF-8 and Latin characters including accents (ñ, á, é, etc.) which are
    common in Spanish, Portuguese, French, and other European languages.
    Removes emoji, decorative symbols, and other "weird" Unicode by checking
    Unicode categories.

    IMPORTANT: This handles the case where window titles contain emoji from
    Discord channel names, Slack emojis, etc. We want to keep legitimate
    accented text but filter out visual noise.

    Strategy:
    - ASCII (< 128): keep printable chars and spaces
    - Latin-1 Supplement (U+0080-U+00FF): keep all (covers ñ, á, é, etc.)
    - Other ranges: keep only letters (L*) and numbers (N*), reject all symbols
    """
    if not title:
        return title
    # First normalize to remove notification counters like "(7)"
    title = normalize_title(title)
    # Remove emoji and symbol characters by Unicode category
    result = []
    for c in title:
        code_point = ord(c)
        # ASCII: keep all printable + whitespace
        if code_point < 128:
            if c.isprintable() or c.isspace():
                result.append(c)
        # Latin-1 Supplement: safe zone for European accented characters
        # U+0080 to U+00FF covers: ñ, á, é, í, ó, ú, à, è, ù, ç, etc.
        elif 0x0080 <= code_point <= 0x00FF:
            result.append(c)
        # Everything else: strict filtering to exclude emoji and weird chars
        else:
            category = unicodedata.category(c)
            # Keep only: Letters (L*) and Numbers (N*)
            # Reject: Symbols (S*), Punctuation (P*), Separators (Z*), etc.
            if category[0] in ("L", "N"):
                result.append(c)
    return "".join(result)


def normalize_title(title: str) -> str:
    """Remove notification counters from window titles to aggregate similar windows.

    Removes patterns like:
    - (7) at start: "(7) WhatsApp" -> "WhatsApp"
    - (1) at end: "Work/Job Hunting (1)" -> "Work/Job Hunting"
    - (2) in middle: "Inbox (2) - Gmail" -> "Inbox - Gmail"
    """
    if not title:
        return title
    # Remove numbers in parentheses: \s*\(\d+\)\s* matches optional spaces, (digits), optional spaces
    normalized = re.sub(r"\s*\(\d+\)\s*", " ", title)
    # Clean up multiple spaces
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def truncate_title(title: str, max_length: int = 60) -> str:
    """Truncate title to max_length with ellipsis if needed."""
    if not title:
        return title
    if len(title) <= max_length:
        return title
    return title[: max_length - 1] + "…"


def abbreviate_project_path(
    project: str, task: str = "", max_content_width: int = 100
) -> str:
    """Abbreviate project path while preserving task description.

    When truncating, keep the full task and abbreviate the project by:
    - Keeping the leaf (rightmost) project level
    - Abbreviating the root project to first 5 chars + "..."
    Format: "Root... > Leaf > Leaf2"
    """
    if " > " not in project:
        # Single-level project, no abbreviation needed
        return project

    parts = project.split(" > ")
    leaf = parts[-1]  # Keep the last (most specific) project level

    # Build abbreviated version: "Root... > Leaf"
    if len(parts) > 1:
        root = parts[0]
        # Abbreviate root to 5 chars max
        root_abbrev = root[:5] + "..." if len(root) > 5 else root
        abbreviated = f"{root_abbrev} > {leaf}"
    else:
        abbreviated = leaf

    # If the result with task is still short enough, use it
    if task:
        full = f"{abbreviated} ▶▶ {task}"
        if len(full) <= max_content_width:
            return abbreviated

    return abbreviated


def format_timeline_line(
    left_part: str, duration_str: str = "", max_left_width: int = 100
) -> str:
    """Format timeline line with truncated content and right-aligned duration.

    Truncates left_part if needed and right-aligns the duration column.
    """
    width = get_terminal_width()

    # Truncate left part if it exceeds max width
    if len(left_part) > max_left_width:
        left_part = left_part[: max_left_width - 3] + "..."

    # Right-align duration
    if duration_str:
        return left_part.ljust(width - len(duration_str) - 1) + " " + duration_str
    return left_part


def print_report_header(
    title: str,
    period: str,
    start_time: datetime,
    end_time: datetime,
    total_duration: timedelta,
    task_based: bool,
    non_afk_time: Optional[timedelta] = None,
    productive_time: Optional[timedelta] = None,
    productive_task_time: Optional[timedelta] = None,
    first_event_time: Optional[datetime] = None,
    last_event_time: Optional[datetime] = None,
    distracting_time: Optional[timedelta] = None,
    unscored_time: Optional[timedelta] = None,
    total_score: Optional[float] = None,
    current_session_start: Optional[datetime] = None,
    current_session_end: Optional[datetime] = None,
    current_session_duration: Optional[timedelta] = None,
    last_break_start: Optional[datetime] = None,
    last_break_end: Optional[datetime] = None,
    last_break_duration: Optional[timedelta] = None,
    total_time_all: Optional[timedelta] = None,
    afk_time: Optional[timedelta] = None,
):
    """Print shared report header with period, active time, and productivity metrics.

    Used by both print_report() and print_timeline_report() to avoid duplication.
    Handles task_based and non-task_based modes. Optional parameters can be omitted.
    """
    width = get_terminal_width()

    print(title.center(width, "="))
    print(f"Period: {period} ({start_time.date()} to {end_time.date()})")

    # Show metrics if available
    if non_afk_time and first_event_time and last_event_time:
        # Calculate total active time (non-AFK + AFK)
        total_active_time = non_afk_time + (afk_time if afk_time else timedelta(0))
        active_time_str = format_duration(total_active_time)
        afk_str = format_duration(afk_time) if afk_time else None

        # Format time window from actual non-afk events
        first_date = first_event_time.date()
        last_date = last_event_time.date()
        first_time_str = first_event_time.strftime("%H:%M")
        last_time_str = last_event_time.strftime("%H:%M")

        time_window = f"{first_date} {first_time_str} to {last_date} {last_time_str}"

        task_time_pct = (
            (total_duration.total_seconds() / non_afk_time.total_seconds() * 100)
            if non_afk_time.total_seconds() > 0
            else 0
        )

        # Calculate productivity percentage of total time
        total_productive_pct = 0
        if productive_time and non_afk_time.total_seconds() > 0:
            total_productive_pct = (
                productive_time.total_seconds() / non_afk_time.total_seconds() * 100
            )

        # Calculate productivity percentage of task time
        task_productive_pct = 0
        if productive_task_time and total_duration.total_seconds() > 0:
            task_productive_pct = (
                productive_task_time.total_seconds()
                / total_duration.total_seconds()
                * 100
            )

        print(f"Active Time: {active_time_str} ({time_window})")
        if afk_str:
            print(f"  • AFK time: {afk_str}")
        if task_based:
            print(
                f"  • Project Tracking: {task_time_pct:.1f}% ({format_duration(total_duration)})"
            )
            if task_time_pct > 0:
                print(
                    f"  • Focus time: {task_productive_pct:.1f}% ({format_duration(productive_task_time)})"
                )
            if total_score is not None:
                print(f"  • Task Productivity Score: {total_score:.2f}")
            untracked_productive_time = productive_time - productive_task_time
            untracked_productive_pct = (
                (untracked_productive_time / non_afk_time * 100) if non_afk_time else 0
            )
            print(
                f"  • Untracked productivity: {untracked_productive_pct:.1f}% ({format_duration(untracked_productive_time)})"
            )
            print(
                f"  • Overall productivity: {total_productive_pct:.1f}% ({format_duration(productive_time)})"
            )
        else:
            # Non-task-based mode: show tracked projects as 0
            print(f"  • Tracked projects: 0.0% ({format_duration(timedelta(0))})")
            if total_score is not None:
                print(f"  • Overall Productivity Score: {total_score:.2f}")
            untracked_productive_time = productive_time - productive_task_time
            untracked_productive_pct = (
                (untracked_productive_time / non_afk_time * 100) if non_afk_time else 0
            )
            print(
                f"  • Untracked productivity: {untracked_productive_pct:.1f}% ({format_duration(untracked_productive_time)})"
            )
            print(
                f"  • Overall productivity: {total_productive_pct:.1f}% ({format_duration(productive_time)})"
            )

        # Print distracting and unscored time (common to both modes)
        if distracting_time:
            distracting_pct = (
                (distracting_time / non_afk_time * 100) if non_afk_time else 0
            )
            print(
                f"  • Overall distracting time: {distracting_pct:.1f}% ({format_duration(distracting_time)})"
            )
        if unscored_time:
            unscored_pct = (unscored_time / non_afk_time * 100) if non_afk_time else 0
            print(
                f"  • Unscored time: {unscored_pct:.1f}% ({format_duration(unscored_time)})"
            )

        # Print current session and last break information
        if current_session_duration and current_session_start and current_session_end:
            session_start_str = current_session_start.strftime("%H:%M")
            session_end_str = current_session_end.strftime("%H:%M")
            print(
                f"Current Session: {format_duration(current_session_duration)} ({session_start_str} to {session_end_str})"
            )

        if last_break_duration and last_break_start and last_break_end:
            break_start_str = last_break_start.strftime("%H:%M")
            break_end_str = last_break_end.strftime("%H:%M")
            print(
                f"Last Break: {format_duration(last_break_duration)} ({break_start_str} to {break_end_str})"
            )

        print("-" * width)
    else:
        # Use total_time_all for "Total Time" display if provided (includes untracked time)
        # Otherwise fall back to total_duration (project-tracked time only)
        display_total = total_time_all if total_time_all is not None else total_duration
        header = f"Total Time: {format_duration(display_total)}"
        if total_score is not None:
            score_header = f"Productivity Score: {total_score:.2f}"
            print(header.ljust(width - len(score_header)) + score_header)
        else:
            print(header)
        print("-" * width)


def print_report(
    report_data: Dict,
    period: str,
    start_time: datetime,
    end_time: datetime,
    task_based: bool,
    detail_level: int = 4,
    non_afk_time: timedelta = None,
    productive_time: timedelta = None,
    productive_task_time: timedelta = None,
    first_event_time: datetime = None,
    last_event_time: datetime = None,
    distracting_time: timedelta = None,
    unscored_time: timedelta = None,
    sort_by_duration: bool = False,
    sort_by_score: bool = True,
    current_session_start: datetime = None,
    current_session_end: datetime = None,
    current_session_duration: timedelta = None,
    last_break_start: datetime = None,
    last_break_end: datetime = None,
    last_break_duration: timedelta = None,
):
    width = get_terminal_width()

    def sort_items(items):
        """Sort items by duration or score based on flags."""
        if sort_by_duration:
            return sorted(items, key=lambda x: x[1]["total_duration"], reverse=True)
        elif sort_by_score:
            return sorted(items, key=lambda x: x[1]["prod_score"], reverse=True)
        else:
            return sorted(items)  # Alphabetical

    # Only count real projects (exclude "No project assigned" sentinel)
    total_duration = sum(
        (
            data["total_duration"]
            for project, data in report_data.items()
            if project != NO_PROJECT
        ),
        timedelta(0),
    )
    total_score = sum(
        data["prod_score"]
        for project, data in report_data.items()
        if project != NO_PROJECT
    )

    # Print shared header using common utility function
    print_report_header(
        title=" Timesheet Report ",
        period=period,
        start_time=start_time,
        end_time=end_time,
        total_duration=total_duration,
        task_based=task_based,
        non_afk_time=non_afk_time,
        productive_time=productive_time,
        productive_task_time=productive_task_time,
        first_event_time=first_event_time,
        last_event_time=last_event_time,
        distracting_time=distracting_time,
        unscored_time=unscored_time,
        total_score=total_score,
        current_session_start=current_session_start,
        current_session_end=current_session_end,
        current_session_duration=current_session_duration,
        last_break_start=last_break_start,
        last_break_end=last_break_end,
        last_break_duration=last_break_duration,
    )

    if not report_data:
        print("No activity found for the specified period.")
        print("=" * width)
        return

    if task_based:
        for project, p_data in sort_items(report_data.items()):
            p_duration = format_duration(p_data["total_duration"])
            p_score = f"({p_data['prod_score']:.2f})"
            p_line = f"▶ Project: {project.replace('.', ' -> ')} {p_score}"
            print(p_line.ljust(width - len(p_duration) - 2) + f" {p_duration}")

            if detail_level < 2:
                continue

            for task, t_data in sort_items(p_data["tasks"].items()):
                t_duration = format_duration(t_data["total_duration"])
                t_score = f"({t_data['prod_score']:.2f})"
                t_line = f"  • Task: {task} {t_score}"
                print(t_line.ljust(width - len(t_duration) - 2) + f" {t_duration}")

                if detail_level < 3:
                    continue

                for cat, c_data in sort_items(t_data["categories"].items()):
                    c_duration = format_duration(c_data["total_duration"])
                    c_score = f"({c_data['prod_score']:.2f})"
                    c_line = f"    - {cat} {c_score}"
                    print(
                        c_line.ljust(width - len(c_duration) - 2, ".")
                        + f" {c_duration}"
                    )

                    if detail_level < 4:
                        continue

                    for app, a_data in sort_items(c_data["apps"].items()):
                        a_duration = format_duration(a_data["total_duration"])
                        a_score = f"({a_data['prod_score']:.2f})"
                        a_line = f"      - {app} {a_score}"

                        # Check if app has nested titles (shown at detail_level 5+)
                        if "titles" in a_data and detail_level >= 5:
                            print(
                                a_line.ljust(width - len(a_duration) - 2, " ")
                                + f" {a_duration}"
                            )
                            for title, title_data in sort_items(
                                a_data["titles"].items()
                            ):
                                title_duration = format_duration(
                                    title_data["total_duration"]
                                )
                                title_score = f"({title_data['prod_score']:.2f})"
                                clean_title = sanitize_title(title)
                                clean_title = truncate_title(clean_title, 90)
                                title_line = f"        - {title_score} {clean_title}"
                                print(
                                    title_line.ljust(
                                        width - len(title_duration) - 2, " "
                                    )
                                    + f" {title_duration}"
                                )
                        else:
                            print(
                                a_line.ljust(width - len(a_duration) - 2, " ")
                                + f" {a_duration}"
                            )

            if detail_level >= 2:
                print()
    else:
        for cat, c_data in sort_items(report_data.items()):
            c_duration = format_duration(c_data["total_duration"])
            c_score = f"({c_data['prod_score']:.2f})"
            c_line = f"▶ Category: {cat} {c_score}"
            print(c_line.ljust(width - len(c_duration) - 2) + f" {c_duration}")

            if detail_level < 2:
                continue

            for app, a_data in sort_items(c_data["apps"].items()):
                a_duration = format_duration(a_data["total_duration"])
                a_score = f"({a_data['prod_score']:.2f})"
                a_line = f"  • App: {app} {a_score}"
                print(a_line.ljust(width - len(a_duration) - 2) + f" {a_duration}")

                # Print window titles under app (shown at detail_level 3+)
                if detail_level >= 3 and "titles" in a_data:
                    for title, title_data in sort_items(a_data["titles"].items()):
                        title_duration = format_duration(title_data["total_duration"])
                        title_score = f"({title_data['prod_score']:.2f})"
                        clean_title = sanitize_title(title)
                        clean_title = truncate_title(clean_title, 90)
                        title_line = f"      • {title_score} {clean_title}"
                        print(
                            title_line.ljust(width - len(title_duration) - 2)
                            + f" {title_duration}"
                        )

            if detail_level >= 2:
                print()

    # Print summary total (excluding "No project assigned" sentinel)
    print_summary_total(total_duration, productive_task_time, total_score)
    print("=" * width)


# --- Timeline Report Generation and Printing ---


def generate_timeline_data(
    report_events: List[Dict[str, Any]],
    afk_events: List[Event],
    cat_score_map: Dict[str, float],
    detail_level: int = 1,
    deduplicate_categories: bool = False,
) -> List[Dict]:
    """
    Generate timeline data grouped by not-afk periods (time slots).

    detail_level controls what sub-data is collected per slot:
      1 = Project only
      2 = Project + Task
      3 = Project + Task + Category
      4 = Project + Task + Category + App
      5 = Project + Task + Category + App + Title

    CORE CONCEPT - What is a "time slot" and "subslot"?
    ==================================================
    A NOT-AFk PERIOD is a continuous work period defined by a single not-afk event.
    Not-afk events come from ActivityWatch AFK bucket (status="not-afk") and
    represent times when the user is active (mouse/keyboard activity).

    A SUBSLOT is a continuous sequence within a not-afk period where PROJECT,
    TASK, and TASKWARRIOR EVENT remain unchanged. Continuity is determined by
    the (project, task, task_event) triplet:
    - Window switching: does NOT break continuity (you can switch apps/windows within same task)
    - Task change: BREAKS continuity and creates a new slot
    - Project change: BREAKS continuity and creates a new slot
    - Task pause/resume (different taskwarrior event): creates a NEW slot (task was paused and restarted)

    GROUPING LOGIC:
    ===============
    For EACH not-afk event:
      1. Find all window events that overlap with this not-afk period
      2. Sort events chronologically
      3. Group consecutive events by (PROJECT, TASK, TASKWARRIOR_EVENT) CONTINUITY
         - When (project, task, task_event) triplet changes → start a new subslot
         - When only app/window changes (same project, task, & task_event) → continue same subslot
         - When task is paused and resumed (different task_event) → create new subslot
      4. Create ONE slot per (project, task, task_event) continuous GROUP
         - Subslot start = earliest event in group
         - Subslot end = latest event in group
         - Subslot duration = sum of all event durations
      5. Multiple gaps/pauses in a day = multiple not-afk events = multiple subslots
      6. Task pause/resume cycles = multiple task_events = multiple subslots

    FILTERING WITH TIMELINE:
    ========================
    When filters (--project, --task, --app, search term) are applied:
    - Window events are pre-filtered BEFORE calling this function
    - Only matching events are passed to this function
    - Not-afk boundaries are preserved (slot structure unchanged)
    - Result: filtered slots that still show pauses between not-afk events

    EXAMPLE TIMELINE (single not-afk event with project/task/pause changes):
    ========================================================================
    Not-afk period: 07:00-18:00 (continuous activity, no AFK breaks)

    Chronological window events with corresponding taskwarrior events:
      - Climb (07:00-09:00, Task A, event_id=1) ← (Climb, Task A, event_id=1)
      - Climb (09:00-11:00, Task B, event_id=2) ← (Climb, Task B, event_id=2) = NEW slot (task changed)
      - Mercado (11:00-13:00, Task X, event_id=3) ← (Mercado, Task X, event_id=3) = NEW slot (project changed)
      - Climb (13:00-15:00, Task A, event_id=4) ← (Climb, Task A, event_id=4) = NEW slot (Task A paused & resumed)
      - Climb (15:00-16:00, Task A, event_id=4) ← (Climb, Task A, event_id=4) = continues same slot (same event_id)
      - Ecosistema (16:00-18:00, Task Y, event_id=5) ← (Ecosistema, Task Y, event_id=5) = NEW slot (project changed)

    Resulting SUBSLOTS ((project, task, task_event) continuous groups):
      Subslot 1: Climb + Task A (event_id=1), 07:00-09:00
      Subslot 2: Climb + Task B (event_id=2), 09:00-11:00 ← separate because task changed
      Subslot 3: Mercado + Task X (event_id=3), 11:00-13:00 ← separate because project changed
      Subslot 4: Climb + Task A (event_id=4), 13:00-16:00 ← separate even though same task (paused & resumed with new event_id)
      Subslot 5: Ecosistema + Task Y (event_id=5), 16:00-18:00 ← separate because project changed

    This preserves activity continuity: each taskwarrior event represents a distinct work session.
    When a task is paused and resumed, it gets a new event_id, triggering a new slot.
    Window switching (e.g., Climb+Task A in Kitty → Climb+Task A in Browser, same event_id) continues
    the same slot because (project, task, task_event) is unchanged.
    """
    if not report_events:
        return []

    # Filter to not-afk periods only
    not_afk_events = filter_keyvals(afk_events, "status", ["not-afk"])
    not_afk_events = sorted(not_afk_events, key=lambda e: e.timestamp)

    slots = []

    # For each not-afk period (time slot boundary)
    for afk_event in not_afk_events:
        # Get all report events that overlap this not-afk period
        window_in_slot = [
            rep
            for rep in report_events
            if rep["event"].timestamp < afk_event.timestamp + afk_event.duration
            and afk_event.timestamp < rep["event"].timestamp + rep["event"].duration
        ]

        if not window_in_slot:
            continue

        # Sort events chronologically to detect (project, task) continuity
        window_in_slot = sorted(window_in_slot, key=lambda r: r["event"].timestamp)

        # Build slots grouped by (project, task, task_event) continuity
        # Window switching does NOT break continuity (same slot continues)
        # Task change breaks continuity (new slot)
        # Project change breaks continuity (new slot)
        # Task pause/resume (different taskwarrior event) creates new slot
        slots_in_period = []
        current_slot = None
        current_project_task_session = None

        for report_event in window_in_slot:
            event = report_event["event"]
            # Skip zero-duration events (noise)
            if event.duration == timedelta(0):
                continue

            task_name = report_event["task"]
            project = report_event["project"]
            active_task = report_event["active_task"]

            app_name = event.data.get("app", "Unknown App")
            window_title = (
                event.data.get("title", "No Title") if detail_level >= 5 else None
            )

            # Include the active_task instance to distinguish between paused/resumed sessions
            # In no-task mode, use a constant session key since there's no task tracking
            project_task_session = (
                project,
                task_name,
                id(active_task) if active_task else 0,
            )

            # Check if (project, task, task_event) changed (breaks slot continuity)
            if project_task_session != current_project_task_session:
                # Start a new slot for this (project, task, task_event) combination
                current_project_task_session = project_task_session
                current_slot = {
                    "project": project,
                    "task": task_name,
                    "events": [report_event],
                    "categories": {} if deduplicate_categories else [],
                }
                # For non-dedup mode: track current category/app/title to detect continuity breaks
                if not deduplicate_categories:
                    current_slot.update(
                        {
                            "_cur_cat": None,
                            "_cur_cat_block": None,
                            "_cur_app": None,
                            "_cur_app_block": None,
                            "_cur_title": None,
                            "_cur_title_entry": None,
                        }
                    )
                slots_in_period.append(current_slot)
            else:
                # Same (project, task, task_event), add event to current slot (window switching doesn't break continuity)
                current_slot["events"].append(report_event)

            # Track category time with nested apps and titles (level 3+)
            if detail_level >= 3:
                event_ts = event.timestamp.astimezone()
                event_end_ts = (event.timestamp + event.duration).astimezone()

                category = event.data.get("$category", ["Uncategorized"])[0]

                if deduplicate_categories:
                    # OLD PATH: Dict-based accumulation (deduplicated)
                    if category not in current_slot["categories"]:
                        current_slot["categories"][category] = {
                            "duration": timedelta(0),
                            "start": event_ts,
                            "end": event_end_ts,
                            "apps": {},
                        }
                    else:
                        # Update start/end to expand range
                        cat_data = current_slot["categories"][category]
                        if event_ts < cat_data["start"]:
                            cat_data["start"] = event_ts
                        if event_end_ts > cat_data["end"]:
                            cat_data["end"] = event_end_ts

                    current_slot["categories"][category]["duration"] += event.duration

                    # Track app time nested under category (level 4+)
                    if detail_level >= 4:
                        if app_name not in current_slot["categories"][category]["apps"]:
                            current_slot["categories"][category]["apps"][app_name] = {
                                "duration": timedelta(0),
                                "start": event_ts,
                                "end": event_end_ts,
                                "titles": {},
                            }
                        else:
                            # Update start/end to expand range
                            app_data = current_slot["categories"][category]["apps"][
                                app_name
                            ]
                            if event_ts < app_data["start"]:
                                app_data["start"] = event_ts
                            if event_end_ts > app_data["end"]:
                                app_data["end"] = event_end_ts

                        current_slot["categories"][category]["apps"][app_name][
                            "duration"
                        ] += event.duration

                        # Track per-title breakdown (level 5+)
                        if window_title:
                            normalized_title = normalize_title(window_title)
                            clean_title = sanitize_title(normalized_title)
                            titles = current_slot["categories"][category]["apps"][
                                app_name
                            ]["titles"]
                            if clean_title not in titles:
                                titles[clean_title] = {
                                    "duration": timedelta(0),
                                    "events": [
                                        {"start": event_ts, "end": event_end_ts}
                                    ],
                                }
                            else:
                                title_data = titles[clean_title]
                                title_data["events"].append(
                                    {"start": event_ts, "end": event_end_ts}
                                )

                            titles[clean_title]["duration"] += event.duration
                else:
                    # NEW PATH: List-based accumulation (timeline order, no dedup)
                    # Category level: start new block if category changes
                    if category != current_slot["_cur_cat"]:
                        new_cat_block = {
                            "category": category,
                            "duration": event.duration,
                            "start": event_ts,
                            "end": event_end_ts,
                            "apps": [],
                        }
                        current_slot["categories"].append(new_cat_block)
                        current_slot["_cur_cat"] = category
                        current_slot["_cur_cat_block"] = new_cat_block
                        current_slot["_cur_app"] = None
                        current_slot["_cur_app_block"] = None
                        current_slot["_cur_title"] = None
                        current_slot["_cur_title_entry"] = None
                    else:
                        # Same category: update the current block
                        cb = current_slot["_cur_cat_block"]
                        cb["duration"] += event.duration
                        if event_end_ts > cb["end"]:
                            cb["end"] = event_end_ts

                    # App level: start new app block if app changes (level 4+)
                    if detail_level >= 4:
                        if app_name != current_slot["_cur_app"]:
                            new_app_block = {
                                "app": app_name,
                                "duration": event.duration,
                                "start": event_ts,
                                "end": event_end_ts,
                                "titles": [],
                            }
                            current_slot["_cur_cat_block"]["apps"].append(new_app_block)
                            current_slot["_cur_app"] = app_name
                            current_slot["_cur_app_block"] = new_app_block
                            current_slot["_cur_title"] = None
                            current_slot["_cur_title_entry"] = None
                        else:
                            # Same app: update the current app block
                            ab = current_slot["_cur_app_block"]
                            ab["duration"] += event.duration
                            if event_end_ts > ab["end"]:
                                ab["end"] = event_end_ts

                        # Title level: start new title entry if title changes (level 5+)
                        if window_title and detail_level >= 5:
                            normalized_title = normalize_title(window_title)
                            clean_title = sanitize_title(normalized_title)

                            if clean_title != current_slot["_cur_title"]:
                                new_title_entry = {
                                    "title": clean_title,
                                    "duration": event.duration,
                                    "events": [
                                        {"start": event_ts, "end": event_end_ts}
                                    ],
                                }
                                current_slot["_cur_app_block"]["titles"].append(
                                    new_title_entry
                                )
                                current_slot["_cur_title"] = clean_title
                                current_slot["_cur_title_entry"] = new_title_entry
                            else:
                                # Same title: add event to current title entry
                                te = current_slot["_cur_title_entry"]
                                te["duration"] += event.duration
                                te["events"].append(
                                    {"start": event_ts, "end": event_end_ts}
                                )

        # Create final slots from collected (project, task) continuity groups
        for slot_data in slots_in_period:
            events = slot_data["events"]
            # Convert UTC timestamps to local time
            event_starts = [e["event"].timestamp.astimezone() for e in events]
            event_ends = [
                (e["event"].timestamp + e["event"].duration).astimezone()
                for e in events
            ]
            slot_start = min(event_starts)
            slot_end = max(event_ends)
            slot_duration = sum((e["event"].duration for e in events), timedelta(0))

            # Build nested category structure: {category, duration, start, end, apps: [{app, duration, start, end, titles}]}
            if deduplicate_categories:
                # OLD PATH: Convert dict to list (deduplicated)
                categories_list = []
                # Sort categories by start time (chronological order)
                for cat, cat_data in sorted(
                    slot_data["categories"].items(), key=lambda x: x[1].get("start", "")
                ):
                    cat_info = {
                        "category": cat,
                        "duration": cat_data["duration"],
                        "start": cat_data.get("start"),
                        "end": cat_data.get("end"),
                    }
                    if detail_level >= 4 and cat_data["apps"]:
                        # Sort apps by start time (chronological order)
                        cat_info["apps"] = [
                            {
                                "app": app_name,
                                "duration": app_data["duration"],
                                "start": app_data.get("start"),
                                "end": app_data.get("end"),
                                "titles": (
                                    [
                                        {
                                            "title": t,
                                            "duration": title_data["duration"],
                                            "events": title_data.get("events")
                                            if isinstance(title_data, dict)
                                            else None,
                                        }
                                        for t, title_data in sorted(
                                            app_data["titles"].items(),
                                            key=lambda x: (x[1].get("events") or [{}])[
                                                0
                                            ].get("start")
                                            if isinstance(x[1], dict)
                                            else x[1],
                                        )
                                    ]
                                    if detail_level >= 5
                                    else []
                                ),
                            }
                            for app_name, app_data in sorted(
                                cat_data["apps"].items(),
                                key=lambda x: x[1].get("start", ""),
                            )
                        ]
                    categories_list.append(cat_info)
            else:
                # NEW PATH: Categories already in list form (timeline order)
                # Just clean up internal tracking fields
                categories_list = slot_data["categories"]
                for k in (
                    "_cur_cat",
                    "_cur_cat_block",
                    "_cur_app",
                    "_cur_app_block",
                    "_cur_title",
                    "_cur_title_entry",
                ):
                    slot_data.pop(k, None)

            productive_in_slot = sum(
                (
                    window_event_productive_duration(e["event"], cat_score_map)
                    for e in events
                ),
                timedelta(0),
            )
            # Extract tags from TW task event (if available)
            task_tags = []
            if events:
                active_task_event = events[0].get("active_task")
                if active_task_event is not None:
                    raw_tags = active_task_event.data.get("tags", [])
                    task_tags = (
                        [raw_tags] if isinstance(raw_tags, str) else list(raw_tags)
                    )

            slot = {
                "type": "regular",
                "start": slot_start,
                "end": slot_end,
                "duration": slot_duration,
                "productive_duration": productive_in_slot,
                "project": slot_data["project"],
                "task": slot_data["task"],
                "afk_period_start": afk_event.timestamp,
                "afk_period_end": afk_event.timestamp + afk_event.duration,
                "tags": task_tags,
            }
            if detail_level >= 3 and categories_list:
                slot["categories"] = categories_list

            slots.append(slot)

    # Sort slots by start time
    slots = sorted(slots, key=lambda s: s["start"])
    return slots


def _slots_overlap(slot_a: Dict, slot_b: Dict) -> bool:
    """Check if two time slots have overlapping time ranges."""
    return slot_a["start"] < slot_b["end"] and slot_b["start"] < slot_a["end"]


def consolidate_timeline_slots(
    slots: List[Dict], ignore_offline: bool = False
) -> List[Dict]:
    """Consolidate timeline slots by merging all sessions of the same task on same date.

    For consolidated timesheet display, merges slots (regular and AFK) that belong to the
    same (date, project, task) into a single entry. By default, OFFLINE entries act as
    group separators (breaking consolidation). AFK slots are absorbed as afk_duration.

    Args:
        slots: List of slot dicts (may include type="offline" entries)
        ignore_offline: If True, OFFLINE entries are dropped and consolidation spans gaps.
                       If False (default), OFFLINE breaks consolidation groups.

    For example (default behavior):
      Task A (12:26-12:29) + [OFFLINE] + Task A (12:30-13:00)
    Shows as:
      Task A (12:26-12:29)    [separate, ends before offline]
      [OFFLINE]               [gap marker]
      Task A (12:30-13:00)    [separate, after offline]

    With ignore_offline=True:
      Task A (12:26-12:29) + [OFFLINE] + Task A (12:30-13:00) + [AFK] + Task A (13:30-15:00)
    Shows as:
      Task A (12:26-15:00)    [merged across offline and afk]

    If another task interrupts, sequences remain separate:
      Task A (12:26-12:29) + Task B (12:30-13:00) + Task A (13:30-15:00)
    Shows as:
      Task A (12:26-12:29)    [separate]
      Task B (12:30-13:00)    [interrupt]
      Task A (13:30-15:00)    [separate]
    """
    if not slots:
        return slots

    consolidated = []
    current_group: List[Dict] = []

    def flush() -> None:
        if current_group:
            consolidated.append(_merge_slot_group(current_group))
            current_group.clear()

    for slot in slots:
        if slot.get("type") == "offline":
            flush()  # Close any open group
            if not ignore_offline:
                consolidated.append(slot)  # Pass OFFLINE through
            continue

        if not current_group:
            current_group.append(slot)
            continue

        # Check if slot belongs to current group
        same_project_task_date = (
            slot["project"] == current_group[0]["project"]
            and slot["task"] == current_group[0]["task"]
            and slot["start"].date() == current_group[0]["start"].date()
        )

        if same_project_task_date:
            current_group.append(slot)
        else:
            flush()
            current_group.append(slot)

    flush()
    return consolidated


def _merge_slot_group(group: List[Dict]) -> Dict:
    """Merge a group of consecutive slots into a single consolidated slot.

    Updates both the time window (to span first start to maximum end) and the
    actual duration (sum of all individual durations). Tracks AFK time if present.
    """
    first = group[0]

    # Calculate time window: from earliest start to latest end
    # Use max() to find the actual maximum end time, not just the last slot
    time_window_start = first["start"]
    time_window_end = max(
        s["start"] + s.get("actual_duration", s["duration"]) for s in group
    )
    time_window = time_window_end - time_window_start

    # Calculate actual duration: sum of all work times
    actual_duration = sum(
        (s.get("actual_duration", s["duration"]) for s in group), timedelta(0)
    )
    productive_duration = sum(
        (s.get("productive_duration", timedelta(0)) for s in group), timedelta(0)
    )

    # Track AFK duration: sum of all AFK slots in this group
    afk_duration = sum(
        (s.get("duration", timedelta(0)) for s in group if s.get("type") == "afk"),
        timedelta(0),
    )

    # Track OFFLINE extension duration: sum of all offline_extension slots in this group
    offline_extension_duration = sum(
        (
            s.get("duration", timedelta(0))
            for s in group
            if s.get("type") == "offline_extension"
        ),
        timedelta(0),
    )

    # Merge categories from all slots (nested with apps and titles)
    # Include ALL slot categories (AFK, offline, regular) to show complete activity picture
    _merged_cats: Dict[str, Dict] = {}
    for s in group:
        for cat_info in s.get("categories", []):
            cat = cat_info["category"]
            if cat not in _merged_cats:
                _merged_cats[cat] = {
                    "duration": timedelta(0),
                    "start": cat_info.get("start"),
                    "end": cat_info.get("end"),
                    "apps": {},
                }
            else:
                # Update start/end to expand range across all slots in group
                cat_start = cat_info.get("start")
                cat_end = cat_info.get("end")
                if cat_start and (
                    not _merged_cats[cat]["start"]
                    or cat_start < _merged_cats[cat]["start"]
                ):
                    _merged_cats[cat]["start"] = cat_start
                if cat_end and (
                    not _merged_cats[cat]["end"] or cat_end > _merged_cats[cat]["end"]
                ):
                    _merged_cats[cat]["end"] = cat_end

            _merged_cats[cat]["duration"] += cat_info["duration"]

            # Merge apps nested under category
            for app_info in cat_info.get("apps", []):
                app = app_info["app"]
                if app not in _merged_cats[cat]["apps"]:
                    _merged_cats[cat]["apps"][app] = {
                        "duration": timedelta(0),
                        "start": app_info.get("start"),
                        "end": app_info.get("end"),
                        "titles": {},
                    }
                else:
                    # Update start/end to expand range
                    app_start = app_info.get("start")
                    app_end = app_info.get("end")
                    if app_start and (
                        not _merged_cats[cat]["apps"][app]["start"]
                        or app_start < _merged_cats[cat]["apps"][app]["start"]
                    ):
                        _merged_cats[cat]["apps"][app]["start"] = app_start
                    if app_end and (
                        not _merged_cats[cat]["apps"][app]["end"]
                        or app_end > _merged_cats[cat]["apps"][app]["end"]
                    ):
                        _merged_cats[cat]["apps"][app]["end"] = app_end

                _merged_cats[cat]["apps"][app]["duration"] += app_info["duration"]

                # Merge titles nested under app
                for title_info in app_info.get("titles", []):
                    t = title_info["title"]
                    title_duration = (
                        title_info.get("duration", timedelta(0))
                        if isinstance(title_info, dict)
                        else title_info
                    )
                    title_start = (
                        title_info.get("start")
                        if isinstance(title_info, dict)
                        else None
                    )
                    title_end = (
                        title_info.get("end") if isinstance(title_info, dict) else None
                    )

                    if t not in _merged_cats[cat]["apps"][app]["titles"]:
                        title_dict = {
                            "duration": title_duration,
                        }
                        # ⚠️ CRITICAL: Copy events list (raw ActivityWatch data, NEVER modified)
                        # Events are preserved as-is through consolidation
                        if isinstance(title_info, dict) and "events" in title_info:
                            title_dict["events"] = title_info["events"]
                        else:
                            title_dict["events"] = []
                        _merged_cats[cat]["apps"][app]["titles"][t] = (
                            title_dict
                            if isinstance(title_info, dict)
                            else title_duration
                        )
                    else:
                        existing = _merged_cats[cat]["apps"][app]["titles"][t]
                        if isinstance(existing, dict):
                            existing["duration"] += title_duration
                            # ⚠️ CRITICAL: Merge events only (raw data, NO modifications)
                            # Extend events list - preserving original ActivityWatch timestamps
                            if isinstance(title_info, dict) and "events" in title_info:
                                if "events" not in existing:
                                    existing["events"] = []
                                existing["events"].extend(title_info["events"])
                        else:
                            # Old format, convert to new
                            _merged_cats[cat]["apps"][app]["titles"][t] = {
                                "duration": existing + title_duration,
                                "events": [],
                            }

    merged_categories = []
    # Sort categories by start time (chronological order)
    for cat, cat_data in sorted(
        _merged_cats.items(), key=lambda x: x[1].get("start", "")
    ):
        cat_info = {
            "category": cat,
            "duration": cat_data["duration"],
            "start": cat_data.get("start"),
            "end": cat_data.get("end"),
        }
        if cat_data["apps"]:
            # Sort apps by start time (chronological order)
            cat_info["apps"] = [
                {
                    "app": app_name,
                    "duration": app_data["duration"],
                    "start": app_data.get("start"),
                    "end": app_data.get("end"),
                    "titles": (
                        [
                            {
                                "title": t,
                                "duration": title_data["duration"]
                                if isinstance(title_data, dict)
                                else title_data,
                                "events": title_data.get("events")
                                if isinstance(title_data, dict)
                                else None,
                            }
                            for t, title_data in sorted(
                                app_data["titles"].items(),
                                key=lambda x: (
                                    str(
                                        (x[1].get("events") or [{}])[0].get("start")
                                        or (
                                            x[1].get("start")
                                            if isinstance(x[1], dict)
                                            else None
                                        )
                                        or "2000-01-01"
                                    )
                                )
                                if isinstance(x[1], dict)
                                else str(x[1]),
                            )
                        ]
                        if app_data["titles"]
                        else []
                    ),
                }
                for app_name, app_data in sorted(
                    cat_data["apps"].items(), key=lambda x: x[1].get("start", "")
                )
            ]

            # App and category start/end are already set from event processing (titles no longer have start/end)

        merged_categories.append(cat_info)

    result = {
        "start": time_window_start,
        "duration": time_window,
        "actual_duration": actual_duration,
        "productive_duration": productive_duration,
        "project": first["project"],
        "task": first["task"],
    }

    if merged_categories:
        result["categories"] = merged_categories

    # Only include afk_duration if there's AFK time
    if afk_duration.total_seconds() > 0:
        result["afk_duration"] = afk_duration

    # Only include offline_extension_duration if there's OFFLINE extension time
    if offline_extension_duration.total_seconds() > 0:
        result["offline_extension_duration"] = offline_extension_duration

    return result


def merge_timeline_slots(slots: List[Dict]) -> List[Dict]:
    """Merge timeline slots by (date, project), combining continuous entries.

    When --detail-level <= 2 is used with --timesheet, collapses multiple entries
    for the same (date, project) into a single merged entry showing:
    - Time window: start of first entry to end of last entry
    - Actual duration: sum of all entries
    This reduces visual noise while preserving actual work duration.
    """
    if not slots:
        return slots

    # Group by (date, project)
    from itertools import groupby

    slots_sorted = sorted(slots, key=lambda s: (s["start"].date(), s["project"]))
    merged_slots = []

    for (slot_date, project), group_iter in groupby(
        slots_sorted, key=lambda s: (s["start"].date(), s["project"])
    ):
        group = list(group_iter)
        if not group:
            continue

        # Calculate the time window (from first start to last end)
        first_start = group[0]["start"]
        last_end = group[-1]["start"] + group[-1]["duration"]
        time_window_duration = last_end - first_start

        # Calculate actual work duration (sum of all durations)
        actual_duration = sum((slot["duration"] for slot in group), timedelta(0))
        productive_duration = sum(
            (slot.get("productive_duration", timedelta(0)) for slot in group),
            timedelta(0),
        )

        # Track AFK duration: sum of all AFK slots in this group
        afk_duration = sum(
            (s.get("duration", timedelta(0)) for s in group if s.get("type") == "afk"),
            timedelta(0),
        )

        # Merge all slots in the group
        merged_slot = {
            "start": first_start,
            "duration": time_window_duration,  # Time span for display calculation
            "actual_duration": actual_duration,  # Actual work time for display
            "productive_duration": productive_duration,
            "project": project,
            "task": group[0]["task"],  # Use first task as representative
            "apps": [],
        }

        # Only include afk_duration if there's AFK time
        if afk_duration.total_seconds() > 0:
            merged_slot["afk_duration"] = afk_duration

        # Combine apps from all slots
        seen_apps = set()
        for slot in group:
            if "apps" in slot:
                for app_info in slot["apps"]:
                    app_key = (app_info["app"], app_info.get("title", ""))
                    if app_key not in seen_apps:
                        merged_slot["apps"].append(app_info)
                        seen_apps.add(app_key)

        merged_slots.append(merged_slot)

    return merged_slots


def _merge_overlapping_events(events: List[Event]) -> List[Event]:
    """Merge overlapping events by taking the union of their time ranges.

    When two events overlap, combine them into a single event covering both periods.
    """
    if not events:
        return events

    # Sort by start time
    sorted_events = sorted(events, key=lambda e: e.timestamp)
    merged = []
    current = sorted_events[0]

    for event in sorted_events[1:]:
        # Check if event overlaps or is adjacent to current
        current_end = current.timestamp + current.duration
        if event.timestamp <= current_end:
            # Overlapping or adjacent: merge by extending current
            new_end = max(current_end, event.timestamp + event.duration)
            current = Event(
                timestamp=current.timestamp,
                duration=new_end - current.timestamp,
                data=current.data,
            )
        else:
            # Non-overlapping: save current and start new
            merged.append(current)
            current = event

    merged.append(current)
    return merged


def generate_gap_entries(
    afk_events: List[Event],
    task_events: Optional[List[Event]],
    offline_threshold_s: float = 120.0,
    window_events: Optional[List[Event]] = None,
) -> List[Dict]:
    """Generate AFK slots and OFFLINE gap markers from AFK bucket events.

    AFK events with status="afk" (user away) are shown as slots, with project/task info
    from overlapping TW tasks (or NO_PROJECT/NO_TASK if no task active).

    Categories from overlapping window events are extracted and attached to AFK slots
    to show what apps/windows were active during AFK periods.

    OFFLINE markers appear for gaps in AFK bucket coverage > threshold (computer off, AW not running).

    Args:
        afk_events: all AFK bucket events (both status="afk" and status="not-afk")
        task_events: TaskWarrior events for resolving active tasks during AFK periods
        offline_threshold_s: gap duration threshold for OFFLINE marker display
        window_events: optional window events to extract categories from for AFK periods

    Returns:
        list of slot dicts with type="afk" or type="offline"
    """
    from aw_transform import filter_keyvals

    result = []

    # Generate AFK slots from explicit status="afk" events
    afk_only_events = filter_keyvals(afk_events, "status", ["afk"])
    # Merge overlapping AFK events to prevent duplicate overlapping slots
    afk_only_events = _merge_overlapping_events(afk_only_events)
    for i, afk_event in enumerate(afk_only_events):
        # Find active TW task during this AFK period (if any)
        active_task = find_active_task(afk_event, task_events) if task_events else None
        if active_task:
            task_name, project = get_task_info(active_task)
        else:
            task_name = NO_TASK
            project = NO_PROJECT

        slot = {
            "type": "afk",
            "start": afk_event.timestamp.astimezone(),
            "end": (afk_event.timestamp + afk_event.duration).astimezone(),
            "duration": afk_event.duration,
            "project": project,
            "task": task_name,
        }

        # Extract categories from overlapping window events if provided
        if window_events:
            afk_start = slot["start"]
            afk_end = slot["end"]
            categories = {}

            for window_event in window_events:
                window_start = window_event.timestamp.astimezone()
                window_end = (
                    window_event.timestamp + window_event.duration
                ).astimezone()

                # Check if window event overlaps with AFK period
                if window_start < afk_end and window_end > afk_start:
                    # Calculate overlap duration
                    overlap_start = max(window_start, afk_start)
                    overlap_end = min(window_end, afk_end)
                    overlap_duration = overlap_end - overlap_start

                    # Extract categories from this window event
                    event_categories = window_event.data.get("$category", [])
                    # Only process if there's actual categorization - don't create fake "Apps > ..." categories
                    # for uncategorized window events during AFK periods

                    for cat in event_categories:
                        if cat not in categories:
                            categories[cat] = {
                                "category": cat,
                                "duration": timedelta(0),
                                "start": overlap_start,
                                "end": overlap_end,
                                "apps": {},
                            }
                        else:
                            # Expand time window (don't accumulate duration here, do it from apps later)
                            cat_data = categories[cat]
                            if overlap_start < cat_data["start"]:
                                cat_data["start"] = overlap_start
                            if overlap_end > cat_data["end"]:
                                cat_data["end"] = overlap_end

                        # Extract app name (window title) if available
                        app_name = window_event.data.get("app", "Unknown")
                        if app_name not in categories[cat]["apps"]:
                            categories[cat]["apps"][app_name] = {
                                "app": app_name,
                                "duration": timedelta(0),
                                "start": overlap_start,
                                "end": overlap_end,
                                "titles": {},
                            }
                        else:
                            app_data = categories[cat]["apps"][app_name]
                            app_data["duration"] += overlap_duration
                            if overlap_start < app_data["start"]:
                                app_data["start"] = overlap_start
                            if overlap_end > app_data["end"]:
                                app_data["end"] = overlap_end

                        # Extract title if available
                        title = window_event.data.get("title", "Unknown")
                        if title not in categories[cat]["apps"][app_name]["titles"]:
                            categories[cat]["apps"][app_name]["titles"][title] = {
                                "title": title,
                                "duration": overlap_duration,
                                "start": overlap_start,
                                "end": overlap_end,
                                "events": [
                                    window_event
                                ],  # Store raw window event for CatPanel
                            }
                        else:
                            title_data = categories[cat]["apps"][app_name]["titles"][
                                title
                            ]
                            title_data["duration"] += overlap_duration
                            if overlap_start < title_data["start"]:
                                title_data["start"] = overlap_start
                            if overlap_end > title_data["end"]:
                                title_data["end"] = overlap_end
                            # Append raw event to events list for CatPanel rendering
                            if "events" not in title_data:
                                title_data["events"] = []
                            title_data["events"].append(window_event)

                        categories[cat]["apps"][app_name]["duration"] += (
                            overlap_duration
                        )

            # Convert categories dict to list format for consistency with regular slots
            merged_categories = []
            for cat, cat_data in categories.items():
                # Compute category duration from sum of app durations (to avoid double-counting)
                cat_duration = sum(
                    (app_data["duration"] for app_data in cat_data["apps"].values()),
                    timedelta(0),
                )

                # Recalculate category start/end from app children's actual times
                # (not from the overall slot span which may include AFK gaps)
                cat_start = None
                cat_end = None
                for app_data in cat_data["apps"].values():
                    app_start = app_data.get("start")
                    app_end = app_data.get("end")
                    if app_start and (cat_start is None or app_start < cat_start):
                        cat_start = app_start
                    if app_end and (cat_end is None or app_end > cat_end):
                        cat_end = app_end

                cat_info = {
                    "category": cat,
                    "duration": cat_duration,
                    "start": cat_start,
                    "end": cat_end,
                }
                if cat_data["apps"]:
                    # Build apps list with recalculated start/end from title children
                    apps_list = []
                    for app_name, app_data in cat_data["apps"].items():
                        # Recalculate app start/end from title children's actual times
                        app_start = None
                        app_end = None
                        for title_data in app_data.get("titles", {}).values():
                            title_start = title_data.get("start")
                            title_end = title_data.get("end")
                            if title_start and (
                                app_start is None or title_start < app_start
                            ):
                                app_start = title_start
                            if title_end and (app_end is None or title_end > app_end):
                                app_end = title_end

                        # If no titles, use the app's existing start/end
                        if app_start is None:
                            app_start = app_data.get("start")
                        if app_end is None:
                            app_end = app_data.get("end")

                        app_info = {
                            "app": app_name,
                            "duration": app_data["duration"],
                            "start": app_start,
                            "end": app_end,
                            "titles": [
                                {
                                    "title": t,
                                    "duration": title_data["duration"],
                                    "start": title_data.get("start"),
                                    "end": title_data.get("end"),
                                    "events": title_data.get(
                                        "events", []
                                    ),  # Include raw events for CatPanel
                                }
                                for t, title_data in app_data["titles"].items()
                            ]
                            if app_data["titles"]
                            else [],
                        }
                        apps_list.append(app_info)

                    cat_info["apps"] = apps_list
                merged_categories.append(cat_info)

            slot["categories"] = merged_categories
        else:
            slot["categories"] = []

        result.append(slot)

    # Generate OFFLINE markers for gaps in AFK bucket coverage
    all_sorted = sorted(afk_events, key=lambda e: e.timestamp)
    for i in range(len(all_sorted) - 1):
        curr_end = all_sorted[i].timestamp + all_sorted[i].duration
        next_start = all_sorted[i + 1].timestamp

        if next_start > curr_end:
            gap_duration = next_start - curr_end
            if gap_duration.total_seconds() > offline_threshold_s:
                offline_entry = {
                    "type": "offline",
                    "start": curr_end.astimezone(),
                    "end": next_start.astimezone(),
                    "duration": gap_duration,
                    "project": "__offline__",
                    "task": "",
                }
                result.append(offline_entry)

    return result


def attach_offline_extensions(slots: List[Dict]) -> List[Dict]:
    """Convert OFFLINE gaps that follow OFFLINE-tagged task slots into offline_extension slots.

    For each regular slot with "offline" tag and an adjacent OFFLINE gap (within 60s),
    transforms the gap into an offline_extension slot that carries the task's project/task info.
    This makes the full task duration (on + offline) visible and attributed to the task.
    """
    TOLERANCE = timedelta(seconds=60)
    for i, slot in enumerate(slots):
        if slot.get("type") != "regular":
            continue
        # Check if task has "offline" tag (case-insensitive)
        tags = [t.lower() for t in slot.get("tags", [])]
        if "offline" not in tags:
            continue
        # Find OFFLINE gap that starts right after this slot
        for j, gap in enumerate(slots):
            if gap.get("type") != "offline":
                continue
            delta_seconds = (gap["start"] - slot["end"]).total_seconds()
            if abs(delta_seconds) <= TOLERANCE.total_seconds():
                # Transform gap into offline_extension carrying task's project/task
                slots[j] = {
                    **gap,
                    "type": "offline_extension",
                    "project": slot["project"],
                    "task": slot["task"],
                }
                break
    return slots


def _render_slot_detail(slot: Dict, detail_level: int, width: int) -> None:
    """Render category/app/title sub-rows for a slot according to detail_level.

    detail_level controls depth:
      1 = Project only          (no sub-rows)
      2 = Project + Task        (no sub-rows)
      3 = + Category
      4 = + App (indented under category)
      5 = + Title (indented under app)

    Note: AFK and OFFLINE slots may have categorized window activity recorded
    during those periods, so we render their details just like regular slots.
    """
    if detail_level >= 3:
        for cat_info in slot.get("categories", []):
            cat_dur_str = format_duration(cat_info["duration"])
            left = " " * 21 + f"- {cat_info['category']}"
            print(left.ljust(width - len(cat_dur_str) - 1) + " " + cat_dur_str)

            # Apps nested under category (level 4+)
            if detail_level >= 4:
                for app_info in cat_info.get("apps", []):
                    app_dur_str = format_duration(app_info["duration"])
                    left = " " * 25 + f"• {app_info['app']}"
                    print(left.ljust(width - len(app_dur_str) - 1) + " " + app_dur_str)

                    # Titles nested under app (level 5+)
                    if detail_level >= 5:
                        for title_info in app_info.get("titles", []):
                            title_dur_str = format_duration(title_info["duration"])
                            clean = truncate_title(title_info["title"], 75)
                            left = " " * 29 + clean
                            print(
                                left.ljust(width - len(title_dur_str) - 1)
                                + " "
                                + title_dur_str
                            )


def print_timeline_report(
    slots: List[Dict],
    period: str,
    start_time: datetime,
    end_time: datetime,
    detail_level: int = 1,
    non_afk_time: timedelta = None,
    productive_time: timedelta = None,
    productive_task_time: timedelta = None,
    first_event_time: datetime = None,
    last_event_time: datetime = None,
    task_based: bool = True,
    distracting_time: timedelta = None,
    unscored_time: timedelta = None,
    rollup: bool = False,
    current_session_start: datetime = None,
    current_session_end: datetime = None,
    current_session_duration: timedelta = None,
    last_break_start: datetime = None,
    last_break_end: datetime = None,
    last_break_duration: timedelta = None,
):
    """Print a timeline report showing activity as continuous time slots with date/week headers and cumulative totals.

    detail_level controls rendering depth:
      1 = Project only
      2 = Project + Task
      3 = Project + Task + Category
      4 = Project + Task + Category + App
      5 = Project + Task + Category + App + Title
    """
    from itertools import groupby

    width = get_terminal_width()
    is_single_day = start_time.date() == end_time.date()
    # Use actual_duration for merged slots, duration for others
    # Exclude AFK and OFFLINE slots from totals (informational only)
    all_regular_slots = [
        s for s in slots if s.get("type") != "afk" and s.get("type") != "offline"
    ]
    # Project-tracked time (excluding "No project assigned")
    tracked_slots = [s for s in all_regular_slots if s.get("project") != NO_PROJECT]

    total_duration = sum(
        (slot.get("actual_duration", slot["duration"]) for slot in tracked_slots),
        timedelta(0),
    )
    total_productive_tracked = sum(
        (slot.get("productive_duration", timedelta(0)) for slot in tracked_slots),
        timedelta(0),
    )

    # Total time including untracked (for "Total Time" display)
    total_time_all = sum(
        (slot.get("actual_duration", slot["duration"]) for slot in all_regular_slots),
        timedelta(0),
    )
    # Total productive time for all slots (including untracked)
    total_productive_all = sum(
        (slot.get("productive_duration", timedelta(0)) for slot in all_regular_slots),
        timedelta(0),
    )

    # Calculate total AFK time
    # Check if slots are consolidated (contain afk_duration field) or regular (type="afk" slots)
    has_consolidated_afk = any(s.get("afk_duration") for s in slots)

    if has_consolidated_afk:
        # Consolidated slots: AFK time is in afk_duration field
        total_afk_time = sum(
            (slot.get("afk_duration", timedelta(0)) for slot in slots),
            timedelta(0),
        )
    else:
        # Regular slots: AFK time is in type="afk" slots
        afk_slots = [s for s in slots if s.get("type") == "afk"]
        total_afk_time = sum(
            (slot.get("actual_duration", slot["duration"]) for slot in afk_slots),
            timedelta(0),
        )

    # Print shared header using common utility function (note: timeline doesn't print total_score)
    print_report_header(
        title=" Timeline Report ",
        period=period,
        start_time=start_time,
        end_time=end_time,
        total_duration=total_duration,
        task_based=task_based,
        non_afk_time=non_afk_time,
        productive_time=productive_time,
        productive_task_time=productive_task_time,
        first_event_time=first_event_time,
        last_event_time=last_event_time,
        distracting_time=distracting_time,
        unscored_time=unscored_time,
        current_session_start=current_session_start,
        current_session_end=current_session_end,
        current_session_duration=current_session_duration,
        last_break_start=last_break_start,
        last_break_end=last_break_end,
        last_break_duration=last_break_duration,
        total_time_all=total_time_all,
        afk_time=total_afk_time,
    )

    if not slots:
        print("No activity found for the specified period.")
        print("=" * width)
        return

    # Print column header
    print("Wk  Date       Day")

    # Group slots by (iso_week_key, date)
    def slot_week_key(slot):
        """Return ISO week key: 'YYYY-Www' (e.g., '2026-W17')"""
        return slot["start"].strftime("%G-W%V")

    def slot_date(slot):
        """Return slot date"""
        return slot["start"].date()

    # Sort slots by start time
    slots = sorted(slots, key=lambda s: s["start"])

    # Group by week, then by date within week
    current_week_key = None
    current_date = None
    week_duration = timedelta(0)
    day_duration = timedelta(0)
    week_productive = timedelta(0)
    day_productive = timedelta(0)
    week_afk_duration = timedelta(0)
    day_afk_duration = timedelta(0)

    # Build list of (project, date, slots) for consecutive same-project same-date runs
    # OFFLINE slots are singleton groups (project="__offline__") to break up regular grouping
    slot_groups = []
    current_project_group = None
    current_project_group_project = None
    current_project_group_date = None

    for slot in slots:
        slot_date_val = slot_date(slot)
        slot_project = slot.get("project") or "__offline__"

        # OFFLINE slots always break grouping (they're singletons)
        if slot_project == "__offline__":
            # Finalize current group if any
            if current_project_group is not None:
                slot_groups.append(
                    (
                        current_project_group_project,
                        current_project_group_date,
                        current_project_group,
                    )
                )
                current_project_group = None
            # Add OFFLINE slot as singleton group
            slot_groups.append(("__offline__", slot_date_val, [slot]))
            current_project_group_project = None
            current_project_group_date = None
            continue

        if (
            slot_project != current_project_group_project
            or slot_date_val != current_project_group_date
        ):
            if current_project_group is not None:
                slot_groups.append(
                    (
                        current_project_group_project,
                        current_project_group_date,
                        current_project_group,
                    )
                )
            current_project_group_project = slot_project
            current_project_group_date = slot_date_val
            current_project_group = [slot]
        else:
            current_project_group.append(slot)

    if current_project_group is not None:
        slot_groups.append(
            (
                current_project_group_project,
                current_project_group_date,
                current_project_group,
            )
        )

    # Pre-compute total slot entries per date to decide rollup per day
    date_total_entries = {}
    for gp, gd, gs in slot_groups:
        date_total_entries[gd] = date_total_entries.get(gd, 0) + len(gs)

    # Rollup state: track whether prev day was rolled up to skip its day total
    prev_date_was_rollup = False
    pending_date_prefix = None  # Date header held until we know if we render inline

    # Now process each group
    for group_project, group_date, group_slots in slot_groups:
        # Sort slots chronologically; secondary key by end time for same-second starts
        group_slots = sorted(
            group_slots,
            key=lambda s: (
                s["start"],
                s["start"] + s.get("actual_duration", s["duration"]),
            ),
        )
        slot_week = group_slots[0]["start"].strftime("%G-W%V")

        # Check if this is an OFFLINE group (singleton, informational only)
        is_offline_group = group_project == "__offline__"

        # Rollup: collapse to inline when exactly one slot entry for this day (exclude OFFLINE)
        group_is_rollup = (
            rollup
            and date_total_entries.get(group_date, 0) == 1
            and not is_offline_group
        )

        if slot_week != current_week_key:
            # Week changed: print previous week's closing totals
            if current_week_key is not None:
                print(("-" * 22).rjust(width))
                if not prev_date_was_rollup:
                    print(
                        (
                            "Day total:   "
                            + format_duration_tracked_prod(day_duration, day_productive)
                        ).rjust(width)
                    )
                if not is_single_day:
                    print(
                        (
                            "Week total (tracked):  "
                            + format_duration_tracked_prod(
                                week_duration, week_productive
                            )
                        ).rjust(width)
                    )
                print()
            current_week_key = slot_week
            week_number = group_slots[0]["start"].isocalendar()[1]
            week_str = f"W{week_number}"
            date_str = group_date.strftime("%Y-%m-%d")
            day_str = group_date.strftime("%a")
            pending_date_prefix = f"{week_str} {date_str} {day_str}"
            current_date = group_date
            week_duration = timedelta(0)
            day_duration = timedelta(0)
            week_productive = timedelta(0)
            day_productive = timedelta(0)
            week_afk_duration = timedelta(0)
            day_afk_duration = timedelta(0)
            prev_date_was_rollup = False
        elif group_date != current_date:
            # Date changed within same week: close previous day
            if not prev_date_was_rollup:
                print(("-" * 22).rjust(width))
                total_day_with_afk = day_duration + day_afk_duration
                print(
                    (
                        "Day total:   "
                        + format_duration_tracked_prod(
                            total_day_with_afk, day_productive
                        )
                    ).rjust(width)
                )
                print()
            day_duration = timedelta(0)
            day_productive = timedelta(0)
            day_afk_duration = timedelta(0)
            date_str = group_date.strftime("%Y-%m-%d")
            day_str = group_date.strftime("%a")
            # Align same-week dates: 4 spaces + date + day = 18 chars (matches week header width)
            pending_date_prefix = f"    {date_str} {day_str}"
            current_date = group_date

        # Flush pending date header for non-rollup days before printing the group
        if pending_date_prefix is not None and not group_is_rollup:
            print(pending_date_prefix)
            pending_date_prefix = None

        # Handle OFFLINE groups specially (informational only, not included in totals)
        if is_offline_group:
            offline_slot = group_slots[0]
            offline_dur = format_duration(offline_slot["duration"])
            indent = " " * 22  # Position to align with where descriptions start
            offline_label = "OFF"
            remaining_width = (
                width - len(indent) - len(offline_label) - len(offline_dur) - 25
            )
            filler = " " * max(remaining_width, 0)
            print(indent + filler + "(" + offline_dur + " " + offline_label + ")")
            # OFFLINE slots are NOT added to day_duration or week_duration
            continue

        # Calculate project group totals
        project_name = group_project.replace(".", " > ")
        group_start = group_slots[0]["start"]
        group_end = max(s["start"] + s["duration"] for s in group_slots)
        group_total_duration = sum(
            (s.get("actual_duration", s["duration"]) for s in group_slots), timedelta(0)
        )
        group_productive_duration = sum(
            (s.get("productive_duration", timedelta(0)) for s in group_slots),
            timedelta(0),
        )
        # Track AFK duration from consolidated slots
        group_afk_duration = sum(
            (s.get("afk_duration", timedelta(0)) for s in group_slots),
            timedelta(0),
        )
        start_str = group_start.strftime("%H:%M")
        end_str = group_end.strftime("%H:%M")
        duration_str = format_duration_with_afk(
            group_total_duration, group_productive_duration, group_afk_duration
        )

        if detail_level == 1:
            # Level 1: Project only — collapse entire (date, project) group to one line
            content = f"▶ {project_name}"
            if group_is_rollup:
                left = f"{pending_date_prefix}  {start_str}-{end_str}  {content}"
                print(format_timeline_line(left, duration_str, max_left_width=95))
                pending_date_prefix = None
            else:
                if pending_date_prefix is not None:
                    print(pending_date_prefix)
                    pending_date_prefix = None
                left = f"             {start_str}  {content}"
                print(format_timeline_line(left, duration_str, max_left_width=95))

        elif group_is_rollup:
            # Single-entry day: date + time on same line with project ▶▶ task
            # (Skip rollup for AFK slots — they display as regular slots)
            slot = group_slots[0]
            if slot.get("type") != "afk":
                task_name = slot["task"]
                abbrev_project = abbreviate_project_path(project_name, task_name)
                content = f"▶ {abbrev_project} ▶▶ {task_name}"
                left = f"{pending_date_prefix}  {start_str}-{end_str}  {content}"
                print(format_timeline_line(left, duration_str, max_left_width=95))
                pending_date_prefix = None
                _render_slot_detail(slot, detail_level, width)
            else:
                # AFK slot on rollup day: render as regular slot
                group_is_rollup = False
                if pending_date_prefix is not None:
                    print(pending_date_prefix)
                    pending_date_prefix = None
                s_start = slot["start"].strftime("%H:%M")
                s_end = (slot["start"] + slot["duration"]).strftime("%H:%M")
                slot_duration = slot.get("actual_duration", slot["duration"])
                slot_dur_str = format_afk_label(slot_duration)
                task_name = slot["task"]
                abbrev_project = abbreviate_project_path(project_name, task_name)
                content = f"▶ {abbrev_project} ▶▶ {task_name}"
                left = f"      *{s_start}-{s_end}   {content}"
                print(
                    format_timeline_line(
                        left, duration_str=slot_dur_str, max_left_width=95
                    )
                )
                # Render AFK slot details (categories/apps/titles)
                _render_slot_detail(slot, detail_level, width)

        else:
            # Multi-entry day: date header, then indented slot rows
            if pending_date_prefix is not None:
                print(pending_date_prefix)
                pending_date_prefix = None

            if len(group_slots) == 1:
                # Single slot for this project today — show inline
                slot = group_slots[0]
                task_name = slot["task"]
                abbrev_project = abbreviate_project_path(project_name, task_name)
                content = f"▶ {abbrev_project} ▶▶ {task_name}"
                if slot.get("type") == "afk":
                    slot_dur_str = format_afk_label(
                        slot.get("actual_duration", slot["duration"])
                    )
                    left = f"      *{start_str}-{end_str}   {content}"
                elif slot.get("type") == "offline_extension":
                    slot_dur_str = format_offline_label(
                        slot.get("actual_duration", slot["duration"])
                    )
                    left = f"      *{start_str}-{end_str}   {content}"
                else:
                    left = f"       {start_str}-{end_str}  {content}"
                    # Use format_duration_with_gaps if offline extensions present
                    if slot.get("offline_extension_duration"):
                        slot_dur_str = format_duration_with_gaps(
                            slot.get("actual_duration", slot["duration"]),
                            slot.get("productive_duration", timedelta(0)),
                            slot.get("afk_duration"),
                            slot.get("offline_extension_duration"),
                        )
                    else:
                        slot_dur_str = format_duration_with_afk(
                            slot.get("actual_duration", slot["duration"]),
                            slot.get("productive_duration", timedelta(0)),
                            slot.get("afk_duration"),
                        )
                print(
                    format_timeline_line(
                        left, duration_str=slot_dur_str, max_left_width=95
                    )
                )
                _render_slot_detail(slot, detail_level, width)
            else:
                # Multiple slots for this project today — one row each
                for slot in group_slots:
                    s_start = slot["start"].strftime("%H:%M")
                    s_end = (slot["start"] + slot["duration"]).strftime("%H:%M")
                    slot_duration = slot.get("actual_duration", slot["duration"])
                    task_name = slot["task"]
                    abbrev_project = abbreviate_project_path(project_name, task_name)
                    content = f"▶ {abbrev_project} ▶▶ {task_name}"

                    if slot.get("type") == "afk":
                        slot_dur_str = format_afk_label(slot_duration)
                        left = f"      *{s_start}-{s_end}  {content}"
                    elif slot.get("type") == "offline_extension":
                        slot_dur_str = format_offline_label(slot_duration)
                        left = f"      *{s_start}-{s_end}  {content}"
                    else:
                        # Use format_duration_with_gaps if offline extensions present
                        if slot.get("offline_extension_duration"):
                            slot_dur_str = format_duration_with_gaps(
                                slot_duration,
                                slot.get("productive_duration", timedelta(0)),
                                slot.get("afk_duration"),
                                slot.get("offline_extension_duration"),
                            )
                        else:
                            slot_dur_str = format_duration_with_afk(
                                slot_duration,
                                slot.get("productive_duration", timedelta(0)),
                                slot.get("afk_duration"),
                            )
                        left = f"       {s_start}-{s_end}  {content}"

                    print(
                        format_timeline_line(
                            left, duration_str=slot_dur_str, max_left_width=95
                        )
                    )
                    _render_slot_detail(slot, detail_level, width)

        # Accumulate totals for all slot types
        # Regular slots (non-AFK/OFFLINE)
        group_regular_duration = sum(
            (
                s.get("actual_duration", s["duration"])
                for s in group_slots
                if s.get("type") not in ("afk", "offline")
            ),
            timedelta(0),
        )
        group_regular_productive = sum(
            (
                s.get("productive_duration", timedelta(0))
                for s in group_slots
                if s.get("type") not in ("afk", "offline")
            ),
            timedelta(0),
        )
        # AFK slots
        group_afk_duration = sum(
            (
                s.get("actual_duration", s["duration"])
                for s in group_slots
                if s.get("type") == "afk"
            ),
            timedelta(0),
        )
        day_duration += group_regular_duration
        week_duration += group_regular_duration
        day_productive += group_regular_productive
        week_productive += group_regular_productive
        day_afk_duration += group_afk_duration
        week_afk_duration += group_afk_duration
        prev_date_was_rollup = group_is_rollup

    # Print final totals
    if slots:
        print(("-" * 22).rjust(width))
        if not prev_date_was_rollup:
            total_day_with_afk = day_duration + day_afk_duration
            print(
                (
                    "Day total:   "
                    + format_duration_tracked_prod(total_day_with_afk, day_productive)
                ).rjust(width)
            )
        total_week_with_afk = week_duration + week_afk_duration
        if not is_single_day:
            print(
                (
                    "Week total (tracked):  "
                    + format_duration_tracked_prod(total_week_with_afk, week_productive)
                ).rjust(width)
            )
        print()

    # Display "Total Time" as all time (project-tracked + untracked + AFK)
    # Note: In consolidated mode, AFK time is already included in total_time_all,
    # so we only add it in regular (non-consolidated) mode
    total_time_final = (
        total_time_all + total_afk_time if not has_consolidated_afk else total_time_all
    )
    print(
        (
            "Total Time: "
            + format_duration_tracked_prod(total_time_final, total_productive_all)
        ).rjust(width)
    )
    print("=" * width)


# --- Main Execution ---


def parse_positional_args(args_list: List[str]) -> tuple:
    """Parse positional arguments to separate period from search terms.

    Period specifications:
    - Start with ':' (e.g., :today, :week)
    - Or are ISO dates (e.g., 2026-05-06, 2026-05-06T10:00)
    Other arguments are treated as search/filter terms.

    Returns: (period, search_term)
    """
    period = ":today"  # Default
    search_term = None

    if not args_list:
        return period, search_term

    # Regex to match ISO dates (YYYY-MM-DD with optional time)
    iso_date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}(T| |$)")

    # Find period (starts with ':' or is an ISO date)
    period_args = [
        arg for arg in args_list if arg.startswith(":") or iso_date_pattern.match(arg)
    ]
    if period_args:
        period = period_args[0]  # Use first period specification

    # Find search terms (everything that's not a period)
    search_terms = [
        arg
        for arg in args_list
        if not arg.startswith(":") and not iso_date_pattern.match(arg)
    ]
    if search_terms:
        search_term = search_terms[0]  # Use first search term as the main one

    return period, search_term


def main():
    """Main script logic."""
    args = parse_args()
    client = ActivityWatchClient("tw-report")

    # Parse positional arguments to separate period from search term
    period, search_term = parse_positional_args(args.args)
    args.search = (
        search_term  # Set search term from positional args (None if not provided)
    )

    start_time, end_time = parse_period(period)
    categories_json = load_categories(args.categories)
    compiled_categories, cat_score_map = compile_category_rules(categories_json)

    window_bucket = get_bucket_id("window")
    window_events = get_events(client, window_bucket, start_time, end_time)

    # Categorize all window events (including those during AFK periods)
    # This ensures generate_gap_entries can extract categories for AFK slot details
    for event in window_events:
        categorize_event(event, compiled_categories)

    # Fetch AFK events (needed for filtering AFK time or for --timesheet)
    afk_bucket = get_bucket_id("afk")
    afk_events = get_events(client, afk_bucket, start_time, end_time)

    # Merge any overlapping not-afk periods (data quality fix)
    afk_events = merge_overlapping_afk_periods(afk_events)

    # Calculate non-afk time for metrics
    not_afk_events = filter_keyvals(afk_events, "status", ["not-afk"])
    non_afk_time = sum((event.duration for event in not_afk_events), timedelta(0))

    # Calculate current session and last break metrics
    current_session_start = None
    current_session_end = None
    current_session_duration = None
    last_break_start = None
    last_break_end = None
    last_break_duration = None

    if not_afk_events:
        # Sort not-afk events by their end time to find the most recent
        sorted_not_afk = sorted(not_afk_events, key=lambda e: e.timestamp + e.duration)

        # Current session: the most recent not-afk event (latest end time)
        last_event = sorted_not_afk[-1]
        current_session_start = last_event.timestamp.astimezone()
        current_session_end = (last_event.timestamp + last_event.duration).astimezone()
        current_session_duration = last_event.duration

        # Last break: find the most recent non-overlapping event before current session
        # (handles overlapping not-afk periods gracefully)
        last_event_start = last_event.timestamp
        non_overlapping_ends = [
            event.timestamp + event.duration
            for event in sorted_not_afk
            if event.timestamp + event.duration <= last_event_start
        ]
        if non_overlapping_ends:
            previous_end = max(non_overlapping_ends)
            current_start = last_event_start

            # Break is the gap between previous end and current start
            if current_start > previous_end:
                last_break_start = previous_end.astimezone()
                last_break_end = current_start.astimezone()
                last_break_duration = current_start - previous_end

    task_events = None
    is_task_based_report = not args.no_taskwarrior

    if is_task_based_report:
        task_bucket = get_bucket_id("taskwarrior")
        task_events = get_events(client, task_bucket, start_time, end_time)
        if not task_events:
            task_events = None
            is_task_based_report = False

    # Calculate metrics (used by both report types)
    first_event_time = None
    last_event_time = None
    if not_afk_events:
        first_event_time = min(event.timestamp.astimezone() for event in not_afk_events)
        last_event_time = max(
            (event.timestamp + event.duration).astimezone() for event in not_afk_events
        )

    canonical_events = build_canonical_events(
        window_events=window_events,
        not_afk_events=not_afk_events,
        include_afk=args.include_afk,
        task_events=task_events,
        args=args,
        no_project_label=NO_PROJECT,
        no_task_label=NO_TASK,
        categorize_event=categorize_event,
        compiled_categories=compiled_categories,
        get_category_score=get_category_score,
        cat_score_map=cat_score_map,
        find_active_task=find_active_task,
        get_task_info=get_task_info,
        matches_any=_matches_any,
        excluded=_excluded,
    )

    # Collect and aggregate OFFLINE task events (tagged "offline")
    # For each (project, task) pair with OFFLINE tag, calculate duration as
    # the span from the earliest start to the latest end across all events.
    offline_task_durations: Dict[Tuple[str, str], timedelta] = {}
    if task_events:
        offline_events_by_key: Dict[Tuple[str, str], List[Event]] = {}
        for event in task_events:
            if task_has_offline_tag(event):
                task_name, project = get_task_info(event)
                key = (project, task_name)
                if key not in offline_events_by_key:
                    offline_events_by_key[key] = []
                offline_events_by_key[key].append(event)

        # Calculate actual duration for each OFFLINE task (sum of sandwiched sessions)
        # A session = Event1 + Gap + Event2, sandwiched if no other tasks/interruptions
        for key, events in offline_events_by_key.items():
            sorted_events = sorted(events, key=lambda e: e.timestamp)

            total_offline_time = timedelta(0)
            valid_sessions = []

            # Process each pair of consecutive events
            for i in range(len(sorted_events) - 1):
                event1 = sorted_events[i]
                event2 = sorted_events[i + 1]

                event1_end = event1.timestamp + event1.duration
                gap_start = event1_end
                gap_end = event2.timestamp
                session_start = event1.timestamp
                session_end = event2.timestamp + event2.duration

                gap = gap_end - gap_start
                session_duration = event1.duration + gap + event2.duration

                # Check if any OTHER tasks were active during this entire session
                other_task_active = False
                for other_event in task_events:
                    other_key = (
                        get_task_info(other_event)[1],
                        get_task_info(other_event)[0],
                    )
                    if other_key == key:  # Skip events from this same task
                        continue
                    # Check if other task overlaps with session
                    if (
                        other_event.timestamp < session_end
                        and other_event.timestamp + other_event.duration > session_start
                    ):
                        other_task_active = True
                        break

                # Check if there are unassigned window events during the gap
                unassigned_window_active = False
                for window_event in window_events:
                    # Check if window event overlaps with gap
                    if (
                        window_event.timestamp < gap_end
                        and window_event.timestamp + window_event.duration > gap_start
                    ):
                        # This window event is during the gap - check if it has a task
                        has_task = False
                        for task_event in task_events:
                            if (
                                task_event.timestamp
                                < window_event.timestamp + window_event.duration
                                and task_event.timestamp + task_event.duration
                                > window_event.timestamp
                            ):
                                has_task = True
                                break
                        if not has_task:
                            unassigned_window_active = True
                            break

                # Only add this session if no other task was active AND no unassigned window events in gap
                if not other_task_active and not unassigned_window_active:
                    total_offline_time += session_duration
                    valid_sessions.append((i, session_duration))

            offline_task_durations[key] = total_offline_time

            # Debug: show which sessions were valid for this task
            if os.environ.get("DEBUG_OFFLINE"):
                project, task_name = key
                print(
                    f"\n[DEBUG] OFFLINE task: {project} > {task_name}", file=sys.stderr
                )
                print(
                    f"[DEBUG] Found {len(sorted_events)} raw task event(s):",
                    file=sys.stderr,
                )
                for i, e in enumerate(sorted_events, 1):
                    e_start = e.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                    e_end = (
                        (e.timestamp + e.duration)
                        .astimezone()
                        .strftime("%Y-%m-%d %H:%M:%S")
                    )
                    e_duration = e.duration.total_seconds()
                    print(
                        f"[DEBUG]   Event {i}: {e_start} to {e_end} ({e_duration:.0f}s)",
                        file=sys.stderr,
                    )

                # Show all sessions with validation
                print(f"[DEBUG] Sessions (Event + Gap + Event):", file=sys.stderr)
                for i in range(len(sorted_events) - 1):
                    event1 = sorted_events[i]
                    event2 = sorted_events[i + 1]
                    event1_end = event1.timestamp + event1.duration
                    session_start = event1.timestamp
                    session_end = event2.timestamp + event2.duration
                    gap = event2.timestamp - event1_end
                    session_duration = event1.duration + gap + event2.duration

                    # Check validation
                    other_task_active = False
                    for other_event in task_events:
                        other_key = (
                            get_task_info(other_event)[1],
                            get_task_info(other_event)[0],
                        )
                        if other_key == key:
                            continue
                        if (
                            other_event.timestamp < session_end
                            and other_event.timestamp + other_event.duration
                            > session_start
                        ):
                            other_task_active = True
                            break

                    unassigned_window_active = False
                    for window_event in window_events:
                        if (
                            window_event.timestamp < event2.timestamp
                            and window_event.timestamp + window_event.duration
                            > event1_end
                        ):
                            has_task = False
                            for task_event in task_events:
                                if (
                                    task_event.timestamp
                                    < window_event.timestamp + window_event.duration
                                    and task_event.timestamp + task_event.duration
                                    > window_event.timestamp
                                ):
                                    has_task = True
                                    break
                            if not has_task:
                                unassigned_window_active = True
                                break

                    status = ""
                    if other_task_active:
                        status = " [EXCLUDED: OTHER TASK]"
                    elif unassigned_window_active:
                        status = " [EXCLUDED: UNASSIGNED WINDOW]"
                    else:
                        status = " [VALID]"

                    dur_str = f"{session_duration.total_seconds() / 3600:.1f}h"
                    print(
                        f"[DEBUG]   Session {i + 1}: Event{i + 1} + Gap + Event{i + 2} = {dur_str}{status}",
                        file=sys.stderr,
                    )

                print(
                    f"[DEBUG] Total offline time: {offline_task_durations[key]}",
                    file=sys.stderr,
                )

    # Exclude window events correlated with OFFLINE tasks — their time comes from
    # the raw task event duration, not from window activity.
    if offline_task_durations:
        canonical_events = [
            rep
            for rep in canonical_events
            if rep.active_task is None or not task_has_offline_tag(rep.active_task)
        ]

    metrics = compute_metrics(
        canonical_events=canonical_events,
        cat_score_map=cat_score_map,
        get_category_score=get_category_score,
        non_afk_time=non_afk_time,
        first_event_time=first_event_time,
        last_event_time=last_event_time,
        current_session_start=current_session_start,
        current_session_end=current_session_end,
        current_session_duration=current_session_duration,
        last_break_start=last_break_start,
        last_break_end=last_break_end,
        last_break_duration=last_break_duration,
    )
    context = build_context(
        canonical_events=canonical_events,
        task_events=task_events,
        afk_events=afk_events,
        cat_score_map=cat_score_map,
        is_task_based_report=is_task_based_report,
        metrics=metrics,
    )
    report_data = aggregate_hierarchy(
        canonical_events,
        task_based=(is_task_based_report and task_events is not None),
        cat_score_map=cat_score_map,
        get_category_score=get_category_score,
        normalize_title=normalize_title,
    )

    # Replace task durations for OFFLINE tasks with aggregated event duration
    # (calculated from span of all task events for that project/task)
    # Skip if --exclude-offline flag is set
    if not args.exclude_offline:
        # Apply user filters to OFFLINE tasks
        search_value = getattr(args, "search", None)
        has_filters = bool(search_value or args.project or args.task or args.app)

        for (project, task_name), offline_duration in offline_task_durations.items():
            # Filter OFFLINE tasks based on user's search/project/task/app filters
            if has_filters:
                # Check if task matches any filter
                project_match = (
                    search_value and _matches_any(project, [search_value], args.exact)
                ) or (args.project and _matches_any(project, args.project, args.exact))
                task_match = (
                    search_value and _matches_any(task_name, [search_value], args.exact)
                ) or (args.task and _matches_any(task_name, args.task, args.exact))

                if not (project_match or task_match):
                    continue  # Skip this OFFLINE task, doesn't match filter

                if _excluded(project, args.exclude_project) or _excluded(
                    task_name, args.exclude_task
                ):
                    continue  # Skip excluded task

            offline_cat = build_offline_category_structure(offline_duration)
            if project in report_data and task_name in report_data[project]["tasks"]:
                # Task exists in report from aggregate_hierarchy; replace its duration
                task_node = report_data[project]["tasks"][task_name]
                old_duration = task_node["total_duration"]
                task_node["total_duration"] = offline_duration
                # Update project node to reflect new task duration
                report_data[project]["total_duration"] = (
                    report_data[project]["total_duration"]
                    - old_duration
                    + offline_duration
                )
                # Replace categories: clear existing and add only the Offline category
                task_node["categories"] = {"Offline": offline_cat}
            else:
                # Task not in report (no window events); add it from scratch
                proj_node = report_data.setdefault(
                    project,
                    {"total_duration": timedelta(0), "tasks": {}, "prod_score": 0.0},
                )
                task_node = proj_node["tasks"].setdefault(
                    task_name,
                    {
                        "total_duration": offline_duration,
                        "categories": {},
                        "prod_score": 0.0,
                    },
                )
                proj_node["total_duration"] += offline_duration
                task_node["categories"]["Offline"] = offline_cat

    # Generate timeline report if --timesheet is specified
    if args.timesheet:
        timeline_events = [
            {
                "event": rep.event,
                "project": rep.project,
                "task": rep.task,
                "active_task": rep.active_task,
            }
            for rep in context.canonical_events
        ]
        slots = generate_timeline_data(
            timeline_events,
            context.afk_events,
            context.cat_score_map,
            detail_level=args.detail_level,
            deduplicate_categories=args.deduplicate_categories,
        )

        # Inject synthetic slots for OFFLINE task events
        # (these use aggregated task event duration from span of all events)
        # Skip if --exclude-offline flag is set
        if offline_task_durations and not args.exclude_offline:
            # Apply user filters to OFFLINE tasks
            search_value = getattr(args, "search", None)
            has_filters = bool(search_value or args.project or args.task or args.app)

            # Need to get the actual event times for these tasks to use as slot boundaries
            if task_events:
                for event in task_events:
                    if task_has_offline_tag(event):
                        task_name, project = get_task_info(event)

                        # Apply filters to OFFLINE tasks
                        if has_filters:
                            # Check if task matches any filter
                            project_match = (
                                search_value
                                and _matches_any(project, [search_value], args.exact)
                            ) or (
                                args.project
                                and _matches_any(project, args.project, args.exact)
                            )
                            task_match = (
                                search_value
                                and _matches_any(task_name, [search_value], args.exact)
                            ) or (
                                args.task
                                and _matches_any(task_name, args.task, args.exact)
                            )

                            if not (project_match or task_match):
                                continue  # Skip this OFFLINE task, doesn't match filter

                            if _excluded(project, args.exclude_project) or _excluded(
                                task_name, args.exclude_task
                            ):
                                continue  # Skip excluded task

                        key = (project, task_name)
                        if key in offline_task_durations:
                            # Find the time span for this task
                            task_events_for_key = [
                                e
                                for e in task_events
                                if get_task_info(e) == (task_name, project)
                                and task_has_offline_tag(e)
                            ]
                            if task_events_for_key:
                                start_times = [e.timestamp for e in task_events_for_key]
                                end_times = [
                                    e.timestamp + e.duration
                                    for e in task_events_for_key
                                ]
                                slot_start = min(start_times)
                                slot_end = max(end_times)
                                slot_duration = offline_task_durations[key]

                                # Get tags from any event in this group
                                raw_tags = task_events_for_key[0].data.get("tags", [])
                                task_tags = (
                                    [raw_tags]
                                    if isinstance(raw_tags, str)
                                    else list(raw_tags)
                                )

                                # Only add if not already in slots (avoid duplicates)
                                existing = [
                                    s
                                    for s in slots
                                    if s.get("project") == project
                                    and s.get("task") == task_name
                                ]
                                if not existing:
                                    slot_start_tz = slot_start.astimezone()
                                    slot_end_tz = slot_end.astimezone()
                                    slots.append(
                                        {
                                            "type": "regular",
                                            "start": slot_start_tz,
                                            "end": slot_end_tz,
                                            "duration": slot_duration,
                                            "productive_duration": timedelta(0),
                                            "project": project,
                                            "task": task_name,
                                            "tags": task_tags,
                                            "categories": [
                                                build_offline_category_structure(
                                                    slot_duration,
                                                    start_time=slot_start_tz,
                                                    end_time=slot_end_tz,
                                                )
                                            ],
                                        }
                                    )

        slots = sorted(slots, key=lambda s: s["start"])

        # Generate AFK slots and OFFLINE markers unconditionally
        # (filtering happens below to allow independent control of each type)
        # Pass original window_events to extract categories from AFK periods
        # (canonical_events are filtered to not-afk only, so can't detect overlaps with AFK)
        gap_entries = generate_gap_entries(
            context.afk_events,
            context.task_events,
            window_events=window_events,
        )

        # Filter gap_entries based on user's search/project/task/app filters
        search_value = getattr(args, "search", None)
        has_filters = bool(search_value or args.project or args.task or args.app)
        if has_filters:
            filtered_gaps = []
            for gap in gap_entries:
                project = gap.get("project", NO_PROJECT)
                task = gap.get("task", NO_TASK)

                # Apply exclusions first
                if _excluded(project, args.exclude_project) or _excluded(
                    task, args.exclude_task
                ):
                    continue

                # Check if gap matches any filter
                gap_matches = False
                if search_value:
                    gap_matches = _matches_any(
                        project, [search_value], args.exact
                    ) or _matches_any(task, [search_value], args.exact)
                if args.project:
                    gap_matches = gap_matches or _matches_any(
                        project, args.project, args.exact
                    )
                if args.task:
                    gap_matches = gap_matches or _matches_any(
                        task, args.task, args.exact
                    )

                if gap_matches:
                    filtered_gaps.append(gap)
            gap_entries = filtered_gaps

        # FIX: --exclude-offline should only remove machine-off gaps, not AFK slots
        if args.exclude_offline:
            gap_entries = [g for g in gap_entries if g.get("type") != "offline"]

        # FIX: --exclude-afk removes AFK period slots from the timeline
        if args.exclude_afk:
            gap_entries = [g for g in gap_entries if g.get("type") != "afk"]

        # FIX: --exclude-non-project should suppress AFK slots that have no active task
        if args.exclude_non_project:
            gap_entries = [
                g
                for g in gap_entries
                if not (g.get("type") == "afk" and g.get("project") == NO_PROJECT)
            ]

        slots = sorted(slots + gap_entries, key=lambda s: s["start"])

        # Only attach OFFLINE extensions when offline markers are present
        if not args.exclude_offline:
            # Attach OFFLINE gaps to OFFLINE-tagged tasks as extensions
            slots = attach_offline_extensions(slots)

        # Optionally consolidate sessions: merge consecutive sessions of the same task
        # unless interrupted by another task
        if args.consolidate:
            slots = consolidate_timeline_slots(
                slots, ignore_offline=getattr(args, "ignore_offline", False)
            )

        TimelineReport(print_timeline_report).present(
            slots=slots,
            period=period,
            start_time=start_time,
            end_time=end_time,
            detail_level=args.detail_level,
            non_afk_time=context.metrics.non_afk_time,
            productive_time=context.metrics.productive_time,
            productive_task_time=context.metrics.productive_task_time,
            first_event_time=context.metrics.first_event_time,
            last_event_time=context.metrics.last_event_time,
            task_based=context.is_task_based_report,
            distracting_time=context.metrics.distracting_time,
            unscored_time=context.metrics.unscored_time,
            rollup=(args.timesheet and args.consolidate),
            current_session_start=context.metrics.current_session_start,
            current_session_end=context.metrics.current_session_end,
            current_session_duration=context.metrics.current_session_duration,
            last_break_start=context.metrics.last_break_start,
            last_break_end=context.metrics.last_break_end,
            last_break_duration=context.metrics.last_break_duration,
        )
    else:
        # If no task_events, treat as non-task-based report regardless of is_task_based_report
        report_task_based = (
            context.is_task_based_report and context.task_events is not None
        )
        HierarchicalReport(print_report).present(
            report_data=report_data,
            period=period,
            start_time=start_time,
            end_time=end_time,
            task_based=report_task_based,
            detail_level=args.detail_level,
            non_afk_time=context.metrics.non_afk_time,
            productive_time=context.metrics.productive_time,
            productive_task_time=context.metrics.productive_task_time,
            first_event_time=context.metrics.first_event_time,
            last_event_time=context.metrics.last_event_time,
            distracting_time=context.metrics.distracting_time,
            unscored_time=context.metrics.unscored_time,
            sort_by_duration=args.sort_by_duration,
            sort_by_score=not args.sort_alphabetically,
            current_session_start=context.metrics.current_session_start,
            current_session_end=context.metrics.current_session_end,
            current_session_duration=context.metrics.current_session_duration,
            last_break_start=context.metrics.last_break_start,
            last_break_end=context.metrics.last_break_end,
            last_break_duration=context.metrics.last_break_duration,
        )


if __name__ == "__main__":
    main()

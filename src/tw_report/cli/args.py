"""
Command-line argument parsing for tw-report.

Provides argument reordering, flag parsing, and positional argument
disambiguation (period vs. search terms).
"""

import argparse
import os
import re
import sys
from typing import List, Optional, Tuple

DEFAULT_CATEGORIES_FILE = os.path.expanduser(
    "~/.config/activitywatch/aw-server/settings.json"
)


def reorder_arguments(argv: List[str]) -> List[str]:
    """Reorder arguments to put all optional arguments before positional ones.

    This allows flexible argument ordering like:
      tw-report :month --timesheet Climb
      tw-report --timesheet Climb :month
    Both get reordered to:
      tw-report --timesheet Climb :month (flags first, then positional)

    CONTEXT: This function exists to support flexible CLI argument ordering,
    a UX feature that's harder to achieve with standard argparse conventions.
    The hard-coded value-taking-flag list below (lines 35-45) is a known
    fragility: adding new flags that take values requires manual updates here.
    A future refactor could replace this with a more robust argparse pattern
    (e.g., custom action classes or explicit value-flag metadata), but that's
    outside the scope of this extraction phase (behavior must be preserved).
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


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command-line arguments to parse (defaults to sys.argv[1:] if None)

    Returns:
        Parsed arguments as argparse.Namespace
    """
    if argv is None:
        argv = sys.argv[1:]

    # Reorder arguments to put optional args before positional ones
    reordered_argv = reorder_arguments(argv)

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
        help="Exclude OFFLINE-tagged TaskWarrior task durations from the report (default: shown).",
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


def parse_positional_args(args_list: List[str]) -> Tuple[str, Optional[str]]:
    """Parse positional arguments to separate period from search terms.

    Period specifications:
    - Start with ':' (e.g., :today, :week)
    - Or are ISO dates (e.g., 2026-05-06, 2026-05-06T10:00)
    Other arguments are treated as search/filter terms.

    Args:
        args_list: List of positional arguments to parse

    Returns:
        Tuple of (period, search_term) where period is always a string and
        search_term is None if not provided
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

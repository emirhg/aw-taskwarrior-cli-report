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

# FIX: OFFLINE work assigned to a task is not being reported properly in a consolidated report, in the next example, the ~4h entry OFFLINE should be in the "Disposicón de residuos" task
"""
❯ dat
Total Duration: 4:22:30
❯ tws

Wk  Date       Day Tags                                                                                                                                                     Start      End    Time   Total
W26 2026-06-28 Sun Ecosistema, Ecosistema.Tratamiento de residuos, Ecosistema.Tratamiento de residuos.Orgánicos, OFFLINE, fede6ab0-c7bf-4b8d-b550-edb1ad7cbf81, pomodoro 11:35:44 15:58:14 4:22:30 4:22:30
                                                                                                                                                                                                          
                                                                                                                                                                                                   4:22:30

❯ t
ID  Project                                                         Scheduled Prio Description                                                       ETC 
372 Ecosistema.Cultivo.Higuera                                          10h   M    Control de plagas                                                 PT4H
398 Ecosistema.Hábitat.Mantenimiento del hogar.Recámara                 10h   L    Instalar contactos y apagadores                                   PT3H
 48 Anarcademia.Ciencias de la computación.Mecanismo de Antikythera      8h        Documentar una presentación sobre el Mecanismo de Antikythera     PT1H
433 Mercado laboral.Presentación.Curriculum Vitae                        7h   M    Revisar contenido del CV modular                                  PT2H
❯ tw
ID  Project                                                         Scheduled Prio Description                                                       ETC 
372 Ecosistema.Cultivo.Higuera                                          10h   M    Control de plagas                                                 PT4H
398 Ecosistema.Hábitat.Mantenimiento del hogar.Recámara                 10h   L    Instalar contactos y apagadores                                   PT3H
 48 Anarcademia.Ciencias de la computación.Mecanismo de Antikythera      8h        Documentar una presentación sobre el Mecanismo de Antikythera     PT1H
433 Mercado laboral.Presentación.Curriculum Vitae                        7h   M    Revisar contenido del CV modular                                  PT2H
                                                                                                                                                    =====
                                                                                                                                                      10H
❯ snt
You have more urgent tasks.
No matches.
Tracking Ecosistema Ecosistema.Cultivo Ecosistema.Cultivo.Higuera OFFLINE "ac254fe0-ee17-47a6-be3e-5d6f069cdc67" pomodoro
  Started 2026-06-28T16:00:07
  Current                  07
  Total               0:00:00
❯ ${HOME}/Desktop/ianua/work_report/tw-report.py --detail-level=1 --timesheet --consolidate --ignore-offline --exclude-non-project :today
================================================================================================== Timeline Report ==================================================================================================
Period: :today (2026-06-28 to 2026-06-28)
Active Time: 0:44:08 (2026-06-28 00:00 to 2026-06-28 16:00)
  • Project Tracking: 0.0% (0:00:00)
  • Untracked productivity: 0.0% (0:00:00)
  • Overall productivity: 0.0% (0:00:00)
Current Session: 0:06:05 (15:54 to 16:00)
Last Break: 4:18:23 (11:35 to 15:54)
---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Wk  Date       Day
W26 2026-06-28 Sun  11:35-11:35  ▶ Ecosistema > Tratamiento de residuos > Orgánicos                                                                                                                           0:00:00
                                                                                                                                                                                               ----------------------

                                                                                                                                                                                                  Total Time: 0:00:00
=====================================================================================================================================================================================================================
❯ ${HOME}/Desktop/ianua/work_report/tw-report.py --detail-level=1 --timesheet --consolidate --exclude-non-project :today
================================================================================================== Timeline Report ==================================================================================================
Period: :today (2026-06-28 to 2026-06-28)
Active Time: 0:44:29 (2026-06-28 00:00 to 2026-06-28 16:00)
  • Project Tracking: 0.0% (0:00:00)
  • Untracked productivity: 0.0% (0:00:00)
  • Overall productivity: 0.0% (0:00:00)
Current Session: 0:06:25 (15:54 to 16:00)
Last Break: 4:18:23 (11:35 to 15:54)
---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Wk  Date       Day
W26 2026-06-28 Sun
                                                                                                                                                                                 (10:42:02 OFF)
                                                                                                                                                                                  (4:18:23 OFF)
             11:35  ▶ Ecosistema > Tratamiento de residuos > Orgánicos                                                                                                                                        0:00:00
             16:00  ▶ Ecosistema > Cultivo > Higuera                                                                                                                                                          0:00:00
                                                                                                                                                                                               ----------------------
                                                                                                                                                                                                 Day total:   0:00:00

                                                                                                                                                                                                  Total Time: 0:00:00
================================
"""

# Add src directory to path so we can import tw_report package
import sys
import os as _os

_script_dir = _os.path.dirname(_os.path.abspath(__file__))
_src_dir = _os.path.join(_script_dir, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

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

from tw_report.cli.args import parse_args, parse_positional_args
from tw_report.pipeline.processors import (
    aggregate_hierarchy,
    build_canonical_events,
    build_context,
    compute_metrics,
    merge_overlapping_afk_periods,
)
from tw_report.pipeline.presenters import HierarchicalReport, TimelineReport
from tw_report.core.filtering import EventFilter
from tw_report.core.consolidation import TimelineSlotManager
from tw_report.core.offline import OfflineTaskProcessor
from tw_report.core.timeline import Timeline, TimelineSlot
from tw_report.core.events import get_bucket_id, get_events
from tw_report.core.period import parse_period
from tw_report.core.categories import (
    load_categories,
    compile_category_rules,
    get_category_score,
    categorize_event,
)
from tw_report.core.task_matching import (
    find_active_task,
    get_task_info,
    task_has_offline_tag,
    build_offline_category_structure,
)
from tw_report.core.filtering import EventFilter, NO_PROJECT, NO_TASK
from tw_report.pipeline.processors import (
    window_event_max_category_score,
    window_event_productive_duration,
)
from tw_report.utils.formatting import (
    format_duration,
    format_duration_tracked_prod,
    format_duration_with_afk,
    format_duration_with_gaps,
    format_offline_task_duration,
    format_afk_label,
    format_offline_label,
    get_terminal_width,
    sanitize_title,
    normalize_title,
    truncate_title,
    abbreviate_project_path,
    format_timeline_line,
)
from tw_report.pipeline.report_render import (
    print_summary_total,
    print_report_header,
    print_report,
)
from tw_report.pipeline.timeline_render import print_timeline_report

# --- Constants and Configuration ---

DEFAULT_CATEGORIES_FILE = os.path.expanduser(
    "~/.config/activitywatch/aw-server/settings.json"
)

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


# --- Time Period Utilities ---




# --- Data Loading and Processing ---







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


# --- Shared Utility Functions (used by both default and timeline reports) ---




# --- Report Formatting and Printing ---


# --- Timeline Report Generation and Printing ---


from tw_report.pipeline.generation import (
    generate_timeline_data,
    generate_gap_entries,
    _merge_overlapping_events,
)



# --- Main Execution ---


def main():
    """Main script logic."""
    args = parse_args()
    client = ActivityWatchClient("tw-report")

    # Parse positional arguments to separate period from search term
    period, search_term = parse_positional_args(args.args)
    args.search = (
        search_term  # Set search term from positional args (None if not provided)
    )

    # Create unified event filter for consistent filtering across all entry types
    event_filter = EventFilter(
        project_patterns=args.project or [],
        task_patterns=args.task or [],
        app_patterns=args.app or [],
        exclude_projects=args.exclude_project or [],
        exclude_tasks=args.exclude_task or [],
        exclude_apps=args.exclude_app or [],
        exclude_non_project=args.exclude_non_project,
        exact_match=args.exact,
        search_term=args.search,
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

    # Process OFFLINE task events using the extracted OfflineTaskProcessor
    # This replaces ~150 lines of scattered logic with a clean, testable class
    offline_task_durations: Dict = {}
    offline_event_durations: Dict = {}
    offline_event_groups: Dict = {}
    if task_events:
        offline_processor = OfflineTaskProcessor(
            task_events=task_events,
            window_events=window_events,
            afk_events=afk_events,
            event_filter=event_filter,
            end_time=end_time,
        )
        offline_task_durations, offline_event_durations, offline_event_groups, offline_task_real_durations = offline_processor.process()

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

        for key, offline_duration in offline_task_durations.items():
            # Handle both 2-element tuples (project, task) and 3-element tuples (project, task, group_idx)
            project = key[0]
            task_name = key[1]
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
        # Use Timeline for internal slot management (Phase 3 migration)
        timeline = Timeline()

        # Add slots from timeline data
        initial_slots = generate_timeline_data(
            timeline_events,
            context.afk_events,
            context.cat_score_map,
            detail_level=args.detail_level,
            deduplicate_categories=args.deduplicate_categories,
            get_category_score=get_category_score,
        )
        timeline.add_slots([TimelineSlot.from_dict(s) for s in initial_slots])

        # Inject synthetic slots for OFFLINE task events
        # (these use aggregated task event duration from span of all events)
        # Skip if --exclude-offline flag is set
        if offline_task_durations and not args.exclude_offline:
            # Apply user filters to OFFLINE tasks
            search_value = getattr(args, "search", None)
            has_filters = bool(search_value or args.project or args.task or args.app)

            # Iterate through offline tasks (keys can be 2-element or 3-element tuples)
            if task_events:
                for key, offline_duration in offline_task_durations.items():
                    # Extract project and task from key
                    project = key[0]
                    task_name = key[1]

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

                    # Use canonical builder from OfflineTaskProcessor
                    # This ensures all offline_task slots are built consistently with proper
                    # event_duration field (critical for TimelineSlot validation).
                    task_events_for_key = offline_event_groups.get(key, [])
                    if task_events_for_key:
                        offline_slot_dict = offline_processor.get_synthetic_slot(
                            key, task_events_for_key
                        )
                        if offline_slot_dict:  # Builder returns {} if events is empty
                            timeline.add_from_dict(offline_slot_dict)

        # Timeline auto-sorts on insertion, no need to manually sort

        # Generate AFK slots and OFFLINE markers unconditionally
        # (filtering happens below to allow independent control of each type)
        # Pass original window_events to extract categories from AFK periods
        # (canonical_events are filtered to not-afk only, so can't detect overlaps with AFK)
        gap_entries = generate_gap_entries(
            context.afk_events,
            context.task_events,
            window_events=window_events,
        )

        # Filter gap_entries using unified EventFilter for consistency
        # (replaces 50+ lines of scattered filter logic)
        gap_entries = [
            g
            for g in gap_entries
            if event_filter.should_include_entry(g, entry_type=g.get("type", "gap"))
        ]

        # FIX: --exclude-afk removes AFK period slots from the timeline
        if args.exclude_afk:
            gap_entries = [g for g in gap_entries if g.get("type") != "afk"]

        # Add gap entries to timeline (auto-sorts on insertion)
        timeline.add_slots([TimelineSlot.from_dict(g) for g in gap_entries])

        # Convert timeline to dicts for downstream processing
        slots = timeline.get_slots_as_dicts()

        # Optionally consolidate sessions: merge consecutive sessions of the same task
        # unless interrupted by another task
        if args.consolidate:
            slot_manager = TimelineSlotManager(None, event_filter)
            slot_manager.add_slots(slots)
            slots = slot_manager.consolidate()

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
            afk_events=afk_events,
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

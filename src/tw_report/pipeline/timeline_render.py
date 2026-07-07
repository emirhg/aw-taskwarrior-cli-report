"""Timeline report rendering (print to stdout).

Renders a detailed timeline of work sessions organized by date and week,
with support for rollup, consolidation, and detail levels.

CRITICAL HISTORY (Phases 5-8, 2026-07-02):
===========================================

Phase 5 refactoring (commit 12def2d) partially extracted this module but left
it incomplete: only ~140 lines of the 615-line print_timeline_report() were
extracted. Missing logic included:
  - Time range calculation and formatting (START - END)
  - Task name extraction with ▶▶ separator
  - Project name abbreviation
  - Productivity percentage calculation per entry
  - Full AFK and OFFLINE slot rendering
  - Metrics aggregation (AFK time, project tracking %, focus time)
  - _render_slot_detail() helper for detail_level >= 3

This caused the broken behavior reported on 2026-07-02:
  - Active Time showed 8:27:21 instead of 8:50:56 (missing 0:23:34 AFK)
  - Project Tracking showed 0.0% instead of 89.0%
  - AFK time metric not displayed
  - Focus time metric missing
  - Timeline entries showed "00:00-..." instead of "00:00 - 04:36"
  - No task names (▶▶ Corregir el reporte...) displayed
  - No per-entry productivity percentages ([prod 48%])

RESTORATION (commit 1b35699):
=============================
The complete implementation was restored from commit 69aeca3 (last working
state before refactoring). This includes:
  - Full print_timeline_report() with consolidated/rollup rendering engine
  - _render_slot_detail() for hierarchical category/app/title sub-rows
  - split_slots_spanning_days() extracted as module-level function
  - Original format_timeline_line() using terminal-width alignment

All metrics are now calculated correctly, time ranges display properly,
and consolidated/detail rendering works as originally designed.

FORMATTING BEHAVIOR:
====================
format_timeline_line() uses ljust(terminal_width - len(duration) - 1)
to pad the left content. This creates lines that:
  - Use full terminal width for dynamic alignment
  - Right-align the duration column
  - Work correctly with both simple and consolidated rendering

Example (terminal width 120):
  Input:  left="     00:00 - 04:36  ▶ Project", duration="4:36:02"
  Output: "     00:00 - 04:36  ▶ Project       4:36:02"
                                        ^~105 chars to 120~^

This approach was chosen over fixed-column padding because:
  1. Consolidation generates different content lengths per entry
  2. Terminal width can vary by user environment
  3. Dynamic padding maintains alignment without truncation
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from itertools import groupby
import re
from aw_transform import filter_keyvals
from aw_core.models import Event

from tw_report.core.filtering import NO_PROJECT, NO_TASK
from tw_report.core.consolidation import collapse_tasks_to_project
from tw_report.pipeline.report_render import print_report_summary, print_report_totals
from tw_report.utils.formatting import (
    format_duration,
    format_duration_tracked_prod,
    format_duration_with_afk,
    format_duration_with_gaps,
    format_offline_task_duration,
    format_afk_label,
    abbreviate_project_path,
    get_terminal_width,
    format_timeline_line,
    format_timeline_columns,
    truncate_title,
    split_gaps_and_duration,
)

def _format_project_task_columns(project_name: str, task_name: str) -> str:
    """Format project and task as aligned columns.

    For "No project assigned" entries, shows only the project (no task decorator).
    For normal entries, shows both with proper alignment.

    Args:
        project_name: Full project name (e.g., "Ecosistema > Cultivo > Hikuri" or "No project assigned")
        task_name: Task name (e.g., "Revisar semillero de Hikuri" or "No task assigned")

    Returns:
        Formatted string with project and task in aligned columns
    """
    if project_name == NO_PROJECT:
        # Special case: no project - just show project name, skip task decorator
        return f"▶ {project_name}"
    else:
        # Normal case: show both project and task
        return f"▶ {project_name} ▶▶ {task_name}"


def split_slots_spanning_days(slots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Split slots that span multiple days into single-day pieces.

    For each slot crossing midnight, creates separate entries for each day,
    with duration proportionally allocated. This ensures timeline display shows
    correct daily totals and week structure.

    Args:
        slots: List of timeline slots (may span multiple days)

    Returns:
        List of slots, with multi-day slots split into single-day pieces
    """
    split_slots = []

    for slot in slots:
        start_dt = slot["start"]
        slot_duration = slot.get("actual_duration", slot["duration"])
        end_dt = start_dt + slot_duration

        start_date = start_dt.date()
        end_date = end_dt.date()

        # Slot stays within same day
        if start_date == end_date:
            split_slots.append(slot)
            continue

        # Slot spans multiple days — split it
        current_dt = start_dt

        while current_dt.date() <= end_date:
            current_date = current_dt.date()
            day_end = datetime.combine(
                current_date + timedelta(days=1),
                datetime.min.time(),
                tzinfo=current_dt.tzinfo,
            )

            piece_start = current_dt
            piece_end = min(day_end, end_dt)
            piece_duration = piece_end - piece_start

            split_slot = slot.copy()
            split_slot["start"] = piece_start
            split_slot["duration"] = piece_duration

            # Proportionally allocate durations based on piece ratio
            if slot_duration.total_seconds() > 0:
                ratio = piece_duration.total_seconds() / slot_duration.total_seconds()
                split_slot["actual_duration"] = piece_duration
                if "productive_duration" in slot:
                    split_slot["productive_duration"] = timedelta(
                        seconds=slot["productive_duration"].total_seconds() * ratio
                    )
                for duration_field in ("afk_duration", "offline_extension_duration"):
                    if duration_field in slot and slot[duration_field]:
                        split_slot[duration_field] = timedelta(
                            seconds=slot[duration_field].total_seconds() * ratio
                        )
            else:
                split_slot["actual_duration"] = piece_duration

            split_slots.append(split_slot)
            current_dt = day_end

    return split_slots


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
    afk_events: List[Event] = None,
):
    """Print a timeline report showing activity as continuous time slots with date/week headers and cumulative totals.

    CRITICAL METRICS CALCULATION (Phase 5 bug fix, 2026-07-02):
    ===========================================================

    This function calculates and displays the following metrics:
      - Active Time: Total time from first to last activity (includes AFK)
      - AFK time: Total time away from keyboard
      - Project Tracking: % of active time on tracked (non-"No project") tasks
      - Focus time: % time on high-priority tasks
      - Untracked productivity: % of untracked time on productive activities
      - Overall productivity: Total productive time / active time
      - Distracting time: Total time on distracting activities
      - Unscored time: Total time unscored

    The broken Phase 5 version (commit 12def2d) failed to:
      - Calculate AFK time separately (showed as reduced Active Time)
      - Include AFK metrics in display
      - Calculate project tracking percentage (showed 0% instead of 89%)
      - Include focus time metric

    This version correctly:
      - Separates AFK time from active time calculation
      - Includes AFK metrics in the report header
      - Properly calculates project tracking percentage
      - Includes all required metrics

    CONSOLIDATION RENDERING (when --consolidate flag used):
    ========================================================
    When slots are consolidated (merged same project/task entries), this
    function detects consolidation via the presence of "afk_duration" field
    and adjusts metrics calculation accordingly:
      - has_consolidated_afk flag: True if consolidation merged AFK gaps
      - Consolidated AFK time is already in the afk_duration field
      - Regular (non-consolidated) AFK time is calculated from type="afk" slots

    DETAIL LEVEL RENDERING:
    =======================
    detail_level controls rendering depth:
      1 = Project only (no sub-rows)
      2 = Project + Task (no sub-rows, but shows task name)
      3 = + Category details (sub-rows showing category breakdown)
      4 = + App (indented under category)
      5 = + Title (window titles under app)

    Each level is rendered via _render_slot_detail() which shows indented
    breakdowns of how time was distributed across categories/apps/titles.

    ROLLUP MODE (when --consolidate and --timesheet used):
    =======================================================
    In rollup mode (used with consolidation), single-entry days show both
    date header and time range inline:
      "W27 2026-07-01 Wed    00:00 - 04:36  ▶ Project > Task"
    instead of on separate lines for brevity.

    PARAMETER NOTES:
      slots: Pre-filtered timeline slots from main() (EventFilter already applied)
      period: Human-readable period description (e.g., ":yesterday", "2026-07-01")
      detail_level: See above (1-5, typically 1-2 for most users)
      rollup: If True, collapse single-entry days to inline format
      non_afk_time: Total non-AFK time from metrics (for % calculations)
      productive_time: Total productive time from metrics
      (other metric parameters used for header display)
    """
    from itertools import groupby

    width = get_terminal_width()
    is_single_day = start_time.date() == end_time.date()
    # Use actual_duration for merged slots, duration for others
    # Exclude OFFLINE gap markers from totals (informational only)
    # Keep offline_task slots (actual work sessions) and AFK slots in totals
    all_regular_slots = [
        s for s in slots if s.get("type") != "offline"
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

    # Calculate total OFFLINE time (system powered off: duration - event_duration for offline_task slots)
    total_offline_time = sum(
        (s.get("duration", timedelta(0)) - s.get("event_duration", timedelta(0))
         for s in slots if s.get("type") == "offline_task"),
        timedelta(0),
    )

    # Print SUMMARY at top
    print_report_summary(
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
    )

    if not slots:
        print("No activity found for the specified period.")

    # Print column header
    print("Wk  Date       Day")

    # Group slots by (iso_week_key, date)
    def slot_week_key(slot):
        """Return ISO week key: 'YYYY-Www' (e.g., '2026-W17')"""
        return slot["start"].strftime("%G-W%V")

    def slot_date(slot):
        """Return slot date"""
        return slot["start"].date()

    def split_slots_spanning_days(slots):
        """
        Split slots that span multiple days.

        For each slot spanning midnight, creates separate slot entries for each day,
        with duration proportionally allocated to each day.

        Returns:
            List of slots, with multi-day slots split into single-day pieces
        """
        split_slots = []

        for slot in slots:
            start_dt = slot["start"]
            slot_duration = slot.get("actual_duration", slot["duration"])
            end_dt = start_dt + slot_duration

            start_date = start_dt.date()
            end_date = end_dt.date()

            # If slot stays within same day, keep as-is
            if start_date == end_date:
                split_slots.append(slot)
                continue

            # Slot spans multiple days - split it
            current_dt = start_dt

            while current_dt.date() <= end_date:
                # Determine this day's end boundary (midnight of current day)
                current_date = current_dt.date()
                day_end = datetime.combine(
                    current_date + timedelta(days=1),
                    datetime.min.time(),
                    tzinfo=current_dt.tzinfo
                )

                # Calculate overlap with this day
                piece_start = current_dt
                piece_end = min(day_end, end_dt)
                piece_duration = piece_end - piece_start

                # Create split slot for this day
                split_slot = slot.copy()
                split_slot["start"] = piece_start
                split_slot["duration"] = piece_duration

                # Proportionally allocate actual_duration and productive_duration
                if slot_duration.total_seconds() > 0:
                    ratio = piece_duration.total_seconds() / slot_duration.total_seconds()
                    split_slot["actual_duration"] = piece_duration  # Use actual piece duration
                    if "productive_duration" in slot:
                        split_slot["productive_duration"] = timedelta(
                            seconds=slot["productive_duration"].total_seconds() * ratio
                        )
                    # Proportionally allocate AFK and other duration fields
                    for duration_field in ("afk_duration", "offline_extension_duration"):
                        if duration_field in slot and slot[duration_field]:
                            split_slot[duration_field] = timedelta(
                                seconds=slot[duration_field].total_seconds() * ratio
                            )
                else:
                    split_slot["actual_duration"] = piece_duration

                split_slots.append(split_slot)

                # Move to next day
                current_dt = day_end

        return split_slots

    # Split slots spanning multiple days
    slots = split_slots_spanning_days(slots)

    # Filter to only include slots within the requested date range
    # After splitting, we should only show portions that fall within [start_time, end_time)
    slots = [
        s for s in slots
        if s["start"] < end_time and (s["start"] + s.get("actual_duration", s["duration"])) > start_time
    ]

    # Recalculate total_time_all after filtering to match the displayed slots
    all_regular_slots_filtered = [
        s for s in slots if s.get("type") != "offline"
    ]
    total_time_all = sum(
        (slot.get("actual_duration", slot["duration"]) for slot in all_regular_slots_filtered),
        timedelta(0),
    )
    total_productive_all = sum(
        (slot.get("productive_duration", timedelta(0)) for slot in all_regular_slots_filtered),
        timedelta(0),
    )

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
    # offline_task slots are singletons to break up regular grouping
    slot_groups = []
    current_project_group = None
    current_project_group_project = None
    current_project_group_date = None

    for slot in slots:
        slot_date_val = slot_date(slot)
        slot_project = slot.get("project")

        # offline_task slots always break grouping (they're singletons)
        if slot.get("type") == "offline_task":
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
            # Add as singleton group
            slot_groups.append((slot_project, slot_date_val, [slot]))
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

        # Check if this is an offline_task group (singleton)
        is_offline_task_group = group_slots[0].get("type") == "offline_task"

        # Rollup: collapse to inline when exactly one slot entry for this day (exclude offline_task)
        group_is_rollup = (
            rollup
            and date_total_entries.get(group_date, 0) == 1
            and not is_offline_task_group
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
            # Align same-week dates: 4 spaces + date + day
            pending_date_prefix = f"    {date_str} {day_str}"
            current_date = group_date

        # Flush pending date header for non-rollup days before printing the group
        if pending_date_prefix is not None and not group_is_rollup:
            print(pending_date_prefix)
            pending_date_prefix = None

        # Handle offline_task slots (synthetic OFFLINE-tagged tasks formatted as gap entries)
        if group_slots[0].get("type") == "offline_task":
            if pending_date_prefix is not None:
                print(pending_date_prefix)
                pending_date_prefix = None

            offline_task_slot = group_slots[0]
            project_name = offline_task_slot.get("project", NO_PROJECT).replace(
                ".", " > "
            )
            task_name = offline_task_slot.get("task", NO_TASK)
            wall_clock_duration = offline_task_slot.get("duration", timedelta(0))
            event_duration = offline_task_slot.get("event_duration", timedelta(0))
            start_str = offline_task_slot["start"].strftime("%H:%M")
            end_str = (offline_task_slot["start"] + wall_clock_duration).strftime("%H:%M")

            # Format OFFLINE task entries with same style as regular entries
            abbrev_project = abbreviate_project_path(project_name, task_name)
            duration_formatted = format_offline_task_duration(wall_clock_duration, event_duration)

            # Parse the duration_formatted to extract gaps and duration
            # Format is like "(HH:MM:SS OFF)  HH:MM:SS  [prod XX%]"
            # Extract the first part (gaps) and the rest (duration)
            if duration_formatted.startswith("("):
                # Has gaps
                close_paren = duration_formatted.find(")")
                gaps_str = duration_formatted[:close_paren+1]
                base_duration = duration_formatted[close_paren+1:].lstrip()
            else:
                gaps_str = ""
                base_duration = duration_formatted

            # Add asterisk prefix to offline task name for easy spotting
            offline_task_name = f"*{task_name}"

            time_range = f"{start_str} - {end_str}"
            print(format_timeline_columns(
                time_range=time_range,
                project=abbrev_project,
                task=offline_task_name,
                gaps=gaps_str,
                duration=base_duration,
            ))

            # Accumulate offline_task to day/week totals with actual tracked (online) time only
            # (wall_clock_duration includes offline periods when system was powered off)
            day_duration += event_duration
            week_duration += event_duration
            day_afk_duration += timedelta(0)  # offline tasks don't have AFK time
            week_afk_duration += timedelta(0)

            # offline_task slots are handled above, skip the regular group handling below
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
                # Separate gaps from duration for column alignment
                gaps_str, base_duration = split_gaps_and_duration(
                    group_total_duration, group_productive_duration, group_afk_duration
                )
                time_range = f"{start_str}-{end_str}"
                # Print date prefix on separate line if available, then content below
                if pending_date_prefix is not None:
                    print(pending_date_prefix)
                    pending_date_prefix = None
                # Add space before task name to preserve alignment with offline tasks (which use *)
                formatted_task = f" {task_name}" if task_name != NO_TASK else task_name
                print(format_timeline_columns(
                    time_range=time_range,
                    project=abbrev_project,
                    task=formatted_task,
                    gaps=gaps_str,
                    duration=base_duration,
                ))
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
                left = f"    *{s_start} - {s_end}   {content}"
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

                # Separate gaps from duration for column alignment
                if slot.get("type") == "afk":
                    slot_dur_str = format_afk_label(
                        slot.get("actual_duration", slot["duration"])
                    )
                    gaps_str = ""
                    base_duration = slot_dur_str
                else:
                    gaps_str, base_duration = split_gaps_and_duration(
                        slot.get("actual_duration", slot["duration"]),
                        slot.get("productive_duration", timedelta(0)),
                        slot.get("afk_duration"),
                    )

                time_range = f"{start_str} - {end_str}"
                # Add space before task name to preserve alignment with offline tasks (which use *)
                formatted_task = f" {task_name}" if task_name != NO_TASK else task_name
                print(format_timeline_columns(
                    time_range=time_range,
                    project=abbrev_project,
                    task=formatted_task,
                    gaps=gaps_str,
                    duration=base_duration,
                ))
                _render_slot_detail(slot, detail_level, width)
            else:
                # Multiple slots for this project today — one row each
                for slot in group_slots:
                    s_start = slot["start"].strftime("%H:%M")
                    s_end = (slot["start"] + slot["duration"]).strftime("%H:%M")
                    slot_duration = slot.get("actual_duration", slot["duration"])
                    task_name = slot["task"]
                    abbrev_project = abbreviate_project_path(project_name, task_name)

                    # Separate gaps from duration for column alignment
                    if slot.get("type") == "afk":
                        slot_dur_str = format_afk_label(slot_duration)
                        gaps_str = ""
                        base_duration = slot_dur_str
                    else:
                        gaps_str, base_duration = split_gaps_and_duration(
                            slot_duration,
                            slot.get("productive_duration", timedelta(0)),
                            slot.get("afk_duration"),
                        )

                    time_range = f"{s_start} - {s_end}"
                    # Add space before task name to preserve alignment with offline tasks (which use *)
                    formatted_task = f" {task_name}" if task_name != NO_TASK else task_name
                    line = format_timeline_columns(
                        time_range=time_range,
                        project=abbrev_project,
                        task=formatted_task,
                        gaps=gaps_str,
                        duration=base_duration,
                    )
                    print(line)
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

    # Print TOTALS at bottom
    # Note: In consolidated mode, AFK time is already included in total_time_all,
    # so we only add it in regular (non-consolidated) mode
    total_time_final = (
        total_time_all + total_afk_time if not has_consolidated_afk else total_time_all
    )

    print_report_totals(
        total_time_all=total_time_final,
        total_productive_all=total_productive_all,
        total_afk=total_afk_time if total_afk_time > timedelta(0) else None,
        total_offline=total_offline_time if total_offline_time > timedelta(0) else None,
    )


def print_period_consolidated_report(
    slots: List[Dict],
    period: str,
    start_time: datetime,
    end_time: datetime,
    period_mode: str,
    detail_level: int = 1,
    non_afk_time: timedelta = None,
    productive_time: timedelta = None,
    task_based: bool = True,
    **kwargs,
):
    """Print a period-consolidated timeline report (day/week/month/year summaries).

    Shows summaries grouped by period and project (or project + task at detail_level >= 2),
    with total duration + productivity, no start/end time range.

    Args:
        slots: Pre-consolidated list from consolidate_by_period() with fields:
               period_start, project, task, duration, actual_duration, productive_duration,
               afk_duration, categories
        period: Human-readable period string (e.g., ":year", "2026-01-01")
        start_time, end_time: Start/end of the query period (for header)
        period_mode: "day" | "week" | "month" | "year" (for labeling)
        detail_level: Controls rendering depth (1=project only, 2+=task, 3+=categories)
        non_afk_time, productive_time: Metrics for header
        task_based: Whether this is task-based report
        **kwargs: Other metrics (distracting_time, unscored_time, current_session_*, etc.)
    """
    from datetime import date

    width = get_terminal_width()

    # Compute totals for header (same as print_timeline_report)
    all_regular = [s for s in slots if s.get("type") != "offline"]
    tracked = [s for s in all_regular if s.get("project") != NO_PROJECT]

    total_duration = sum(
        (s.get("actual_duration", s["duration"]) for s in tracked), timedelta(0)
    )
    total_productive = sum(
        (s.get("productive_duration", timedelta(0)) for s in tracked), timedelta(0)
    )
    total_all = sum(
        (s.get("actual_duration", s["duration"]) for s in all_regular), timedelta(0)
    )
    total_productive_all = sum(
        (s.get("productive_duration", timedelta(0)) for s in all_regular), timedelta(0)
    )
    total_afk = sum(
        (s.get("afk_duration", timedelta(0)) for s in slots), timedelta(0)
    )
    total_offline = sum(
        (s.get("offline_extension_duration", timedelta(0)) for s in slots), timedelta(0)
    )

    # Print SUMMARY at top
    print_report_summary(
        title=" Timeline Report ",
        period=period,
        start_time=start_time,
        end_time=end_time,
        total_duration=total_duration,
        task_based=task_based,
        non_afk_time=non_afk_time,
        productive_time=productive_time,
        productive_task_time=kwargs.get("productive_task_time"),
        first_event_time=kwargs.get("first_event_time"),
        last_event_time=kwargs.get("last_event_time"),
        distracting_time=kwargs.get("distracting_time"),
        unscored_time=kwargs.get("unscored_time"),
        current_session_start=kwargs.get("current_session_start"),
        current_session_end=kwargs.get("current_session_end"),
        current_session_duration=kwargs.get("current_session_duration"),
        last_break_start=kwargs.get("last_break_start"),
        last_break_end=kwargs.get("last_break_end"),
        last_break_duration=kwargs.get("last_break_duration"),
    )

    if not slots:
        print("No activity found for the specified period.")

    # Group by period_start for display
    current_period = None
    period_slots = []
    period_total_duration = timedelta(0)
    period_total_productive = timedelta(0)

    def format_period_label(period_start: date, mode: str) -> str:
        """Format period-start date as a label."""
        if mode == "day":
            return period_start.strftime("%Y-%m-%d %a")
        elif mode == "week":
            sunday = period_start + timedelta(days=6)
            week_num = period_start.isocalendar()[1]
            return f"W{week_num} {period_start.strftime('%Y-%m-%d')} - {sunday.strftime('%Y-%m-%d')}"
        elif mode == "month":
            return period_start.strftime("%Y-%m %B")
        elif mode == "year":
            return period_start.strftime("%Y")
        return str(period_start)

    def print_period_block(ps: date, slots_in_period: List[Dict], mode: str):
        """Print one period block (label + projects/tasks in period + period total)."""
        print(format_period_label(ps, mode))

        # Collapse to project-only at detail_level == 1
        rows_to_display = slots_in_period
        if detail_level == 1:
            rows_to_display = collapse_tasks_to_project(slots_in_period)

        total_dur = timedelta(0)
        total_prod = timedelta(0)
        period_afk = timedelta(0)
        period_offline = timedelta(0)
        for row in rows_to_display:
            project = row["project"]
            task = row.get("task", NO_TASK)
            duration = row.get("actual_duration", row["duration"])
            productive = row.get("productive_duration", timedelta(0))

            total_dur += duration
            total_prod += productive
            # Accumulate AFK and OFFLINE gap time for period total (silent accumulation)
            period_afk += row.get("afk_duration", timedelta(0))
            period_offline += row.get("offline_extension_duration", timedelta(0))

            # Skip zero-duration rows from rendering (but keep them in totals)
            # These are tasks that exist in TaskWarrior but have no tracked time
            if duration == timedelta(0):
                continue

            # Render based on detail level
            if detail_level == 1:
                # Project only
                duration_str = format_duration_tracked_prod(duration, productive)
                left = f"     ▶ {project}"
                print(format_timeline_line(left, duration_str, max_left_width=95))
            else:
                # detail_level >= 2: show project >> task
                duration_str = format_duration_tracked_prod(duration, productive)
                abbrev_project = abbreviate_project_path(project, task)
                # Always show task if: (a) project is NO_PROJECT (task is main ID), or (b) task is meaningful
                if task and (task != NO_TASK or project == NO_PROJECT):
                    left = f"     ▶ {abbrev_project} ▶▶ {task}"
                else:
                    left = f"     ▶ {abbrev_project}"
                print(format_timeline_line(left, duration_str, max_left_width=95))

                # detail_level >= 3: render category/app/title sub-rows
                if detail_level >= 3:
                    _render_slot_detail(row, detail_level, width)

        # Period total line — show AFK/OFFLINE breakdown
        total_line = ("Week total (tracked):" if mode == "week"
                     else "Month total (tracked):" if mode == "month"
                     else "Year total (tracked):" if mode == "year"
                     else "Day total (tracked):")
        duration_str = format_duration_with_gaps(total_dur, total_prod, period_afk, period_offline)
        print((total_line + "  " + duration_str).rjust(width))
        print()

    # Print all periods
    for slot in slots:
        ps = slot["period_start"]
        if ps != current_period:
            if current_period is not None:
                print_period_block(current_period, period_slots, period_mode)
            current_period = ps
            period_slots = []
        period_slots.append(slot)

    # Print final period
    if current_period is not None:
        print_period_block(current_period, period_slots, period_mode)

    # Print TOTALS at bottom
    print_report_totals(
        total_time_all=total_all,
        total_productive_all=total_productive_all,
        total_afk=total_afk if total_afk > timedelta(0) else None,
        total_offline=total_offline if total_offline > timedelta(0) else None,
    )


# --- Main Execution ---

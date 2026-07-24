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
  - Online Time showed 8:27:21 instead of 8:50:56 (missing 0:23:34 AFK)
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

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from itertools import groupby
import re
from aw_transform import filter_keyvals
from aw_core.models import Event

from tw_report.core.filtering import NO_PROJECT, NO_TASK
from tw_report.core.consolidation import collapse_tasks_to_project
from tw_report.pipeline.generation import MIN_EVENT_DURATION
from tw_report.pipeline.models import TimeslotDuration, PeriodMetrics
from tw_report.pipeline.report_render import print_report_summary, print_report_totals
from tw_report.utils.formatting import (
    format_duration,
    format_duration_tracked_prod,
    format_duration_with_afk,
    format_duration_with_gaps,
    format_offline_task_duration,
    format_timeslot_duration,
    format_afk_label,
    abbreviate_project_path,
    get_terminal_width,
    format_timeline_line,
    format_timeline_columns,
    truncate_title,
    split_gaps_and_duration,
)

def _render_system_shutdown_separator() -> None:
    """Print a blank line to indicate a gap (system shutdown, break, etc.)."""
    print()


def _create_period_metrics_from_dict(
    online: Optional[timedelta] = None,
    afk: Optional[timedelta] = None,
    offline: Optional[timedelta] = None,
    productive: Optional[timedelta] = None,
) -> PeriodMetrics:
    """Create a PeriodMetrics object from individual duration values.

    Helper function that demonstrates how to migrate from manual variable
    accumulation to PeriodMetrics pattern. This enables gradual adoption
    of PeriodMetrics throughout the rendering pipeline.

    Args:
        online: Online time (AFK + non-AFK combined)
        afk: AFK time (subset of online)
        offline: Offline gap (system powered off)
        productive: Productive time

    Returns:
        PeriodMetrics object with the given durations

    Example migration:
        Old way:
            day_duration += online_time
            day_afk_duration += afk_time
            day_offline_duration += offline_time
            day_productive += prod_time

        New way:
            daily_metrics = _create_period_metrics_from_dict(
                online=online_time,
                afk=afk_time,
                offline=offline_time,
                productive=prod_time
            )
    """
    metrics = PeriodMetrics()
    metrics.add(online=online, afk=afk, offline=offline, productive=productive)
    return metrics


def _render_embedded_afk_slots(afk_slots: List[Dict], width: int) -> None:
    """Render embedded AFK slots as indented sub-entries under a work slot.

    Args:
        afk_slots: List of AFK slot dicts to render as nested entries
        width: Terminal width for formatting
    """
    for afk_slot in afk_slots:
        s_start = afk_slot["start"].strftime("%H:%M")
        s_end = (afk_slot["start"] + afk_slot["duration"]).strftime("%H:%M")
        slot_duration = afk_slot.get("actual_duration", afk_slot["duration"])
        slot_dur_str = format_afk_label(slot_duration)

        # Render as indented sub-entry with "└─" prefix to show hierarchy
        time_range = f"{s_start} - {s_end}".ljust(15)
        # Indent with 12 spaces (more than work slots) and add └─ prefix
        left = f"           └─ {time_range}"
        print(format_timeline_line(left, duration_str=slot_dur_str, max_left_width=95))


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


def _get_displayed_duration(slot: Dict[str, Any]) -> timedelta:
    """Return the duration that's actually displayed for this slot.

    Regular and AFK slots use wall-clock duration (from window events).
    OFFLINE task slots use actual_duration (online/tracked time).

    This ensures day/week/report totals sum to the displayed entries.

    Args:
        slot: A timeline slot dict

    Returns:
        The duration as displayed in the output
    """
    slot_type = slot.get("type")
    if slot_type == "offline_task":
        return slot.get("actual_duration", timedelta(0))
    else:
        # Regular and AFK slots use wall-clock duration (matches display)
        return slot["duration"]


def split_slots_spanning_days(slots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Split slots that span multiple days into single-day pieces.

    NOW DELEGATES TO ReportTimelineSlot.split_at_boundaries("day") for unified splitting logic.
    See core/report_slot.py for the actual implementation.

    Args:
        slots: List of timeline slots (may span multiple days)

    Returns:
        List of slots, with multi-day slots split into single-day pieces
    """
    from tw_report.core.report_slot import ReportTimelineSlot
    from tw_report.core.timeline import Timeline, TimelineSlot

    # Convert dicts to TimelineSlots, build a Timeline
    timeline = Timeline()
    for slot_dict in slots:
        try:
            slot = TimelineSlot.from_dict(slot_dict)
            timeline.add_slot(slot)
        except Exception:
            # Backward compatibility: skip malformed slots
            continue

    # Split each slot at day boundaries using the unified implementation
    split_report_slots = []
    for slot in timeline.get_slots():
        report_slot = ReportTimelineSlot.from_timeline_slot(slot)
        split_report_slots.extend(report_slot.split_at_boundaries("day"))

    # Convert back to dicts
    return [rs.to_dict() for rs in split_report_slots]


def filter_short_slots(slots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter out slots shorter than MIN_EVENT_DURATION.

    After split_slots_spanning_days(), very small fragments can remain.
    This filter removes them to avoid cluttering the timeline display.

    Args:
        slots: List of timeline slots

    Returns:
        Filtered list with slots < MIN_EVENT_DURATION removed
    """
    return [
        slot for slot in slots
        if slot.get("duration", timedelta(0)) >= MIN_EVENT_DURATION
    ]


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
    non_afk_time: Optional[timedelta] = None,
    productive_time: Optional[timedelta] = None,
    productive_task_time: Optional[timedelta] = None,
    first_event_time: Optional[datetime] = None,
    last_event_time: Optional[datetime] = None,
    task_based: bool = True,
    distracting_time: Optional[timedelta] = None,
    unscored_time: Optional[timedelta] = None,
    rollup: bool = False,
    current_session_start: Optional[datetime] = None,
    current_session_end: Optional[datetime] = None,
    current_session_duration: Optional[timedelta] = None,
    last_break_start: Optional[datetime] = None,
    last_break_end: Optional[datetime] = None,
    last_break_duration: Optional[timedelta] = None,
    afk_events: Optional[List[Event]] = None,
    exclude_online: bool = False,
):
    """Print a timeline report showing activity as continuous time slots with date/week headers and cumulative totals.

    CRITICAL METRICS CALCULATION (Phase 5 bug fix, 2026-07-02):
    ===========================================================

    This function calculates and displays the following metrics:
      - Online Time: Total time from first to last activity (AFK + non-AFK combined)
      - Active Time: Total focused work time (non-AFK only)
      - AFK time: Total time away from keyboard
      - Project Tracking: % of online time on tracked (non-"No project") tasks
      - Focus time: % time on high-priority tasks
      - Untracked productivity: % of untracked time on productive activities
      - Overall productivity: Total productive time / online time
      - Distracting time: Total time on distracting activities
      - Unscored time: Total time unscored

    The broken Phase 5 version (commit 12def2d) failed to:
      - Calculate AFK time separately (showed as reduced Online Time)
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

    GAP DETECTION & VISUAL SEPARATION (2026-07-23):
    ===============================================
    Blank lines appear between work sessions with gaps > 5 minutes. This feature
    improves readability by visually separating work sessions from breaks,
    system shutdowns, or mode changes.

    CRITICAL: This is an intentional UX feature. Do not remove or disable without
    explicit user request. It helps users quickly scan the timeline and identify
    distinct work periods.

    Implementation:
      - Track last_slot_end time as slots are rendered (initialized to None)
      - Before rendering each slot, check if gap from last_slot_end > 5 minutes
      - If gap exceeds threshold, call _render_system_shutdown_separator() (prints blank line)
      - Update last_slot_end after rendering each slot
      - Applied to all rendering paths: offline_task singletons, single-slot inline, multi-slot loop

    Configuration:
      - Threshold: gap_threshold = timedelta(minutes=5) in line 574
      - To adjust: Change minutes=5 to desired threshold (e.g., minutes=10)
      - To disable: Set gap_threshold = timedelta(hours=24) or similar large value

    Why this matters:
      - Without gap detection, continuous scrolling blends work sessions together
      - Users struggle to identify distinct work periods and breaks
      - Gap visualization makes work session boundaries immediately obvious
      - Especially important for long reports with many activities

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
      non_afk_time: Total Active Time (non-AFK) from metrics (for % calculations)
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
        (_get_displayed_duration(slot) for slot in tracked_slots),
        timedelta(0),
    )
    total_productive_tracked = sum(
        (slot.get("productive_duration", timedelta(0)) for slot in tracked_slots),
        timedelta(0),
    )

    # Total time including untracked (for "Total Time" display)
    # Use displayed durations: slot["duration"] for regular/AFK, actual_duration for OFFLINE
    total_time_all = sum(
        (_get_displayed_duration(slot) for slot in all_regular_slots),
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
        # Regular slots: AFK time is in type="afk" slots OR embedded_afk_slots
        # (After combine_work_with_embedded_afk(), AFK slots are nested inside work slots)
        afk_slots = [s for s in slots if s.get("type") == "afk"]
        total_afk_time = sum(
            (slot.get("actual_duration", slot["duration"]) for slot in afk_slots),
            timedelta(0),
        )
        # Add embedded AFK slots (nested within work slots after combining)
        for slot in slots:
            embedded_afk = slot.get("embedded_afk_slots", [])
            if embedded_afk:
                total_afk_time += sum(
                    (afk.get("actual_duration", afk["duration"]) for afk in embedded_afk),
                    timedelta(0),
                )

    # Calculate total OFFLINE time (system powered off during task work)
    # IMPORTANT: Only count offline_task gaps, NOT offline_extension_duration from window events.
    #
    # Why not offline_extension_duration?
    # =====================================
    # offline_extension_duration marks WINDOW ACTIVITY during OFFLINE tasks.
    # This activity is already accounted for in the offline_task's event_duration
    # (which comes from AFK bucket overlaps during the OFFLINE period).
    # Summing both would double-count the same time!
    #
    # Example: OFFLINE task 09:55-11:08 (73 min wall-clock)
    #   - Window events during this time: 21:47 (marked with offline_extension_duration)
    #   - AFK events during this time: 21:47 (becomes event_duration)
    #   - Offline gap: 73 - 21:47 = 51:13
    #
    # Correct: Count only the gap (51:13)
    # Wrong: Count window activity (21:47) + gap (51:13) = 72:60 (DOUBLE-COUNT!)
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
        total_offline_time=total_offline_time,
        total_time_all=total_time_all,
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

    # Split slots spanning multiple days
    slots = split_slots_spanning_days(slots)

    # Filter out slots shorter than MIN_EVENT_DURATION (tracking noise)
    slots = filter_short_slots(slots)

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
        (_get_displayed_duration(slot) for slot in all_regular_slots_filtered),
        timedelta(0),
    )
    total_productive_all = sum(
        (slot.get("productive_duration", timedelta(0)) for slot in all_regular_slots_filtered),
        timedelta(0),
    )

    # Sort slots by start time
    slots = sorted(slots, key=lambda s: s["start"])

    # Filter out slots where display time range equals zero (confusing display like "11:19 - 11:19")
    # These occur when slot["duration"] represents wall-clock time but is zero
    slots = [
        s for s in slots
        if s.get("duration", timedelta(0)) > timedelta(milliseconds=100)  # > 100ms to handle rounding
    ]

    # Remove regular slots that overlap/fall within OFFLINE periods for the same task
    # OFFLINE slots represent untracked periods; showing both OFFLINE + regular slots creates
    # visual duplication and confusion.
    offline_slots_by_task = {}
    for slot in slots:
        if slot.get("type") == "offline_task":
            key = (slot.get("project"), slot.get("task"))
            if key not in offline_slots_by_task:
                offline_slots_by_task[key] = []
            offline_slots_by_task[key].append(slot)

    # Remove regular slots that occur within OFFLINE periods for the same task
    filtered_slots = []
    for slot in slots:
        if slot.get("type") == "offline_task":
            filtered_slots.append(slot)
        else:
            # Check if this regular slot overlaps with any OFFLINE period for the same task
            key = (slot.get("project"), slot.get("task"))
            slot_start = slot["start"]
            slot_end = slot["start"] + slot.get("duration", timedelta(0))

            overlaps_offline = False
            if key in offline_slots_by_task:
                for offline_slot in offline_slots_by_task[key]:
                    offline_start = offline_slot["start"]
                    offline_end = offline_start + offline_slot["duration"]

                    # Check if regular slot overlaps with or falls within OFFLINE period
                    if slot_start < offline_end and slot_end > offline_start:
                        overlaps_offline = True
                        break

            if not overlaps_offline:
                filtered_slots.append(slot)

    slots = filtered_slots

    # ============================================================================
    # DAY/WEEK METRICS ACCUMULATION
    # ============================================================================
    # This section tracks metrics for each day and week as we render the timeline.
    # The current implementation uses 8 separate variables (day_duration, day_afk_duration,
    # day_offline_duration, day_productive, and their week_ equivalents).
    #
    # FUTURE REFACTORING (Phase 4+):
    # These variables should be replaced with PeriodMetrics objects:
    #
    #   daily_metrics = PeriodMetrics()  # replaces: day_duration, day_afk_duration, etc.
    #   weekly_metrics = PeriodMetrics() # replaces: week_duration, week_afk_duration, etc.
    #
    # Migration pattern for accumulation sites:
    #
    #   OLD:  day_duration += online; day_afk_duration += afk; ...
    #   NEW:  daily_metrics.add(online=online, afk=afk, offline=offline, productive=prod)
    #
    # Or for TimeslotDuration objects:
    #
    #   NEW:  daily_metrics.add_timeslot(slot_duration, productive=prod)
    #
    # Benefits of refactoring:
    #   - Single source of truth for metrics (PeriodMetrics object)
    #   - Clearer intent: grouped metrics rather than scattered variables
    #   - Type safety: invalid metric combinations prevented at construction
    #   - Easier to extend: add new metrics without adding new variables
    #   - Self-documenting: properties like .total_duration and .active_duration
    #
    # Call sites to refactor:
    #   - Line 817-823: offline_task accumulation
    #   - Line 1076-1082: regular_slot accumulation loop
    #   - Line 1090-1100: day/week totals display and reset
    #
    # See _create_period_metrics_from_dict() for migration helper function.
    # ============================================================================

    # Group by week, then by date within week
    current_week_key = None
    current_date = None

    # Use PeriodMetrics for cleaner day/week accumulation
    # These replace: week_duration, day_duration, week_productive, day_productive,
    #               week_afk_duration, day_afk_duration, week_offline_duration, day_offline_duration
    daily_metrics = PeriodMetrics()
    weekly_metrics = PeriodMetrics()

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
    last_slot_end = None  # Track end time of last rendered slot (for gap detection)
    gap_threshold = timedelta(minutes=5)  # Minimum gap to display separator

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
                    # Use online_duration only (not total_duration) since offline_gap is displayed separately
                    total_day_with_afk = daily_metrics.online_duration
                    # Format offline time in gap notation if present
                    if daily_metrics.offline_gap and daily_metrics.offline_gap > timedelta(0):
                        gaps_str = f"({format_duration(daily_metrics.offline_gap)} OFF)"
                    else:
                        gaps_str = ""
                    base_duration = format_duration_tracked_prod(total_day_with_afk, daily_metrics.productive_duration)
                    right_part = f"{gaps_str}  {base_duration}" if gaps_str else base_duration
                    # Day total with right-side padding for pyramid shape
                    left_part = "       Day total:   "
                    full_line = left_part.ljust(width - len(right_part) - 9) + "  " + right_part
                    print(full_line.rstrip())
                if not is_single_day:
                    # Use online_duration only (not total_duration) since offline_gap is displayed separately
                    total_week_with_afk = weekly_metrics.online_duration
                    # Format offline time in gap notation if present
                    if weekly_metrics.offline_gap and weekly_metrics.offline_gap > timedelta(0):
                        gaps_str = f"({format_duration(weekly_metrics.offline_gap)} OFF)"
                    else:
                        gaps_str = ""
                    base_duration = format_duration_tracked_prod(total_week_with_afk, weekly_metrics.productive_duration)
                    right_part = f"{gaps_str}  {base_duration}" if gaps_str else base_duration
                    # Week total aligned with week header (0 spaces) for pyramid shape
                    left_part = "Week total (tracked):  "
                    full_line = left_part.ljust(width - len(right_part) - 2) + "  " + right_part
                    print(full_line.rstrip())
                print()
            current_week_key = slot_week
            week_number = group_slots[0]["start"].isocalendar()[1]
            week_str = f"W{week_number}"
            date_str = group_date.strftime("%Y-%m-%d")
            day_str = group_date.strftime("%a")
            pending_date_prefix = f"{week_str} {date_str} {day_str}"
            current_date = group_date
            daily_metrics = PeriodMetrics()
            weekly_metrics = PeriodMetrics()
            prev_date_was_rollup = False
        elif group_date != current_date:
            # Date changed within same week: close previous day
            if not prev_date_was_rollup:
                print(("-" * 22).rjust(width))
                # Use online_duration only (not total_duration) since offline_gap is displayed separately
                total_day_with_afk = daily_metrics.online_duration
                # Format offline time in gap notation if present
                if daily_metrics.offline_gap and daily_metrics.offline_gap > timedelta(0):
                    gaps_str = f"({format_duration(daily_metrics.offline_gap)} OFF)"
                else:
                    gaps_str = ""
                base_duration = format_duration_tracked_prod(total_day_with_afk, daily_metrics.productive_duration)
                right_part = f"{gaps_str}  {base_duration}" if gaps_str else base_duration
                # Day total indented like entries (7 spaces) for pyramid shape
                left_part = "       Day total:   "
                full_line = left_part.ljust(width - len(right_part) - 9) + "  " + right_part
                print(full_line.rstrip())
                print()
            daily_metrics = PeriodMetrics()
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

            # Check for gap before rendering
            if last_slot_end is not None:
                gap = offline_task_slot["start"] - last_slot_end
                if gap > gap_threshold:
                    _render_system_shutdown_separator()
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
            # Pass productive_duration from the offline_task slot for consistent productivity measurement
            productive_dur = slot.get("productive_duration", timedelta(0))
            duration_formatted = format_offline_task_duration(wall_clock_duration, event_duration, productive_dur)

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

            time_range = f"{start_str} - {end_str}".ljust(15)  # Pad for column alignment
            print(format_timeline_columns(
                time_range=time_range,
                project=abbrev_project,
                task=offline_task_name,
                gaps=gaps_str,
                duration=base_duration,
            ))

            # Accumulate offline_task to day/week totals using TimeslotDuration
            # for clear accounting of online vs offline time
            offline_ext = wall_clock_duration - event_duration
            slot_duration = TimeslotDuration(
                online_duration=event_duration if event_duration.total_seconds() > 0 else None,
                offline_gap=offline_ext if offline_ext.total_seconds() > 0 else None,
                afk_portion=None,  # offline tasks don't have separate AFK tracking
            )
            # Accumulate to daily and weekly metrics using PeriodMetrics
            daily_metrics.add_timeslot(slot_duration, productive=None)
            weekly_metrics.add_timeslot(slot_duration, productive=None)

            # Update last_slot_end for gap detection
            last_slot_end = offline_task_slot["start"] + wall_clock_duration

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
                time_range = f"{start_str}-{end_str}".ljust(15)  # Pad for column alignment
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

                # Check for gap before rendering
                if last_slot_end is not None:
                    gap = slot["start"] - last_slot_end
                    if gap > gap_threshold:
                        _render_system_shutdown_separator()

                task_name = slot["task"]
                abbrev_project = abbreviate_project_path(project_name, task_name)

                # Separate gaps from duration for column alignment
                if slot.get("type") == "afk":
                    slot_dur_str = format_afk_label(
                        slot.get("actual_duration", slot["duration"])
                    )
                    gaps_str = ""
                    base_duration = slot_dur_str
                elif slot.get("type") == "offline_task":
                    # For OFFLINE slots, display the actual_duration (online/tracked time)
                    # The duration field is the wall-clock span (offline+online)
                    display_duration = slot.get("actual_duration", timedelta(0))
                    gaps_str, base_duration = split_gaps_and_duration(
                        display_duration,
                        slot.get("productive_duration", timedelta(0)),
                        slot.get("afk_duration"),
                    )
                else:
                    # For regular slots, display the wall-clock duration (not TaskWarrior duration)
                    # This ensures the displayed duration matches the time range
                    display_duration = slot["duration"]
                    gaps_str, base_duration = split_gaps_and_duration(
                        display_duration,
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

                # Render embedded AFK slots as indented sub-entries
                embedded_afk = slot.get("embedded_afk_slots", [])
                if embedded_afk:
                    _render_embedded_afk_slots(embedded_afk, width)

                # Update last_slot_end for gap detection
                last_slot_end = slot["start"] + slot.get("actual_duration", slot["duration"])
            else:
                # Multiple slots for this project today — one row each
                for slot in group_slots:
                    # Check for gap before rendering
                    if last_slot_end is not None:
                        gap = slot["start"] - last_slot_end
                        if gap > gap_threshold:
                            _render_system_shutdown_separator()

                    s_start = slot["start"].strftime("%H:%M")
                    s_end = (slot["start"] + slot["duration"]).strftime("%H:%M")
                    task_name = slot["task"]
                    abbrev_project = abbreviate_project_path(project_name, task_name)

                    # Separate gaps from duration for column alignment
                    if slot.get("type") == "afk":
                        slot_dur_str = format_afk_label(
                            slot.get("actual_duration", slot["duration"])
                        )
                        gaps_str = ""
                        base_duration = slot_dur_str
                    elif slot.get("type") == "offline_task":
                        # For OFFLINE slots, display the actual_duration (online/tracked time)
                        # The duration field is the wall-clock span (offline+online)
                        # If --exclude-online is set, show 00:00:00 (omit online time reporting)
                        if exclude_online:
                            display_duration = timedelta(0)
                        else:
                            display_duration = slot.get("actual_duration", timedelta(0))
                        gaps_str, base_duration = split_gaps_and_duration(
                            display_duration,
                            slot.get("productive_duration", timedelta(0)),
                            slot.get("afk_duration"),
                        )
                    else:
                        # For regular slots, display the wall-clock duration (not TaskWarrior duration)
                        # This ensures the displayed duration matches the time range
                        display_duration = slot["duration"]
                        gaps_str, base_duration = split_gaps_and_duration(
                            display_duration,
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

                    # Render embedded AFK slots as indented sub-entries
                    embedded_afk = slot.get("embedded_afk_slots", [])
                    if embedded_afk:
                        _render_embedded_afk_slots(embedded_afk, width)

                    # Update last_slot_end for gap detection
                    last_slot_end = slot["start"] + slot.get("actual_duration", slot["duration"])

        # Accumulate totals using TimeslotDuration for clear accounting
        group_regular_duration = timedelta(0)
        group_regular_productive = timedelta(0)
        group_afk_duration = timedelta(0)

        for s in group_slots:
            slot_type = s.get("type")

            if slot_type == "afk":
                # AFK slots: pure idle time (100% AFK, still counts as online)
                # Display uses: actual_duration
                afk_duration = s.get("actual_duration", s["duration"])
                group_afk_duration += afk_duration
                # AFK-only slots are online time! Add to regular_duration so online total is correct
                group_regular_duration += afk_duration
            elif slot_type == "offline_task":
                # OFFLINE slots: display uses actual_duration
                offline_duration = s.get("actual_duration", timedelta(0))
                group_regular_duration += offline_duration
                afk_portion = s.get("afk_duration")  # May be None
                if afk_portion and afk_portion.total_seconds() > 0:
                    group_afk_duration += afk_portion
                productive_duration = s.get("productive_duration", timedelta(0))
                group_regular_productive += productive_duration
            else:
                # Regular (work) slots: display uses slot["duration"] (wall-clock)
                # Match what's displayed in rendering (line 983)
                displayed_duration = s["duration"]
                group_regular_duration += displayed_duration
                afk_portion = s.get("afk_duration")  # May be None
                productive_duration = s.get("productive_duration", timedelta(0))

                # CRITICAL FIX: Accumulate embedded AFK periods from combined work+AFK slots
                # When a work slot has embedded AFK (from combine_work_with_embedded_afk()),
                # the afk_duration field contains the total AFK time during that work period.
                # These must be accumulated separately to prevent undercounting AFK in metrics.
                if afk_portion and afk_portion.total_seconds() > 0:
                    group_afk_duration += afk_portion
                group_regular_productive += productive_duration

        # Accumulate group totals to daily and weekly metrics
        daily_metrics.add(
            online=group_regular_duration,
            afk=group_afk_duration,
            productive=group_regular_productive
        )
        weekly_metrics.add(
            online=group_regular_duration,
            afk=group_afk_duration,
            productive=group_regular_productive
        )
        prev_date_was_rollup = group_is_rollup

    # Print final totals
    if slots:
        print(("-" * 22).rjust(width))
        if not prev_date_was_rollup:
            # Use online_duration only (not total_duration) since offline_gap is displayed separately
            total_day_with_afk = daily_metrics.online_duration
            # Format offline time in gap notation if present
            if daily_metrics.offline_gap and daily_metrics.offline_gap > timedelta(0):
                gaps_str = f"({format_duration(daily_metrics.offline_gap)} OFF)"
            else:
                gaps_str = ""
            base_duration = format_duration_tracked_prod(total_day_with_afk, daily_metrics.productive_duration)
            right_part = f"{gaps_str}  {base_duration}" if gaps_str else base_duration
            # Day total indented like entries (7 spaces) for pyramid shape
            left_part = "       Day total:   "
            full_line = left_part.ljust(width - len(right_part) - 9) + "  " + right_part
            print(full_line.rstrip())
        # Use online_duration only (not total_duration) since offline_gap is displayed separately
        total_week_with_afk = weekly_metrics.online_duration
        if not is_single_day:
            # Format offline time in gap notation if present
            if weekly_metrics.offline_gap and weekly_metrics.offline_gap > timedelta(0):
                gaps_str = f"({format_duration(weekly_metrics.offline_gap)} OFF)"
            else:
                gaps_str = ""
            base_duration = format_duration_tracked_prod(total_week_with_afk, weekly_metrics.productive_duration)
            right_part = f"{gaps_str}  {base_duration}" if gaps_str else base_duration
            # Week total aligned with week header (0 spaces) for pyramid shape
            left_part = "Week total (tracked):  "
            full_line = left_part.ljust(width - len(right_part) - 2) + "  " + right_part
            print(full_line.rstrip())
        print()

    # Print TOTALS at bottom
    # Calculate "Online Time" (AFK + non-AFK combined, from AFK bucket)
    # In consolidated mode: AFK is already embedded in work slots (total_time_all = online time)
    # In non-consolidated mode: AFK is stored separately, so we add it to get online time
    total_time_final = (
        total_time_all + total_afk_time if not has_consolidated_afk else total_time_all
    )

    # Calculate "Active Time" (non-AFK only, focused work periods)
    # In consolidated mode: AFK is embedded in work slots, so subtract it from online time
    # In non-consolidated mode: total_time_all is already just non-AFK (no AFK embedded)
    if has_consolidated_afk and total_afk_time:
        true_non_afk = total_time_all - total_afk_time
    else:
        true_non_afk = total_time_all

    print_report_totals(
        total_time_all=total_time_final,
        total_productive_all=total_productive_all,
        total_afk=total_afk_time if total_afk_time > timedelta(0) else None,
        total_offline=total_offline_time if total_offline_time > timedelta(0) else None,
        total_non_afk=true_non_afk if true_non_afk > timedelta(0) else None,
    )


def print_period_consolidated_report(
    slots: List[Dict],
    period: str,
    start_time: datetime,
    end_time: datetime,
    period_mode: str,
    detail_level: int = 1,
    non_afk_time: Optional[timedelta] = None,
    productive_time: Optional[timedelta] = None,
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
        (_get_displayed_duration(s) for s in tracked), timedelta(0)
    )
    total_productive = sum(
        (s.get("productive_duration", timedelta(0)) for s in tracked), timedelta(0)
    )
    total_all = sum(
        (_get_displayed_duration(s) for s in all_regular), timedelta(0)
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
        total_offline_time=total_offline,
        total_time_all=total_all,
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

        # Accumulate totals and AFK/OFFLINE for all rows first
        for row in rows_to_display:
            duration = row.get("actual_duration", row["duration"])
            offline_ext = row.get("offline_extension_duration", timedelta(0))
            display_duration = duration + offline_ext
            productive = row.get("productive_duration", timedelta(0))
            total_dur += display_duration
            total_prod += productive
            period_afk += row.get("afk_duration", timedelta(0))
            period_offline += row.get("offline_extension_duration", timedelta(0))

        # Render based on detail level
        if detail_level == 1:
            # Project only: render flat list
            for row in rows_to_display:
                project = row["project"]
                duration = row.get("actual_duration", row["duration"])
                offline_ext = row.get("offline_extension_duration", timedelta(0))
                display_duration = duration + offline_ext
                productive = row.get("productive_duration", timedelta(0))
                duration_str = format_duration_tracked_prod(display_duration, productive)
                left = f"     ▶ {project}"
                print(format_timeline_line(left, duration_str, max_left_width=95))
        else:
            # detail_level >= 2: group tasks by project
            # First, calculate project totals for sorting
            project_totals = {}
            for row in rows_to_display:
                proj = row["project"]
                dur = row.get("actual_duration", row["duration"]) + row.get("offline_extension_duration", timedelta(0))
                project_totals[proj] = project_totals.get(proj, timedelta(0)) + dur

            # Sort rows by project duration (descending), then by project name
            sorted_rows = sorted(rows_to_display, key=lambda r: (-project_totals[r["project"]].total_seconds(), r["project"]))

            for project, project_group in groupby(sorted_rows, key=lambda r: r["project"]):
                project_rows = list(project_group)

                # Calculate project total
                proj_duration = sum((r.get("actual_duration", r["duration"]) + r.get("offline_extension_duration", timedelta(0)) for r in project_rows), timedelta(0))
                proj_productive = sum((r.get("productive_duration", timedelta(0)) for r in project_rows), timedelta(0))

                # Render project header
                duration_str = format_duration_tracked_prod(proj_duration, proj_productive)
                left = f"     ▶ {project}"
                print(format_timeline_line(left, duration_str, max_left_width=95))

                # Render tasks under this project
                for row in project_rows:
                    task = row.get("task", NO_TASK)
                    duration = row.get("actual_duration", row["duration"])
                    offline_ext = row.get("offline_extension_duration", timedelta(0))
                    display_duration = duration + offline_ext
                    productive = row.get("productive_duration", timedelta(0))
                    duration_str = format_duration_tracked_prod(display_duration, productive)

                    if task and task != NO_TASK:
                        left = f"       ▶▶ {task}"
                    else:
                        left = f"       ▶▶ No task"
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
    # In consolidated mode, total_afk is embedded in total_all, so non-AFK = total_all - total_afk
    total_non_afk_all = total_all - total_afk if total_afk > timedelta(0) else total_all
    print_report_totals(
        total_time_all=total_all,
        total_productive_all=total_productive_all,
        total_afk=total_afk if total_afk > timedelta(0) else None,
        total_offline=total_offline if total_offline > timedelta(0) else None,
        total_non_afk=total_non_afk_all if total_non_afk_all > timedelta(0) else None,
    )


# --- Main Execution ---

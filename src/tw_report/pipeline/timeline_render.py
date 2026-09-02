"""Timeline report rendering (print to stdout).

Renders a detailed timeline of work sessions organized by date and week,
with support for consolidation and detail levels.

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
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from aw_core.models import Event

from tw_report.core.filtering import NO_PROJECT, NO_TASK
from tw_report.core.period import logical_date

if TYPE_CHECKING:
    from tw_report.core.report_slot import ReportTimelineSlot
from tw_report.pipeline.generation import MIN_EVENT_DURATION
from tw_report.pipeline.models import PeriodMetrics, TimeslotDuration
from tw_report.pipeline.report_render import print_report_summary, print_report_totals
from tw_report.utils.formatting import (
    format_afk_label,
    format_duration,
    format_duration_tracked_prod,
    format_timeline_line,
    get_terminal_width,
    truncate_title,
)

# BREAKS COLUMN FEATURE (Phase 3)
# Functions for calculating and rendering break durations between work slots

MIN_BREAK_DURATION = timedelta(minutes=5)  # Breaks < 5 min are tracking noise


def calculate_break_duration(slot_end: datetime, next_slot_start: datetime) -> timedelta:
    """Calculate break duration between two slots.

    Args:
        slot_end: End time of the current slot
        next_slot_start: Start time of the next slot

    Returns:
        Break duration (clamped to 0 minimum for overlapping slots)
    """
    gap = next_slot_start - slot_end
    return max(gap, timedelta(0))


def get_gap_between_slots(slot1: Dict[str, Any], slot2: Dict[str, Any]) -> timedelta:
    """Extract gap time between two slots.

    Args:
        slot1: First slot dict with 'start' and 'end' keys
        slot2: Second slot dict with 'start' and 'end' keys

    Returns:
        Gap duration between slot1.end and slot2.start
    """
    return calculate_break_duration(slot1["end"], slot2["start"])


def format_break_column(break_duration: Optional[timedelta]) -> str:
    """Format break duration for timeline column display.

    Args:
        break_duration: Break duration (None or timedelta)

    Returns:
        Formatted string "HH:MM:SS" (8 chars) or blank (8 spaces)
    """
    if break_duration is None or break_duration < MIN_BREAK_DURATION:
        return " " * 8  # 8 spaces for consistent column width

    return format_duration(break_duration)


# MODULE-LEVEL SLOT GROUPING FUNCTIONS (extracted from print_timeline_report)
# These are separated to enable unit testing and reuse


def compute_afk_offline_totals(slots: List["ReportTimelineSlot"]) -> Tuple[timedelta, timedelta]:
    """Compute total AFK and Offline duration from normalized report slots.

    This calculation is used by both timeline and hierarchical reports to ensure
    consistent TOTALS display. It mirrors the logic at print_timeline_report():663-701.

    Returns:
        (total_afk_time, total_offline_time) tuple of timedeltas
    """
    # Check if slots have afk_duration field (from consolidation)
    has_consolidated_afk = any(s.afk_duration is not None for s in slots)

    if has_consolidated_afk:
        # Consolidated slots: AFK time is in afk_duration field
        total_afk_time = sum(
            (slot.afk_duration or timedelta(0) for slot in slots),
            timedelta(0),
        )
    else:
        # Regular slots: AFK time is in is_afk_only slots
        afk_slots = [s for s in slots if s.is_afk_only]
        total_afk_time = sum(
            (slot.actual_duration if slot.actual_duration else slot.duration for slot in afk_slots),
            timedelta(0),
        )

    # Calculate total OFFLINE time
    def get_offline_duration(s):
        # Prefer offline_extension_duration if set (consolidated slots)
        if hasattr(s, 'offline_extension_duration') and s.offline_extension_duration:
            return s.offline_extension_duration
        # Fall back to duration - event_duration (pre-consolidation slots)
        return s.duration - (s.event_duration or timedelta(0))

    total_offline_time = sum(
        (get_offline_duration(s) for s in slots if s.is_offline_task),
        timedelta(0),
    )

    return total_afk_time, total_offline_time


def get_slot_week_key(slot: Union[Dict, "ReportTimelineSlot"], day_start_hour: int = 4) -> str:
    """Get ISO week key for a slot based on its logical date.

    Calculates which ISO week a slot belongs to, accounting for day_start_hour.
    This ensures consistent week assignment when logical day != calendar day.

    Args:
        slot: Timeline slot (dict or ReportTimelineSlot object)
        day_start_hour: Hour when logical day starts (0-23, default 4)

    Returns:
        ISO week key string in format 'YYYY-Www' (e.g., '2026-W35')

    Example:
        >>> from datetime import datetime
        >>> slot = {"start": datetime(2026, 8, 31, 22, 0)}
        >>> get_slot_week_key(slot, day_start_hour=4)
        '2026-W36'
    """
    if isinstance(slot, dict):
        start_time = slot.get("start")
    else:
        start_time = slot.start

    logical_dt = logical_date(start_time, day_start_hour)
    iso_year, iso_week, iso_weekday = logical_dt.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def get_slot_logical_date(slot: Union[Dict, "ReportTimelineSlot"], day_start_hour: int = 4):
    """Get logical date for a slot.

    Determines which logical day a slot belongs to, accounting for day_start_hour.
    Logical days start at day_start_hour instead of midnight.

    Args:
        slot: Timeline slot (dict or ReportTimelineSlot object)
        day_start_hour: Hour when logical day starts (0-23, default 4)

    Returns:
        datetime.date object representing the logical day

    Example:
        >>> from datetime import datetime
        >>> slot = {"start": datetime(2026, 9, 1, 2, 30)}
        >>> get_slot_logical_date(slot, day_start_hour=4)
        datetime.date(2026, 8, 31)  # Still in previous logical day
    """
    if isinstance(slot, dict):
        start_time = slot.get("start")
    else:
        start_time = slot.start

    return logical_date(start_time, day_start_hour)


def _to_local_time(dt: datetime) -> datetime:
    """Convert UTC datetime to local timezone.

    Fixes timezone display issue where UTC times were shown as local times.

    Args:
        dt: Datetime in UTC (typically from ActivityWatch)

    Returns:
        Datetime converted to local timezone, with timezone info preserved
    """
    if dt.tzinfo is None or dt.tzinfo == timezone.utc:
        # UTC-aware or naive UTC datetime
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone()
    return dt


def _render_system_shutdown_separator(break_duration: Optional[timedelta] = None, width: int = 180) -> None:
    """Print a break row showing duration between work sessions.

    Args:
        break_duration: Duration of the break (gap between slots)
        width: Terminal width for alignment (default 180)
    """
    from tw_report.utils.formatting import display_width, ljust_display

    # Use the BREAK column to show break duration
    break_col = format_break_column(break_duration)

    # Left section: empty (for alignment with time column)
    left_section = " " * 87  # Match header_left_section width

    # Right section: BREAK column + empty OFFLINE/AFK/ACTIVE (8 + 12 + 12 + 8 + 14 = 54)
    right_section = (ljust_display(break_col, 8) +
                     ljust_display("", 12) +  # OFFLINE blank
                     ljust_display("", 12) +  # AFK blank
                     ljust_display("", 8) +   # ACTIVE blank
                     ljust_display("", 14))   # PRODUCTIVITY blank

    # Build break row with proper alignment
    left_section_width = display_width(left_section)
    right_section_width = display_width(right_section)
    left_padding = width - left_section_width - right_section_width - 2

    if left_padding < 0:
        break_line = left_section + "  " + right_section
    else:
        break_line = left_section + (" " * left_padding) + "  " + right_section

    print(break_line.rstrip())


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
        s_start = _to_local_time(afk_slot.start).strftime("%H:%M")
        s_end = _to_local_time(afk_slot.start + afk_slot["duration"]).strftime("%H:%M")
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


def _get_displayed_duration(slot: Union[Dict, "ReportTimelineSlot"]) -> timedelta:
    """Return the duration that's actually displayed for this slot.

    Matches the exact logic used in rendering code to ensure totals are consistent:
    - AFK slots: prefer actual_duration over duration
    - OFFLINE tasks: prefer actual_duration over duration
    - Regular slots: use wall-clock duration

    This ensures day/week/report totals sum to the displayed entries.

    Args:
        slot: A timeline slot (dict or ReportTimelineSlot object)

    Returns:
        The duration as displayed in the output
    """
    if isinstance(slot, dict):
        slot_type = slot.get("type")
        if slot_type == "afk":
            # AFK slots: prefer actual_duration
            return slot.get("actual_duration", slot.get("duration", timedelta(0)))
        elif slot_type == "offline_task":
            # OFFLINE tasks: prefer actual_duration
            return slot.get("actual_duration", timedelta(0))
        else:
            # Regular slots: use wall-clock duration
            return slot.get("duration", timedelta(0))
    else:
        # ReportTimelineSlot object
        if slot.is_afk_only:
            # AFK slots: prefer actual_duration
            return slot.actual_duration if slot.actual_duration else slot.duration
        elif slot.is_offline_task:
            # OFFLINE tasks: prefer actual_duration
            return slot.actual_duration or timedelta(0)
        else:
            # Regular slots: use wall-clock duration
            return slot.duration


def split_slots_spanning_days(slots: List[Union[Dict, "ReportTimelineSlot"]], day_start_hour: int = 4) -> List[Union[Dict, "ReportTimelineSlot"]]:
    """Split slots that span multiple days into single-day pieces.

    Accepts both dicts and ReportTimelineSlot objects for backward compatibility.
    Uses ReportTimelineSlot.split_at_boundaries("day") for unified splitting logic.
    See core/report_slot.py for the actual implementation.

    Args:
        slots: List of slots (dicts or ReportTimelineSlot objects) that may span multiple days
        day_start_hour: Hour when a logical day starts (0-23, default 4)

    Returns:
        List of slots, with multi-day slots split into single-day pieces (same type as input)
    """
    from tw_report.core.report_slot import ReportTimelineSlot

    # Handle mixed input: convert dicts to ReportTimelineSlot, process, then convert back if needed
    input_is_dict = slots and isinstance(slots[0], dict)

    if input_is_dict:
        # Convert dicts to ReportTimelineSlot for processing
        report_slots = []
        for slot_dict in slots:
            try:
                rs = ReportTimelineSlot.from_dict(slot_dict)
                report_slots.append(rs)
            except Exception:
                # Backward compatibility: skip malformed slots
                continue
    else:
        report_slots = slots

    # Split each slot at day boundaries
    split_slots = []
    for slot in report_slots:
        split_slots.extend(slot.split_at_boundaries("day", day_start_hour))

    # Convert back to dicts if input was dicts
    if input_is_dict:
        return [s.to_dict() for s in split_slots]
    else:
        return split_slots


def filter_short_slots(slots: List[Union[Dict, "ReportTimelineSlot"]]) -> List[Union[Dict, "ReportTimelineSlot"]]:
    """Filter out slots shorter than MIN_EVENT_DURATION.

    After split_slots_spanning_days(), very small fragments can remain.
    This filter removes them to avoid cluttering the timeline display.

    Accepts both dicts and ReportTimelineSlot objects for backward compatibility.

    Args:
        slots: List of slots (dicts or ReportTimelineSlot objects)

    Returns:
        Filtered list with slots < MIN_EVENT_DURATION removed (same type as input)
    """
    result = []
    for slot in slots:
        duration = slot.get("duration", timedelta(0)) if isinstance(slot, dict) else slot.duration
        if duration >= MIN_EVENT_DURATION:
            result.append(slot)
    return result


def _render_slot_detail(slot: Union[Dict, "ReportTimelineSlot"], detail_level: int, width: int) -> None:
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
        categories = slot.get("categories", []) if isinstance(slot, dict) else slot.categories
        for cat_info in categories:
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



def format_and_print_day_total(daily_metrics, width):
    """Format and print day total with proper DisplayColumns alignment.

    Single source of truth for day total formatting used by all three code paths:
    - Week boundary closure
    - Date change within week
    - End-of-report totals
    """
    from tw_report.utils.formatting import display_width, ljust_display

    total_day_online = daily_metrics.online_duration
    indent = " " * 7
    day_total_label = "Day total:   "

    # OFFLINE column: show offline_gap without parentheses
    offline_col = ljust_display(
        (format_duration(daily_metrics.offline_gap)
         if daily_metrics.offline_gap and daily_metrics.offline_gap.total_seconds() > 0
         else ""), 12)
    # AFK column: show total AFK time from daily_metrics
    afk_col = ljust_display(
        (format_duration(daily_metrics.afk_duration)
         if daily_metrics.afk_duration and daily_metrics.afk_duration.total_seconds() > 0
         else ""), 12)
    # ACTIVE column: online_duration minus afk_duration (ACTIVE = ONLINE - AFK)
    active_duration = total_day_online - (daily_metrics.afk_duration or timedelta(0))
    active_col = ljust_display(format_duration(active_duration) if active_duration.total_seconds() > 0 else "", 8)
    productivity_col = ljust_display(
        "  " + f"[prod {(daily_metrics.productive_duration.total_seconds() / total_day_online.total_seconds() * 100) if total_day_online.total_seconds() > 0 else 0:>3.0f}%]"
        if daily_metrics.productive_duration and daily_metrics.productive_duration.total_seconds() > 0
        else "", 14)

    right_section = f"{offline_col}{afk_col}{active_col}{productivity_col}"
    left_part = ljust_display(f"{indent}{day_total_label}", 87)
    left_part_width = display_width(left_part)
    right_section_width = display_width(right_section)
    dynamic_left_padding = width - left_part_width - right_section_width - 2

    if dynamic_left_padding < 0:
        full_line = left_part + "  " + right_section
    else:
        full_line = left_part + (" " * dynamic_left_padding) + "  " + right_section
    print(full_line)


def format_and_print_day_total_displayed(
    displayed_offline: timedelta,
    displayed_afk: timedelta,
    displayed_active: timedelta,
    productive_duration: Optional[timedelta],
    width: int = 120,
    displayed_break: Optional[timedelta] = None,
) -> None:
    """Format and print day total using actual displayed column values.

    This is the accurate version that sums the actual values displayed in the timeline,
    rather than relying on potentially inflated accumulated metrics.

    Args:
        displayed_offline: Sum of OFFLINE column values displayed for the day
        displayed_afk: Sum of AFK column values displayed for the day
        displayed_active: Sum of ACTIVE column values displayed for the day
        productive_duration: Productive time in the day
        width: Terminal width for formatting
        displayed_break: Sum of break durations (gaps > 5 minutes) for the day
    """
    from tw_report.utils.formatting import display_width, ljust_display

    indent = " " * 7
    day_total_label = "Day total:   "

    # Format BREAK column
    break_col = ljust_display(
        format_duration(displayed_break) if displayed_break and displayed_break.total_seconds() > 0 else "",
        8
    )

    # Format each column using the actual displayed values
    offline_col = ljust_display(
        format_duration(displayed_offline) if displayed_offline and displayed_offline.total_seconds() > 0 else "",
        12
    )
    afk_col = ljust_display(
        format_duration(displayed_afk) if displayed_afk and displayed_afk.total_seconds() > 0 else "",
        12
    )
    active_col = ljust_display(
        format_duration(displayed_active) if displayed_active and displayed_active.total_seconds() > 0 else "",
        8
    )

    # Calculate online time as sum of afk + active
    total_online = (displayed_afk or timedelta(0)) + (displayed_active or timedelta(0))
    productivity_col = ljust_display(
        "  " + f"[prod {(productive_duration.total_seconds() / total_online.total_seconds() * 100) if total_online.total_seconds() > 0 else 0:>3.0f}%]"
        if productive_duration and productive_duration.total_seconds() > 0
        else "",
        14
    )

    right_section = f"{break_col}{offline_col}{afk_col}{active_col}{productivity_col}"
    left_part = ljust_display(f"{indent}{day_total_label}", 87)
    left_part_width = display_width(left_part)
    right_section_width = display_width(right_section)
    dynamic_left_padding = width - left_part_width - right_section_width - 2

    if dynamic_left_padding < 0:
        full_line = left_part + "  " + right_section
    else:
        full_line = left_part + (" " * dynamic_left_padding) + "  " + right_section
    print(full_line)


def print_timeline_report(
    slots: List[Union[Dict, "ReportTimelineSlot"]],
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
    current_session_start: Optional[datetime] = None,
    current_session_end: Optional[datetime] = None,
    current_session_duration: Optional[timedelta] = None,
    last_break_start: Optional[datetime] = None,
    last_break_end: Optional[datetime] = None,
    last_break_duration: Optional[timedelta] = None,
    afk_events: Optional[List[Event]] = None,
    day_start_hour: int = 4,
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

    PARAMETER NOTES:
      slots: Pre-filtered timeline slots from main() (EventFilter already applied)
      period: Human-readable period description (e.g., ":yesterday", "2026-07-01")
      detail_level: See above (1-5, typically 1-2 for most users)
      non_afk_time: Total Active Time (non-AFK) from metrics (for % calculations)
      productive_time: Total productive time from metrics
      (other metric parameters used for header display)
    """

    # Convert dicts to ReportTimelineSlot objects if needed (for backward compatibility with tests)
    from tw_report.core.report_slot import ReportTimelineSlot
    if slots and isinstance(slots[0], dict):
        converted_slots = []
        for slot_dict in slots:
            try:
                rs = ReportTimelineSlot.from_dict(slot_dict)
                converted_slots.append(rs)
            except Exception:
                # Skip malformed slots
                pass
        slots = converted_slots

    width = get_terminal_width()
    is_single_day = logical_date(start_time, day_start_hour) == logical_date(end_time, day_start_hour)


    # Use actual_duration for merged slots, duration for others
    # Include all slots (offline, regular, afk, offline_task) in totals
    # OFFLINE gaps represent system-off time and should be counted
    all_regular_slots = slots
    # Project-tracked time (excluding "No project assigned")
    tracked_slots = [s for s in all_regular_slots if s.project != NO_PROJECT]

    total_duration = sum(
        (_get_displayed_duration(slot) for slot in tracked_slots),
        timedelta(0),
    )
    total_productive_tracked = sum(
        (slot.productive_duration for slot in tracked_slots),
        timedelta(0),
    )

    # Total time including untracked (for "Total Time" display)
    # Use displayed durations: slot.duration for regular/AFK, actual_duration for OFFLINE
    total_time_all = sum(
        (_get_displayed_duration(slot) for slot in all_regular_slots),
        timedelta(0),
    )
    # Total productive time for all slots (including untracked)
    total_productive_all = sum(
        (slot.productive_duration for slot in all_regular_slots),
        timedelta(0),
    )

    # Calculate total AFK and OFFLINE time using the shared calculation
    # This ensures both timeline and hierarchical reports show identical TOTALS
    # CRITICAL: Calculate totals AFTER period-based consolidation, not here
    # Early calculation on pre-consolidation slots counts duplicates multiple times
    # See line ~1036 for the CORRECT calculation on deduplicated slots
    # Placeholder values will be replaced after consolidation
    total_afk_time = timedelta(0)
    total_offline_time = timedelta(0)

    # Calculate total_time_including_offline for Project Tracking percentage denominator
    # Project Tracking should be calculated as % of total time (online + offline)
    # This ensures the percentage matches the "Total Time" value displayed
    total_time_including_offline = total_time_all + total_offline_time

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
        afk_time=total_afk_time,
        total_time_all=total_time_including_offline,
    )

    if not slots:
        print("No activity found for the specified period.")

    # CRITICAL: Print date/week header with duration column labels on same line
    # ============================================================================
    # ALIGNMENT ISSUES FIXED (2026-07-28):
    # 1. Header must use IDENTICAL structure to DisplayColumns.format()
    # 2. Terminal width must be dynamic, not fixed positions
    # 3. Right section width MUST include ALL columns (even empty ones)
    #
    # PAST BUGS (lessons learned):
    # - Bug 1: Using fixed byte positions (89, 101, 113) instead of dynamic
    #   terminal_width padding. On wider terminals (150+ chars), columns
    #   appeared completely misaligned because labels stayed at 89 but
    #   durations moved to position 150+.
    #   Fix: Use same terminal_width calculation as DisplayColumns
    #
    # - Bug 2: Header missing PRODUCTIVITY column (14 chars) that DisplayColumns
    #   includes. This caused 14-char difference in right_section_width:
    #   - DisplayColumns: 46 width (12+12+8+14)
    #   - Header (broken): 32 width (12+12+8)
    #   Result: Different left_padding calculations = misalignment on all widths
    #   Fix: Include productivity column (14 empty spaces) in header
    #
    # - Bug 3: Using ljust() instead of ljust_display() for multi-byte UTF-8.
    #   ljust() counts bytes, not display width. With UTF-8 chars (▶, ñ, etc.),
    #   columns drifted. Fix: Use ljust_display() everywhere.
    # ============================================================================

    from tw_report.utils.formatting import display_width, ljust_display

    header_text = "Wk  Date       Day"

    # Match DisplayColumns.format() structure EXACTLY:
    # Left section: 7 indent + 13 time + 2 sep + 28 project + 2 sep + 35 task = 87
    header_left_visual_width = 87
    header_text_width = display_width(header_text)
    padding_to_left_section = header_left_visual_width - header_text_width

    header_left_section = header_text + (" " * padding_to_left_section)

    # CRITICAL: Right section MUST include ALL columns DisplayColumns uses
    # Format: BREAK(8) + OFFLINE(12) + AFK(12) + ACTIVE(8) + PRODUCTIVITY(14) = 54 total
    # If you add/remove/resize any duration column in DisplayColumns, update here too!
    header_right_section = (ljust_display("BREAK", 8) + ljust_display("OFFLINE", 12) +
                            ljust_display("AFK", 12) + ljust_display("ACTIVE", 8) +
                            ljust_display("", 14))

    # CRITICAL: Use SAME terminal_width as DisplayColumns for all calculations
    # Both header and data rows use this formula:
    #   left_padding = terminal_width - left_section_width - right_section_width - 2
    # If terminal_width differs between header and data, columns WILL NOT align.
    terminal_width = width
    left_section_width = display_width(header_left_section)
    right_section_width = display_width(header_right_section)
    left_padding = terminal_width - left_section_width - right_section_width - 2

    # Build header using IDENTICAL logic to DisplayColumns.format()
    if left_padding < 0:
        header_line = header_left_section + "  " + header_right_section
    else:
        header_line = header_left_section + (" " * left_padding) + "  " + header_right_section

    print(header_line)

    # BUG: Day/Week grouping inconsistency with day_start_hour (Session 2026-08-31)
    # ============================================================================
    # When day_start_hour is set (default 4), logical days start at 4 AM instead of midnight.
    # Currently: slot_week_key uses ISO calendar (strftime "%G-W%V"), but slot_date uses logical_date(day_start_hour).
    # Problem: These two calculations are INDEPENDENT, causing:
    #   1. Same calendar date split into multiple logical days → appears multiple times with separate totals
    #   2. Week numbers flip for same calendar date (W35, W36, W35, W36 for 2026-08-30)
    #   3. "Day total" lines don't accumulate properly — each logical day shown separately
    #
    # Example from session 2026-08-31 output:
    #   W35 2026-08-30 Sun [entries] Day total: 03:02:36
    #   W36 2026-08-30 Sun [entries] Day total: 03:18:44  ← WRONG: same calendar date, different totals!
    #   W35 2026-08-30 Sun [entries] Day total: 03:18:44
    #   W36 2026-08-30 Sun [entries] Day total: 03:51:56
    #
    # Root cause: slot_week_key uses calendar dates (via ISO calendar), not logical dates.
    # When logical day != calendar day, week numbers can differ for entries within same calendar day.
    #
    # Solution: Calculate week key from logical_date, not calendar strftime:
    #   OLD: slot.start.strftime("%G-W%V")  # Uses calendar date
    #   NEW: Derive week from logical_date(slot.start, day_start_hour) using Monday-start logic
    #        iso_week = logical_date.isocalendar()[1]
    #        week_key = f"{logical_date.year}-W{iso_week:02d}"
    #
    # This ensures:
    #   - Same logical day always in same week (no W35/W36 flipping)
    #   - Entries consolidated by logical day boundary, not calendar boundary
    #   - Week totals accumulate correctly
    #
    # Migration: Update slot_week_key() to use logical_date; update slot_week assignment at line 953.
    # Test: Run "tw-report --by-day :today" with day_start_hour=4; verify no day repeats with different weeks.

    # Use module-level grouping functions (extracted for testability)
    def slot_week_key(slot):
        """Return ISO week key based on LOGICAL date: 'YYYY-Www' (e.g., '2026-W17')"""
        return get_slot_week_key(slot, day_start_hour)

    def slot_date(slot):
        """Return slot logical date"""
        return get_slot_logical_date(slot, day_start_hour)

    # Split slots spanning multiple days
    slots = split_slots_spanning_days(slots, day_start_hour)

    # Filter out slots shorter than MIN_EVENT_DURATION (tracking noise)
    slots = filter_short_slots(slots)

    # Filter to only include slots within the requested date range
    # After splitting, we should only show portions that fall within [start_time, end_time)
    slots = [
        s for s in slots
        if s.start < end_time and (s.start + (s.actual_duration or s.duration)) > start_time
    ]

    # Recalculate total_time_all after filtering to match the displayed slots
    # Include OFFLINE gaps in totals (they represent system-off time)
    total_time_all = sum(
        (_get_displayed_duration(slot) for slot in slots),
        timedelta(0),
    )
    total_productive_all = sum(
        (slot.productive_duration for slot in slots),
        timedelta(0),
    )

    # Sort slots by start time
    slots = sorted(slots, key=lambda s: s.start)

    # Filter out slots where display time range equals zero (confusing display like "11:19 - 11:19")
    # These occur when slot["duration"] represents wall-clock time but is zero
    slots = [
        s for s in slots
        if s.duration > timedelta(milliseconds=100)  # > 100ms to handle rounding
    ]

    # Remove regular slots that overlap/fall within OFFLINE periods for the same task
    # OFFLINE slots represent untracked periods; showing both OFFLINE + regular slots creates
    # visual duplication and confusion.
    #
    # ARCHITECTURAL NOTE: This filtering should ideally happen at slot generation time
    # (OfflineTaskProcessor.consumed_window_event_ids in offline.py), not in rendering.
    # Currently kept here as the proper generation-layer fix requires additional investigation.
    offline_slots_by_task = {}
    # Helper to check if slot has event_duration (field-driven offline_task detection)
    def is_offline_task_slot(s):
        if isinstance(s, dict):
            return s.get("event_duration") is not None
        else:
            return getattr(s, "event_duration", None) is not None

    for slot in slots:
        if is_offline_task_slot(slot):
            key = (slot.project, slot.task)
            if key not in offline_slots_by_task:
                offline_slots_by_task[key] = []
            offline_slots_by_task[key].append(slot)

    # Remove regular slots that occur within OFFLINE periods
    # This includes:
    # 1. Regular slots for the same task (originally implemented)
    # 2. "No project assigned" unassigned slots (new fix for overlapping unassigned activity)
    filtered_slots = []
    all_offline_periods = []
    for offline_slots in offline_slots_by_task.values():
        for offline_slot in offline_slots:
            all_offline_periods.append((offline_slot.start, offline_slot.start + offline_slot.duration))


    for slot in slots:
        if is_offline_task_slot(slot):
            filtered_slots.append(slot)
        else:
            slot_start = slot.start
            slot_end = slot.start + slot.duration

            overlaps_offline = False

            # Check if slot is "No project assigned" - these should be removed if they overlap with ANY OFFLINE period
            if slot.project in [NO_PROJECT, "No project assigned", None, ""] or \
               slot.task in [NO_TASK, "No task assigned", None, ""]:
                # "No project assigned" slots should not overlap with any OFFLINE period
                # Use > (not >=) to allow slots that end exactly when OFFLINE starts (boundary touch is OK)
                for offline_start, offline_end in all_offline_periods:
                    if slot_start < offline_end and slot_end > offline_start:
                        overlaps_offline = True
                        break
            else:
                # Regular task slots: only remove if they match the same task as an OFFLINE period
                key = (slot.project, slot.task)
                if key in offline_slots_by_task:
                    for offline_slot in offline_slots_by_task[key]:
                        offline_start = offline_slot.start
                        offline_end = offline_start + offline_slot.duration
                        if slot_start < offline_end and slot_end > offline_start:
                            overlaps_offline = True
                            break

            if not overlaps_offline:
                filtered_slots.append(slot)

    slots = filtered_slots

    # ============================================================================
    # PERIOD-AWARE CONSOLIDATION
    # ============================================================================
    # Consolidate slots by (project, task) within each logical period.
    # This ensures consolidation respects the rendering granularity:
    # - --by-day: consolidate within each day only
    # - --by-week: consolidate within each week only
    # - --by-month: consolidate within each month only
    # This prevents cross-period consolidation that creates 24+ hour entries.

    from tw_report.core.period import logical_date as get_logical_date

    # Group slots by logical period
    period_groups = {}
    for slot in slots:
        # Helper to get slot attribute (works with dict or object)
        def get_attr(s, attr):
            if isinstance(s, dict):
                return s.get(attr)
            else:
                return getattr(s, attr, None)

        # Get the logical date for this slot
        slot_start = get_attr(slot, "start")
        if slot_start:
            period_key = get_logical_date(slot_start, day_start_hour)
            if period_key not in period_groups:
                period_groups[period_key] = []
            period_groups[period_key].append(slot)

    # NOTE: Consolidation now happens in main.py before rendering,
    # so we skip it here to avoid double-consolidation which causes
    # small discrepancies in OFFLINE time calculations (17 sec differences).
    # The slots arriving here are already deduplicated and consolidated.
    # Just convert dicts to objects if needed and sort
    normalized_slots = []
    for slot in slots:
        if isinstance(slot, dict):
            normalized_slots.append(ReportTimelineSlot.from_dict(slot))
        else:
            normalized_slots.append(slot)
    slots = sorted(normalized_slots, key=lambda s: s.start)

    # CRITICAL: Recalculate total_time_all after all filtering/deduplication
    # The previous calculation (line 555) included slots that are now filtered out.
    # This must happen AFTER zero-duration filtering and OFFLINE deduplication.
    # Include OFFLINE gaps in totals (they represent system-off time)
    total_time_all = sum(
        (_get_displayed_duration(slot) for slot in slots),
        timedelta(0),
    )
    total_productive_all = sum(
        (slot.productive_duration for slot in slots),
        timedelta(0),
    )

    # RECALCULATE AFK and OFFLINE TOTALS POST-consolidation
    # Use consolidated slots for accuracy (avoids double-counting duplicates)
    # This replaces the early placeholder calculation at line 707

    # AFK time calculation (same logic as compute_afk_offline_totals)
    has_consolidated_afk = any(s.afk_duration is not None for s in slots if not isinstance(s, dict))
    if has_consolidated_afk:
        # Consolidated slots: AFK time is in afk_duration field
        total_afk_time = sum(
            (s.afk_duration or timedelta(0) for s in slots if not isinstance(s, dict) and s.afk_duration),
            timedelta(0),
        )
    else:
        # Regular slots: AFK time is in is_afk_only slots
        total_afk_time = sum(
            (s.actual_duration if s.actual_duration else s.duration
             for s in slots if not isinstance(s, dict) and s.is_afk_only),
            timedelta(0),
        )

    # OFFLINE time calculation
    def get_offline_duration(s):
        # Prefer offline_extension_duration if set (consolidated slots)
        if hasattr(s, 'offline_extension_duration') and s.offline_extension_duration:
            return s.offline_extension_duration
        # Fall back to duration - event_duration (pre-consolidation slots)
        return s.duration - (s.event_duration or timedelta(0))

    total_offline_time = sum(
        (get_offline_duration(s)
         for s in slots if not isinstance(s, dict) and s.is_offline_task),
        timedelta(0),
    )

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

    # Track displayed column values separately by summing the actual rendered values
    # This avoids metric calculation bugs and uses the source of truth: what's actually displayed
    daily_displayed_offline = timedelta(0)
    daily_displayed_afk = timedelta(0)
    daily_displayed_active = timedelta(0)
    daily_displayed_break = timedelta(0)
    weekly_displayed_offline = timedelta(0)
    weekly_displayed_afk = timedelta(0)
    weekly_displayed_active = timedelta(0)
    weekly_displayed_break = timedelta(0)

    # Track pending week total to print AFTER we have authoritative online_time from AFK bucket
    # This ensures week total uses same data source (AFK bucket) as TOTALS section
    pending_week_total_data = None  # Will store (productive_duration, offline_gap) when week ends

    # Slots are already sorted and filtered by this point (line 729).
    # Render each slot individually — no grouping.
    last_slot_end = None  # Track end time of last rendered slot (for gap detection)
    gap_threshold = timedelta(minutes=5)  # Minimum gap to display separator
    pending_date_prefix = None  # Date header held until the next slot prints

    # BUG: Intercalated day rendering in --by-day mode (Session 2026-08-31)
    # ================================================================
    # The grouping logic here uses slot_week (calendar-based ISO week) and slot_date_val (logical day).
    # When these two calculations are misaligned (due to day_start_hour), we get:
    #   1. Multiple entries for same calendar date (2026-08-30 appears 5+ times)
    #   2. Each appearance gets its own "Day total" line (should consolidate into ONE)
    #   3. Week numbers alternate (W35, W36, W35, W36) for same calendar date
    #
    # Current flow:
    #   - slot_week = slot.start.strftime("%G-W%V")  ← Uses calendar date
    #   - slot_date_val = slot_date(slot)            ← Uses logical date
    #   - When week changes: print week total, reset metrics, show new date header
    #   - When date changes (but week same): print day total, reset daily metrics only
    #   - But slot_week and slot_date_val can DISAGREE on boundaries
    #
    # Example: 2026-08-30 23:42-00:14 (spans logical day boundary at 04:00)
    #   - Calendar: both in 2026-08-30, both in W35
    #   - Logical (day_start_hour=4): split into 2026-08-30 (W35) and 2026-08-31 (W36)
    #   - Result: Same calendar date, different weeks → renders twice!
    #
    # Fix: Use logical_date for BOTH week and date calculations.
    # See slot_week_key() BUG comment above for implementation details.

    # Helper to check if slot has event_duration (field-driven offline_task detection)
    def is_offline_task_slot_v2(s):
        if isinstance(s, dict):
            return s.get("event_duration") is not None
        else:
            return getattr(s, "event_duration", None) is not None

    # Process each slot individually
    for slot in slots:
        slot_week = slot_week_key(slot)  # Now uses logical_date (fixed 2026-08-31)
        slot_date_val = slot_date(slot)
        is_offline_task = is_offline_task_slot_v2(slot)

        if slot_week != current_week_key:
            # Week changed: print previous week's closing totals
            if current_week_key is not None:
                # Separator under the three duration columns using SAME dynamic padding as DisplayColumns
                # CRITICAL: Must account for PRODUCTIVITY column (14 chars) to match DisplayColumns total_right_width (46)
                # Left section (87) + dynamic padding + separator (2) + dashes (32 for OFFLINE+AFK+ACTIVE) + spaces (14 for PRODUCTIVITY)
                left_padding_width = 87
                right_section_width = 46  # OFFLINE 12 + AFK 12 + ACTIVE 8 + PRODUCTIVITY 14 (must match DisplayColumns!)
                dynamic_padding = width - left_padding_width - right_section_width - 2
                dashes_for_columns = 32  # Only OFFLINE+AFK+ACTIVE get dashes, PRODUCTIVITY is spaces
                if dynamic_padding < 0:
                    separator_line = " " * left_padding_width + "  " + "-" * dashes_for_columns + " " * (right_section_width - dashes_for_columns)
                else:
                    separator_line = " " * left_padding_width + (" " * dynamic_padding) + "  " + "-" * dashes_for_columns + " " * (right_section_width - dashes_for_columns)
                print(separator_line)
                # Use displayed values for accurate day totals instead of accumulated metrics
                format_and_print_day_total_displayed(
                    daily_displayed_offline, daily_displayed_afk, daily_displayed_active,
                    daily_metrics.productive_duration, width, daily_displayed_break
                )
                if not is_single_day:
                    # DEFER week total printing until after we have authoritative online_time from AFK bucket
                    # Save the data for printing after the render loop
                    pending_week_total_data = (weekly_metrics.productive_duration, weekly_metrics.offline_gap)
                print()
            current_week_key = slot_week
            # Extract week number from week_key (format: 'YYYY-Www')
            week_number = int(current_week_key.split('-W')[1])
            week_str = f"W{week_number}"
            date_str = slot_date_val.strftime("%Y-%m-%d")
            day_str = slot_date_val.strftime("%a")
            pending_date_prefix = f"{week_str} {date_str} {day_str}"
            current_date = slot_date_val
            daily_metrics = PeriodMetrics()
            weekly_metrics = PeriodMetrics()
        elif slot_date_val != current_date:
            # Date changed within same week: close previous day
            if current_date is not None:
                # Separator under the three duration columns using SAME dynamic padding as DisplayColumns
                # CRITICAL: Must account for PRODUCTIVITY column (14 chars) to match DisplayColumns total_right_width (46)
                # Left section (87) + dynamic padding + separator (2) + dashes (32 for OFFLINE+AFK+ACTIVE) + spaces (14 for PRODUCTIVITY)
                left_padding_width = 87
                right_section_width = 46  # OFFLINE 12 + AFK 12 + ACTIVE 8 + PRODUCTIVITY 14 (must match DisplayColumns!)
                dynamic_padding = width - left_padding_width - right_section_width - 2
                dashes_for_columns = 32  # Only OFFLINE+AFK+ACTIVE get dashes, PRODUCTIVITY is spaces
                if dynamic_padding < 0:
                    separator_line = " " * left_padding_width + "  " + "-" * dashes_for_columns + " " * (right_section_width - dashes_for_columns)
                else:
                    separator_line = " " * left_padding_width + (" " * dynamic_padding) + "  " + "-" * dashes_for_columns + " " * (right_section_width - dashes_for_columns)
                print(separator_line)
                # Use displayed values for accurate day totals instead of accumulated metrics
                format_and_print_day_total_displayed(
                    daily_displayed_offline, daily_displayed_afk, daily_displayed_active,
                    daily_metrics.productive_duration, width, daily_displayed_break
                )
                print()
            daily_metrics = PeriodMetrics()
            daily_displayed_offline = timedelta(0)
            daily_displayed_afk = timedelta(0)
            daily_displayed_active = timedelta(0)
            daily_displayed_break = timedelta(0)
            date_str = slot_date_val.strftime("%Y-%m-%d")
            day_str = slot_date_val.strftime("%a")
            # Align same-week dates: 4 spaces + date + day
            pending_date_prefix = f"    {date_str} {day_str}"
            current_date = slot_date_val

        # Flush pending date header before rendering this slot
        if pending_date_prefix is not None:
            print(pending_date_prefix)
            pending_date_prefix = None

        # UNIFIED SLOT RENDERING (2026-07-30):
        # Single code path for ALL slot types (offline_task, regular, afk).
        # All slots are treated uniformly based on their properties, not special-cased by type.
        # This ensures consistent accumulation of OFFLINE/AFK/ACTIVE columns regardless of source.

        # Check for gap before rendering
        if last_slot_end is not None:
            gap = slot.start - last_slot_end
            if gap > gap_threshold:
                _render_system_shutdown_separator(break_duration=gap, width=width)
                # Accumulate break time to metrics
                daily_metrics.add(break_time=gap)
                weekly_metrics.add(break_time=gap)
                daily_displayed_break += gap
                weekly_displayed_break += gap

        # Extract slot properties uniformly (works for dict or object)
        def get_slot_attr(attr, default=None):
            if isinstance(slot, dict):
                return slot.get(attr, default)
            else:
                return getattr(slot, attr, default)

        slot_start = slot.start
        slot_end = slot.end if hasattr(slot, 'end') else slot.start + slot.duration
        slot_duration = slot.duration
        slot_online = slot.get("duration") if isinstance(slot, dict) else slot.duration
        slot_afk = get_slot_attr("afk_duration")
        slot_offline_ext = get_slot_attr("offline_extension_duration")
        slot_event_duration = get_slot_attr("event_duration")
        slot_actual_duration = get_slot_attr("actual_duration")
        slot_productive = get_slot_attr("productive_duration")

        # Special handling for offline_task display: prepend "*" to task name (field-driven)
        slot_for_display = slot.copy() if isinstance(slot, dict) else slot
        if slot_event_duration is not None and isinstance(slot_for_display, dict):
            if slot_for_display.get("task"):
                slot_for_display["task"] = f"*{slot_for_display['task']}"

        # For detail_level == 1, suppress task column by passing NO_TASK
        if detail_level == 1 and isinstance(slot_for_display, dict):
            slot_for_display["task"] = NO_TASK

        # Render slot with DisplayColumns (works for all slot types)
        slot_start_local = _to_local_time(slot_start)
        slot_end_local = _to_local_time(slot_end)

        from tw_report.core.report_slot import DisplayColumns
        cols = DisplayColumns.from_slot_dict(slot_for_display, slot_start_local, slot_end_local)
        print(cols.format(width))

        # Render detail (categories/apps/titles for detail_level >= 3)
        # Skip for offline_task slots (no window data) - field-driven check
        if slot_event_duration is None:
            _render_slot_detail(slot if isinstance(slot, dict) else slot.to_dict(), detail_level, width)

        # Render embedded AFK slots as indented sub-entries (should be empty now, defensive)
        if isinstance(slot, dict) and slot.get("embedded_afk_slots"):
            _render_embedded_afk_slots(slot["embedded_afk_slots"], width)

        # Update last_slot_end for gap detection (wall-clock duration for all slots)
        last_slot_end = slot_start + slot_duration

        # UNIFIED METRICS & ACCUMULATION (field-driven, no type discrimination):
        # All slots contribute their duration components to metrics.
        # Key insight: online_duration and offline_gap are computed from fields, not from type.
        # Consolidation allows a single slot to have multiple components (ACTIVE + AFK + OFFLINE).

        # Compute online and offline durations from component fields
        online_from_event = slot_event_duration or timedelta(0)  # Online time from offline_task split
        online_from_actual = slot_actual_duration or timedelta(0)  # Online time from active work (not AFK)
        online_duration = online_from_event + online_from_actual + (slot_afk or timedelta(0))
        online_duration = online_duration if online_duration.total_seconds() > 0 else None

        offline_gap = slot_offline_ext or timedelta(0)  # System-off time from offline_extension
        offline_gap = offline_gap if offline_gap.total_seconds() > 0 else None

        # Accumulate metrics (unified for all slot types)
        slot_duration_obj = TimeslotDuration(
            online_duration=online_duration,
            offline_gap=offline_gap,
            afk_portion=slot_afk,
        )
        daily_metrics.add_timeslot(slot_duration_obj, productive=slot_productive)
        weekly_metrics.add_timeslot(slot_duration_obj, productive=slot_productive)

        # UNIFIED COLUMN ACCUMULATION (field-driven):
        # Accumulate whatever columns are present in the slot, regardless of type.
        # Columns are determined by slot properties, not by type special-casing.

        # OFFLINE column: from offline_extension_duration (system-off time)
        if slot_offline_ext and slot_offline_ext.total_seconds() > 0:
            daily_displayed_offline += slot_offline_ext
            weekly_displayed_offline += slot_offline_ext

        # AFK column: from afk_duration field (idle time regardless of slot type)
        if slot_afk and slot_afk.total_seconds() > 0:
            daily_displayed_afk += slot_afk
            weekly_displayed_afk += slot_afk

        # ACTIVE column: from actual_duration field (online work time, not idle)
        slot_active = slot_actual_duration if slot_actual_duration is not None else timedelta(0)
        if slot_active and slot_active.total_seconds() > 0:
            daily_displayed_active += slot_active
            weekly_displayed_active += slot_active

    # Print final totals
    if slots:
        # Separator under the three duration columns using SAME dynamic padding as DisplayColumns
        # CRITICAL: Must account for PRODUCTIVITY column (14 chars) to match DisplayColumns total_right_width (46)
        left_padding_width = 87
        right_section_width = 46  # OFFLINE 12 + AFK 12 + ACTIVE 8 + PRODUCTIVITY 14 (must match DisplayColumns!)
        dynamic_padding = width - left_padding_width - right_section_width - 2
        dashes_for_columns = 32  # Only OFFLINE+AFK+ACTIVE get dashes, PRODUCTIVITY is spaces
        if dynamic_padding < 0:
            separator_line = " " * left_padding_width + "  " + "-" * dashes_for_columns + " " * (right_section_width - dashes_for_columns)
        else:
            separator_line = " " * left_padding_width + (" " * dynamic_padding) + "  " + "-" * dashes_for_columns + " " * (right_section_width - dashes_for_columns)
        print(separator_line)
        # CRITICAL FIX (2026-08-31): Use displayed values accumulated during rendering, not metrics
        # daily_metrics has ambiguous semantics; use the values actually accumulated in the display loop
        # daily_displayed_offline, daily_displayed_afk, daily_displayed_active are the canonical display values
        # BUG FIX: Use daily_displayed_active, NOT non_afk_time (which is the entire week's active time)
        daily_active = daily_displayed_active
        format_and_print_day_total_displayed(
            daily_displayed_offline,
            daily_displayed_afk,
            daily_active,
            daily_metrics.productive_duration, width
        )
        print()
        # Save final week's totals (flush at end of render loop)
        if not is_single_day:
            pending_week_total_data = (weekly_metrics.productive_duration, weekly_metrics.offline_gap)

    # Calculate authoritative online time from AFK bucket BEFORE printing week total
    # This ensures week total uses same data source (AFK bucket) as TOTALS section
    # Online time must satisfy: Online = Active Time + AFK Time
    # Active Time comes from non_afk_time (AFK bucket not-afk events)
    # AFK Time comes from total_afk_time (from final slots or AFK bucket afk events)
    #
    # Note: We use non_afk_time from AFK bucket (parameter) which is the authoritative
    # source, matching what the summary uses. This may differ from what slots show
    # if there's untracked/gap time in "No project assigned" slots.

    # Use non_afk_time parameter (from AFK bucket) as Active Time
    active_time_final = non_afk_time if non_afk_time else timedelta(0)

    # Online = Active + AFK (this ensures the mathematical relationship holds)
    online_time_final = active_time_final + total_afk_time

    # Total = Online + Offline (not passed to print_report_totals; calculated internally)
    total_time_final = online_time_final + total_offline_time

    # NOW print deferred week total using authoritative online_time_final
    if not is_single_day and pending_week_total_data is not None:
        productive_duration, offline_gap = pending_week_total_data
        # Format offline time in gap notation if present
        if offline_gap and offline_gap > timedelta(0):
            gaps_str = f"({format_duration(offline_gap)} OFF)"
        else:
            gaps_str = ""
        # Use authoritative online_time_final from AFK bucket (matches TOTALS section)
        base_duration = format_duration_tracked_prod(online_time_final, productive_duration)
        right_part = f"{gaps_str}  {base_duration}" if gaps_str else base_duration
        # Week total aligned with week header (0 spaces) for pyramid shape
        left_part = "Week total (tracked):  "
        full_line = left_part.ljust(width - len(right_part) - 2) + "  " + right_part
        print(full_line.rstrip())
        print()

    # DEBUG: Verify what we're actually passing to print_report_totals

    print_report_totals(
        total_time_all=online_time_final,
        total_productive_all=total_productive_all,
        total_afk=total_afk_time if total_afk_time > timedelta(0) else None,
        total_offline=total_offline_time if total_offline_time > timedelta(0) else None,
        total_non_afk=active_time_final if active_time_final > timedelta(0) else None,
    )

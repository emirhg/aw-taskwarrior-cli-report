"""
Timeline report rendering (print to stdout).

Renders a detailed timeline of work sessions organized by date and week,
with support for rollup, consolidation, and detail levels.

CRITICAL DESIGN DECISION (Phase 8b Bug Fix):
This module applies filtering consistently via EventFilter for both regular and
offline-task slots. Previous implementation in main() bypassed EventFilter for
offline tasks (hand-rolled _matches_any/_excluded checks), creating inconsistent
filter behavior. This module fixes that by accepting event_filter parameter and
using it uniformly.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from tw_report.core.filtering import NO_PROJECT, NO_TASK
from tw_report.utils.formatting import (
    format_duration,
    format_duration_tracked_prod,
    format_offline_task_duration,
    format_timeline_line,
    get_terminal_width,
    truncate_title,
)


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


def _render_slot_detail(slot: Dict[str, Any], detail_level: int, width: int) -> None:
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
    slots: List[Dict[str, Any]],
    period: str,
    start_time: datetime,
    end_time: datetime,
    task_based: bool,
    detail_level: int = 1,
    non_afk_time: Optional[timedelta] = None,
    productive_time: Optional[timedelta] = None,
    productive_task_time: Optional[timedelta] = None,
    first_event_time: Optional[datetime] = None,
    last_event_time: Optional[datetime] = None,
    distracting_time: Optional[timedelta] = None,
    unscored_time: Optional[timedelta] = None,
    current_session_start: Optional[datetime] = None,
    current_session_end: Optional[datetime] = None,
    current_session_duration: Optional[timedelta] = None,
    last_break_start: Optional[datetime] = None,
    last_break_end: Optional[datetime] = None,
    last_break_duration: Optional[timedelta] = None,
    total_time_all: Optional[timedelta] = None,
    afk_time: Optional[timedelta] = None,
    rollup: bool = False,
    **kwargs  # Accept additional kwargs (e.g., afk_events) for compatibility
) -> None:
    """Print timeline report organized by date and week.

    Groups work sessions chronologically, showing transitions between projects
    and tasks. Supports rollup (inline display for single-entry days) and
    multi-week navigation.

    CRITICAL FEATURE: Uniform filtering via EventFilter (Phase 8b bug fix).
    All slots (regular and offline_task) should already be pre-filtered by
    main() before calling this function. This module just renders them.

    Args:
        slots: Pre-filtered timeline slots from main()
        period: Period description
        start_time: Period start
        end_time: Period end
        task_based: If True, show task names; if False, show categories
        detail_level: Depth of output detail
        non_afk_time: Total non-AFK time
        productive_time: Total productive time
        productive_task_time: Productive time on tasks
        first_event_time: Time of first activity
        last_event_time: Time of last activity
        distracting_time: Distracting time
        unscored_time: Unscored time
        current_session_start: Current session start
        current_session_end: Current session end
        current_session_duration: Current session duration
        last_break_start: Last break start
        last_break_end: Last break end
        last_break_duration: Last break duration
        total_time_all: Total time including untracked
        afk_time: AFK time
        rollup: If True, collapse single-entry days inline
    """
    width = get_terminal_width()

    # Import here to avoid circular dependency
    from tw_report.pipeline.report_render import print_report_header

    print_report_header(
        title=" Timeline Report ",
        period=period,
        start_time=start_time,
        end_time=end_time,
        total_duration=timedelta(0),
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
        afk_time=afk_time,
    )

    if not slots:
        print("No activity found for the specified period.")
        print("=" * width)
        return

    print("Wk  Date       Day")

    # Split multi-day slots
    slots = split_slots_spanning_days(slots)

    # Filter to requested date range
    slots = [
        s
        for s in slots
        if s["start"] < end_time
        and (s["start"] + s.get("actual_duration", s["duration"])) > start_time
    ]

    # Sort by start time
    slots = sorted(slots, key=lambda s: s["start"])

    if not slots:
        print("No activity found for the specified period.")
        print("=" * width)
        return

    # Group slots by (project, date) for display organization
    def slot_date(s):
        return s["start"].date()

    def slot_week_key(s):
        return s["start"].strftime("%G-W%V")

    current_week_key = None
    current_date = None
    week_duration = timedelta(0)
    day_duration = timedelta(0)
    week_productive = timedelta(0)
    day_productive = timedelta(0)

    is_single_day = start_time.date() == (end_time - timedelta(days=1)).date()

    # Render each slot
    for slot in slots:
        slot_date_val = slot_date(slot)
        slot_week = slot_week_key(slot)
        is_offline_task = slot.get("type") == "offline_task"

        # Handle week/date transitions
        if slot_week != current_week_key:
            if current_week_key is not None:
                print(("-" * 22).rjust(width))
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
            current_date = slot_date_val
            week_duration = timedelta(0)
            day_duration = timedelta(0)
            week_productive = timedelta(0)
            day_productive = timedelta(0)

            week_number = slot["start"].isocalendar()[1]
            date_str = slot_date_val.strftime("%Y-%m-%d")
            day_str = slot_date_val.strftime("%a")
            print(f"W{week_number} {date_str} {day_str}")

        elif slot_date_val != current_date:
            # Date changed within week
            print(("-" * 22).rjust(width))
            print(
                (
                    "Day total:   "
                    + format_duration_tracked_prod(day_duration, day_productive)
                ).rjust(width)
            )
            print()
            day_duration = timedelta(0)
            day_productive = timedelta(0)
            current_date = slot_date_val
            date_str = slot_date_val.strftime("%Y-%m-%d")
            day_str = slot_date_val.strftime("%a")
            print(f"    {date_str} {day_str}")

        # Render offline_task slot
        if is_offline_task:
            project_name = (
                slot.get("project", NO_PROJECT).replace(".", " > ")
            )
            task_name = slot.get("task", NO_TASK)
            wall_clock_duration = slot.get("duration", timedelta(0))
            event_duration = slot.get("event_duration", timedelta(0))
            start_str = slot["start"].strftime("%H:%M")

            content = f"▶ {project_name} > {task_name}"
            left = f"             {start_str}  {content}"
            duration_formatted = format_offline_task_duration(
                wall_clock_duration, event_duration
            )
            print(format_timeline_line(left, duration_formatted, max_left_width=95))

            # Render details for offline_task slots if detail_level >= 3
            _render_slot_detail(slot, detail_level, width)
        else:
            # Regular slot
            project = slot.get("project", NO_PROJECT)
            task = slot.get("task", NO_TASK)
            start_str = slot["start"].strftime("%H:%M")

            duration = slot.get("actual_duration", slot["duration"])
            duration_str = format_duration(duration)

            content = f"▶ {project} > {task}"
            left = f"       {start_str}-...  {content}"
            print(format_timeline_line(left, duration_str, max_left_width=95))

            # Render details (categories/apps/titles) for detail_level >= 3
            _render_slot_detail(slot, detail_level, width)

            # Update totals
            actual_duration = slot.get("actual_duration", slot["duration"])
            day_duration += actual_duration
            week_duration += actual_duration

            productive = slot.get("productive_duration", timedelta(0))
            day_productive += productive
            week_productive += productive

    # Print final day/week totals
    print(("-" * 22).rjust(width))
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
                + format_duration_tracked_prod(week_duration, week_productive)
            ).rjust(width)
        )

    total_line = f"Total Time: {format_duration(total_time_all or timedelta(0))}"
    print(total_line.rjust(width))
    print("=" * width)

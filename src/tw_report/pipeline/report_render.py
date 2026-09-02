"""
Hierarchical report rendering (print to stdout).

Renders task-based or category-based hierarchical reports with productivity
metrics, detail levels, and sorting options. Used by the --timesheet output mode.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union

from tw_report.core.filtering import NO_PROJECT


def _to_local_time(dt: datetime) -> datetime:
    """Convert UTC datetime to local timezone.

    Fixes timezone display issue where UTC times were shown as local times.

    Args:
        dt: Datetime in UTC (typically from ActivityWatch)

    Returns:
        Datetime converted to local timezone, with timezone info preserved
    """
    if dt.tzinfo is None or dt.tzinfo == timezone.utc:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone()
    return dt
from tw_report.pipeline.models import ReportTotals
from tw_report.utils.formatting import (
    format_duration,
    format_duration_tracked_prod,
    get_terminal_width,
    sanitize_title,
    truncate_title,
)


def print_report_summary(
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
    total_offline_time: Optional[timedelta] = None,
    afk_time: Optional[timedelta] = None,
    total_time_all: Optional[timedelta] = None,
) -> None:
    """Print report header with SUMMARY section at the top.

    Displays period info and metrics in a clean aligned format at the top.

    Metric Semantics:
    - Active Time (non_afk_time): Keyboard/mouse focus time (non-AFK events only)
    - AFK Time: Away-from-keyboard idle periods (subset of Online Time)
    - Online Time: Total system recording time (Active + AFK combined) = non_afk_time + afk_time
    - Offline Time: System powered off during task work
    - Total Time: Online + Offline = full wall-clock duration
    - Project Tracking %: tracked_time / total_time × 100

    Note: AFK time is NOT shown in this SUMMARY section (it appears in TOTALS to avoid duplication).

    Args:
        title: Report title (centered with = padding)
        period: Period descriptor (e.g., ":today", ":yesterday")
        start_time: Start of report period
        end_time: End of report period
        total_duration: Total project-tracked time
        task_based: If True, show task-based metrics; if False, show category-based
        non_afk_time: Total Active Time (non-AFK only; focused work periods, must be present for metric display)
        productive_time: Total productive time
        productive_task_time: Productive time on tracked projects (task-based only)
        first_event_time: Time of first activity
        last_event_time: Time of last activity
        distracting_time: Time spent on distracting activities
        unscored_time: Time with no productivity score
        total_score: Overall productivity score
        current_session_start: Start of current work session
        current_session_end: End of current work session
        current_session_duration: Duration of current session
        last_break_start: Start of last break
        last_break_end: End of last break
        last_break_duration: Duration of last break
        total_offline_time: Total time system was offline (from OFFLINE-tagged tasks)
    """
    width = get_terminal_width()

    print(title.center(width, "="))

    # SUMMARY section: period, online tracking time, and metrics (NO AFK time)
    print("SUMMARY")
    print("─" * width)

    print(f"Period{' ' * (32 - 6)}{period} ({start_time.date()} to {end_time.date()})")

    # Show actual tracked activity window (first to last event) with duration if available
    if first_event_time and last_event_time:
        from tw_report.utils.formatting import format_duration
        tracked_duration = last_event_time - first_event_time
        duration_str = format_duration(tracked_duration)
        print(f"Tracked Activity{' ' * (32 - 16)}{duration_str}")

    if non_afk_time and first_event_time and last_event_time:
        # Calculate total tracking time for percentage denominator
        # Prefer total_time_all (online time: AFK + non-AFK combined) for accurate percentages
        # Fallback to non_afk_time + offline_time if total_time_all unavailable
        if total_time_all and total_time_all > timedelta(0):
            total_tracking_time = total_time_all
        else:
            # Fallback: sum individual time components (Active + AFK + Offline)
            afk_duration = afk_time if afk_time else timedelta(0)
            total_offline_duration = total_offline_time if total_offline_time else timedelta(0)
            total_tracking_time = non_afk_time + afk_duration + total_offline_duration

        # Display online time only (clarify it's not total)
        online_time_str = format_duration(non_afk_time)

        # Format time window from actual non-afk events
        first_date = first_event_time.date()
        last_date = last_event_time.date()
        first_time_str = _to_local_time(first_event_time).strftime("%H:%M")
        last_time_str = _to_local_time(last_event_time).strftime("%H:%M")

        time_window = f"{first_date} {first_time_str} to {last_date} {last_time_str}"

        summary_line = f"Active Time{' ' * (32 - 11)}{online_time_str} ({time_window})"
        print(summary_line)

        if task_based:
            # Calculate percentage against total tracking time (online + offline)
            task_time_pct = (
                (total_duration.total_seconds() / total_tracking_time.total_seconds() * 100)
                if total_tracking_time.total_seconds() > 0
                else 0
            )
            proj_track_str = f"{task_time_pct:.1f}% ({format_duration(total_duration)})"
            print(f"Project Tracking{' ' * (32 - 16)}{proj_track_str}")

            task_productive_pct = 0
            if productive_task_time and total_duration.total_seconds() > 0:
                task_productive_pct = (
                    productive_task_time.total_seconds()
                    / total_duration.total_seconds()
                    * 100
                )
            if task_time_pct > 0 and productive_task_time:
                focus_str = f"{task_productive_pct:.1f}% ({format_duration(productive_task_time)})"
                print(f"Focus time{' ' * (32 - 10)}{focus_str}")

            if productive_time and productive_task_time:
                untracked_productive_time = productive_time - productive_task_time
                untracked_productive_pct = (
                    (untracked_productive_time / total_tracking_time * 100)
                    if total_tracking_time
                    else 0
                )
                untracked_str = f"{untracked_productive_pct:.1f}% ({format_duration(untracked_productive_time)})"
                print(f"Untracked productivity{' ' * (32 - 21)}{untracked_str}")

        # Calculate productivity percentage of total time
        total_productive_pct = 0
        if productive_time and total_tracking_time.total_seconds() > 0:
            total_productive_pct = (
                productive_time.total_seconds() / total_tracking_time.total_seconds() * 100
            )

        if productive_time:
            overall_prod_str = f"{total_productive_pct:.1f}% ({format_duration(productive_time)})"
            print(f"Overall productivity{' ' * (32 - 19)}{overall_prod_str}")

        # Print distracting and unscored time (common to both modes)
        if distracting_time:
            distracting_pct = (
                (distracting_time / total_tracking_time * 100) if total_tracking_time else 0
            )
            distracting_str = f"{distracting_pct:.1f}% ({format_duration(distracting_time)})"
            print(f"Overall distracting time{' ' * (32 - 23)}{distracting_str}")

        if unscored_time:
            unscored_pct = (unscored_time / total_tracking_time * 100) if total_tracking_time else 0
            unscored_str = f"{unscored_pct:.1f}% ({format_duration(unscored_time)})"
            print(f"Unscored time{' ' * (32 - 12)}{unscored_str}")

        # Print current session and last break information
        if current_session_duration and current_session_start and current_session_end:
            session_start_str = _to_local_time(current_session_start).strftime("%H:%M")
            session_end_str = _to_local_time(current_session_end).strftime("%H:%M")
            session_str = f"{format_duration(current_session_duration)} ({session_start_str} to {session_end_str})"
            print(f"Current Session{' ' * (32 - 14)}{session_str}")

        # Only show Last Break if it's not due to offline time
        if last_break_duration and last_break_start and last_break_end:
            # Check if the break gap is primarily due to offline time
            break_is_offline_gap = (
                total_offline_time and
                last_break_duration > timedelta(hours=1) and
                total_offline_time > timedelta(0)
            )
            if not break_is_offline_gap:
                break_start_str = _to_local_time(last_break_start).strftime("%H:%M")
                break_end_str = _to_local_time(last_break_end).strftime("%H:%M")
                break_str = f"{format_duration(last_break_duration)} ({break_start_str} to {break_end_str})"
                print(f"Last Break{' ' * (32 - 10)}{break_str}")

    print("-" * width)


def print_report_totals(
    total_time_all: Union[timedelta, ReportTotals],
    total_productive_all: Optional[timedelta] = None,
    total_afk: Optional[timedelta] = None,
    total_offline: Optional[timedelta] = None,
    total_non_afk: Optional[timedelta] = None,
) -> None:
    """Print TOTALS section with hierarchical breakdown of time composition.

    Shows Total Time (grand total of all system-recorded time) with nested breakdown:
    - Online Time (AFK + non-AFK combined; time system was actively recording)
      - Active Time (non-AFK only; focused work periods)
      - AFK time (idle periods; system still recording)
    - Time Worked While System Offline (work done when system powered off)

    Supports both old-style raw parameters and new ReportTotals object:

    Old way (deprecated but still works):
        print_report_totals(
            total_time_all=timedelta(hours=17),
            total_productive_all=timedelta(hours=8),
            total_afk=timedelta(hours=1),
            total_offline=timedelta(hours=2),
            total_non_afk=timedelta(hours=15)
        )

    New way (recommended):
        totals = ReportTotals(
            online_time=timedelta(hours=17),
            productive_time=timedelta(hours=8),
            afk_time=timedelta(hours=1),
            offline_time=timedelta(hours=2)
        )
        print_report_totals(totals)

    Args:
        total_time_all: Either a ReportTotals object (new) or Online Time timedelta (old, deprecated)
        total_productive_all: (Old API) Grand total productive time
        total_afk: (Old API) Total AFK time (for nested breakdown, shown only if non-zero)
        total_offline: (Old API) Time Worked While System Offline (shown only if non-zero)
        total_non_afk: (Old API) Active Time — non-AFK time only (for nested breakdown, shown only if non-zero)
    """
    # Handle both old-style parameters and new ReportTotals object
    if isinstance(total_time_all, ReportTotals):
        # New API: accept ReportTotals object
        totals = total_time_all
        online_time = totals.online_time or timedelta(0)
        productive_time = totals.productive_time or timedelta(0)
        afk_time = totals.afk_time
        offline_time = totals.offline_time
        active_time = totals.active_time
    else:
        # Old API: accept raw timedelta parameters
        online_time = total_time_all or timedelta(0)
        productive_time = total_productive_all or timedelta(0)
        afk_time = total_afk
        offline_time = total_offline
        active_time = total_non_afk

    width = get_terminal_width()
    label_width = 48  # Fixed column position for all values (increased for proper indentation)

    print()
    print("TOTALS")
    print("─" * width)

    # Breakdown of online: Active (non-AFK) and AFK as further indented sub-lines (indented 4 spaces)
    if active_time and active_time > timedelta(0):
        active_str = format_duration(active_time)
        print(f"{'    Active Time'.ljust(label_width)}{' ' * 4}{active_str}")

    if afk_time and afk_time > timedelta(0):
        afk_str = format_duration(afk_time)
        print(f"{'    AFK time'.ljust(label_width)}{' ' * 4}{afk_str}")

    # Online (renamed from "Total Online time") as sub-level (indented 2 spaces)
    online_time_str = format_duration_tracked_prod(online_time, productive_time)
    print(f"{'  Online'.ljust(label_width)}{' ' * 2}{online_time_str}")

    # Offline tracked (renamed from "Time Worked While System Offline") as sub-level (indented 2 spaces) - only if present
    if offline_time and offline_time > timedelta(0):
        offline_str = format_duration(offline_time)
        print(f"{'  Offline tracked'.ljust(label_width)}{' ' * 2}{offline_str}")

    # Calculate grand total (online + offline) - last entry (no indent)
    grand_total = online_time + (offline_time if offline_time else timedelta(0))
    grand_total_str = format_duration_tracked_prod(grand_total, productive_time)
    print(f"{'Total Time'.ljust(label_width)}{grand_total_str}")

    print("=" * width)


def print_summary_total(
    total_duration: timedelta,
    productive_duration: Optional[timedelta] = None,
    total_score: Optional[float] = None,
) -> None:
    """Print summary total line with duration and productivity.

    Used by both hierarchical and timeline reports for consistent output format.
    Displays: Total Time: HH:MM:SS  [prod XX%]
    Right-aligned to terminal width for visual consistency.

    Args:
        total_duration: Total duration to display
        productive_duration: Optional productive time within total (for % calculation)
        total_score: Optional total productivity score (not used in output, for compatibility)
    """
    width = get_terminal_width()
    summary_line = f"Total Time: {format_duration_tracked_prod(total_duration, productive_duration or timedelta(0))}"
    print(summary_line.rjust(width))


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
) -> None:
    """Print shared report header with period, active time, and productivity metrics.

    Used by both hierarchical (print_report) and timeline reports to avoid duplication.
    Handles task-based and non-task-based display modes. Optional parameters allow
    flexible use across different report types.

    Args:
        title: Report title (will be centered and padded with =)
        period: Period descriptor (e.g., ":today", ":yesterday", "2026-07-01 to 2026-07-02")
        start_time: Start of report period
        end_time: End of report period
        total_duration: Total project-tracked time
        task_based: If True, show task-based metrics; if False, show category-based
        non_afk_time: Total non-AFK time (must be present for metric display)
        productive_time: Total productive time
        productive_task_time: Productive time on tracked projects (task-based only)
        first_event_time: Time of first activity (for time window calculation)
        last_event_time: Time of last activity (for time window calculation)
        distracting_time: Time spent on distracting activities
        unscored_time: Time with no productivity score
        total_score: Overall productivity score
        current_session_start: Start of current work session
        current_session_end: End of current work session
        current_session_duration: Duration of current session
        last_break_start: Start of last break
        last_break_end: End of last break
        last_break_duration: Duration of last break
        total_time_all: Total time including untracked (fallback if detailed metrics unavailable)
        afk_time: Time spent away from keyboard
    """
    width = get_terminal_width()

    print(title.center(width, "="))
    print(f"Period: {period} ({start_time.date()} to {end_time.date()})")

    if non_afk_time and first_event_time and last_event_time:
        # Calculate total active time (non-AFK + AFK)
        total_active_time = non_afk_time + (afk_time if afk_time else timedelta(0))
        active_time_str = format_duration(total_active_time)
        afk_str = format_duration(afk_time) if afk_time else None

        # Format time window from actual non-afk events
        first_date = first_event_time.date()
        last_date = last_event_time.date()
        first_time_str = _to_local_time(first_event_time).strftime("%H:%M")
        last_time_str = _to_local_time(last_event_time).strftime("%H:%M")

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
                (untracked_productive_time / non_afk_time * 100)
                if non_afk_time
                else 0
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
                (untracked_productive_time / non_afk_time * 100)
                if non_afk_time
                else 0
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
            print(f"  • Unscored time: {unscored_pct:.1f}% ({format_duration(unscored_time)})")

        # Print current session and last break information
        if current_session_duration and current_session_start and current_session_end:
            session_start_str = _to_local_time(current_session_start).strftime("%H:%M")
            session_end_str = _to_local_time(current_session_end).strftime("%H:%M")
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
        # Minimal header when detailed metrics unavailable
        display_total = (
            total_time_all if total_time_all is not None else total_duration
        )
        header = f"Total Time: {format_duration(display_total)}"
        if total_score is not None:
            score_header = f"Productivity Score: {total_score:.2f}"
            print(header.ljust(width - len(score_header)) + score_header)
        else:
            print(header)
        print("-" * width)


def print_report(
    report_data: Dict[str, Any],
    period: str,
    start_time: datetime,
    end_time: datetime,
    task_based: bool,
    detail_level: int = 4,
    non_afk_time: Optional[timedelta] = None,
    productive_time: Optional[timedelta] = None,
    productive_task_time: Optional[timedelta] = None,
    first_event_time: Optional[datetime] = None,
    last_event_time: Optional[datetime] = None,
    distracting_time: Optional[timedelta] = None,
    unscored_time: Optional[timedelta] = None,
    sort_by_duration: bool = False,
    sort_by_score: bool = True,
    current_session_start: Optional[datetime] = None,
    current_session_end: Optional[datetime] = None,
    current_session_duration: Optional[timedelta] = None,
    last_break_start: Optional[datetime] = None,
    last_break_end: Optional[datetime] = None,
    last_break_duration: Optional[timedelta] = None,
    afk_time: Optional[timedelta] = None,
    total_offline_time: Optional[timedelta] = None,
    total_time_all: Optional[timedelta] = None,
) -> None:
    """Print hierarchical report (project-based or category-based).

    Renders a detailed, multi-level report of activities and productivity.
    Task-based mode shows: Project > Task > Category > App > Title hierarchy.
    Category-based mode shows: Category > App > Title hierarchy.

    Args:
        report_data: Hierarchical dict of projects/categories and their breakdown
        period: Period description
        start_time: Period start
        end_time: Period end
        task_based: If True, show task hierarchy; if False, show category hierarchy
        detail_level: Depth of output (1=top-level only, up to 5=window titles)
        non_afk_time: Total non-AFK time for metrics
        productive_time: Total productive time
        productive_task_time: Productive time on tasks (task-based only)
        first_event_time: Time of first activity
        last_event_time: Time of last activity
        distracting_time: Distracting time
        unscored_time: Unscored time
        sort_by_duration: Sort by duration instead of score
        sort_by_score: Sort by productivity score (default)
        current_session_start: Current session start
        current_session_end: Current session end
        current_session_duration: Current session duration
        last_break_start: Last break start
        last_break_end: Last break end
        last_break_duration: Last break duration
    """
    width = get_terminal_width()

    def sort_items(items):
        """Sort items by duration or score based on flags."""
        if sort_by_duration:
            return sorted(items, key=lambda x: x[1]["total_duration"], reverse=True)
        elif sort_by_score:
            return sorted(items, key=lambda x: x[1]["prod_score"], reverse=True)
        else:
            return sorted(items)

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

    # Print SUMMARY at top
    print_report_summary(
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
        total_offline_time=total_offline_time or timedelta(0),
        afk_time=afk_time,
        total_time_all=total_time_all,
    )

    if not report_data:
        print("No activity found for the specified period.")

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

                if detail_level >= 3 and "titles" in a_data:
                    for title, title_data in sort_items(a_data["titles"].items()):
                        title_duration = format_duration(
                            title_data["total_duration"]
                        )
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

    # Print TOTALS at bottom
    # Calculate online time = active + afk
    online_time_for_totals = non_afk_time
    if afk_time:
        online_time_for_totals = (non_afk_time or timedelta(0)) + afk_time

    print_report_totals(
        total_time_all=online_time_for_totals,
        total_productive_all=productive_task_time or timedelta(0),
        total_afk=afk_time,
        total_offline=total_offline_time,
        total_non_afk=non_afk_time or total_duration,
    )

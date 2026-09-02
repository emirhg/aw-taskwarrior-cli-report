"""
tw-report CLI entry point with full orchestration.

Handles all argument parsing, data fetching, processing, and report generation.
"""

import sys
import os
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Optional, Tuple

# Unbuffered output for debugging long-running commands
if os.environ.get('TW_REPORT_DEBUG'):
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 1)
    sys.stderr = os.fdopen(sys.stderr.fileno(), 'w', 1)

# Profiling log file
_profile_log = None
_profile_start = time.perf_counter()

def _profile(stage_name):
    """Log timing checkpoint to profile execution."""
    global _profile_log, _profile_start
    if not _profile_log and os.environ.get('TW_REPORT_PROFILE'):
        _profile_log = open('/tmp/tw_report_profile.log', 'w', buffering=1)
    if _profile_log:
        elapsed = time.perf_counter() - _profile_start
        _profile_log.write(f'[{elapsed:7.2f}s] {stage_name}\n')
        _profile_log.flush()

from aw_client import ActivityWatchClient
from aw_core.models import Event
from aw_transform import filter_keyvals

if TYPE_CHECKING:
    pass

from tw_report.cli.args import parse_args, parse_positional_args
from tw_report.config import load_user_config, resolve_settings
from tw_report.core.categories import (
    categorize_event,
    compile_category_rules,
    get_category_score,
    load_categories,
)
from tw_report.core.events import (
    get_bucket_id,
    get_events,
)
from tw_report.core.filtering import NO_PROJECT, EventFilter

# OfflineTaskProcessor removed in Phase 2 refactor — builder handles offline classification
from tw_report.core.period import parse_period
from tw_report.core.project_filtering import (
    _is_uuid_like,
    get_events_by_project,
    resolve_project_filter_value,
)
from tw_report.core.report_slot import ReportEntries
from tw_report.core.task_filtering import (
    get_events_by_task,
    resolve_task_filter_value,
)
from tw_report.core.task_uuid_filtering import (
    get_events_by_uuid,
    get_task_uuid,
)
from tw_report.core.timeline import Timeline, TimelineSlot
from tw_report.core.timeslot_builder import build_timeslot_timeline

# generate_untracked_gap_events removed in Phase 2 refactor — builder handles gaps
from tw_report.pipeline.presenters import HierarchicalReport, TimelineReport
from tw_report.pipeline.processors import (
    aggregate_hierarchy_from_slots,
    build_context,
    compute_metrics,
    merge_overlapping_afk_periods,
)
from tw_report.pipeline.report_render import print_report
from tw_report.pipeline.timeline_render import print_timeline_report
from tw_report.utils.formatting import normalize_title


def _matches_any(name: str, patterns: Optional[List[str]], exact: bool) -> bool:
    """Check if name matches any pattern (case-insensitive substring or exact)."""
    if not patterns:
        return False
    return any(
        (exact and name.lower() == p.lower()) or (not exact and p.lower() in name.lower())
        for p in patterns
    )


def _excluded(name: str, exclusions: Optional[List[str]]) -> bool:
    """Check if name is in exclusion list (case-insensitive substring match)."""
    if not exclusions:
        return False
    return any(excl.lower() in name.lower() for excl in exclusions)


def _get_time_ranges_from_events(events: List[Event]) -> List[Tuple[datetime, datetime]]:
    """Extract non-overlapping time ranges from a list of events.

    Merges overlapping or adjacent events into continuous time windows.
    Used to optimize AFK/window fetching by only querying times when task events exist.
    """
    if not events:
        return []

    # Sort by start time
    sorted_events = sorted(events, key=lambda e: e.timestamp)
    ranges = []

    for event in sorted_events:
        event_start = event.timestamp
        event_end = event.timestamp + event.duration

        if ranges and ranges[-1][1] >= event_start:
            # Overlapping or adjacent: merge
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], event_end))
        else:
            # New range
            ranges.append((event_start, event_end))

    return ranges


def _fetch_events_for_ranges(
    client: ActivityWatchClient,
    bucket_name: str,
    time_ranges: List[Tuple[datetime, datetime]],
    event_cls: type = Event,
) -> List[Event]:
    """Fetch events from specified bucket for multiple time ranges.

    More efficient than fetching for entire period when events are sparse.

    Args:
        event_cls: Event subclass to use for re-wrapping events (WindowEvent, AFKEvent, TaskWarriorEvent)
    """
    events = []
    bucket_id = get_bucket_id(bucket_name)
    for start, end in time_ranges:
        # Add small buffer (1 second) to ensure boundary events are included
        buffer = timedelta(seconds=1)
        range_events = get_events(client, bucket_id, start - buffer, end + buffer, event_cls=event_cls)
        events.extend(range_events)
    return events


def main():
    """Main script logic: orchestrate data fetching, processing, and report generation."""
    _profile("MAIN START")
    args = parse_args()
    _profile("parse_args() done")
    client = ActivityWatchClient("tw-report")
    _profile("ActivityWatchClient created")

    # Load config file and resolve settings (CLI args > config file > defaults)
    user_config = load_user_config()
    resolved_settings = resolve_settings(
        cli_args={"day_start_hour": args.day_start_hour},
        user_config=user_config
    )
    day_start_hour = resolved_settings.day_start_hour

    # Determine grouping mode (default to --by-day)
    grouping_mode = None
    if args.by_project:
        grouping_mode = "project"
    elif args.by_day:
        grouping_mode = "day"
    elif args.by_week:
        grouping_mode = "week"
    elif args.by_month:
        grouping_mode = "month"
    elif args.by_year:
        grouping_mode = "year"
    else:
        # Default to by-day if no grouping mode specified
        grouping_mode = "day"

    # Parse positional arguments to separate period from search term
    period, search_term = parse_positional_args(args.args)
    args.search = search_term  # Set search term from positional args (None if not provided)

    # Adjust default period based on grouping mode (if no explicit period provided)
    if period == ":today":  # Only adjust if using the default period
        if grouping_mode == "week" and not any(arg.startswith(":") or arg[0].isdigit() for arg in args.args):
            period = ":week"
        elif grouping_mode == "month" and not any(arg.startswith(":") or arg[0].isdigit() for arg in args.args):
            period = ":month"
        elif grouping_mode == "year" and not any(arg.startswith(":") or arg[0].isdigit() for arg in args.args):
            period = ":year"

    # Resolve task UUID if --task-id is provided
    task_uuid = None
    if args.task_id:
        task_uuid = get_task_uuid(args.task_id)
        if not task_uuid:
            print(f"Error: Task {args.task_id} not found", file=sys.stderr)
            return 1

    # Detect task ID/UUID in a single --task value for efficient server-side
    # filtering (mirrors --task-id). Only applies when exactly one --task value
    # is given, since bucket-level fetch elsewhere only ever honors args.task[0].
    if not task_uuid and args.task and len(args.task) == 1:
        value = args.task[0]
        if value.isdigit():
            task_uuid = get_task_uuid(int(value))
        elif _is_uuid_like(value):
            task_uuid = value
        # If resolution fails, leave task_uuid as None — the existing
        # resolve_task_filter_value() call below will raise the correct
        # "not found" error for this same value.

    # Check if --project accidentally consumed a period token (e.g., :lastweek)
    # This happens when --project is used without an argument
    if args.project:
        for value in args.project:
            if value.startswith(':') and value in [':today', ':yesterday', ':week', ':lastweek', ':month', ':lastmonth', ':year', ':all']:
                print(f"Error: --project requires an argument. Did you mean to use a period ('{value}') without a filter?\n"
                      f"Correct usage: tw-report {value} --project PATTERN", file=sys.stderr)
                return 1

    # Resolve project filter values (may be task IDs, UUIDs, or literal patterns)
    if args.project:
        resolved_projects = []
        for value in args.project:
            resolved, error = resolve_project_filter_value(value)
            if error:
                print(f"Error: {error}", file=sys.stderr)
                return 1
            resolved_projects.append(resolved)
        args.project = resolved_projects

    # Resolve task filter values (may be task IDs, UUIDs, or literal patterns)
    if args.task:
        resolved_tasks = []
        for value in args.task:
            resolved, error = resolve_task_filter_value(value)
            if error:
                print(f"Error: {error}", file=sys.stderr)
                return 1
            resolved_tasks.append(resolved)
        args.task = resolved_tasks

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

    start_time, end_time = parse_period(period, day_start_hour)
    categories_json = load_categories(args.categories)
    compiled_categories, cat_score_map = compile_category_rules(categories_json)

    # Smart optimization: when filtering by task UUID, fetch task events FIRST,
    # then only fetch AFK/window events for the time ranges where tasks exist.
    # This dramatically reduces data volume for sparse task data.
    task_events_early = None
    task_time_ranges = None
    task_events = None  # Will be populated later; used for window-fetch decision

    if task_uuid and not args.no_taskwarrior:
        # Fetch task events first to determine what time windows we care about
        task_bucket = get_bucket_id("taskwarrior")
        task_events_early = get_events_by_uuid(
            client, task_bucket, start_time, end_time, task_uuid
        )
        if task_events_early:
            # Extract time ranges: only fetch AFK/window during these windows
            task_time_ranges = _get_time_ranges_from_events(task_events_early)

    window_events = []
    afk_events = []

    # Determine if we can SKIP windows (opt-out pattern, but constrained)
    is_filtered_task_mode = task_uuid or (args.project and not args.app) or (args.task and not args.app)
    can_skip_window = is_filtered_task_mode and args.detail_level <= 2 and grouping_mode in ["day", "week", "month", "year"]

    # For opt-out: fetch windows by default, skip only in constrained cases
    requires_window_data = not can_skip_window

    # AFK data is always needed for metrics and OFFLINE reconciliation
    requires_afk_data = True

    # Fetch AFK events (always required for metrics and OFFLINE reconciliation)
    if requires_afk_data:
        from tw_report.core.aw_events import AFKEvent

        if task_time_ranges:
            # Smart optimization: only fetch AFK for times when tasks exist
            # This dramatically reduces data volume for sparse task data (e.g., :year, :all)
            afk_events = _fetch_events_for_ranges(client, "afk", task_time_ranges, event_cls=AFKEvent)
        else:
            # No task time ranges: fetch entire period
            afk_bucket = get_bucket_id("afk")
            _profile(f"Fetching AFK events from {start_time.date()} to {end_time.date()}")
            afk_events = get_events(client, afk_bucket, start_time, end_time, event_cls=AFKEvent)
            _profile(f"Fetched {len(afk_events)} AFK events")

        # Filter AFK to only events overlapping task time ranges (if available)
        # CRITICAL: Only filter if task_time_ranges is non-empty. If no tasks exist,
        # we still need all AFK events to display untracked time and detect system state.
        if task_time_ranges:
            filtered_afk = []
            for afk_event in afk_events:
                afk_start = afk_event.timestamp
                afk_end = afk_start + afk_event.duration
                for task_start, task_end in task_time_ranges:
                    if afk_start < task_end and afk_end > task_start:
                        filtered_afk.append(afk_event)
                        break
            afk_events = filtered_afk
        # else: keep all AFK events if no tasks exist (showing untracked time)

    # ============================================================================
    # CRITICAL ARCHITECTURE: Window Bucket On-Demand Fetching (Phase 13)
    # ============================================================================
    # PRIMARY DATA SOURCE: AFK bucket (always fetched)
    # - Used for: metrics, OFFLINE reconciliation, untracked time detection
    # - Always available and sufficient for baseline reporting
    #
    # SECONDARY DATA SOURCE: Window bucket (ON-DEMAND ONLY)
    # - Purpose: Refine task event knowledge by partitioning into ACTIVE/AFK/OFFLINE
    # - Only fetched when: task_events exist AND we need detailed partitioning
    # - NOT fetched when: no tasks exist (nothing to partition) or task-only modes
    #
    # ARCHITECTURAL RULE: Window events are expensive (~10K events per day).
    # Do NOT fetch speculatively. Only fetch if we have TaskWarrior events
    # to refine with partitioning. If task_events is None, skip windows entirely.
    # ============================================================================

    # Fetch window events for AFK false positive detection via split_by_coverage()
    # Window events are needed to validate which AFK periods are real (have window coverage)
    # vs false positives (system was off). This is critical for accurate AFK/OFFLINE reporting.
    from tw_report.core.aw_events import WindowEvent

    if task_time_ranges:
        # Smart optimization: only fetch windows for times when tasks exist
        window_events = _fetch_events_for_ranges(client, "window", task_time_ranges, event_cls=WindowEvent)
    else:
        # No task time ranges: fetch entire period
        window_bucket = get_bucket_id("window")
        _profile(f"Fetching window events from {start_time.date()} to {end_time.date()}")
        window_events = get_events(client, window_bucket, start_time, end_time, event_cls=WindowEvent)
        _profile(f"Fetched {len(window_events)} window events")

    # Categorize all window events (including those during AFK periods)
    # This ensures generate_afk_and_offline_slots can extract categories for AFK slot details
    for event in window_events:
        categorize_event(event, compiled_categories)

    # Filter AFK events to only those that START within the requested period
    # (ActivityWatch sometimes returns events from outside the range if they overlap it)
    afk_events = [
        event for event in afk_events
        if event.timestamp >= start_time and event.timestamp < end_time
    ]

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

    task_events = task_events_early  # Use pre-fetched task events if available
    is_task_based_report = not args.no_taskwarrior

    if is_task_based_report and task_events is None:
        task_bucket = get_bucket_id("taskwarrior")
        # Apply bucket-level filtering based on query type
        if task_uuid:
            # Task UUID mode: filter by UUID (already fetched early, skip)
            task_events = task_events_early
        elif not requires_window_data and args.project:
            # Project filter mode (window not required): filter by project at bucket level
            task_events = get_events_by_project(
                client, task_bucket, start_time, end_time, args.project[0]
            )
        elif not requires_window_data and args.task:
            # Task filter mode (window not required): filter by task name at bucket level
            task_events = get_events_by_task(
                client, task_bucket, start_time, end_time, args.task[0]
            )
        else:
            # Normal mode: fetch all events
            task_events = get_events(client, task_bucket, start_time, end_time)
        if not task_events:
            task_events = None
            is_task_based_report = False
            # CRITICAL: Always keep window events for AFK false positive detection via split_by_coverage()
            # Even without tasks, we need windows to validate which AFK periods are real (have coverage)
            # vs false positives (system was off). Don't clear window_events here.

    # Calculate metrics (used by both report types)
    # Calculate period from ALL event sources (AFK + window + task) in UTC
    # Not just not_afk_events, since slots are built from all sources
    # Window events may start before AFK events, and task events may extend beyond both
    # CRITICAL: Keep calculations in UTC, convert to local ONLY for display
    # IMPORTANT: Exclude zero-duration events (metadata only) to match slot builder's behavior
    all_events_for_period_utc = []
    if not_afk_events:
        all_events_for_period_utc.extend(
            [(e.timestamp, e.timestamp + e.duration) for e in not_afk_events if e.duration > timedelta(0)]
        )
    if window_events:
        all_events_for_period_utc.extend(
            [(e.timestamp, e.timestamp + e.duration) for e in window_events if e.duration > timedelta(0)]
        )
    if task_events:
        all_events_for_period_utc.extend(
            [(e.timestamp, e.timestamp + e.duration) for e in task_events if e.duration > timedelta(0)]
        )

    first_event_time = None
    last_event_time = None
    if all_events_for_period_utc:
        # Keep in UTC for all calculations
        first_event_time = min(start for start, end in all_events_for_period_utc)
        last_event_time = max(end for start, end in all_events_for_period_utc)


    # PHASE 2 REFACTOR: Use unified builder instead of 5 scattered generators
    # Build non-overlapping slots directly from raw events
    from tw_report.core.report_slot import ReportTimelineSlot
    _profile("Starting slot building phase")

    # OPTIMIZATION: Filter raw events BEFORE building slots to avoid processing unused data
    # This significantly reduces slot-building overhead for filtered queries
    filtered_window_events = [
        e for e in window_events
        if not event_filter.app_patterns or any(
            event_filter._matches_any([e.app], [pattern])
            for pattern in event_filter.app_patterns
        )
    ] if hasattr(event_filter, 'app_patterns') and event_filter.app_patterns else window_events

    filtered_task_events = [
        e for e in (task_events or [])
        if event_filter.should_include_entry({
            'project': e.project if hasattr(e, 'project') else e.data.get('project', ''),
            'task': e.task if hasattr(e, 'task') else e.data.get('task', ''),
            'type': 'regular'
        })
    ] if task_events else None

    _profile(f"Building slots from {len(afk_events)} AFK, {len(filtered_window_events)} window, {len(filtered_task_events or [])} task events")
    final_slots = build_timeslot_timeline(
        afk_events=afk_events,  # Keep all AFK events (needed for time context)
        window_events=filtered_window_events,
        task_events=filtered_task_events or []
    )
    _profile(f"Built {len(final_slots)} slots")

    # Consolidate slots by (project, task) to merge multi-entry work sessions
    _profile("Starting consolidation")
    consolidated = ReportEntries(slots_list=final_slots)
    consolidated_slots = consolidated.consolidate_by_task().slots_list
    _profile(f"Consolidated to {len(consolidated_slots)} slots")

    # Tracked Activity from event times (includes all buckets: AFK + window + task)
    tracked_activity_from_slots = None
    if first_event_time and last_event_time:
        tracked_activity_from_slots = last_event_time - first_event_time

    # Apply EventFilter once (unified point, replaces 3 scattered implementations)
    # This is the ONLY filter application point for slots
    # Extract apps from slot categories for app-level filtering in consolidation modes
    def _get_apps_from_slot(slot):
        """Extract all unique app names from slot's categories."""
        apps = set()
        for cat_entry in (slot.categories or []):
            for app_entry in cat_entry.get("apps", []):
                app_name = app_entry.get("app", "")
                if app_name:
                    apps.add(app_name)
        return list(apps)

    all_slot_entries = [
        s.to_dict()
        for s in consolidated_slots
        if event_filter.should_include_entry({
            'project': s.project,
            'task': s.task,
            'app': "|".join(_get_apps_from_slot(s)) or "",  # Join multiple apps with |
            'type': 'regular' if s.project != NO_PROJECT else 'afk'
        })
        and not (args.exclude_non_project and s.project == NO_PROJECT)
    ]

    # PHASE 2 REFACTOR: Metrics computed from slots directly (no canonical_events bridge)
    # Slots already have categories populated by builder, enabling direct productivity scoring
    metrics = compute_metrics(
        consolidated_slots=consolidated_slots,
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
        detail_level=args.detail_level,
    )
    context = build_context(
        consolidated_slots=consolidated_slots,
        task_events=task_events,
        afk_events=afk_events,
        cat_score_map=cat_score_map,
        is_task_based_report=is_task_based_report,
        metrics=metrics,
    )
    # Use new slot-based hierarchy builder (Phase 2 refactor)
    report_data = aggregate_hierarchy_from_slots(
        consolidated_slots=consolidated_slots,
        task_based=(is_task_based_report and task_events is not None),
        cat_score_map=cat_score_map,
        get_category_score=get_category_score,
        normalize_title=normalize_title,
        event_filter=event_filter,
    )

    # PHASE 2 REFACTOR: No OfflineTaskProcessor needed
    # Builder handles offline/online classification correctly
    # Old duration-replacement logic eliminated

    # Generate timeline slots for BOTH period-based (day/week/month/year) and hierarchical reports
    # Both report modes need consistent AFK/Offline calculations, so slots are built unconditionally
    # The if/else below only controls which rendering mode (timeline vs hierarchical) is used

    # Use Timeline for internal slot management (Phase 3 migration)
    timeline = Timeline()

    # EVENT-BASED TIMESHEET APPROACH (2026-07-30):
    # For timesheet modes, use per-event OFFLINE task slots (one per event)
    # These are now included in partitioned_task_slots, so DON'T add them separately
    # to avoid duplication. Just document the approach for clarity.
    # (Previously added event_based_offline_slots separately at this point, but
    # that caused double-counting with partitioned_task_slots, so we skip it now.)

    # Build all timeline slots using the unified sweep-line builder
    # This produces guaranteed non-overlapping slots classified by active events
    report_slots = build_timeslot_timeline(
        afk_events=context.afk_events or [],
        window_events=window_events or [],
        task_events=context.task_events or [],
    )

    # Convert ReportTimelineSlot objects to dict format for downstream processing
    # Add the 'type' field based on slot discriminators
    def _infer_slot_type(slot):
        if slot.is_afk_only:
            return "afk"
        elif slot.is_offline_gap:
            return "offline"
        elif slot.is_offline_task:
            return "offline_task"
        else:
            return "regular"

    all_slot_entries = []
    for s in report_slots:
        slot_dict = s.to_dict()
        slot_dict["type"] = _infer_slot_type(s)
        all_slot_entries.append(slot_dict)

    # Apply EventFilter to the flat slot list
    # This is the single, unified filter application point (replaces 3 scattered implementations)
    all_slot_entries = [
        g
        for g in all_slot_entries
        if event_filter.should_include_entry(g, entry_type=g.get("type", "regular"))
        and not (args.exclude_non_project and g.get("project") == NO_PROJECT)
    ]

    # FIX: --exclude-afk removes AFK period slots from the timeline
    if args.exclude_afk:
        all_slot_entries = [g for g in all_slot_entries if g.get("type") != "afk"]

    # All timeline-based modes (--by-day/week/month/year and hierarchical/project)
    # Use the standard timeline rendering which shows chronological slots
    # Each slot renders independently: no combining of work slots with embedded AFK

    # Add all slot entries to timeline (auto-sorts on insertion)
    timeline.add_slots([TimelineSlot.from_dict(g) for g in all_slot_entries])

    # Convert timeline to ReportEntries for type normalization
    # CRITICAL: This converts "active_task"/"afk_task" types to standard "regular"/"afk" types
    # that the rendering code understands. Do NOT combine work with embedded AFK here.
    report_timeline = timeline.to_report_timeline()

    # NOTE: consolidate_by_task() is now called in the rendering layer (print_timeline_report)
    # so that consolidation respects the rendering period (day, week, month, year)
    # This prevents cross-period consolidation that would create entries spanning multiple days

    final_dicts = report_timeline.as_dicts()

    # Apply session-merging consolidation if --consolidate flag is set
    if args.consolidate:
        from tw_report.pipeline.consolidation import consolidate_sessions
        final_dicts = consolidate_sessions(final_dicts)

    # CRITICAL: Do NOT consolidate_by_task() on builder output!
    # The sweep-line builder produces GUARANTEED non-overlapping slots by construction.
    # Consolidating would merge non-contiguous gaps into one mega-slot, re-introducing overlaps.
    # Instead, use the raw builder output directly for rendering, and apply filtering.

    from tw_report.core.report_slot import ReportTimelineSlot
    from tw_report.pipeline.timeline_render import compute_afk_offline_totals

    # Convert final_dicts to ReportTimelineSlot objects for filtering
    report_slots = []
    for slot_dict in final_dicts:
        slot_obj = ReportTimelineSlot.from_dict(slot_dict)
        report_slots.append(slot_obj)

    # Apply EventFilter to slots BEFORE any metrics calculation
    # Totals should only include entries that match the applied filters
    filtered_slots = [
        s for s in report_slots
        if event_filter.should_include_entry(
            {
                'project': s.project,
                'task': s.task,
                'app': "|".join(_get_apps_from_slot(s)) or "",
                'type': 'regular'
            },
            entry_type='regular'
        )
    ]

    # Recalculate ALL metrics from filtered slots (non-overlapping by construction)
    slot_afk_time, slot_offline_time = compute_afk_offline_totals(filtered_slots)

    # Calculate filtered active time from builder output
    # Active time = actual_duration (work time without AFK)
    slot_active_time = sum(
        (s.actual_duration or timedelta(0) for s in filtered_slots),
        timedelta(0)
    )

    # Convert slots back to dicts for rendering (use raw builder output, NO filtering)
    # IMPORTANT: Rendering shows ALL slots (including AFK) while metrics can be filtered.
    # This is by design — the report shows complete timeline, but summary metrics respect filters.
    consolidated_dicts = [s.to_dict() if hasattr(s, 'to_dict') else s for s in report_slots]

    # Now determine which rendering mode to use: timeline (period-based) or hierarchical
    # BUG REPORTS:
    # 1. Month consolidation (--by-month) crashes: ValueError zero-duration slot in offline.py
    #    Root cause: OFFLINE slot duration calculation creates degenerate (start==end) slots
    #    Fix needed: offline_processor.get_synthetic_slot() duration validation
    # 2. Year consolidation (--by-year) hangs/timeouts: Possible O(n^2) or infinite loop
    #    Likely in period grouping or consolidation logic when spanning 56+ years of history
    #    Fix needed: Performance audit of consolidate_by_period() for large datasets
    _profile(f"Starting rendering phase with {len(consolidated_slots)} slots")
    if grouping_mode in ["day", "week", "month", "year"]:
        _profile(f"Rendering timeline report (period: {period})")
        TimelineReport(print_timeline_report).present(
            slots=consolidated_dicts,
            period=period,
            start_time=start_time,
            end_time=end_time,
            detail_level=args.detail_level,
            non_afk_time=slot_active_time,
            productive_time=context.metrics.productive_time,
            productive_task_time=context.metrics.productive_task_time,
            first_event_time=first_event_time,
            last_event_time=last_event_time,
            task_based=context.is_task_based_report,
            distracting_time=context.metrics.distracting_time,
            unscored_time=context.metrics.unscored_time,
            current_session_start=context.metrics.current_session_start,
            current_session_end=context.metrics.current_session_end,
            current_session_duration=context.metrics.current_session_duration,
            last_break_start=context.metrics.last_break_start,
            last_break_end=context.metrics.last_break_end,
            last_break_duration=context.metrics.last_break_duration,
            afk_events=afk_events,
            day_start_hour=day_start_hour,
            tracked_activity=tracked_activity_from_slots,
        )
    else:
        # Hierarchical (--by-project) report: use slot-based AFK/Offline calculations for consistency
        # If no task_events, treat as non-task-based report regardless of is_task_based_report
        report_task_based = (
            context.is_task_based_report and context.task_events is not None
        )

        # Use filtered slot-based metrics — same calculation as timeline report
        afk_time_calc = slot_afk_time if slot_afk_time > timedelta(0) else None
        total_offline_calc = slot_offline_time if slot_offline_time > timedelta(0) else None

        # Total online time = Active + AFK (using filtered active time)
        total_time_calc = None
        if slot_active_time:
            total_time_calc = slot_active_time + (afk_time_calc or timedelta(0))

        HierarchicalReport(print_report).present(
            report_data=report_data,
            period=period,
            start_time=start_time,
            end_time=end_time,
            task_based=report_task_based,
            detail_level=args.detail_level,
            non_afk_time=slot_active_time,
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
            afk_time=afk_time_calc,
            total_offline_time=total_offline_calc,
            total_time_all=total_time_calc,
        )

    _profile("MAIN END - rendering complete")


if __name__ == "__main__":
    main()

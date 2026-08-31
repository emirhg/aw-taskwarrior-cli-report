"""
tw-report CLI entry point with full orchestration.

Handles all argument parsing, data fetching, processing, and report generation.
"""

import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from aw_client import ActivityWatchClient
from aw_core.models import Event
from aw_transform import filter_keyvals

if TYPE_CHECKING:
    from tw_report.core.aw_events import WindowEvent, AFKEvent, TaskWarriorEvent

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
from tw_report.core.filtering import EventFilter, NO_PROJECT, NO_TASK
from tw_report.core.offline import OfflineTaskProcessor
from tw_report.core.period import parse_period
from tw_report.core.task_matching import (
    build_offline_category_structure,
    find_active_task,
    get_task_info,
    task_has_offline_tag,
)
from tw_report.core.task_uuid_filtering import (
    get_task_uuid,
    get_events_by_uuid,
)
from tw_report.core.project_filtering import (
    _is_uuid_like,
    get_events_by_project,
    resolve_project_filter_value,
)
from tw_report.core.task_filtering import (
    get_events_by_task,
    resolve_task_filter_value,
)
from tw_report.core.timeline import Timeline, TimelineSlot
from tw_report.pipeline.generation import (
    convert_active_periods_to_slots,
    generate_afk_and_offline_slots,
    generate_partitioned_task_slots,
    generate_timeline_data,
    generate_untracked_gap_events,
)
from tw_report.pipeline.models import ReportContext
from tw_report.pipeline.presenters import HierarchicalReport, TimelineReport
from tw_report.pipeline.processors import (
    build_canonical_events,
    build_context,
    compute_metrics,
    merge_overlapping_afk_periods,
    aggregate_hierarchy,
    matches_user_filters,
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
    args = parse_args()
    client = ActivityWatchClient("tw-report")

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
            afk_events = get_events(client, afk_bucket, start_time, end_time, event_cls=AFKEvent)

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
        window_events = get_events(client, window_bucket, start_time, end_time, event_cls=WindowEvent)

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
    first_event_time = None
    last_event_time = None
    if not_afk_events:
        first_event_time = min(event.timestamp.astimezone() for event in not_afk_events)
        last_event_time = max(
            (event.timestamp + event.duration).astimezone() for event in not_afk_events
        )


    # Special case: window data not required or not fetched
    # Convert taskwarrior events directly to canonical events (skip window correlation)
    if not requires_window_data or not window_events:
        from tw_report.pipeline.models import ReportEvent

        canonical_events = []

        # Add taskwarrior events if they exist
        if task_events:
            for task_event in task_events:
                task_name, project = get_task_info(task_event)
                rep = ReportEvent(
                    event=task_event,
                    project=project,
                    task=task_name,
                    active_task=task_event,
                )
                # Apply user filters to ensure correctness (e.g., when --task filtering is set)
                if matches_user_filters(rep, args, _matches_any, _excluded):
                    canonical_events.append(rep)

        # Add untracked (NO_PROJECT) time gaps from uncovered not-afk periods
        # Only when window_events are skipped (using task-only path)
        # This fills the visibility gap when window events can't be fetched due to optimization
        # This now works even when there are NO task_events (just untracked window activity)
        if not window_events and not_afk_events:
            # Generate untracked gaps from not-afk periods
            # not_afk_events are ALREADY the ACTIVE periods from the AFK bucket
            # No need to partition with afk_events (that would contradict the definitions)
            untracked_events = generate_untracked_gap_events(
                not_afk_events,
                task_events or [],
                afk_events=None,  # not_afk already represents ACTIVE, no partitioning needed
            )
            # Apply filters to synthetic NO_PROJECT events (same as for task events)
            for untracked_rep in untracked_events:
                if matches_user_filters(untracked_rep, args, _matches_any, _excluded):
                    canonical_events.append(untracked_rep)
            # Re-sort by timestamp to maintain chronological order
            canonical_events = sorted(canonical_events, key=lambda rep: rep.event.timestamp)
    else:
        # Normal mode: correlate window events to task events
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

    # OFFLINE task reconciliation requires window events to determine tracked online time.
    # If window events were skipped (e.g., when filtering by task UUID), check if we have
    # OFFLINE-tagged tasks and re-fetch windows if needed.
    # Unless --exclude-online is set, in which case we intentionally skip online time reporting.
    exclude_online = getattr(args, "exclude_online", False)
    if not requires_window_data and task_events and not window_events and not exclude_online:
        has_offline_tasks = any(
            any('offline' in t.lower() for t in e.data.get('tags', []))
            for e in task_events
        )
        if has_offline_tasks:
            # Re-fetch windows for OFFLINE task reconciliation
            # Optimization: use task_time_ranges if available to avoid fetching entire period
            if task_time_ranges:
                from tw_report.core.aw_events import WindowEvent
                window_events = _fetch_events_for_ranges(client, "window", task_time_ranges, event_cls=WindowEvent)
            else:
                window_bucket = get_bucket_id("window")
                window_events = get_events(client, window_bucket, start_time, end_time)
            for event in window_events:
                categorize_event(event, compiled_categories)

    # Process OFFLINE task events using the extracted OfflineTaskProcessor
    # This replaces ~150 lines of scattered logic with a clean, testable class
    offline_task_durations: Dict = {}
    offline_event_durations: Dict = {}
    offline_event_groups: Dict = {}
    offline_processor = None

    if task_events:
        offline_processor = OfflineTaskProcessor(
            task_events=task_events,
            window_events=window_events,
            afk_events=afk_events,
            event_filter=event_filter,
            end_time=end_time,
            use_afk_for_reconciliation=not requires_window_data,
            tail_tolerance_seconds=args.tail_tolerance,
            afk_validation_tolerance_seconds=args.afk_validation_tolerance,
            day_start_hour=day_start_hour,
        )

        # EVENT-BASED TIMESHEET APPROACH (no grouping for timesheet modes):
        # For timesheet modes (day/week/month/year), use event-based slots (one per task event)
        # For hierarchical modes, use grouping logic
        event_based_offline_slots = []
        if grouping_mode in ("day", "week", "month", "year"):
            # Timesheet/timeline mode: use per-event slots, skip grouping
            event_based_offline_slots = offline_processor.get_event_based_slots()
            offline_task_durations = {}
            offline_event_durations = {}
            offline_event_groups = {}
            offline_task_real_durations = {}
        else:
            # Hierarchical mode: use grouping approach
            offline_task_durations, offline_event_durations, offline_event_groups, offline_task_real_durations = offline_processor.process()

    # Exclude ONLY window events that were actually consumed by OFFLINE task groups.
    # Window events tied to offline-tagged tasks but outside any group's span are NOT excluded,
    # allowing them to flow through aggregate_hierarchy() normally (fixes a latent bug).
    if offline_processor and offline_processor.consumed_window_event_ids:
        canonical_events = [
            rep
            for rep in canonical_events
            if id(rep.event) not in offline_processor.consumed_window_event_ids
        ]

    # Filter out zero-duration events (< 100ms tracking noise)
    # This must happen before metrics calculation so unscored_time is accurate
    from tw_report.pipeline.generation import MIN_EVENT_DURATION
    canonical_events = [
        rep
        for rep in canonical_events
        if rep.event.duration >= MIN_EVENT_DURATION
    ]

    # Remove regular events that overlap with OFFLINE task periods (avoid duplication)
    # This must happen before metrics calculation for consistency
    # Use offline_event_groups from processor which already has computed OFFLINE periods
    # SKIP this for timesheet mode (event-based slots don't use grouping)
    if offline_processor and offline_event_groups and grouping_mode != "day" and grouping_mode != "week" and grouping_mode != "month" and grouping_mode != "year":
        # Build periods for each (project, task) from offline event groups
        offline_periods = {}  # (project, task) -> [(start, end), ...]
        for key, events in offline_event_groups.items():
            project = key[0]
            task = key[1]
            pair_key = (project, task)
            if pair_key not in offline_periods:
                offline_periods[pair_key] = []
            # Get time span for this group
            if events:
                sorted_events = sorted(events, key=lambda e: e.timestamp)
                group_start = sorted_events[0].timestamp
                group_end = sorted_events[-1].timestamp + (sorted_events[-1].duration or timedelta(0))
                offline_periods[pair_key].append((group_start, group_end))

        # Filter out canonical events that overlap OFFLINE periods for same task
        filtered_canonical = []
        for rep in canonical_events:
            event = rep.event
            project = rep.project
            task = rep.task
            pair_key = (project, task)

            event_start = event.timestamp
            event_end = event_start + event.duration

            overlaps_offline = False
            if pair_key in offline_periods:
                for offline_start, offline_end in offline_periods[pair_key]:
                    if event_start < offline_end and event_end > offline_start:
                        overlaps_offline = True
                        break

            if not overlaps_offline:
                filtered_canonical.append(rep)

        canonical_events = filtered_canonical

    # Mark window events with offline_extension_duration to show OFFLINE time notation.
    # For each window event that overlaps with an OFFLINE task period, calculate the overlap
    # and store it as offline_extension_duration so timeline rendering can display "(HH:MM:SS OFFLINE)".
    # Note: Use only offline_durations (the aggregated duration per task), not the groups,
    # to determine if activity occurred during an OFFLINE session. A task is "offline" if we
    # have an entry for it, regardless of which specific events comprised it.
    if offline_processor and offline_task_durations:
        # For each canonical event (window activity), check if active_task is OFFLINE-tagged
        for rep in canonical_events:
            active_task = rep.active_task
            if active_task and task_has_offline_tag(active_task):
                # This window event occurred during an OFFLINE-tagged task.
                # Mark the entire window event duration as offline_extension.
                window_duration = rep.event.duration
                rep.event.data["offline_extension_duration"] = window_duration

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
    if not args.exclude_offline and offline_processor:
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

            # Build categories from reconciled window+offline breakdown
            # Get categories from OfflineTaskProcessor (which includes real window events
            # + offline remainder), convert from list-of-dicts to dict-by-category-name
            reconciled_categories_list = offline_processor.offline_categories.get(key, [])
            offline_categories_dict = {}
            for cat_dict in reconciled_categories_list:
                cat_name = cat_dict.get("category", "Unknown")
                # Convert list format to hierarchical dict format with duration + apps
                offline_categories_dict[cat_name] = {
                    "total_duration": cat_dict.get("duration", timedelta(0)),
                    "prod_score": 0.0,
                    # Note: apps/titles breakdown from list format not used in hierarchical
                    # reporting, only the duration per category
                }

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
                # Replace categories with reconciled breakdown
                task_node["categories"] = offline_categories_dict
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
                task_node["categories"] = offline_categories_dict

    # Generate timeline report for period-based grouping (day/week/month/year)
    # Hierarchical (by-project) is handled in the else clause
    if grouping_mode in ["day", "week", "month", "year"]:
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

        # EVENT-BASED TIMESHEET APPROACH (2026-07-30):
        # For timesheet modes, use per-event OFFLINE task slots (one per event)
        # These are now included in partitioned_task_slots, so DON'T add them separately
        # to avoid duplication. Just document the approach for clarity.
        # (Previously added event_based_offline_slots separately at this point, but
        # that caused double-counting with partitioned_task_slots, so we skip it now.)

        # Task-only modes: taskwarrior events (no window events, no AFK correlation)
        # This includes: task UUID mode (--task-id) and project filter mode
        if not requires_window_data:
            # Build slots directly from taskwarrior events (simpler format)
            initial_slots = []
            for rep in context.canonical_events:
                event = rep.event

                # Determine slot type: regular task or untracked ACTIVE/AFK gap
                gap_type = event.data.get("gap_type") if event.data else None
                if gap_type == "untracked_active":
                    # ACTIVE gap: duration is active time, afk_duration is 0
                    slot = {
                        "start": event.timestamp.astimezone(),
                        "end": (event.timestamp + event.duration).astimezone(),
                        "duration": event.duration,
                        "actual_duration": event.duration,
                        "afk_duration": timedelta(0),  # No AFK in this slot
                        "project": rep.project,
                        "task": rep.task,
                        "category": "Task Activity",
                        "type": "regular",
                        "categories": [],
                    }
                elif gap_type == "untracked_afk":
                    # AFK gap: afk_duration equals total duration
                    slot = {
                        "start": event.timestamp.astimezone(),
                        "end": (event.timestamp + event.duration).astimezone(),
                        "duration": event.duration,
                        "actual_duration": event.duration,
                        "afk_duration": event.duration,  # Entire slot is AFK
                        "project": rep.project,
                        "task": rep.task,
                        "category": "Task Activity",
                        "type": "afk",
                        "categories": [],
                    }
                else:
                    # Regular task event
                    slot = {
                        "start": event.timestamp.astimezone(),
                        "end": (event.timestamp + event.duration).astimezone(),
                        "duration": event.duration,
                        "actual_duration": event.duration,
                        "project": rep.project,
                        "task": rep.task,
                        "category": "Task Activity",
                        "type": "regular",
                        "categories": [],
                    }
                initial_slots.append(slot)
        else:
            # Normal mode: use partitioned task slots instead of combined ones
            # This ensures ACTIVE and AFK time are represented in separate slots
            initial_slots = []

        # Add initial slots to timeline (task-only or window-free modes)
        # When requires_window_data is False, these are the only slots we have
        # (partitioned_task_slots are generated separately when window data IS available)
        if initial_slots:
            timeline.add_slots([TimelineSlot.from_dict(s) for s in initial_slots])

        # Inject synthetic slots for OFFLINE task events
        # (these use aggregated task event duration from span of all events)
        # Skip if --exclude-offline flag is set
        if offline_task_durations and not args.exclude_offline and offline_processor:
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
                    # event_duration field (critical for identification via is_offline_task).
                    task_events_for_key = offline_event_groups.get(key, [])
                    if task_events_for_key:
                        offline_slot_rts = offline_processor.get_synthetic_slot(
                            key, task_events_for_key
                        )
                        if offline_slot_rts and offline_slot_rts.duration > timedelta(0):
                            # Convert ReportTimelineSlot back to TimelineSlot for Timeline compatibility
                            # (temporary bridge during migration to new model)
                            ts = TimelineSlot(
                                type="offline_task",
                                start=offline_slot_rts.start,
                                end=offline_slot_rts.end,
                                duration=offline_slot_rts.duration,
                                actual_duration=offline_slot_rts.actual_duration,
                                productive_duration=offline_slot_rts.productive_duration,
                                project=offline_slot_rts.project,
                                task=offline_slot_rts.task,
                                tags=offline_slot_rts.tags,
                                categories=offline_slot_rts.categories,
                                event_duration=offline_slot_rts.event_duration,
                            )
                            timeline.add_from_dict(ts.to_dict())

        # Timeline auto-sorts on insertion, no need to manually sort

        # FIX: Fetch window events if not already loaded, needed for AFK false positive detection
        # Even if optimization skipped windows earlier, we need them to detect offline periods
        if not window_events and context.afk_events:
            from tw_report.core.aw_events import WindowEvent
            window_bucket = get_bucket_id("window")
            window_events = get_events(client, window_bucket, start_time, end_time, event_cls=WindowEvent)
            for event in window_events:
                categorize_event(event, compiled_categories)

        # Generate AFK and OFFLINE slots from uncovered AFK events (not associated with any task)
        # Delegates false-positive detection (system offline vs. user idle) to AFKEvent.split_by_coverage()
        afk_offline_slots = generate_afk_and_offline_slots(
            context.afk_events,
            context.task_events,
            window_events=window_events,
        )

        # Generate ACTIVE slots from status="not-afk" events (keyboard/mouse activity)
        # Partition by AFK events to split long continuous periods into AFK and pure ACTIVE portions
        active_periods = context.bucket_events.get_active_periods()
        active_slots = convert_active_periods_to_slots(
            active_periods,
            context.task_events,
            afk_events=context.afk_events,
        )

        # Generate partitioned TaskWarrior task slots (ACTIVE/AFK/OFFLINE portions)
        # This breaks down each task duration into its constituent components,
        # enabling proper AFK time accountability (fixes 42-second mismatch)
        partitioned_task_slots = generate_partitioned_task_slots(
            context.task_events,
            window_events,
            context.afk_events,
        )

        # Combine AFK/offline slots with partitioned task slots and ACTIVE slots for uncovered periods
        # BUGFIX: In timesheet mode (day/week/month/year), skip afk_offline_slots since
        # partitioned_task_slots already includes per-event offline task slots with proper
        # ACTIVE/AFK/OFFLINE breakdown. Adding afk_offline_slots would duplicate them.
        if grouping_mode in ("day", "week", "month", "year"):
            # Timesheet mode: skip afk_offline_slots, use partitioned_task_slots instead
            all_slot_entries = active_slots + partitioned_task_slots
        else:
            # Hierarchical mode: use afk_offline_slots as normal
            all_slot_entries = afk_offline_slots + active_slots + partitioned_task_slots

        # Filter entries using unified EventFilter for consistency
        # (replaces 50+ lines of scattered filter logic)
        all_slot_entries = [
            g
            for g in all_slot_entries
            if event_filter.should_include_entry(g, entry_type=g.get("type", "gap"))
        ]

        # FIX: --exclude-afk removes AFK period slots from the timeline
        if args.exclude_afk:
            all_slot_entries = [g for g in all_slot_entries if g.get("type") != "afk"]

        # BUGFIX: Remove AFK slots for OFFLINE-tagged tasks to prevent overlap with OFFLINE synthetic slots
        # When a user is AFK during an OFFLINE-tagged task, the OFFLINE synthetic slot already
        # captures that period with accurate duration. Showing both AFK and OFFLINE slots creates
        # confusing overlapping entries. Keep AFK-only entries (tasks="NO TASK") and AFK for non-OFFLINE tasks.
        if offline_task_durations and all_slot_entries:
            # Extract the base (project, task) keys from offline_task_durations
            # (some keys might be 3-tuples with group_idx, so extract first 2 elements)
            offline_tasks = set()
            for key in offline_task_durations.keys():
                offline_tasks.add((key[0], key[1]))

            all_slot_entries = [
                g for g in all_slot_entries
                if g.get("type") not in ("afk", "afk_task") or (g.get("project"), g.get("task")) not in offline_tasks
            ]

        # All timeline-based modes (--by-day/week/month/year and hierarchical/project)
        # Use the standard timeline rendering which shows chronological slots
        # Each slot renders independently: no combining of work slots with embedded AFK

        # Add all slot entries to timeline (auto-sorts on insertion)
        timeline.add_slots([TimelineSlot.from_dict(g) for g in all_slot_entries])

        # Convert timeline to ReportEntries for type normalization
        # CRITICAL: This converts "active_task"/"afk_task" types to standard "regular"/"afk" types
        # that the rendering code understands. Do NOT combine work with embedded AFK here.
        report_timeline = timeline.to_report_timeline()
        final_dicts = report_timeline.as_dicts()

        # Apply session-merging consolidation if --consolidate flag is set
        if args.consolidate:
            from tw_report.pipeline.consolidation import consolidate_sessions
            print(f"[CONSOLIDATION] Applying to {len(final_dicts)} slots", file=sys.stderr)
            before = len(final_dicts)
            final_dicts = consolidate_sessions(final_dicts)
            after = len(final_dicts)
            print(f"[CONSOLIDATION] Result: {before} → {after} slots", file=sys.stderr)

            # Log what the consolidated slots are
            task_summary = {}
            preparar_slots = []
            for slot in final_dicts:
                task = slot.get('task', 'unknown')
                task_summary[task] = task_summary.get(task, 0) + 1
                if 'Preparar masa' in task:
                    preparar_slots.append((slot['start'], slot['end'], slot['duration']))

            print(f"[CONSOLIDATION] Consolidated slots by task:", file=sys.stderr)
            for task, count in sorted(task_summary.items()):
                print(f"  {task}: {count} slot(s)", file=sys.stderr)

            if preparar_slots:
                print(f"[CONSOLIDATION] 'Preparar masa' consolidated groups:", file=sys.stderr)
                for i, (start, end, dur) in enumerate(preparar_slots, 1):
                    print(f"  Group {i}: {start} to {end} ({dur})", file=sys.stderr)

        TimelineReport(print_timeline_report).present(
            slots=final_dicts,
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
            current_session_start=context.metrics.current_session_start,
            current_session_end=context.metrics.current_session_end,
            current_session_duration=context.metrics.current_session_duration,
            last_break_start=context.metrics.last_break_start,
            last_break_end=context.metrics.last_break_end,
            last_break_duration=context.metrics.last_break_duration,
            afk_events=afk_events,
            exclude_online=exclude_online,
            day_start_hour=day_start_hour,
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

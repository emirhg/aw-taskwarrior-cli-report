"""
tw-report CLI entry point with full orchestration.

Handles all argument parsing, data fetching, processing, and report generation.
"""

import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from aw_client import ActivityWatchClient
from aw_core.models import Event
from aw_transform import filter_keyvals

from tw_report.cli.args import parse_args, parse_positional_args
from tw_report.core.categories import (
    categorize_event,
    compile_category_rules,
    get_category_score,
    load_categories,
)
from tw_report.core.consolidation import TimelineSlotManager, consolidate_by_period
from tw_report.core.events import get_bucket_id, get_events
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
    should_skip_window_bucket,
    resolve_project_filter_value,
)
from tw_report.core.task_filtering import (
    get_events_by_task,
    resolve_task_filter_value,
)
from tw_report.core.timeline import Timeline, TimelineSlot
from tw_report.pipeline.generation import generate_gap_entries, generate_timeline_data
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
from tw_report.pipeline.timeline_render import print_timeline_report, print_period_consolidated_report
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
) -> List[Event]:
    """Fetch events from specified bucket for multiple time ranges.

    More efficient than fetching for entire period when events are sparse.
    """
    events = []
    bucket_id = get_bucket_id(bucket_name)
    for start, end in time_ranges:
        # Add small buffer (1 second) to ensure boundary events are included
        buffer = timedelta(seconds=1)
        range_events = get_events(client, bucket_id, start - buffer, end + buffer)
        events.extend(range_events)
    return events


def main():
    """Main script logic: orchestrate data fetching, processing, and report generation."""
    args = parse_args()
    client = ActivityWatchClient("tw-report")

    # Period consolidation flags imply --timesheet (user shouldn't need to pass both)
    if args.consolidate_day or args.consolidate_week or args.consolidate_month or args.consolidate_year:
        args.timesheet = True

    # Parse positional arguments to separate period from search term
    period, search_term = parse_positional_args(args.args)
    args.search = search_term  # Set search term from positional args (None if not provided)

    # Adjust default period based on consolidation mode (if no explicit period provided)
    if period == ":today":  # Only adjust if using the default period
        if args.consolidate_week and not any(arg.startswith(":") or arg[0].isdigit() for arg in args.args):
            period = ":week"
        elif args.consolidate_month and not any(arg.startswith(":") or arg[0].isdigit() for arg in args.args):
            period = ":month"
        elif args.consolidate_year and not any(arg.startswith(":") or arg[0].isdigit() for arg in args.args):
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

    start_time, end_time = parse_period(period)
    categories_json = load_categories(args.categories)
    compiled_categories, cat_score_map = compile_category_rules(categories_json)

    # Smart optimization: when filtering by task UUID, fetch task events FIRST,
    # then only fetch AFK/window events for the time ranges where tasks exist.
    # This dramatically reduces data volume for sparse task data.
    task_events_early = None
    task_time_ranges = None
    if task_uuid and not args.no_taskwarrior:
        # Fetch task events first to determine what time windows we care about
        task_bucket = get_bucket_id("taskwarrior")
        task_events_early = get_events_by_uuid(
            client, task_bucket, start_time, end_time, task_uuid
        )
        if task_events_early:
            # Extract time ranges: only fetch AFK/window during these windows
            task_time_ranges = _get_time_ranges_from_events(task_events_early)

    # Determine if window bucket queries can be skipped for general filtering
    skip_window = should_skip_window_bucket(args, args.detail_level)

    # AFK-based optimization for detail_level <= 2:
    # When we don't need category/app/title detail, skip expensive window bucket fetch
    # and use AFK events for OFFLINE task reconciliation (much faster).
    use_afk_optimization = args.detail_level <= 2 and args.timesheet

    # Fetch events based on optimization and filtering strategy
    if skip_window and not use_afk_optimization:
        # Skip both windows and AFK (extreme filtering case, not OFFLINE reconciliation needed)
        window_events = []
        afk_events = []
    elif use_afk_optimization:
        # AFK optimization: skip windows, fetch AFK for OFFLINE reconciliation
        # NOTE: Don't use time range optimization with AFK fetch, as incomplete AFK data
        # breaks online/offline calculation. Always fetch complete AFK for the period.
        window_events = []
        afk_bucket = get_bucket_id("afk")
        afk_events = get_events(client, afk_bucket, start_time, end_time)
    else:
        # Normal case: fetch both windows and AFK for category detail
        if task_time_ranges:
            # Smart optimization: only fetch windows/AFK for times when tasks exist
            # This dramatically reduces data volume for sparse task data (e.g., :year, :all)
            window_events = _fetch_events_for_ranges(client, "window", task_time_ranges)
            # Categorize all window events (including those during AFK periods)
            for event in window_events:
                categorize_event(event, compiled_categories)
            afk_events = _fetch_events_for_ranges(client, "afk", task_time_ranges)
        else:
            # Normal: fetch for entire period
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

    task_events = task_events_early  # Use pre-fetched task events if available
    is_task_based_report = not args.no_taskwarrior

    if is_task_based_report and task_events is None:
        task_bucket = get_bucket_id("taskwarrior")
        # Apply bucket-level filtering based on query type
        if task_uuid:
            # Task UUID mode: filter by UUID (already fetched early, skip)
            task_events = task_events_early
        elif skip_window and args.project:
            # Project filter mode (window skipped): filter by project at bucket level
            task_events = get_events_by_project(
                client, task_bucket, start_time, end_time, args.project[0]
            )
        elif skip_window and args.task:
            # Task filter mode (window skipped): filter by task name at bucket level
            task_events = get_events_by_task(
                client, task_bucket, start_time, end_time, args.task[0]
            )
        else:
            # Normal mode: fetch all events
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

    # Special case: task-UUID mode or project/task-filter mode (skip window bucket)
    # Convert taskwarrior events directly to canonical events (skip window correlation)
    if skip_window and task_events:
        from tw_report.pipeline.models import ReportEvent

        canonical_events = []
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
    if skip_window and task_events and not window_events and not exclude_online:
        has_offline_tasks = any(
            any('offline' in t.lower() for t in e.data.get('tags', []))
            for e in task_events
        )
        if has_offline_tasks:
            # Re-fetch windows for OFFLINE task reconciliation
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
            use_afk_for_reconciliation=use_afk_optimization,
        )
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

        # Task-only modes: taskwarrior events (no window events, no AFK correlation)
        # This includes: task UUID mode (--task-id) and project filter mode
        if skip_window:
            # Build slots directly from taskwarrior events (simpler format)
            initial_slots = []
            for rep in context.canonical_events:
                event = rep.event
                slot = {
                    "start": event.timestamp.astimezone(),
                    "end": (event.timestamp + event.duration).astimezone(),
                    "duration": event.duration,
                    "actual_duration": event.duration,  # Required by TimelineSlot
                    "project": rep.project,
                    "task": rep.task,
                    "category": "Task Activity",  # Placeholder category
                    "type": "activity",
                    "categories": [],
                }
                initial_slots.append(slot)
        else:
            # Normal mode: window events with AFK correlation
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

        # BUGFIX: Remove AFK slots for OFFLINE-tagged tasks to prevent overlap with OFFLINE synthetic slots
        # When a user is AFK during an OFFLINE-tagged task, the OFFLINE synthetic slot already
        # captures that period with accurate duration. Showing both AFK and OFFLINE slots creates
        # confusing overlapping entries. Keep AFK-only entries (tasks="NO TASK") and AFK for non-OFFLINE tasks.
        if offline_task_durations and gap_entries:
            # Extract the base (project, task) keys from offline_task_durations
            # (some keys might be 3-tuples with group_idx, so extract first 2 elements)
            offline_tasks = set()
            for key in offline_task_durations.keys():
                offline_tasks.add((key[0], key[1]))

            gap_entries = [
                g for g in gap_entries
                if g.get("type") != "afk" or (g.get("project"), g.get("task")) not in offline_tasks
            ]

        # Add gap entries to timeline (auto-sorts on insertion)
        timeline.add_slots([TimelineSlot.from_dict(g) for g in gap_entries])

        # Convert timeline to dicts for downstream processing
        slots = timeline.get_slots_as_dicts()

        # Determine which consolidation mode to use
        period_mode = None
        if args.consolidate_day:
            period_mode = "day"
        elif args.consolidate_week:
            period_mode = "week"
        elif args.consolidate_month:
            period_mode = "month"
        elif args.consolidate_year:
            period_mode = "year"

        if period_mode:
            # Period-level consolidation (day/week/month/year)
            consolidated = consolidate_by_period(slots, period_mode)
            # Filter consolidated results based on EventFilter rules
            # (e.g., --exclude-non-project, --exclude-offline)
            filtered_consolidated = [
                slot for slot in consolidated
                if event_filter.should_include_entry(slot)
            ]
            TimelineReport(print_period_consolidated_report).present(
                slots=filtered_consolidated,
                period=period,
                start_time=start_time,
                end_time=end_time,
                period_mode=period_mode,
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
            )
        else:
            # Standard timeline report (optionally with fine-grain consolidation)
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
                exclude_online=exclude_online,
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

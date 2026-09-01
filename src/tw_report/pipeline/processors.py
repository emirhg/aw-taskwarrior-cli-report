from copy import deepcopy
from datetime import timedelta
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

from aw_core.models import Event
from aw_transform import filter_period_intersect

from tw_report.pipeline.models import ReportContext, ReportEvent, ReportMetrics

if TYPE_CHECKING:
    from tw_report.core.report_slot import ReportTimelineSlot


def _overlaps(event: Event, other: Event) -> bool:
    return (
        event.timestamp < other.timestamp + other.duration
        and other.timestamp < event.timestamp + event.duration
    )


def window_event_max_category_score(
    event: Event,
    cat_score_map: Dict[str, float],
    get_category_score: Callable[[str, Dict[str, float]], float],
) -> float:
    category_list = event.data.get("$category", ["Uncategorized"])
    max_score = None
    for category in category_list:
        score = get_category_score(category, cat_score_map)
        if max_score is None:
            max_score = score
        else:
            max_score = max(max_score, score)
    return float(max_score) if max_score is not None else 0.0


def window_event_productive_duration(
    event: Event,
    cat_score_map: Dict[str, float],
    get_category_score: Callable[[str, Dict[str, float]], float],
) -> timedelta:
    if window_event_max_category_score(event, cat_score_map, get_category_score) > 0:
        return event.duration
    return timedelta(0)


def apply_score_filters(
    events: List[ReportEvent],
    min_score: Optional[float],
    max_score: Optional[float],
    cat_score_map: Dict[str, float],
    get_category_score: Callable[[str, Dict[str, float]], float],
) -> List[ReportEvent]:
    if min_score is None and max_score is None:
        return events

    filtered_events: List[ReportEvent] = []
    for report_event in events:
        event_categories = report_event.event.data.get("$category")
        scores = [0]
        if event_categories:
            scores = [get_category_score(cat, cat_score_map) for cat in event_categories]

        should_keep = any(
            (min_score is None or score >= min_score) and (max_score is None or score <= max_score)
            for score in scores
        )
        if should_keep:
            filtered_events.append(report_event)
    return filtered_events


def matches_user_filters(
    report_event: ReportEvent,
    args,
    matches_any: Callable[[str, Optional[List[str]], bool], bool],
    excluded: Callable[[str, Optional[List[str]]], bool],
) -> bool:
    project = report_event.project
    task = report_event.task
    app_name = report_event.event.data.get("app", "Unknown App")

    if excluded(project, args.exclude_project):
        return False
    if excluded(task, args.exclude_task):
        return False
    if args.exclude_app and excluded(app_name, args.exclude_app):
        return False

    # Check if args.search exists (it's manually set in main(), but be defensive)
    search_value = getattr(args, "search", None)

    has_filters = bool(search_value or args.project or args.task or args.app)
    if not has_filters:
        return True

    if search_value:
        search_patterns = [search_value]
        if (
            matches_any(project, search_patterns, args.exact)
            or matches_any(task, search_patterns, args.exact)
            or matches_any(app_name, search_patterns, args.exact)
        ):
            return True

    if args.project and matches_any(project, args.project, args.exact):
        return True
    if args.task and matches_any(task, args.task, args.exact):
        return True
    if args.app and matches_any(app_name, args.app, args.exact):
        return True

    return False


def resolve_report_event(
    event: Event,
    task_events: Optional[List[Event]],
    no_task_mode: bool,
    exclude_non_project: bool,
    no_project_label: str,
    no_task_label: str,
    find_active_task: Callable[[Event, List[Event]], Optional[Event]],
    get_task_info: Callable[[Event], Tuple[str, str]],
) -> Optional[ReportEvent]:
    if no_task_mode:
        return ReportEvent(
            event=event,
            project=no_project_label,
            task=no_task_label,
            active_task=None,
        )

    active_task = find_active_task(event, task_events or [])
    if not active_task:
        if exclude_non_project:
            return None
        return ReportEvent(
            event=event,
            project=no_project_label,
            task=no_task_label,
            active_task=None,
        )

    task_name, project = get_task_info(active_task)
    return ReportEvent(event=event, project=project, task=task_name, active_task=active_task)


def build_canonical_events(
    window_events: List[Event],
    not_afk_events: List[Event],
    include_afk: bool,
    task_events: Optional[List[Event]],
    args,
    no_project_label: str,
    no_task_label: str,
    categorize_event: Callable[[Event, List], None],
    compiled_categories: List,
    get_category_score: Callable[[str, Dict[str, float]], float],
    cat_score_map: Dict[str, float],
    find_active_task: Callable[[Event, List[Event]], Optional[Event]],
    get_task_info: Callable[[Event], Tuple[str, str]],
    matches_any: Callable[[str, Optional[List[str]], bool], bool],
    excluded: Callable[[str, Optional[List[str]]], bool],
) -> List[ReportEvent]:
    active_events = (
        window_events if include_afk else filter_period_intersect(window_events, not_afk_events)
    )

    for event in active_events:
        categorize_event(event, compiled_categories)

    no_task_mode = task_events is None or len(task_events) == 0
    resolved: List[ReportEvent] = []
    for event in active_events:
        report_event = resolve_report_event(
            event=event,
            task_events=task_events,
            no_task_mode=no_task_mode,
            exclude_non_project=args.exclude_non_project,
            no_project_label=no_project_label,
            no_task_label=no_task_label,
            find_active_task=find_active_task,
            get_task_info=get_task_info,
        )
        if report_event is not None:
            resolved.append(report_event)

    resolved = apply_score_filters(
        resolved, args.min_score, args.max_score, cat_score_map, get_category_score
    )

    return [rep for rep in resolved if matches_user_filters(rep, args, matches_any, excluded)]


def aggregate_hierarchy(
    canonical_events: List[ReportEvent],
    task_based: bool,
    cat_score_map: Dict[str, float],
    get_category_score: Callable[[str, Dict[str, float]], float],
    normalize_title: Callable[[str], str],
) -> Dict:
    report: Dict = {}

    def get_app_name(event: Event) -> str:
        return event.data.get("app", "Unknown App")

    def get_title(event: Event) -> str:
        return event.data.get("title", "No Title")

    if task_based:
        for report_event in canonical_events:
            event = report_event.event
            task_name = report_event.task
            project = report_event.project
            category_list = event.data.get("$category", ["Uncategorized"])
            app_name = get_app_name(event)

            for category in category_list:
                score = get_category_score(category, cat_score_map)
                prod_score = (event.duration.total_seconds() / 3600) * score

                proj_node = report.setdefault(
                    project,
                    {"total_duration": timedelta(0), "tasks": {}, "prod_score": 0.0},
                )
                task_node = proj_node["tasks"].setdefault(
                    task_name,
                    {"total_duration": timedelta(0), "categories": {}, "prod_score": 0.0},
                )
                cat_node = task_node["categories"].setdefault(
                    category,
                    {"total_duration": timedelta(0), "apps": {}, "prod_score": 0.0},
                )
                app_node = cat_node["apps"].setdefault(
                    app_name, {"total_duration": timedelta(0), "prod_score": 0.0}
                )

                proj_node["total_duration"] += event.duration
                proj_node["prod_score"] += prod_score
                task_node["total_duration"] += event.duration
                task_node["prod_score"] += prod_score
                cat_node["total_duration"] += event.duration
                cat_node["prod_score"] += prod_score
                app_node["total_duration"] += event.duration
                app_node["prod_score"] += prod_score

                title = get_title(event)
                normalized_title = normalize_title(title)
                title_node = app_node.setdefault("titles", {}).setdefault(
                    normalized_title,
                    {"total_duration": timedelta(0), "prod_score": 0.0},
                )
                title_node["total_duration"] += event.duration
                title_node["prod_score"] += prod_score
    else:
        for report_event in canonical_events:
            event = report_event.event
            category_list = event.data.get("$category", ["Uncategorized"])
            app_name = get_app_name(event)
            for category in category_list:
                score = get_category_score(category, cat_score_map)
                prod_score = (event.duration.total_seconds() / 3600) * score

                cat_node = report.setdefault(
                    category,
                    {"total_duration": timedelta(0), "apps": {}, "prod_score": 0.0},
                )
                app_node = cat_node["apps"].setdefault(
                    app_name, {"total_duration": timedelta(0), "prod_score": 0.0}
                )
                cat_node["total_duration"] += event.duration
                cat_node["prod_score"] += prod_score
                app_node["total_duration"] += event.duration
                app_node["prod_score"] += prod_score

                title = event.data.get("title", "No Title")
                normalized_title = normalize_title(title)
                title_node = app_node.setdefault("titles", {}).setdefault(
                    normalized_title,
                    {"total_duration": timedelta(0), "prod_score": 0.0},
                )
                title_node["total_duration"] += event.duration
                title_node["prod_score"] += prod_score

    return report


def aggregate_hierarchy_from_slots(
    consolidated_slots: List["ReportTimelineSlot"],
    task_based: bool,
    cat_score_map: Dict[str, float],
    get_category_score: Callable[[str, Dict[str, float]], float],
    normalize_title: Callable[[str], str],
) -> Dict:
    """
    Build hierarchical report structure from consolidated slots (Phase 2 refactor).

    Replaces aggregate_hierarchy() by working with pre-built slots instead of canonical_events.
    Slots already have categories populated by build_timeslot_timeline(), so we only need
    to group by project/task and sum durations with productivity scoring.

    Same output shape as aggregate_hierarchy() — print_report() needs zero changes.

    Args:
        consolidated_slots: List of ReportTimelineSlot with categories pre-populated
        task_based: If True, group by project > task; if False, group by category only
        cat_score_map: Category -> productivity score mapping
        get_category_score: Function to look up category score
        normalize_title: Function to normalize window titles

    Returns:
        Dict with structure:
        - task_based=True: {project: {total_duration, prod_score, tasks: {...}}}
        - task_based=False: {category: {total_duration, prod_score, apps: {...}}}
    """
    report: Dict = {}

    if task_based:
        # Group by: Project > Task > Category > App > Title
        for slot in consolidated_slots:
            # Skip AFK-only slots (no task assignment)
            if not slot.project or slot.project == "No project assigned":
                continue

            # Each slot may have multiple categories; iterate over them
            for cat_entry in (slot.categories or []):
                category = cat_entry.get("category", "Uncategorized")
                score = get_category_score(category, cat_score_map)

                proj_node = report.setdefault(
                    slot.project,
                    {"total_duration": timedelta(0), "tasks": {}, "prod_score": 0.0},
                )
                task_node = proj_node["tasks"].setdefault(
                    slot.task or "No task",
                    {"total_duration": timedelta(0), "categories": {}, "prod_score": 0.0},
                )
                cat_node = task_node["categories"].setdefault(
                    category,
                    {"total_duration": timedelta(0), "apps": {}, "prod_score": 0.0},
                )

                # Iterate over apps within this category entry
                for app_entry in (cat_entry.get("apps") or []):
                    app_name = app_entry.get("app", "Unknown App")
                    app_duration = app_entry.get("duration", timedelta(0))
                    prod_score = (app_duration.total_seconds() / 3600) * score

                    app_node = cat_node["apps"].setdefault(
                        app_name, {"total_duration": timedelta(0), "prod_score": 0.0}
                    )

                    proj_node["total_duration"] += app_duration
                    proj_node["prod_score"] += prod_score
                    task_node["total_duration"] += app_duration
                    task_node["prod_score"] += prod_score
                    cat_node["total_duration"] += app_duration
                    cat_node["prod_score"] += prod_score
                    app_node["total_duration"] += app_duration
                    app_node["prod_score"] += prod_score

                    # Iterate over titles within this app entry
                    for title_entry in (app_entry.get("titles") or []):
                        title = title_entry.get("title", "No Title")
                        normalized_title = normalize_title(title)
                        title_duration = title_entry.get("duration", timedelta(0))
                        title_prod_score = (title_duration.total_seconds() / 3600) * score

                        title_node = app_node.setdefault("titles", {}).setdefault(
                            normalized_title,
                            {"total_duration": timedelta(0), "prod_score": 0.0},
                        )
                        title_node["total_duration"] += title_duration
                        title_node["prod_score"] += title_prod_score
    else:
        # Group by: Category > App > Title (no project/task level)
        for slot in consolidated_slots:
            for cat_entry in (slot.categories or []):
                category = cat_entry.get("category", "Uncategorized")
                score = get_category_score(category, cat_score_map)

                cat_node = report.setdefault(
                    category,
                    {"total_duration": timedelta(0), "apps": {}, "prod_score": 0.0},
                )

                for app_entry in (cat_entry.get("apps") or []):
                    app_name = app_entry.get("app", "Unknown App")
                    app_duration = app_entry.get("duration", timedelta(0))
                    prod_score = (app_duration.total_seconds() / 3600) * score

                    app_node = cat_node["apps"].setdefault(
                        app_name, {"total_duration": timedelta(0), "prod_score": 0.0}
                    )

                    cat_node["total_duration"] += app_duration
                    cat_node["prod_score"] += prod_score
                    app_node["total_duration"] += app_duration
                    app_node["prod_score"] += prod_score

                    for title_entry in (app_entry.get("titles") or []):
                        title = title_entry.get("title", "No Title")
                        normalized_title = normalize_title(title)
                        title_duration = title_entry.get("duration", timedelta(0))
                        title_prod_score = (title_duration.total_seconds() / 3600) * score

                        title_node = app_node.setdefault("titles", {}).setdefault(
                            normalized_title,
                            {"total_duration": timedelta(0), "prod_score": 0.0},
                        )
                        title_node["total_duration"] += title_duration
                        title_node["prod_score"] += title_prod_score

    return report


def compute_metrics(
    canonical_events: List[ReportEvent],
    cat_score_map: Dict[str, float],
    get_category_score: Callable[[str, Dict[str, float]], float],
    non_afk_time: timedelta,
    first_event_time,
    last_event_time,
    current_session_start,
    current_session_end,
    current_session_duration,
    last_break_start,
    last_break_end,
    last_break_duration,
    detail_level: int = 1,
) -> ReportMetrics:
    productive_time = timedelta(0)
    productive_task_time = timedelta(0)
    distracting_time = timedelta(0)
    unscored_time = timedelta(0)

    # Check if events have category data (window events from ActivityWatch)
    # If no window events were fetched (AFK optimization mode), category scoring is meaningless
    # Also, only calculate productivity metrics if detail_level >= 3, since lower levels
    # don't display window categories (can't justify the percentages with visible data)
    has_category_data = any(rep.event.data.get("$category") for rep in canonical_events)

    if has_category_data and detail_level >= 3:
        # Normal path: score events by category (productive/distracting/unscored)
        for report_event in canonical_events:
            event = report_event.event
            max_score = window_event_max_category_score(event, cat_score_map, get_category_score)
            if max_score > 0:
                productive_time += event.duration
                if report_event.active_task is not None:
                    productive_task_time += event.duration
            elif max_score < 0:
                distracting_time += event.duration
            else:
                unscored_time += event.duration
    # else: AFK optimization mode (no window events), skip category scoring entirely

    return ReportMetrics(
        productive_time=productive_time,
        productive_task_time=productive_task_time,
        distracting_time=distracting_time,
        unscored_time=unscored_time,
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


def build_context(
    canonical_events: List[ReportEvent],
    task_events: Optional[List[Event]],
    afk_events: List[Event],
    cat_score_map: Dict[str, float],
    is_task_based_report: bool,
    metrics: ReportMetrics,
) -> ReportContext:
    from tw_report.pipeline.models import BucketEvents

    # Organize events into typed BucketEvents collection
    bucket_events = BucketEvents(
        afk=afk_events,
        taskwarrior=task_events or [],
        window=[],  # Window events not stored in context (fetched on-demand)
    )

    return ReportContext(
        bucket_events=bucket_events,
        canonical_events=canonical_events,
        cat_score_map=cat_score_map,
        is_task_based_report=is_task_based_report,
        metrics=metrics,
    )


def merge_overlapping_afk_periods(afk_events: List[Event]) -> List[Event]:
    """Merge overlapping/touching AFK periods and bridge micro-gaps.

    Merges:
    1. All overlapping AFK events (both 'afk' and 'not-afk' status)
    2. Events separated by micro-gaps (< 2 seconds), treating them as continuous online time
    3. This eliminates spurious offline-time noise (2-7s gaps) caused by ActivityWatch
       sometimes recording events separately vs. merging them

    The 2-second threshold is chosen because:
    - Micro-gaps smaller than this are almost certainly AW recording artifacts
    - A genuine system powerdown would produce seconds-to-minutes gaps, not milliseconds
    - This matches typical AW event boundary jitter (~0.5s precision)

    Args:
        afk_events: list of AFK bucket events with 'status' field ('afk' or 'not-afk')

    Returns:
        new list with overlapping periods and micro-gaps merged
    """
    from datetime import timedelta

    if not afk_events or len(afk_events) <= 1:
        return afk_events

    # Sort all AFK events (both 'afk' and 'not-afk') by start time
    sorted_events = sorted(afk_events, key=lambda e: e.timestamp)

    # Merge overlapping and micro-gap-separated events (SAME STATUS ONLY)
    merged = []
    current_event = deepcopy(sorted_events[0])
    current_start = current_event.timestamp
    current_end = current_event.timestamp + current_event.duration
    current_status = current_event.data.get("status")

    for event in sorted_events[1:]:
        event_status = event.data.get("status")
        event_start = event.timestamp
        event_end = event.timestamp + event.duration
        gap = event_start - current_end

        # Only merge if same status AND (overlapping OR micro-gap < 2 seconds)
        # Don't merge across status changes (afk ≠ not-afk)
        if event_status == current_status and gap < timedelta(seconds=2):
            # Same status + overlap/small gap: extend the range
            current_end = max(current_end, event_end)
        else:
            # Status changed OR real gap: finalize current period and start new one
            merged_duration = current_end - current_start
            current_event.timestamp = current_start
            current_event.duration = merged_duration
            merged.append(current_event)

            current_event = deepcopy(event)
            current_start = event_start
            current_end = event_end
            current_status = event_status

    # Finalize last period
    merged_duration = current_end - current_start
    current_event.timestamp = current_start
    current_event.duration = merged_duration
    merged.append(current_event)

    return sorted(merged, key=lambda e: e.timestamp)

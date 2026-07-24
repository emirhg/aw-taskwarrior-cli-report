from copy import deepcopy
from datetime import timedelta
from typing import Callable, Dict, List, Optional, Tuple

from aw_core.models import Event
from aw_transform import filter_period_intersect

from tw_report.pipeline.models import ReportContext, ReportEvent, ReportMetrics


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
) -> ReportMetrics:
    productive_time = timedelta(0)
    productive_task_time = timedelta(0)
    distracting_time = timedelta(0)
    unscored_time = timedelta(0)

    # Check if events have category data (window events from ActivityWatch)
    # If no window events were fetched (AFK optimization mode), category scoring is meaningless
    has_category_data = any(rep.event.data.get("$category") for rep in canonical_events)

    if has_category_data:
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
    return ReportContext(
        canonical_events=canonical_events,
        task_events=task_events,
        afk_events=afk_events,
        cat_score_map=cat_score_map,
        is_task_based_report=is_task_based_report,
        metrics=metrics,
    )


def merge_overlapping_afk_periods(afk_events: List[Event]) -> List[Event]:
    """Merge overlapping not-afk periods into single continuous periods.

    When not-afk events overlap (which shouldn't happen normally but can occur due to
    data quality issues), merge them into single continuous periods. This ensures clean
    non-overlapping periods for downstream processing.

    Args:
        afk_events: list of AFK bucket events with 'status' field ('afk' or 'not-afk')

    Returns:
        new list with overlapping not-afk periods merged
    """
    from aw_transform import filter_keyvals

    # Filter to not-afk periods only
    not_afk_events = filter_keyvals(afk_events, "status", ["not-afk"])
    if len(not_afk_events) <= 1:
        return afk_events

    # Sort by start time
    sorted_events = sorted(not_afk_events, key=lambda e: e.timestamp)

    # Merge overlapping periods
    merged = []
    current_start = sorted_events[0].timestamp
    current_end = sorted_events[0].timestamp + sorted_events[0].duration

    for event in sorted_events[1:]:
        event_end = event.timestamp + event.duration

        # Check if current event overlaps with merged range
        if event.timestamp <= current_end:
            # Overlap: extend the range
            current_end = max(current_end, event_end)
        else:
            # No overlap: finalize current period and start new one
            merged_duration = current_end - current_start
            merged_event = deepcopy(sorted_events[0])
            merged_event.timestamp = current_start
            merged_event.duration = merged_duration
            merged.append(merged_event)

            current_start = event.timestamp
            current_end = event_end

    # Finalize last period
    merged_duration = current_end - current_start
    merged_event = deepcopy(sorted_events[0])
    merged_event.timestamp = current_start
    merged_event.duration = merged_duration
    merged.append(merged_event)

    # Reconstruct afk_events list with merged not-afk periods and original afk periods
    afk_only = filter_keyvals(afk_events, "status", ["afk"])
    result = list(afk_only) + merged
    return sorted(result, key=lambda e: e.timestamp)

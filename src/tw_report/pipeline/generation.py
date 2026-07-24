"""
Timeline data generation: converts raw events into timeline slots.

This module handles the core logic for:
- Merging overlapping AFK events
- Generating activity slots from window events (with project/task/category grouping)
- Generating AFK/gap slots from AFK bucket events
"""

from datetime import timedelta
from typing import Any, Dict, List, Optional

from aw_core.models import Event
from aw_transform import filter_keyvals

from tw_report.core.categories import (
    build_categories_from_window_events,
    get_category_score as default_get_category_score,
)
from tw_report.core.filtering import NO_PROJECT, NO_TASK
from tw_report.core.task_matching import (
    find_active_task,
    get_task_info,
)
from tw_report.pipeline.models import ReportEvent
from tw_report.pipeline.processors import window_event_productive_duration
from tw_report.utils.formatting import normalize_title, sanitize_title


# Minimum duration threshold for including window events in timeline
# Events shorter than this are considered ActivityWatch tracking noise
MIN_EVENT_DURATION = timedelta(seconds=60)


def _merge_overlapping_events(events: List[Event]) -> List[Event]:
    """Merge overlapping events by taking the union of their time ranges.

    When two events overlap, combine them into a single event covering both periods.
    """
    if not events:
        return events

    # Sort by start time
    sorted_events = sorted(events, key=lambda e: e.timestamp)
    merged = []
    current = sorted_events[0]

    for event in sorted_events[1:]:
        # Check if event overlaps or is adjacent to current
        current_end = current.timestamp + current.duration
        if event.timestamp <= current_end:
            # Overlapping or adjacent: merge by extending current
            new_end = max(current_end, event.timestamp + event.duration)
            current = Event(
                timestamp=current.timestamp,
                duration=new_end - current.timestamp,
                data=current.data,
            )
        else:
            # Non-overlapping: save current and start new
            merged.append(current)
            current = event

    merged.append(current)
    return merged


def generate_untracked_gap_events(
    not_afk_events: List[Event],
    task_events: Optional[List[Event]],
) -> List[ReportEvent]:
    """Generate synthetic NO_PROJECT/NO_TASK events for not-afk time uncovered by any task.

    For each not-afk period, subtracts sub-ranges already covered by a TaskWarrior task event.
    Remaining uncovered sub-ranges >= MIN_EVENT_DURATION become synthetic ReportEvent entries,
    allowing untracked activity time to be represented in timesheets without fetching window events.

    Args:
        not_afk_events: List of not-afk events (periods when user was active)
        task_events: List of TaskWarrior task events (may be None if no tasks)

    Returns:
        List of ReportEvent instances tagged NO_PROJECT/NO_TASK for uncovered gaps
    """
    result = []

    if not not_afk_events:
        return result

    # If no task events, entire not-afk periods are uncovered
    if not task_events:
        for not_afk_event in not_afk_events:
            if not_afk_event.duration >= MIN_EVENT_DURATION:
                synthetic_event = Event(
                    timestamp=not_afk_event.timestamp,
                    duration=not_afk_event.duration,
                    data={},
                )
                result.append(ReportEvent(
                    event=synthetic_event,
                    project=NO_PROJECT,
                    task=NO_TASK,
                    active_task=None,
                ))
        return result

    # Process each not-afk period
    for not_afk_event in not_afk_events:
        not_afk_start = not_afk_event.timestamp
        not_afk_end = not_afk_start + not_afk_event.duration

        # Find all task events that overlap this not-afk period
        overlapping_tasks = [
            t for t in task_events
            if t.timestamp < not_afk_end and (t.timestamp + t.duration) > not_afk_start
        ]

        if not overlapping_tasks:
            # Entire not-afk period is uncovered by any task
            if not_afk_event.duration >= MIN_EVENT_DURATION:
                synthetic_event = Event(
                    timestamp=not_afk_start,
                    duration=not_afk_event.duration,
                    data={},
                )
                result.append(ReportEvent(
                    event=synthetic_event,
                    project=NO_PROJECT,
                    task=NO_TASK,
                    active_task=None,
                ))
            continue

        # Sort task events by start time
        overlapping_tasks = sorted(overlapping_tasks, key=lambda t: t.timestamp)

        # Merge overlapping task intervals to find covered sub-ranges
        merged_tasks = []
        for task in overlapping_tasks:
            task_start = max(task.timestamp, not_afk_start)
            task_end = min(task.timestamp + task.duration, not_afk_end)

            if merged_tasks and task_start <= merged_tasks[-1][1]:
                # Overlaps with previous merged interval: extend
                merged_tasks[-1] = (merged_tasks[-1][0], max(merged_tasks[-1][1], task_end))
            else:
                # Non-overlapping: add new interval
                merged_tasks.append((task_start, task_end))

        # Compute gaps (uncovered intervals) as complement of covered intervals
        current_pos = not_afk_start
        for covered_start, covered_end in merged_tasks:
            # Gap before this covered interval
            if current_pos < covered_start:
                gap_duration = covered_start - current_pos
                if gap_duration >= MIN_EVENT_DURATION:
                    synthetic_event = Event(
                        timestamp=current_pos,
                        duration=gap_duration,
                        data={},
                    )
                    result.append(ReportEvent(
                        event=synthetic_event,
                        project=NO_PROJECT,
                        task=NO_TASK,
                        active_task=None,
                    ))
            current_pos = max(current_pos, covered_end)

        # Gap after all covered intervals
        if current_pos < not_afk_end:
            gap_duration = not_afk_end - current_pos
            if gap_duration >= MIN_EVENT_DURATION:
                synthetic_event = Event(
                    timestamp=current_pos,
                    duration=gap_duration,
                    data={},
                )
                result.append(ReportEvent(
                    event=synthetic_event,
                    project=NO_PROJECT,
                    task=NO_TASK,
                    active_task=None,
                ))

    return result


def generate_gap_entries(
    afk_events: List[Event],
    task_events: Optional[List[Event]],
    offline_threshold_s: float = 120.0,
    window_events: Optional[List[Event]] = None,
) -> List[Dict]:
    """Generate AFK slots from AFK bucket events.

    AFK events with status="afk" (user away) are shown as slots, with project/task info
    from overlapping TW tasks (or NO_PROJECT/NO_TASK if no task active).

    Categories from overlapping window events are extracted and attached to AFK slots
    to show what apps/windows were active during AFK periods.

    Args:
        afk_events: all AFK bucket events (both status="afk" and status="not-afk")
        task_events: TaskWarrior events for resolving active tasks during AFK periods
        offline_threshold_s: (deprecated, no longer used)
        window_events: optional window events to extract categories from for AFK periods

    Returns:
        list of slot dicts with type="afk"
    """
    result = []

    # Generate AFK slots from explicit status="afk" events
    afk_only_events = filter_keyvals(afk_events, "status", ["afk"])
    # Merge overlapping AFK events to prevent duplicate overlapping slots
    afk_only_events = _merge_overlapping_events(afk_only_events)
    for i, afk_event in enumerate(afk_only_events):
        # Find active TW task during this AFK period (if any)
        active_task = find_active_task(afk_event, task_events) if task_events else None
        if active_task:
            task_name, project = get_task_info(active_task)
        else:
            task_name = NO_TASK
            project = NO_PROJECT

        # HARDENING: AFK slots now require explicit actual_duration.
        # For AFK time, actual_duration == duration (AFK is always "actual" tracked time).
        # Previously, this was silently defaulted in TimelineSlot.__post_init__, which
        # masked bugs in other slot types. Now all slots must be explicit.
        slot = {
            "type": "afk",
            "start": afk_event.timestamp.astimezone(),
            "end": (afk_event.timestamp + afk_event.duration).astimezone(),
            "duration": afk_event.duration,
            "actual_duration": afk_event.duration,  # Required: afk time is always actual
            "project": project,
            "task": task_name,
        }

        # Extract categories from overlapping window events if provided
        if window_events:
            afk_start = slot["start"]
            afk_end = slot["end"]
            slot["categories"] = build_categories_from_window_events(
                window_events, afk_start, afk_end
            )
        else:
            slot["categories"] = []

        result.append(slot)

    return result


def generate_timeline_data(
    report_events: List[Dict[str, Any]],
    afk_events: List[Event],
    cat_score_map: Dict[str, float],
    detail_level: int = 1,
    deduplicate_categories: bool = False,
    get_category_score=None,
) -> List[Dict]:
    """
    Generate timeline data grouped by not-afk periods (time slots).

    detail_level controls what sub-data is collected per slot:
      1 = Project only
      2 = Project + Task
      3 = Project + Task + Category
      4 = Project + Task + Category + App
      5 = Project + Task + Category + App + Title

    CORE CONCEPT - What is a "time slot" and "subslot"?
    ==================================================
    A NOT-AFk PERIOD is a continuous work period defined by a single not-afk event.
    Not-afk events come from ActivityWatch AFK bucket (status="not-afk") and
    represent times when the user is active (mouse/keyboard activity).

    A SUBSLOT is a continuous sequence within a not-afk period where PROJECT,
    TASK, and TASKWARRIOR EVENT remain unchanged. Continuity is determined by
    the (project, task, task_event) triplet:
    - Window switching: does NOT break continuity (you can switch apps/windows within same task)
    - Task change: BREAKS continuity and creates a new slot
    - Project change: BREAKS continuity and creates a new slot
    - Task pause/resume (different taskwarrior event): creates a NEW slot (task was paused and restarted)

    GROUPING LOGIC:
    ===============
    For EACH not-afk event:
      1. Find all window events that overlap with this not-afk period
      2. Sort events chronologically
      3. Group consecutive events by (PROJECT, TASK, TASKWARRIOR_EVENT) CONTINUITY
         - When (project, task, task_event) triplet changes → start a new subslot
         - When only app/window changes (same project, task, & task_event) → continue same subslot
         - When task is paused and resumed (different task_event) → create new subslot
      4. Create ONE slot per (project, task, task_event) continuous GROUP
         - Subslot start = earliest event in group
         - Subslot end = latest event in group
         - Subslot duration = sum of all event durations
      5. Multiple gaps/pauses in a day = multiple not-afk events = multiple subslots
      6. Task pause/resume cycles = multiple task_events = multiple subslots

    FILTERING WITH TIMELINE:
    ========================
    When filters (--project, --task, --app, search term) are applied:
    - Window events are pre-filtered BEFORE calling this function
    - Only matching events are passed to this function
    - Not-afk boundaries are preserved (slot structure unchanged)
    - Result: filtered slots that still show pauses between not-afk events

    EXAMPLE TIMELINE (single not-afk event with project/task/pause changes):
    ========================================================================
    Not-afk period: 07:00-18:00 (continuous activity, no AFK breaks)

    Chronological window events with corresponding taskwarrior events:
      - Climb (07:00-09:00, Task A, event_id=1) ← (Climb, Task A, event_id=1)
      - Climb (09:00-11:00, Task B, event_id=2) ← (Climb, Task B, event_id=2) = NEW slot (task changed)
      - Mercado (11:00-13:00, Task X, event_id=3) ← (Mercado, Task X, event_id=3) = NEW slot (project changed)
      - Climb (13:00-15:00, Task A, event_id=4) ← (Climb, Task A, event_id=4) = NEW slot (Task A paused & resumed)
      - Climb (15:00-16:00, Task A, event_id=4) ← (Climb, Task A, event_id=4) = continues same slot (same event_id)
      - Ecosistema (16:00-18:00, Task Y, event_id=5) ← (Ecosistema, Task Y, event_id=5) = NEW slot (project changed)

    Resulting SUBSLOTS ((project, task, task_event) continuous groups):
      Subslot 1: Climb + Task A (event_id=1), 07:00-09:00
      Subslot 2: Climb + Task B (event_id=2), 09:00-11:00 ← separate because task changed
      Subslot 3: Mercado + Task X (event_id=3), 11:00-13:00 ← separate because project changed
      Subslot 4: Climb + Task A (event_id=4), 13:00-16:00 ← separate even though same task (paused & resumed with new event_id)
      Subslot 5: Ecosistema + Task Y (event_id=5), 16:00-18:00 ← separate because project changed

    This preserves activity continuity: each taskwarrior event represents a distinct work session.
    When a task is paused and resumed, it gets a new event_id, triggering a new slot.
    Window switching (e.g., Climb+Task A in Kitty → Climb+Task A in Browser, same event_id) continues
    the same slot because (project, task, task_event) is unchanged.
    """
    if not report_events:
        return []

    # Filter to not-afk periods only
    not_afk_events = filter_keyvals(afk_events, "status", ["not-afk"])
    not_afk_events = sorted(not_afk_events, key=lambda e: e.timestamp)

    slots = []

    # For each not-afk period (time slot boundary)
    for afk_event in not_afk_events:
        # Get all report events that overlap this not-afk period
        window_in_slot = [
            rep
            for rep in report_events
            if rep["event"].timestamp < afk_event.timestamp + afk_event.duration
            and afk_event.timestamp < rep["event"].timestamp + rep["event"].duration
        ]

        if not window_in_slot:
            continue

        # Sort events chronologically to detect (project, task) continuity
        window_in_slot = sorted(window_in_slot, key=lambda r: r["event"].timestamp)

        # Build slots grouped by (project, task, task_event) continuity
        # Window switching does NOT break continuity (same slot continues)
        # Task change breaks continuity (new slot)
        # Project change breaks continuity (new slot)
        # Task pause/resume (different taskwarrior event) creates new slot
        slots_in_period = []
        current_slot = None
        current_project_task_session = None

        for report_event in window_in_slot:
            event = report_event["event"]
            # Skip zero-duration and very brief events (< MIN_EVENT_DURATION - likely noise from AW tracking)
            # These create visual clutter in the timeline without meaningful activity information
            if event.duration < MIN_EVENT_DURATION:
                continue

            task_name = report_event["task"]
            project = report_event["project"]
            active_task = report_event["active_task"]

            app_name = event.data.get("app", "Unknown App")
            window_title = (
                event.data.get("title", "No Title") if detail_level >= 5 else None
            )

            # Include the active_task instance to distinguish between paused/resumed sessions
            # In no-task mode, use a constant session key since there's no task tracking
            project_task_session = (
                project,
                task_name,
                id(active_task) if active_task else 0,
            )

            # Check if (project, task, task_event) changed (breaks slot continuity)
            if project_task_session != current_project_task_session:
                # Start a new slot for this (project, task, task_event) combination
                current_project_task_session = project_task_session
                current_slot = {
                    "project": project,
                    "task": task_name,
                    "events": [report_event],
                    "categories": {} if deduplicate_categories else [],
                }
                # For non-dedup mode: track current category/app/title to detect continuity breaks
                if not deduplicate_categories:
                    current_slot.update(
                        {
                            "_cur_cat": None,
                            "_cur_cat_block": None,
                            "_cur_app": None,
                            "_cur_app_block": None,
                            "_cur_title": None,
                            "_cur_title_entry": None,
                        }
                    )
                slots_in_period.append(current_slot)
            else:
                # Same (project, task, task_event), add event to current slot (window switching doesn't break continuity)
                current_slot["events"].append(report_event)

            # Track category time with nested apps and titles (level 3+)
            if detail_level >= 3:
                event_ts = event.timestamp.astimezone()
                event_end_ts = (event.timestamp + event.duration).astimezone()

                category = event.data.get("$category", ["Uncategorized"])[0]

                if deduplicate_categories:
                    # OLD PATH: Dict-based accumulation (deduplicated)
                    if category not in current_slot["categories"]:
                        current_slot["categories"][category] = {
                            "duration": timedelta(0),
                            "start": event_ts,
                            "end": event_end_ts,
                            "apps": {},
                        }
                    else:
                        # Update start/end to expand range
                        cat_data = current_slot["categories"][category]
                        if event_ts < cat_data["start"]:
                            cat_data["start"] = event_ts
                        if event_end_ts > cat_data["end"]:
                            cat_data["end"] = event_end_ts

                    current_slot["categories"][category]["duration"] += event.duration

                    # Track app time nested under category (level 4+)
                    if detail_level >= 4:
                        if app_name not in current_slot["categories"][category]["apps"]:
                            current_slot["categories"][category]["apps"][app_name] = {
                                "duration": timedelta(0),
                                "start": event_ts,
                                "end": event_end_ts,
                                "titles": {},
                            }
                        else:
                            # Update start/end to expand range
                            app_data = current_slot["categories"][category]["apps"][
                                app_name
                            ]
                            if event_ts < app_data["start"]:
                                app_data["start"] = event_ts
                            if event_end_ts > app_data["end"]:
                                app_data["end"] = event_end_ts

                        current_slot["categories"][category]["apps"][app_name][
                            "duration"
                        ] += event.duration

                        # Track per-title breakdown (level 5+)
                        if window_title:
                            normalized_title = normalize_title(window_title)
                            clean_title = sanitize_title(normalized_title)
                            titles = current_slot["categories"][category]["apps"][
                                app_name
                            ]["titles"]
                            if clean_title not in titles:
                                titles[clean_title] = {
                                    "duration": timedelta(0),
                                    "events": [
                                        {"start": event_ts, "end": event_end_ts}
                                    ],
                                }
                            else:
                                title_data = titles[clean_title]
                                title_data["events"].append(
                                    {"start": event_ts, "end": event_end_ts}
                                )

                            titles[clean_title]["duration"] += event.duration
                else:
                    # NEW PATH: List-based accumulation (timeline order, no dedup)
                    # Category level: start new block if category changes
                    if category != current_slot["_cur_cat"]:
                        new_cat_block = {
                            "category": category,
                            "duration": event.duration,
                            "start": event_ts,
                            "end": event_end_ts,
                            "apps": [],
                        }
                        current_slot["categories"].append(new_cat_block)
                        current_slot["_cur_cat"] = category
                        current_slot["_cur_cat_block"] = new_cat_block
                        current_slot["_cur_app"] = None
                        current_slot["_cur_app_block"] = None
                        current_slot["_cur_title"] = None
                        current_slot["_cur_title_entry"] = None
                    else:
                        # Same category: update the current block
                        cb = current_slot["_cur_cat_block"]
                        cb["duration"] += event.duration
                        if event_end_ts > cb["end"]:
                            cb["end"] = event_end_ts

                    # App level: start new app block if app changes (level 4+)
                    if detail_level >= 4:
                        if app_name != current_slot["_cur_app"]:
                            new_app_block = {
                                "app": app_name,
                                "duration": event.duration,
                                "start": event_ts,
                                "end": event_end_ts,
                                "titles": [],
                            }
                            current_slot["_cur_cat_block"]["apps"].append(new_app_block)
                            current_slot["_cur_app"] = app_name
                            current_slot["_cur_app_block"] = new_app_block
                            current_slot["_cur_title"] = None
                            current_slot["_cur_title_entry"] = None
                        else:
                            # Same app: update the current app block
                            ab = current_slot["_cur_app_block"]
                            ab["duration"] += event.duration
                            if event_end_ts > ab["end"]:
                                ab["end"] = event_end_ts

                        # Title level: start new title entry if title changes (level 5+)
                        if window_title and detail_level >= 5:
                            normalized_title = normalize_title(window_title)
                            clean_title = sanitize_title(normalized_title)

                            if clean_title != current_slot["_cur_title"]:
                                new_title_entry = {
                                    "title": clean_title,
                                    "duration": event.duration,
                                    "events": [
                                        {"start": event_ts, "end": event_end_ts}
                                    ],
                                }
                                current_slot["_cur_app_block"]["titles"].append(
                                    new_title_entry
                                )
                                current_slot["_cur_title"] = clean_title
                                current_slot["_cur_title_entry"] = new_title_entry
                            else:
                                # Same title: add event to current title entry
                                te = current_slot["_cur_title_entry"]
                                te["duration"] += event.duration
                                te["events"].append(
                                    {"start": event_ts, "end": event_end_ts}
                                )

        # Create final slots from collected (project, task) continuity groups
        for slot_data in slots_in_period:
            events = slot_data["events"]
            # Convert UTC timestamps to local time
            event_starts = [e["event"].timestamp.astimezone() for e in events]
            event_ends = [
                (e["event"].timestamp + e["event"].duration).astimezone()
                for e in events
            ]
            slot_start = min(event_starts)
            slot_end = max(event_ends)
            # Duration fields for the slot:
            # - slot_duration: wall-clock time span (for display end_time calculation)
            # - actual_duration: TaskWarrior task duration (ground truth)
            slot_duration = slot_end - slot_start

            # Use TaskWarrior task duration as the source of truth
            active_task_event = events[0]["active_task"] if events else None
            if active_task_event and active_task_event.duration:
                actual_duration = active_task_event.duration
            else:
                # Fallback for --no-taskwarrior mode: sum window event durations
                actual_duration = sum((e["event"].duration for e in events), timedelta(0))

            # Build nested category structure: {category, duration, start, end, apps: [{app, duration, start, end, titles}]}
            if deduplicate_categories:
                # OLD PATH: Convert dict to list (deduplicated)
                categories_list = []
                # Sort categories by start time (chronological order)
                for cat, cat_data in sorted(
                    slot_data["categories"].items(), key=lambda x: x[1].get("start", "")
                ):
                    cat_info = {
                        "category": cat,
                        "duration": cat_data["duration"],
                        "start": cat_data.get("start"),
                        "end": cat_data.get("end"),
                    }
                    if detail_level >= 4 and cat_data["apps"]:
                        # Sort apps by start time (chronological order)
                        cat_info["apps"] = [
                            {
                                "app": app_name,
                                "duration": app_data["duration"],
                                "start": app_data.get("start"),
                                "end": app_data.get("end"),
                                "titles": (
                                    [
                                        {
                                            "title": t,
                                            "duration": title_data["duration"],
                                            "events": title_data.get("events")
                                            if isinstance(title_data, dict)
                                            else None,
                                        }
                                        for t, title_data in sorted(
                                            app_data["titles"].items(),
                                            key=lambda x: (x[1].get("events") or [{}])[
                                                0
                                            ].get("start")
                                            if isinstance(x[1], dict)
                                            else x[1],
                                        )
                                    ]
                                    if detail_level >= 5
                                    else []
                                ),
                            }
                            for app_name, app_data in sorted(
                                cat_data["apps"].items(),
                                key=lambda x: x[1].get("start", ""),
                            )
                        ]
                    categories_list.append(cat_info)
            else:
                # NEW PATH: Categories already in list form (timeline order)
                # Just clean up internal tracking fields
                categories_list = slot_data["categories"]
                for k in (
                    "_cur_cat",
                    "_cur_cat_block",
                    "_cur_app",
                    "_cur_app_block",
                    "_cur_title",
                    "_cur_title_entry",
                ):
                    slot_data.pop(k, None)

            # Use provided get_category_score or default implementation
            score_func = get_category_score if get_category_score is not None else default_get_category_score
            productive_in_slot = sum(
                (
                    window_event_productive_duration(e["event"], cat_score_map, score_func)
                    for e in events
                ),
                timedelta(0),
            )
            # Extract tags from TW task event (if available)
            task_tags = []
            if events:
                active_task_event = events[0].get("active_task")
                if active_task_event is not None:
                    raw_tags = active_task_event.data.get("tags", [])
                    task_tags = (
                        [raw_tags] if isinstance(raw_tags, str) else list(raw_tags)
                    )

            # Calculate total offline_extension_duration from all window events in this slot
            offline_overlap = timedelta(0)
            for event_wrapper in events:
                window_event = event_wrapper["event"]
                if "offline_extension_duration" in window_event.data:
                    offline_overlap += window_event.data["offline_extension_duration"]

            slot = {
                "type": "regular",
                "start": slot_start,
                "end": slot_end,
                "duration": slot_duration,
                "actual_duration": actual_duration,
                "productive_duration": productive_in_slot,
                "project": slot_data["project"],
                "task": slot_data["task"],
                "afk_period_start": afk_event.timestamp,
                "afk_period_end": afk_event.timestamp + afk_event.duration,
                "tags": task_tags,
            }
            if offline_overlap.total_seconds() > 0:
                slot["offline_extension_duration"] = offline_overlap
            if detail_level >= 3 and categories_list:
                slot["categories"] = categories_list

            slots.append(slot)

    # Sort slots by start time
    slots = sorted(slots, key=lambda s: s["start"])

    # Deduplicate regular slots created by overlapping window events across multiple not-afk periods.
    # When a window event spans multiple not-afk periods (with micro-pauses between them),
    # the same regular slot gets created multiple times. We keep only the first occurrence.
    # This is safe because all duplicates have identical properties (except afk_period metadata).
    # Note: We only deduplicate regular slots; gap entries (AFK slots) are handled separately.
    seen_regular_slots = {}
    deduped_slots = []
    for slot in slots:
        # Only deduplicate regular slots; gap entries (AFK, etc.) pass through
        if slot.get("type") == "regular":
            # Create dedup key for regular slots
            key = (
                slot["start"],
                slot["end"],
                slot["project"],
                slot["task"],
            )
            if key not in seen_regular_slots:
                seen_regular_slots[key] = True
                deduped_slots.append(slot)
            # Skip duplicate regular slots
        else:
            # Non-regular slots (shouldn't happen here, but preserve them)
            deduped_slots.append(slot)

    return deduped_slots

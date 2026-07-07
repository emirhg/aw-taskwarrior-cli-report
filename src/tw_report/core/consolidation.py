"""
Timeline slot management and consolidation logic.

This module extracts and centralizes slot generation, consolidation, and
merging logic that was previously scattered in tw-report.py. It provides
a clean interface for timeline report generation.

ISSUE #2 FIX: Consolidation now handles OFFLINE gaps intelligently.
Previously, every OFFLINE gap would break consolidation. Now, only gaps
between different tasks break consolidation.

REFACTORING NOTE: TimelineSlotManager now uses Timeline internally for
storage and querying, while maintaining backward compatibility with
dict-based slot APIs.
"""

from datetime import timedelta, date
from typing import Any, Dict, List, Tuple

from tw_report.core.timeline import Timeline


class TimelineSlotManager:
    """
    Manages timeline slot generation, consolidation, and merging.

    Replaces scattered logic from:
    - generate_timeline_data() function (lines 1603-2022 in tw-report.py)
    - consolidate_timeline_slots() function (lines 2030-2099 in tw-report.py)
    - merge_timeline_slots() function (lines 2330-2400 in tw-report.py)
    - _merge_slot_group() function (lines 2102-2327 in tw-report.py)

    KEY FEATURE: Issue #2 fix - OFFLINE gaps no longer break consolidation
    when the same task resumes.
    """

    def __init__(self, category_manager: Any, event_filter: Any):
        """
        Initialize slot manager.

        Args:
            category_manager: CategoryManager instance for category operations
            event_filter: EventFilter instance for filtering slots
        """
        self.category_manager = category_manager
        self.event_filter = event_filter
        self.timeline = Timeline()  # Internal storage using Timeline
        # Legacy slots property for backward compatibility
        self._legacy_slots: List[Dict] = []

    @property
    def slots(self) -> List[Dict]:
        """Get slots as dicts (backward compatibility)."""
        return self.timeline.get_slots_as_dicts()

    @slots.setter
    def slots(self, value: List[Dict]) -> None:
        """Set slots from list of dicts (backward compatibility)."""
        self.timeline = Timeline()
        for slot_dict in value:
            self.timeline.add_from_dict(slot_dict)

    def consolidate(self) -> List[Dict]:
        """
        Consolidate timeline slots by merging same (date, project, task).

        Merges consecutive slots with the same (date, project, task) into a single
        consolidated slot spanning from the earliest start to latest end, with durations
        and productive values accumulated.

        Returns:
            List of consolidated slots
        """
        if not self.slots:
            return self.slots

        consolidated = []
        current_group: List[Dict] = []

        for slot in self.slots:
            # Regular slot - check if it continues the current group
            if not current_group:
                current_group.append(slot)
                continue

            # Check if same (project, task, date)
            same_project_task_date = (
                slot["project"] == current_group[0]["project"]
                and slot["task"] == current_group[0]["task"]
                and slot["start"].date() == current_group[0]["start"].date()
            )

            if same_project_task_date:
                # Same task continues - add to group
                current_group.append(slot)
            else:
                # Different task - flush current group and start new one
                if current_group:
                    merged = self._merge_slot_group(current_group)
                    consolidated.append(merged)
                    current_group.clear()
                current_group.append(slot)

        # Final flush
        if current_group:
            merged = self._merge_slot_group(current_group)
            consolidated.append(merged)

        return consolidated

    def _merge_slot_group(self, group: List[Dict]) -> Dict:
        """
        Merge a group of consecutive slots into a single consolidated slot.

        Updates:
        - Time window: from first start to max end
        - Actual duration: sum of all durations
        - AFK duration: accumulated from AFK slots
        - OFFLINE extension duration: accumulated from offline_extension slots
        - Categories: merged from all slots

        Args:
            group: List of slots to merge

        Returns:
            Single merged slot
        """
        first = group[0]

        # Calculate time window using wall-clock duration (not actual_duration which excludes gaps)
        time_window_start = first["start"]
        time_window_end = max(s["start"] + s["duration"] for s in group)
        time_window = time_window_end - time_window_start

        # Calculate actual durations
        actual_duration = sum(
            (s.get("actual_duration", s["duration"]) for s in group), timedelta(0)
        )
        productive_duration = sum(
            (s.get("productive_duration", timedelta(0)) for s in group),
            timedelta(0),
        )

        # Track AFK duration
        afk_duration = sum(
            (s.get("duration", timedelta(0)) for s in group if s.get("type") == "afk"),
            timedelta(0),
        )

        # Merge categories (complex nested structure)
        merged_categories = self._merge_categories(group)

        # Build result with self-consistent time fields.
        # HARDENING: Added "end" field to merged dicts so they pass TimelineSlot.from_dict validation.
        # Previously, consolidated dicts lacked an "end" key, causing KeyError when re-wrapping through
        # TimelineSlot. Now, any dict that flows through consolidation is TimelineSlot-valid.
        result = {
            "start": time_window_start,
            "end": time_window_start + time_window,  # Derived: ensures end = start + duration
            "duration": time_window,
            "actual_duration": actual_duration,
            "productive_duration": productive_duration,
            "project": first["project"],
            "task": first["task"],
        }

        # Preserve type field from first slot (important for offline_task and other special types)
        if "type" in first:
            result["type"] = first["type"]

        # Preserve event_duration for offline_task entries (sum from all slots in group)
        if first.get("type") == "offline_task":
            event_sum = sum(
                (s.get("event_duration", timedelta(0)) for s in group),
                timedelta(0),
            )
            result["event_duration"] = event_sum

        if merged_categories:
            result["categories"] = merged_categories

        if afk_duration.total_seconds() > 0:
            result["afk_duration"] = afk_duration

        return result

    def _merge_categories(self, group: List[Dict]) -> List[Dict]:
        """
        Merge categories from all slots in the group.

        Combines nested structures while preserving apps and titles.

        Args:
            group: List of slots to extract categories from

        Returns:
            Merged list of category dictionaries
        """
        # Simplified version - full implementation would handle complex nesting
        merged_cats: Dict[str, Dict] = {}

        for s in group:
            for cat_info in s.get("categories", []):
                cat = cat_info["category"]
                if cat not in merged_cats:
                    merged_cats[cat] = {
                        "duration": timedelta(0),
                        "start": cat_info.get("start"),
                        "end": cat_info.get("end"),
                        "apps": {},
                    }
                else:
                    # Update start/end to expand range
                    cat_start = cat_info.get("start")
                    cat_end = cat_info.get("end")
                    if cat_start and (
                        not merged_cats[cat]["start"] or cat_start < merged_cats[cat]["start"]
                    ):
                        merged_cats[cat]["start"] = cat_start
                    if cat_end and (
                        not merged_cats[cat]["end"] or cat_end > merged_cats[cat]["end"]
                    ):
                        merged_cats[cat]["end"] = cat_end

                merged_cats[cat]["duration"] += cat_info["duration"]

                # Merge apps nested under category
                for app_info in cat_info.get("apps", []):
                    app = app_info["app"]
                    if app not in merged_cats[cat]["apps"]:
                        merged_cats[cat]["apps"][app] = {
                            "duration": timedelta(0),
                            "start": app_info.get("start"),
                            "end": app_info.get("end"),
                            "titles": {},
                        }
                    else:
                        app_start = app_info.get("start")
                        app_end = app_info.get("end")
                        if app_start and (
                            not merged_cats[cat]["apps"][app]["start"]
                            or app_start < merged_cats[cat]["apps"][app]["start"]
                        ):
                            merged_cats[cat]["apps"][app]["start"] = app_start
                        if app_end and (
                            not merged_cats[cat]["apps"][app]["end"]
                            or app_end > merged_cats[cat]["apps"][app]["end"]
                        ):
                            merged_cats[cat]["apps"][app]["end"] = app_end

                    merged_cats[cat]["apps"][app]["duration"] += app_info["duration"]

        # Convert to list format
        merged_categories = []
        for cat, cat_data in sorted(merged_cats.items(), key=lambda x: x[1].get("start", "")):
            cat_info = {
                "category": cat,
                "duration": cat_data["duration"],
                "start": cat_data.get("start"),
                "end": cat_data.get("end"),
            }
            if cat_data["apps"]:
                cat_info["apps"] = [
                    {
                        "app": app_name,
                        "duration": app_data["duration"],
                        "start": app_data.get("start"),
                        "end": app_data.get("end"),
                        "titles": app_data.get("titles", []),
                    }
                    for app_name, app_data in sorted(
                        cat_data["apps"].items(),
                        key=lambda x: x[1].get("start", ""),
                    )
                ]

            merged_categories.append(cat_info)

        return merged_categories

    def merge_by_project_date(self) -> List[Dict]:
        """
        Merge slots by (date, project) for low detail levels.

        When detail_level <= 2, collapse multiple entries for the same
        (date, project) into a single merged entry.

        Returns:
            Merged list of slots
        """
        if not self.slots:
            return self.slots

        from itertools import groupby

        # Sort by (date, project)
        slots_sorted = sorted(self.slots, key=lambda s: (s["start"].date(), s["project"]))
        merged_slots = []

        for (slot_date, project), group_iter in groupby(
            slots_sorted, key=lambda s: (s["start"].date(), s["project"])
        ):
            group = list(group_iter)
            if not group:
                continue

            # Calculate time window and durations
            first_start = group[0]["start"]
            last_end = group[-1]["start"] + group[-1]["duration"]
            time_window_duration = last_end - first_start

            actual_duration = sum((slot["duration"] for slot in group), timedelta(0))
            productive_duration = sum(
                (slot.get("productive_duration", timedelta(0)) for slot in group),
                timedelta(0),
            )

            afk_duration = sum(
                (s.get("duration", timedelta(0)) for s in group if s.get("type") == "afk"),
                timedelta(0),
            )

            # Build merged slot
            merged_slot = {
                "start": first_start,
                "end": first_start + time_window_duration,
                "duration": time_window_duration,
                "actual_duration": actual_duration,
                "productive_duration": productive_duration,
                "type": group[0].get("type", "regular"),
                "project": project,
                "task": group[0]["task"],
                "apps": [],
            }

            if afk_duration.total_seconds() > 0:
                merged_slot["afk_duration"] = afk_duration

            # Combine apps from all slots
            seen_apps = set()
            for slot in group:
                if "apps" in slot:
                    for app_info in slot["apps"]:
                        app_key = (app_info["app"], app_info.get("title", ""))
                        if app_key not in seen_apps:
                            merged_slot["apps"].append(app_info)
                            seen_apps.add(app_key)

            merged_slots.append(merged_slot)

        return merged_slots

    def apply_filters(self, entry_type: str = "regular") -> None:
        """
        Apply event filter to all slots in place.

        Args:
            entry_type: Type of entries being filtered
        """
        self.slots = [
            s for s in self.slots if self.event_filter.should_include_entry(s, entry_type)
        ]

    def add_slots(self, new_slots: List[Dict]) -> None:
        """
        Add slots to the manager.

        Args:
            new_slots: List of slots to add
        """
        for slot_dict in new_slots:
            self.timeline.add_from_dict(slot_dict)

    def get_slots(self) -> List[Dict]:
        """
        Get all current slots.

        Returns:
            List of slots
        """
        return self.timeline.get_slots_as_dicts()


def merge_categories(group: List[Dict]) -> List[Dict]:
    """Merge categories from all slots in a group (extracted from TimelineSlotManager).

    Combines nested category/app/title structures while preserving all detail.
    Produces a list of category dicts in the exact format expected by
    _render_slot_detail() in timeline_render.py.

    Args:
        group: List of slot dicts to extract categories from

    Returns:
        Merged list of category dictionaries with nested apps and titles
    """
    merged_cats: Dict[str, Dict] = {}

    for s in group:
        for cat_info in s.get("categories", []):
            cat = cat_info["category"]
            if cat not in merged_cats:
                merged_cats[cat] = {
                    "duration": timedelta(0),
                    "start": cat_info.get("start"),
                    "end": cat_info.get("end"),
                    "apps": {},
                }
            else:
                # Update start/end to expand range
                cat_start = cat_info.get("start")
                cat_end = cat_info.get("end")
                if cat_start and (
                    not merged_cats[cat]["start"] or cat_start < merged_cats[cat]["start"]
                ):
                    merged_cats[cat]["start"] = cat_start
                if cat_end and (
                    not merged_cats[cat]["end"] or cat_end > merged_cats[cat]["end"]
                ):
                    merged_cats[cat]["end"] = cat_end

            merged_cats[cat]["duration"] += cat_info["duration"]

            # Merge apps nested under category
            for app_info in cat_info.get("apps", []):
                app = app_info["app"]
                if app not in merged_cats[cat]["apps"]:
                    merged_cats[cat]["apps"][app] = {
                        "duration": timedelta(0),
                        "start": app_info.get("start"),
                        "end": app_info.get("end"),
                        "titles": {},
                    }
                else:
                    app_start = app_info.get("start")
                    app_end = app_info.get("end")
                    if app_start and (
                        not merged_cats[cat]["apps"][app]["start"]
                        or app_start < merged_cats[cat]["apps"][app]["start"]
                    ):
                        merged_cats[cat]["apps"][app]["start"] = app_start
                    if app_end and (
                        not merged_cats[cat]["apps"][app]["end"]
                        or app_end > merged_cats[cat]["apps"][app]["end"]
                    ):
                        merged_cats[cat]["apps"][app]["end"] = app_end

                merged_cats[cat]["apps"][app]["duration"] += app_info["duration"]

                # Merge titles under app
                for title_info in app_info.get("titles", []):
                    title = title_info["title"]
                    if title not in merged_cats[cat]["apps"][app]["titles"]:
                        merged_cats[cat]["apps"][app]["titles"][title] = {
                            "duration": timedelta(0),
                            "start": title_info.get("start"),
                            "end": title_info.get("end"),
                        }
                    else:
                        t_start = title_info.get("start")
                        t_end = title_info.get("end")
                        if t_start and (
                            not merged_cats[cat]["apps"][app]["titles"][title]["start"]
                            or t_start < merged_cats[cat]["apps"][app]["titles"][title]["start"]
                        ):
                            merged_cats[cat]["apps"][app]["titles"][title]["start"] = t_start
                        if t_end and (
                            not merged_cats[cat]["apps"][app]["titles"][title]["end"]
                            or t_end > merged_cats[cat]["apps"][app]["titles"][title]["end"]
                        ):
                            merged_cats[cat]["apps"][app]["titles"][title]["end"] = t_end

                    merged_cats[cat]["apps"][app]["titles"][title]["duration"] += title_info["duration"]

    # Convert to list format with sorted apps/titles
    merged_categories = []
    for cat, cat_data in sorted(merged_cats.items(), key=lambda x: x[1].get("start", "")):
        cat_info = {
            "category": cat,
            "duration": cat_data["duration"],
            "start": cat_data.get("start"),
            "end": cat_data.get("end"),
        }
        if cat_data["apps"]:
            cat_info["apps"] = []
            for app_name in sorted(cat_data["apps"].keys()):
                app_data = cat_data["apps"][app_name]
                app_info = {
                    "app": app_name,
                    "duration": app_data["duration"],
                    "start": app_data.get("start"),
                    "end": app_data.get("end"),
                }
                if app_data["titles"]:
                    app_info["titles"] = [
                        {
                            "title": title_name,
                            "duration": app_data["titles"][title_name]["duration"],
                            "start": app_data["titles"][title_name].get("start"),
                            "end": app_data["titles"][title_name].get("end"),
                        }
                        for title_name in sorted(app_data["titles"].keys())
                    ]
                else:
                    app_info["titles"] = []
                cat_info["apps"].append(app_info)

        merged_categories.append(cat_info)

    return merged_categories


def collapse_tasks_to_project(rows: List[Dict]) -> List[Dict]:
    """Collapse (period, project, task) rows down to (period, project) totals.

    Sums durations/productivity per project, drops task and categories fields.
    Used by print_period_consolidated_report() when detail_level == 1 to
    reproduce the original project-only summary from the now-finer-grained
    consolidate_by_period() output.

    Args:
        rows: List of (period, project, task) rows from consolidate_by_period()

    Returns:
        List of (period, project) summary rows
    """
    groups: Dict[Tuple[date, str], List[Dict]] = {}
    for row in rows:
        key = (row["period_start"], row["project"])
        groups.setdefault(key, []).append(row)

    result = []
    for (period_start, project), group_rows in groups.items():
        actual_duration = sum(
            (r.get("actual_duration", r["duration"]) for r in group_rows), timedelta(0)
        )
        productive_duration = sum(
            (r.get("productive_duration", timedelta(0)) for r in group_rows), timedelta(0)
        )
        afk_duration = sum(
            (r.get("afk_duration", timedelta(0)) for r in group_rows), timedelta(0)
        )
        offline_extension_duration = sum(
            (r.get("offline_extension_duration", timedelta(0)) for r in group_rows), timedelta(0)
        )
        result.append({
            "period_start": period_start,
            "project": project,
            "duration": actual_duration,
            "actual_duration": actual_duration,
            "productive_duration": productive_duration,
            "afk_duration": afk_duration,
            "offline_extension_duration": offline_extension_duration,
        })

    result.sort(key=lambda r: (r["period_start"], -r["actual_duration"].total_seconds()))
    return result


def consolidate_by_period(slots: List[Dict], period: str) -> List[Dict]:
    """Group slots into (period_bucket, project, task) totals with category data.

    Groups at task granularity (finer than before) for all detail levels, then
    print_period_consolidated_report() decides whether to collapse to project-only
    or show task detail. This allows detail_level >= 2 to show task breakdown.

    Each result row includes merged categories for detail_level >= 3.

    Args:
        slots: List of slot dicts (from timeline or consolidation)
        period: "day" | "week" | "month" | "year"

    Returns:
        List of dicts with fields: period_start, project, task, duration, actual_duration,
        productive_duration, afk_duration, categories. Sorted by period, then project total
        duration (descending), then task duration (descending).

    Raises:
        ValueError: If period is not one of the recognized values
    """
    from datetime import date, timedelta
    from typing import Dict, Tuple

    def bucket_start(dt) -> date:
        d = dt.date()
        if period == "day":
            return d
        elif period == "week":
            # Monday of the week containing dt, same as period.py :week/:lastweek
            return d - timedelta(days=dt.weekday())
        elif period == "month":
            return d.replace(day=1)
        elif period == "year":
            return d.replace(month=1, day=1)
        raise ValueError(f"Unknown period: {period}")

    # Group-by (period, project, task): exclude offline gap markers, keep everything else
    groups: Dict[Tuple[date, str, str], List[Dict]] = {}
    for slot in slots:
        if slot.get("type") == "offline":
            continue  # gap markers only
        key = (bucket_start(slot["start"]), slot["project"], slot["task"])
        groups.setdefault(key, []).append(slot)

    result = []
    for (period_start, project, task), group_slots in groups.items():
        actual_duration = sum(
            (s.get("actual_duration", s["duration"]) for s in group_slots), timedelta(0)
        )
        productive_duration = sum(
            (s.get("productive_duration", timedelta(0)) for s in group_slots), timedelta(0)
        )
        afk_duration = sum(
            (s.get("actual_duration", s["duration"]) for s in group_slots if s.get("type") == "afk"),
            timedelta(0),
        )
        # For offline_task slots: offline time = duration - event_duration (system was off)
        # For other slots: no offline extension (they were tracked live)
        offline_extension_duration = sum(
            (s.get("duration", timedelta(0)) - s.get("event_duration", timedelta(0))
             for s in group_slots if s.get("type") == "offline_task"),
            timedelta(0),
        )
        result.append({
            "period_start": period_start,
            "project": project,
            "task": task,
            "duration": actual_duration,
            "actual_duration": actual_duration,
            "productive_duration": productive_duration,
            "afk_duration": afk_duration,
            "offline_extension_duration": offline_extension_duration,
            "categories": merge_categories(group_slots),
        })

    # Sort by: period_start, then project's total duration (descending),
    # then individual task duration (descending)
    # To get project totals for sorting, group by (period, project)
    project_totals = {}
    for row in result:
        key = (row["period_start"], row["project"])
        project_totals[key] = project_totals.get(key, timedelta(0)) + row["actual_duration"]

    result.sort(
        key=lambda r: (
            r["period_start"],
            -project_totals[(r["period_start"], r["project"])].total_seconds(),
            -r["actual_duration"].total_seconds(),
        )
    )
    return result

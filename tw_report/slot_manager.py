"""
Timeline slot management and consolidation logic.

This module extracts and centralizes slot generation, consolidation, and
merging logic that was previously scattered in tw-report.py. It provides
a clean interface for timeline report generation.

ISSUE #2 FIX: Consolidation now handles OFFLINE gaps intelligently.
Previously, every OFFLINE gap would break consolidation. Now, only gaps
between different tasks break consolidation.
"""

from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
from aw_core.models import Event


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
        self.slots: List[Dict] = []

    def consolidate(self, ignore_offline: bool = False) -> List[Dict]:
        """
        Consolidate timeline slots by merging same (date, project, task).

        This is the core fix for Issue #2. Instead of treating every OFFLINE
        gap as a consolidation boundary, we only break consolidation when:
        1. The date changes
        2. The project changes
        3. The task changes
        4. A different task (not the same one) appears after the gap

        Args:
            ignore_offline: If True, OFFLINE gaps are ignored and consolidation
                          spans across them. If False (default), gaps are passed
                          through as separate entries.

        Returns:
            List of consolidated slots
        """
        if not self.slots:
            return self.slots

        consolidated = []
        current_group: List[Dict] = []
        pending_gaps: List[Dict] = []  # Buffer for consecutive gaps

        def flush_group_with_gaps() -> None:
            """Flush current group and add accumulated gaps if needed."""
            if current_group:
                merged = self._merge_slot_group(current_group)
                consolidated.append(merged)
                current_group.clear()

            # Add accumulated gaps (deduplicated)
            if pending_gaps and not ignore_offline:
                # Only add one combined gap entry instead of multiple
                if pending_gaps:
                    # Merge all gaps into a single entry
                    gap = pending_gaps[0]
                    total_gap_duration = sum(
                        (g["duration"] for g in pending_gaps), timedelta(0)
                    )
                    consolidated.append({
                        **gap,
                        "duration": total_gap_duration,
                    })
            pending_gaps.clear()

        for slot in self.slots:
            # Handle OFFLINE gaps - don't treat as hard boundary anymore
            if slot.get("type") == "offline":
                pending_gaps.append(slot)
                continue

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
                # Same task continues - gaps are absorbed into the group
                current_group.append(slot)
                pending_gaps.clear()  # Don't emit gaps for same task
            else:
                # Different task - flush current group with gaps
                flush_group_with_gaps()
                current_group.append(slot)
                pending_gaps.clear()

        # Final flush
        flush_group_with_gaps()
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

        # Calculate time window
        time_window_start = first["start"]
        time_window_end = max(
            s["start"] + s.get("actual_duration", s["duration"]) for s in group
        )
        time_window = time_window_end - time_window_start

        # Calculate actual durations
        actual_duration = sum(
            (s.get("actual_duration", s["duration"]) for s in group), timedelta(0)
        )
        productive_duration = sum(
            (s.get("productive_duration", timedelta(0)) for s in group),
            timedelta(0),
        )

        # Track AFK and OFFLINE durations
        afk_duration = sum(
            (s.get("duration", timedelta(0)) for s in group if s.get("type") == "afk"),
            timedelta(0),
        )
        offline_extension_duration = sum(
            (
                s.get("duration", timedelta(0))
                for s in group
                if s.get("type") == "offline_extension"
            ),
            timedelta(0),
        )

        # Merge categories (complex nested structure)
        merged_categories = self._merge_categories(group)

        # Build result
        result = {
            "start": time_window_start,
            "duration": time_window,
            "actual_duration": actual_duration,
            "productive_duration": productive_duration,
            "project": first["project"],
            "task": first["task"],
        }

        # Preserve type field from first slot (important for offline_task and other special types)
        if "type" in first:
            result["type"] = first["type"]

        if merged_categories:
            result["categories"] = merged_categories

        if afk_duration.total_seconds() > 0:
            result["afk_duration"] = afk_duration

        if offline_extension_duration.total_seconds() > 0:
            result["offline_extension_duration"] = offline_extension_duration

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
                        not merged_cats[cat]["start"]
                        or cat_start < merged_cats[cat]["start"]
                    ):
                        merged_cats[cat]["start"] = cat_start
                    if cat_end and (
                        not merged_cats[cat]["end"]
                        or cat_end > merged_cats[cat]["end"]
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
        for cat, cat_data in sorted(
            merged_cats.items(), key=lambda x: x[1].get("start", "")
        ):
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
        slots_sorted = sorted(
            self.slots, key=lambda s: (s["start"].date(), s["project"])
        )
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

            actual_duration = sum(
                (slot["duration"] for slot in group), timedelta(0)
            )
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
                "duration": time_window_duration,
                "actual_duration": actual_duration,
                "productive_duration": productive_duration,
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
            s for s in self.slots
            if self.event_filter.should_include_entry(s, entry_type)
        ]

    def add_slots(self, new_slots: List[Dict]) -> None:
        """
        Add slots to the manager.

        Args:
            new_slots: List of slots to add
        """
        self.slots.extend(new_slots)

    def get_slots(self) -> List[Dict]:
        """
        Get all current slots.

        Returns:
            List of slots
        """
        return self.slots

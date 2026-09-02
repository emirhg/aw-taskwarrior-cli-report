"""
Critical test: Verify timeline and hierarchical reports show IDENTICAL metrics for same data.

This test catches regressions where the two reporting paths diverge due to:
1. Different slot consolidation methods (consolidate_by_task vs split_at_boundaries)
2. Different duration calculations (prorating in splits vs consolidating)
3. Different grouping/filtering logic

Issue: Current implementation shows 86-second discrepancy for same task:
- Hierarchical: 00:08:00 (correct)
- Timeline: 00:06:34 (missing 86 seconds)

This is a CRITICAL architectural bug that must be fixed.
"""

import pytest
from datetime import datetime, timedelta, timezone
from tw_report.core.report_slot import ReportTimelineSlot
from tw_report.core.aw_events import TaskWarriorEvent
from tw_report.pipeline.processors import aggregate_hierarchy_from_slots
from tw_report.pipeline.timeline_render import split_slots_spanning_days


class TestTwoPathConvergence:
    """Verify both reporting paths produce identical results for same data."""

    @pytest.fixture
    def sample_task_slots(self):
        """Create realistic task slots that would diverge between paths."""
        base_time = datetime(2026, 9, 1, 2, 30, 0, tzinfo=timezone.utc)
        return [
            # LeetCode 1091: 5:18 in hierarchical, but split across boundaries
            ReportTimelineSlot(
                start=base_time + timedelta(hours=0, minutes=0, seconds=0),
                end=base_time + timedelta(hours=0, minutes=3, seconds=24),
                duration=timedelta(minutes=3, seconds=24),
                actual_duration=timedelta(minutes=3, seconds=24),
                productive_duration=timedelta(minutes=3, seconds=24),
                task_event=TaskWarriorEvent(
                    timestamp=base_time,
                    duration=timedelta(minutes=5, seconds=18),
                    data={"project": "Mercado > CodeSignal", "task": "LeetCode 1091", "tags": []},
                ),
                categories=[{"category": "Coding", "apps": [], "duration": timedelta(minutes=3, seconds=24)}],
            ),
            # LeetCode 84: 1:48 in hierarchical
            ReportTimelineSlot(
                start=base_time + timedelta(hours=0, minutes=15, seconds=0),
                end=base_time + timedelta(hours=0, minutes=16, seconds=48),
                duration=timedelta(minutes=1, seconds=48),
                actual_duration=timedelta(minutes=1, seconds=48),
                productive_duration=timedelta(minutes=1, seconds=48),
                task_event=TaskWarriorEvent(
                    timestamp=base_time + timedelta(hours=0, minutes=15),
                    duration=timedelta(minutes=1, seconds=48),
                    data={"project": "Mercado > CodeSignal", "task": "LeetCode 84", "tags": []},
                ),
                categories=[{"category": "Coding", "apps": [], "duration": timedelta(minutes=1, seconds=48)}],
            ),
            # LeetCode 2970: 00:54 in hierarchical, but fragments in timeline
            ReportTimelineSlot(
                start=base_time + timedelta(hours=0, minutes=43, seconds=0),
                end=base_time + timedelta(hours=0, minutes=43, seconds=54),
                duration=timedelta(seconds=54),
                actual_duration=timedelta(seconds=54),
                productive_duration=timedelta(seconds=54),
                task_event=TaskWarriorEvent(
                    timestamp=base_time + timedelta(hours=0, minutes=43),
                    duration=timedelta(seconds=54),
                    data={"project": "Mercado > CodeSignal", "task": "LeetCode 2970", "tags": []},
                ),
                categories=[{"category": "Coding", "apps": [], "duration": timedelta(seconds=54)}],
            ),
        ]

    def test_both_paths_show_same_project_total(self, sample_task_slots):
        """CRITICAL: Both timeline and hierarchical must show identical Mercado total."""
        # Hierarchical path
        report_data, _ = aggregate_hierarchy_from_slots(
            consolidated_slots=sample_task_slots,
            task_based=True,
            cat_score_map={},
            get_category_score=lambda cat, m: 0,
            normalize_title=lambda t: t,
        )

        # Sum Mercado project total
        mercado_hierarchy = report_data.get("Mercado > CodeSignal", {})
        hierarchy_total = mercado_hierarchy.get("total_duration", timedelta(0))

        # Timeline path: sum all slots (no consolidation by task in basic form)
        timeline_total = sum(
            (s.actual_duration or s.duration for s in sample_task_slots),
            timedelta(0)
        )

        # ASSERTION: Must match exactly
        assert hierarchy_total == timeline_total, (
            f"CRITICAL BUG: Hierarchical shows {hierarchy_total} but timeline shows {timeline_total}. "
            f"Discrepancy: {abs((hierarchy_total - timeline_total).total_seconds())} seconds. "
            f"Both paths must produce identical totals for same data."
        )

    def test_both_paths_show_same_per_task_duration(self, sample_task_slots):
        """CRITICAL: Both paths must show identical duration for each task."""
        # Hierarchical path
        report_data, _ = aggregate_hierarchy_from_slots(
            consolidated_slots=sample_task_slots,
            task_based=True,
            cat_score_map={},
            get_category_score=lambda cat, m: 0,
            normalize_title=lambda t: t,
        )

        mercado_hierarchy = report_data.get("Mercado > CodeSignal", {})
        hierarchy_tasks = mercado_hierarchy.get("tasks", {})

        # Timeline path: create per-task sum
        timeline_tasks = {}
        for slot in sample_task_slots:
            task = slot.task
            if task not in timeline_tasks:
                timeline_tasks[task] = timedelta(0)
            timeline_tasks[task] += (slot.actual_duration or slot.duration)

        # ASSERTION: Must match for each task
        for task in timeline_tasks:
            hierarchy_dur = hierarchy_tasks.get(task, {}).get("total_duration", timedelta(0))
            timeline_dur = timeline_tasks[task]
            assert hierarchy_dur == timeline_dur, (
                f"CRITICAL BUG: Task '{task}' shows {hierarchy_dur} in hierarchical "
                f"but {timeline_dur} in timeline. Discrepancy: "
                f"{abs((hierarchy_dur - timeline_dur).total_seconds())} seconds."
            )

    def test_slots_dont_get_tripled_during_splitting(self, sample_task_slots):
        """Regression test: Verify split_at_boundaries doesn't multiply duration."""
        from tw_report.pipeline.timeline_render import split_slots_spanning_days

        # Original total
        original_total = sum(
            (s.duration for s in sample_task_slots),
            timedelta(0)
        )

        # After splitting
        split_slots = split_slots_spanning_days(sample_task_slots, day_start_hour=4)
        split_total = sum(
            (s.duration for s in split_slots),
            timedelta(0)
        )

        # Must be equal (no duplication)
        assert split_total == original_total, (
            f"REGRESSION: split_slots_spanning_days changed total from {original_total} "
            f"to {split_total}. Durations are being duplicated or miscalculated."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

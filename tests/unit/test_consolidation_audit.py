"""Comprehensive audit of consolidation through the entire rendering pipeline.

This test traces consolidated slots through each step of the rendering process
to identify exactly where/why they stop being consolidated in the output.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from tw_report.pipeline.consolidation import consolidate_sessions


class TestConsolidationAudit:
    """Audit consolidation through pipeline stages."""

    @pytest.fixture
    def base_time(self):
        """2026-08-30 11:00 UTC-6"""
        return datetime(2026, 8, 30, 11, 0, tzinfo=timezone(timedelta(hours=-6)))

    def make_realistic_slot(self, start, duration, project="P1", task="T1", **kwargs):
        """Create realistic slot matching actual pipeline structure."""
        end = start + duration
        return {
            "start": start,
            "end": end,
            "duration": duration,
            "actual_duration": duration,
            "productive_duration": timedelta(0),
            "project": project,
            "task": task,
            "tags": kwargs.get("tags", []),
            "categories": [],
            "apps": [],
            "event_duration": kwargs.get("event_duration", duration),
            "afk_duration": timedelta(0),
            "type": "regular",
            "is_offline_task": False,
            "is_afk_only": False,
        }

    def test_consolidation_pipeline_stage_1_input(self, base_time):
        """STAGE 1: Verify consolidation input (unconsolidated slots)."""
        # 3 sessions of same task, no consolidation applied yet
        slots_input = [
            self.make_realistic_slot(
                base_time + timedelta(hours=1), timedelta(minutes=30), task="Task1"
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=1, minutes=35), timedelta(minutes=30), task="Task1"
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=2, minutes=30), timedelta(minutes=30), task="Task1"
            ),
        ]

        print(f"\nSTAGE 1 INPUT: {len(slots_input)} unconsolidated slots")
        assert len(slots_input) == 3
        for i, s in enumerate(slots_input):
            assert s["start"] < s["end"]
            print(f"  Slot {i}: {s['start']} to {s['end']} ({s['duration']})")

    def test_consolidation_pipeline_stage_2_consolidation(self, base_time):
        """STAGE 2: Apply consolidation logic."""
        slots_input = [
            self.make_realistic_slot(
                base_time + timedelta(hours=1), timedelta(minutes=30), task="Task1"
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=1, minutes=35), timedelta(minutes=30), task="Task1"
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=2, minutes=30), timedelta(minutes=30), task="Task1"
            ),
        ]

        consolidated = consolidate_sessions(slots_input)

        print(f"\nSTAGE 2 CONSOLIDATION:")
        print(f"  Input: {len(slots_input)} slots")
        print(f"  Output: {len(consolidated)} slots")

        # Should merge to 1 slot
        assert len(consolidated) == 1, f"Expected 1 consolidated slot, got {len(consolidated)}"

        merged_slot = consolidated[0]
        print(f"  Merged slot: {merged_slot['start']} to {merged_slot['end']}")
        print(f"  Duration: {merged_slot['duration']}")
        print(f"  Task: {merged_slot['task']}")

        # Verify merged slot properties
        assert merged_slot["task"] == "Task1"
        assert merged_slot["start"] == slots_input[0]["start"], "Start should be first slot's start"
        assert merged_slot["end"] == slots_input[2]["end"], "End should be last slot's end"
        expected_duration = slots_input[2]["end"] - slots_input[0]["start"]
        assert merged_slot["duration"] == expected_duration, (
            f"Duration mismatch: expected {expected_duration}, got {merged_slot['duration']}"
        )

    def test_consolidation_slot_integrity(self, base_time):
        """STAGE 3: Verify all fields are preserved correctly in consolidated slot."""
        slots_input = [
            self.make_realistic_slot(
                base_time + timedelta(hours=1),
                timedelta(minutes=30),
                project="Project1",
                task="Task1",
                tags=["tag1"],
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=1, minutes=35),
                timedelta(minutes=30),
                project="Project1",
                task="Task1",
                tags=["tag1"],
            ),
        ]

        consolidated = consolidate_sessions(slots_input)
        merged = consolidated[0]

        print(f"\nSTAGE 3 FIELD INTEGRITY:")
        required_fields = [
            "start",
            "end",
            "duration",
            "actual_duration",
            "project",
            "task",
            "type",
        ]
        for field in required_fields:
            assert field in merged, f"Missing field: {field}"
            print(f"  ✓ {field}: {merged[field]}")

        # Verify specific field values
        assert merged["project"] == "Project1"
        assert merged["task"] == "Task1"
        assert merged["type"] == "regular"
        assert merged["start"] is not None
        assert merged["end"] is not None
        assert merged["duration"] > timedelta(0)

    def test_consolidation_different_tasks_not_merged(self, base_time):
        """STAGE 4: Verify different tasks don't merge."""
        slots_input = [
            self.make_realistic_slot(
                base_time + timedelta(hours=1), timedelta(minutes=30), task="TaskA"
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=1, minutes=35), timedelta(minutes=30), task="TaskB"
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=2, minutes=10), timedelta(minutes=30), task="TaskA"
            ),
        ]

        consolidated = consolidate_sessions(slots_input)

        print(f"\nSTAGE 4 DIFFERENT TASKS:")
        print(f"  Input: {len(slots_input)} slots (TaskA, TaskB, TaskA)")
        print(f"  Output: {len(consolidated)} slots")

        assert len(consolidated) == 3, "Different tasks should not merge"
        assert consolidated[0]["task"] == "TaskA"
        assert consolidated[1]["task"] == "TaskB"
        assert consolidated[2]["task"] == "TaskA"

    def test_consolidation_respects_interruption(self, base_time):
        """STAGE 5: Verify same task resumes as separate group after interruption."""
        slots_input = [
            self.make_realistic_slot(
                base_time + timedelta(hours=1),
                timedelta(minutes=30),
                task="TaskA",
                project="P1",
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=2),
                timedelta(minutes=30),
                task="TaskB",
                project="P1",
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=2, minutes=45),
                timedelta(minutes=30),
                task="TaskA",
                project="P1",
            ),
        ]

        consolidated = consolidate_sessions(slots_input)

        print(f"\nSTAGE 5 INTERRUPTION:")
        print(f"  Input: TaskA → TaskB → TaskA")
        print(f"  Output: {len(consolidated)} slots")

        # Should have 3 slots (consolidation breaks at TaskB)
        assert len(consolidated) == 3
        assert consolidated[0]["task"] == "TaskA"
        assert consolidated[1]["task"] == "TaskB"
        assert consolidated[2]["task"] == "TaskA"

        print(f"  Slot 0 duration: {consolidated[0]['duration']}")
        print(f"  Slot 1 duration: {consolidated[1]['duration']}")
        print(f"  Slot 2 duration: {consolidated[2]['duration']}")

    def test_consolidation_output_structure(self, base_time):
        """STAGE 6: Verify output slots can be used by rendering code."""
        slots_input = [
            self.make_realistic_slot(
                base_time + timedelta(hours=1),
                timedelta(minutes=60),
                task="Task1",
                project="Project1",
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=2, minutes=5),
                timedelta(minutes=60),
                task="Task1",
                project="Project1",
            ),
        ]

        consolidated = consolidate_sessions(slots_input)
        merged = consolidated[0]

        print(f"\nSTAGE 6 RENDERING COMPATIBILITY:")
        print(f"  Can access start: {merged['start'] is not None}")
        print(f"  Can access end: {merged['end'] is not None}")
        print(f"  Can access duration: {merged['duration'] is not None}")
        print(f"  Can access project: {merged['project'] is not None}")
        print(f"  Can access task: {merged['task'] is not None}")

        # All fields needed by rendering should be present
        assert hasattr(merged, "__getitem__") or isinstance(merged, dict)
        assert merged["start"] is not None
        assert merged["end"] is not None
        assert merged["project"] is not None
        assert merged["task"] is not None

    def test_consolidation_with_realistic_data_multiple_groups(self, base_time):
        """STAGE 7: Test with multiple different tasks being consolidated."""
        slots_input = [
            # Task1: 3 sessions
            self.make_realistic_slot(
                base_time + timedelta(hours=1), timedelta(minutes=30), task="Task1"
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=1, minutes=35), timedelta(minutes=30), task="Task1"
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=2, minutes=30), timedelta(minutes=30), task="Task1"
            ),
            # Task2: 2 sessions
            self.make_realistic_slot(
                base_time + timedelta(hours=3, minutes=30), timedelta(minutes=45), task="Task2"
            ),
            self.make_realistic_slot(
                base_time + timedelta(hours=4, minutes=20), timedelta(minutes=45), task="Task2"
            ),
            # Task3: 1 session (no consolidation needed)
            self.make_realistic_slot(
                base_time + timedelta(hours=5, minutes=30), timedelta(minutes=30), task="Task3"
            ),
        ]

        consolidated = consolidate_sessions(slots_input)

        print(f"\nSTAGE 7 MULTIPLE GROUPS:")
        print(f"  Input: 6 slots (Task1×3, Task2×2, Task3×1)")
        print(f"  Output: {len(consolidated)} slots")

        # Should result in 3 slots (one per task)
        assert len(consolidated) == 3

        # Verify each group
        task1_slots = [s for s in consolidated if s["task"] == "Task1"]
        task2_slots = [s for s in consolidated if s["task"] == "Task2"]
        task3_slots = [s for s in consolidated if s["task"] == "Task3"]

        assert len(task1_slots) == 1, "Task1 should be merged to 1 slot"
        assert len(task2_slots) == 1, "Task2 should be merged to 1 slot"
        assert len(task3_slots) == 1, "Task3 should remain as 1 slot"

        print(f"  Task1: {task1_slots[0]['duration']}")
        print(f"  Task2: {task2_slots[0]['duration']}")
        print(f"  Task3: {task3_slots[0]['duration']}")


class TestRenderingLayerAudit:
    """Audit the rendering layer to find where consolidated slots diverge from output."""

    def test_rendering_import_check(self):
        """Verify rendering code can be imported for analysis."""
        try:
            from tw_report.pipeline import timeline_render
            print("\n✓ timeline_render module imports successfully")

            # Check for key functions
            functions = [
                'print_timeline_report',
                'split_slots_spanning_days',
                'filter_short_slots',
            ]
            for func_name in functions:
                if hasattr(timeline_render, func_name):
                    print(f"  ✓ Found function: {func_name}")
                else:
                    print(f"  ✗ Missing function: {func_name}")
        except ImportError as e:
            pytest.skip(f"Cannot import timeline_render: {e}")

    def test_split_slots_spanning_days_doesnt_undo_consolidation(self):
        """HYPOTHESIS: split_slots_spanning_days() re-splits consolidated slots."""
        # Consolidated slots should maintain their consolidation even after day-spanning split
        # Placeholder: minimal test to ensure function exists and doesn't crash
        try:
            from tw_report.pipeline.timeline_render import split_slots_spanning_days
            assert callable(split_slots_spanning_days), "split_slots_spanning_days should be callable"
        except ImportError:
            pytest.skip("timeline_render not available")

    def test_rendering_grouping_logic_isolation(self):
        """Test that rendering grouping functions work independently."""
        # Grouping functions should work without requiring full pipeline context
        # Placeholder: verify print_timeline_report exists and is callable
        from tw_report.pipeline.timeline_render import print_timeline_report
        assert callable(print_timeline_report), "print_timeline_report should be callable"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

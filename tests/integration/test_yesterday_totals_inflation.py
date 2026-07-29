"""
Integration test to reproduce the :yesterday 40-minute totals inflation.

This test captures the real data flow and identifies where the inflation occurs
during metrics accumulation and day/period total calculation.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
from aw_core.models import Event

from tw_report.core.period import parse_period
from tw_report.pipeline.generation import generate_timeline_data
from tw_report.pipeline.processors import build_canonical_events


class TestYesterdayTotalsInflation:
    """Integration tests for the actual :yesterday inflation bug."""

    @staticmethod
    def create_mock_aw_client_yesterday():
        """
        Create a mock AW client with realistic data for yesterday.

        Scenario:
        - 2 not-afk periods (user worked with breaks)
        - Multiple TaskWarrior events (task switches)
        - Some window events overlapping with different tasks
        """
        tz = timezone(timedelta(hours=-6))  # CST
        yesterday = datetime(2026, 7, 28, 0, 0, 0, tzinfo=tz)

        # Not-afk periods totaling ~10.5 hours
        # Period 1: 9:00-12:30 (3.5 hours)
        # Period 2: 14:00-23:00 (9 hours) <- This is where inflation might occur
        not_afk_events = [
            Event(
                timestamp=yesterday.replace(hour=9, minute=0),
                duration=timedelta(hours=3, minutes=30),
                data={"status": "not-afk"}
            ),
            Event(
                timestamp=yesterday.replace(hour=14, minute=0),
                duration=timedelta(hours=9),
                data={"status": "not-afk"}
            ),
        ]

        # Total not-afk time = 12.5 hours = 45000 seconds
        total_not_afk = sum((e.duration for e in not_afk_events), timedelta(0))
        print(f"Total not-afk (source of truth): {total_not_afk}")

        # Window events (ActivityWatch tracking)
        # These are individual window activity events that might overlap
        window_events = [
            # First not-afk period: 9:00-12:30
            Event(timestamp=yesterday.replace(hour=9, minute=0), duration=timedelta(minutes=45), data={"app": "VSCode", "title": "code.py", "$category": ["Programming"]}),
            Event(timestamp=yesterday.replace(hour=9, minute=45), duration=timedelta(minutes=30), data={"app": "Browser", "title": "GitHub", "$category": ["Work"]}),
            Event(timestamp=yesterday.replace(hour=10, minute=15), duration=timedelta(minutes=60), data={"app": "VSCode", "title": "code.py", "$category": ["Programming"]}),
            Event(timestamp=yesterday.replace(hour=11, minute=15), duration=timedelta(minutes=75), data={"app": "Terminal", "title": "bash", "$category": ["Programming"]}),

            # Second not-afk period: 14:00-23:00
            Event(timestamp=yesterday.replace(hour=14, minute=0), duration=timedelta(minutes=120), data={"app": "Slack", "title": "messages", "$category": ["Communication"]}),
            Event(timestamp=yesterday.replace(hour=16, minute=0), duration=timedelta(minutes=90), data={"app": "VSCode", "title": "code.py", "$category": ["Programming"]}),
            Event(timestamp=yesterday.replace(hour=17, minute=30), duration=timedelta(minutes=45), data={"app": "Browser", "title": "docs", "$category": ["Research"]}),
            Event(timestamp=yesterday.replace(hour=18, minute=15), duration=timedelta(minutes=120), data={"app": "VSCode", "title": "code.py", "$category": ["Programming"]}),
            Event(timestamp=yesterday.replace(hour=20, minute=15), duration=timedelta(minutes=165), data={"app": "Meetings", "title": "zoom call", "$category": ["Communication"]}),
        ]

        window_sum = sum((e.duration for e in window_events), timedelta(0))
        print(f"Total window events sum: {window_sum}")

        # Task events (TaskWarrior tracking)
        task_events = [
            Event(timestamp=yesterday.replace(hour=9, minute=0), duration=timedelta(hours=4), data={"project": "MyProject", "description": "Feature A", "uuid": "task-1", "tags": []}),
            Event(timestamp=yesterday.replace(hour=13, minute=0), duration=timedelta(hours=1, minutes=30), data={"project": "MyProject", "description": "Code Review", "uuid": "task-2", "tags": []}),
            Event(timestamp=yesterday.replace(hour=14, minute=30), duration=timedelta(hours=8), data={"project": "MyProject", "description": "Feature B", "uuid": "task-3", "tags": ["offline"]}),
        ]

        return {
            "not_afk_events": not_afk_events,
            "window_events": window_events,
            "task_events": task_events,
            "total_not_afk": total_not_afk,
            "window_sum": window_sum,
        }

    def test_generate_timeline_data_does_not_inflate(self):
        """
        Test: generate_timeline_data should not inflate durations.
        Slots should have actual_duration = sum of window events in that slot.
        """
        data = self.create_mock_aw_client_yesterday()

        # Convert to report format for generate_timeline_data
        report_events = [
            {
                "event": e,
                "project": "MyProject",
                "task": "GenericTask",
                "active_task": None,
            }
            for e in data["window_events"]
        ]

        slots = generate_timeline_data(
            report_events=report_events,
            afk_events=data["not_afk_events"],
            cat_score_map={"Programming": 1.0, "Work": 0.8, "Communication": 0.5, "Research": 0.7},
            detail_level=1,
            deduplicate_categories=False,
            get_category_score=lambda cat, score_map: score_map.get(cat, 0.5),
        )

        print(f"\nGenerated {len(slots)} slots")

        # Sum actual_duration across all slots
        total_actual_duration = sum((s["actual_duration"] for s in slots), timedelta(0))
        print(f"Total actual_duration from slots: {total_actual_duration}")
        print(f"Window events sum (truth): {data['window_sum']}")

        # They should match (no inflation from generate_timeline_data)
        assert total_actual_duration == data["window_sum"], \
            f"Inflation detected: slots={total_actual_duration} vs window_sum={data['window_sum']}"

    def test_find_inflation_source_with_real_scenario(self):
        """
        Test: Trace through the complete pipeline to identify WHERE inflation occurs.
        """
        data = self.create_mock_aw_client_yesterday()

        # Step 1: Check window events sum vs not-afk (should not match, windows are sparse)
        window_sum = data["window_sum"]
        not_afk_sum = data["total_not_afk"]

        print(f"\n=== INFLATION TRACE ===")
        print(f"Step 1: Source of truth")
        print(f"  Not-afk sum (online time): {not_afk_sum}")
        print(f"  Window events sum: {window_sum}")
        print(f"  Unaccounted (gap): {not_afk_sum - window_sum}")

        # Step 2: Create slots
        report_events = [
            {
                "event": e,
                "project": "MyProject",
                "task": "GenericTask",
                "active_task": None,
            }
            for e in data["window_events"]
        ]

        slots = generate_timeline_data(
            report_events=report_events,
            afk_events=data["not_afk_events"],
            cat_score_map={"Programming": 1.0, "Work": 0.8, "Communication": 0.5, "Research": 0.7},
            detail_level=1,
            deduplicate_categories=False,
            get_category_score=lambda cat, score_map: score_map.get(cat, 0.5),
        )

        slots_actual_sum = sum((s["actual_duration"] for s in slots), timedelta(0))
        slots_wall_clock_sum = sum((s["duration"] for s in slots), timedelta(0))

        print(f"\nStep 2: After generate_timeline_data")
        print(f"  Slots actual_duration sum: {slots_actual_sum}")
        print(f"  Slots wall-clock sum: {slots_wall_clock_sum}")
        print(f"  Actual vs window match: {slots_actual_sum == window_sum}")

        # Step 3: Check if slots were deduplicated correctly
        print(f"\nStep 3: Slot analysis")
        print(f"  Number of slots: {len(slots)}")
        for i, slot in enumerate(slots):
            print(f"  Slot {i}: {slot['project']}/{slot['task']} {slot['start'].time()}-{slot['end'].time()}")
            print(f"    duration={slot['duration']}, actual_duration={slot['actual_duration']}")

        # The inflation must occur in metrics accumulation or rendering
        # This test sets up the data pattern to enable manual inspection

if __name__ == "__main__":
    # Run with pytest -xvs tests/integration/test_yesterday_totals_inflation.py
    pytest.main([__file__, "-xvs"])

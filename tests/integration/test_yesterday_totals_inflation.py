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
from tw_report.core.timeslot_builder import build_timeslot_timeline
from tw_report.core.aw_events import AFKEvent, WindowEvent, TaskWarriorEvent


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

    def test_builder_does_not_inflate(self):
        """
        Test: Builder should not inflate durations.
        Slots should have actual_duration that matches input data correctly.

        Phase 2 refactor: Builder guarantees non-overlapping slots by construction.
        """
        data = self.create_mock_aw_client_yesterday()

        # Convert to typed event objects for builder
        afk_events = [AFKEvent(
            timestamp=e.timestamp,
            duration=e.duration,
            data=e.data,
        ) for e in data["not_afk_events"]]

        window_events = [WindowEvent(
            timestamp=e.timestamp,
            duration=e.duration,
            data=e.data,
        ) for e in data["window_events"]]

        task_events = [TaskWarriorEvent(
            timestamp=e.timestamp,
            duration=e.duration,
            data=e.data,
        ) for e in data["task_events"]]

        # Use new builder API (Phase 2 refactor)
        slots = build_timeslot_timeline(
            afk_events=afk_events,
            window_events=window_events,
            task_events=task_events,
        )

        print(f"\nGenerated {len(slots)} slots from builder")

        # Sum actual_duration across all slots (represents active work time)
        total_active_duration = sum((s.actual_duration or timedelta(0) for s in slots), timedelta(0))
        print(f"Total active_duration from slots: {total_active_duration}")
        print(f"Window events sum (reference): {data['window_sum']}")

        # Builder should NOT inflate: slots cover input time correctly
        # (Window events and AFK events should map to slots without duplication)
        # Total should not exceed the span of input events
        max_time = max(
            (e.timestamp + e.duration for e in data["window_events"] + data["task_events"]),
            default=datetime.now(timezone.utc)
        )
        min_time = min(
            (e.timestamp for e in data["window_events"] + data["task_events"]),
            default=datetime.now(timezone.utc)
        )
        span = max_time - min_time

        print(f"Input span: {span}")
        total_slot_span = sum((s.duration for s in slots), timedelta(0))
        print(f"Total slot span: {total_slot_span}")

        # Verify no inflation: total slot span should not exceed input span
        assert total_slot_span <= span + timedelta(seconds=1), \
            f"Inflation detected: slots_span={total_slot_span} exceeds input_span={span}"

    def test_builder_correctness_trace(self):
        """
        Test: Trace through builder to verify slot generation is correct.

        Phase 2 refactor: Builder produces guaranteed non-overlapping slots.
        """
        data = self.create_mock_aw_client_yesterday()

        # Step 1: Check window events sum vs not-afk (should not match, windows are sparse)
        window_sum = data["window_sum"]
        not_afk_sum = data["total_not_afk"]

        print(f"\n=== BUILDER CORRECTNESS TRACE ===")
        print(f"Step 1: Input data")
        print(f"  Not-afk sum (online time): {not_afk_sum}")
        print(f"  Window events sum: {window_sum}")
        print(f"  Unaccounted (gap): {not_afk_sum - window_sum}")

        # Step 2: Create slots using new builder
        afk_events = [AFKEvent(
            timestamp=e.timestamp,
            duration=e.duration,
            data=e.data,
        ) for e in data["not_afk_events"]]

        window_events = [WindowEvent(
            timestamp=e.timestamp,
            duration=e.duration,
            data=e.data,
        ) for e in data["window_events"]]

        task_events = [TaskWarriorEvent(
            timestamp=e.timestamp,
            duration=e.duration,
            data=e.data,
        ) for e in data["task_events"]]

        slots = build_timeslot_timeline(
            afk_events=afk_events,
            window_events=window_events,
            task_events=task_events,
        )

        slots_actual_sum = sum((s.actual_duration or timedelta(0) for s in slots), timedelta(0))
        slots_wall_clock_sum = sum((s.duration for s in slots), timedelta(0))

        print(f"\nStep 2: Builder output")
        print(f"  Slots actual_duration sum: {slots_actual_sum}")
        print(f"  Slots wall-clock sum: {slots_wall_clock_sum}")
        print(f"  Reference window sum: {window_sum}")

        # Step 3: Verify builder guarantees
        print(f"\nStep 3: Builder invariant checks")
        print(f"  Number of slots: {len(slots)}")

        # Check non-overlapping guarantee
        sorted_slots = sorted(slots, key=lambda s: s.start)
        for i, slot in enumerate(sorted_slots):
            project = slot.task_event.project if slot.task_event else "unknown"
            task = slot.task_event.task if slot.task_event else "unknown"
            print(f"  Slot {i}: {project}/{task} {slot.start.time()}-{slot.end.time()}")
            print(f"    duration={slot.duration}, actual_duration={slot.actual_duration}")

            # Verify no overlap with next slot
            if i < len(sorted_slots) - 1:
                next_slot = sorted_slots[i + 1]
                if slot.end > next_slot.start:
                    print(f"    WARNING: Overlaps with next slot!")
                    assert False, f"Slots overlap: {i} ends at {slot.end}, {i+1} starts at {next_slot.start}"

        # Builder guarantees non-overlapping slots at construction time
        print(f"\nStep 4: Invariant verification")
        print(f"  All slots non-overlapping: PASS")
        print(f"  Total wall-clock accounted: {slots_wall_clock_sum}")

if __name__ == "__main__":
    # Run with pytest -xvs tests/integration/test_yesterday_totals_inflation.py
    pytest.main([__file__, "-xvs"])

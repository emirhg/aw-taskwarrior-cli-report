"""
CRITICAL: Event-Backed Slot Invariants

These tests enforce the fundamental rule:
- EVERY slot must be backed by at least ONE event (AFK, WINDOW, or TASK)
- NO phantom slots invented from gaps without events
- NO slot should exist without event coverage
"""

import pytest
from datetime import datetime, timedelta, timezone
from tw_report.core.aw_events import AFKEvent, WindowEvent, TaskWarriorEvent
from tw_report.core.timeslot_builder import build_timeslot_timeline


class TestEventBackedInvariant:
    """Core invariant: Every slot must be backed by at least one event"""

    def test_no_phantom_slots_for_gaps_without_events(self):
        """
        BUG: Builder creates phantom slots for gaps with zero event coverage.

        Scenario:
        - AFK event: 14:00-14:03:11
        - [GAP 14:03:14-14:18:43: ZERO events]
        - AFK event: 14:18:44-14:30:00

        WRONG: Builder creates a slot for 14:03:14-14:18:43 (phantom)
        CORRECT: No slot should exist for that gap

        This test WILL FAIL until builder is fixed.
        """
        afk_events = [
            AFKEvent(
                timestamp=datetime(2026, 8, 30, 20, 0, 0, tzinfo=timezone.utc),
                duration=timedelta(minutes=3, seconds=11),
                data={"status": "not-afk"}
            ),
            AFKEvent(
                timestamp=datetime(2026, 8, 30, 20, 18, 44, tzinfo=timezone.utc),
                duration=timedelta(minutes=11, seconds=16),
                data={"status": "not-afk"}
            ),
        ]

        # NO window or task events - pure gap
        slots = build_timeslot_timeline(afk_events, [], [])

        # Should have exactly 2 slots (one per AFK event)
        assert len(slots) == 2, f"Expected 2 slots, got {len(slots)}. Phantom slots created for gap!"

        # Verify no slot spans the gap
        for slot in slots:
            gap_start = datetime(2026, 8, 30, 20, 3, 14, tzinfo=timezone.utc)
            gap_end = datetime(2026, 8, 30, 20, 18, 43, tzinfo=timezone.utc)

            # Slot must not cover the entire gap
            assert not (slot.start <= gap_start and slot.end >= gap_end), \
                f"Slot {slot.start}-{slot.end} covers the gap with no events!"

    def test_every_slot_has_event_coverage(self):
        """
        Invariant: Every returned slot must have at least one event covering it.

        For each slot, verify:
        - At least one AFK event covers it, OR
        - At least one WINDOW event covers it, OR
        - At least one TASK event covers it
        """
        afk_events = [
            AFKEvent(
                timestamp=datetime(2026, 8, 30, 20, 0, 0, tzinfo=timezone.utc),
                duration=timedelta(hours=1),
                data={"status": "not-afk"}
            ),
        ]
        window_events = [
            WindowEvent(
                timestamp=datetime(2026, 8, 30, 20, 30, 0, tzinfo=timezone.utc),
                duration=timedelta(minutes=20),
                data={"app": "kitty"}
            ),
        ]

        slots = build_timeslot_timeline(afk_events, window_events, [])

        # For each slot, verify event backing
        for slot in slots:
            has_afk_coverage = any(
                e.timestamp <= slot.start < e.timestamp + e.duration
                or e.timestamp < slot.end <= e.timestamp + e.duration
                or (e.timestamp <= slot.start and slot.end <= e.timestamp + e.duration)
                for e in afk_events
            )
            has_window_coverage = any(
                e.timestamp <= slot.start < e.timestamp + e.duration
                or e.timestamp < slot.end <= e.timestamp + e.duration
                or (e.timestamp <= slot.start and slot.end <= e.timestamp + e.duration)
                for e in window_events
            )

            assert has_afk_coverage or has_window_coverage, \
                f"Slot {slot.start}-{slot.end} has no event coverage! Phantom slot!"

    def test_all_events_converted_to_slots(self):
        """
        Invariant: Every event must be converted to at least one slot.

        No event should disappear or be lost in conversion.
        """
        afk_events = [
            AFKEvent(
                timestamp=datetime(2026, 8, 30, 20, 0, 0, tzinfo=timezone.utc),
                duration=timedelta(minutes=10),
                data={"status": "not-afk"}
            ),
            AFKEvent(
                timestamp=datetime(2026, 8, 30, 20, 20, 0, tzinfo=timezone.utc),
                duration=timedelta(minutes=10),
                data={"status": "afk"}
            ),
        ]

        slots = build_timeslot_timeline(afk_events, [], [])

        # Should have at least one slot per event
        assert len(slots) >= len(afk_events), \
            f"Events lost! {len(afk_events)} events but only {len(slots)} slots"

    def test_no_invented_durations(self):
        """
        CRITICAL: No slot should have duration beyond what events cover.

        Example BUG:
        - Gap 14:03:14-14:18:43 (15.5 minutes) with ZERO events
        - Builder creates slot with duration 00:15:32
        - This duration is INVENTED, not backed by any event!
        """
        afk_events = [
            AFKEvent(
                timestamp=datetime(2026, 8, 30, 20, 0, 0, tzinfo=timezone.utc),
                duration=timedelta(minutes=5),
                data={"status": "not-afk"}
            ),
            # GAP: 14:05-14:20 (15 minutes, zero events)
            AFKEvent(
                timestamp=datetime(2026, 8, 30, 20, 20, 0, tzinfo=timezone.utc),
                duration=timedelta(minutes=5),
                data={"status": "not-afk"}
            ),
        ]

        total_event_duration = sum((e.duration for e in afk_events), timedelta(0))

        slots = build_timeslot_timeline(afk_events, [], [])
        total_slot_duration = sum((s.duration for s in slots), timedelta(0))

        # Total slot duration should match total event duration
        # (no invented duration for gaps)
        assert total_slot_duration == total_event_duration, \
            f"Invented duration! Events total {total_event_duration}, slots total {total_slot_duration}"

    def test_gap_detection_realistic_scenario(self):
        """
        Real-world scenario: 14:03-14:18 gap with zero AFK/WINDOW/TASK events.

        This is the EXACT bug we caught:
        - AFK ends at 14:03:11
        - WINDOW ends at 14:03:14
        - ZERO events from 14:03:14 to 14:18:43
        - AFK resumes at 14:18:44

        Expected: NO slot for the gap
        Actual (BUGGY): Creates phantom "No project assigned" slot with 00:15:32
        """
        afk_events = [
            AFKEvent(
                timestamp=datetime(2026, 8, 30, 20, 0, 0, tzinfo=timezone.utc),
                duration=timedelta(minutes=3, seconds=11),
                data={"status": "not-afk"}
            ),
            AFKEvent(
                timestamp=datetime(2026, 8, 30, 20, 18, 44, tzinfo=timezone.utc),
                duration=timedelta(minutes=11, seconds=16),
                data={"status": "not-afk"}
            ),
        ]
        window_events = [
            WindowEvent(
                timestamp=datetime(2026, 8, 30, 20, 0, 0, tzinfo=timezone.utc),
                duration=timedelta(minutes=3, seconds=14),
                data={"app": "kitty"}
            ),
            # WINDOW ends at 14:03:14
            # AFK resumes at 14:18:44
            # GAP: 14:03:14-14:18:43 with ZERO events
            WindowEvent(
                timestamp=datetime(2026, 8, 30, 20, 18, 43, tzinfo=timezone.utc),
                duration=timedelta(minutes=6),
                data={"app": "kitty"}
            ),
        ]

        slots = build_timeslot_timeline(afk_events, window_events, [])

        # Should NOT have a slot covering 14:03:14-14:18:43
        gap_start = datetime(2026, 8, 30, 20, 3, 14, tzinfo=timezone.utc)
        gap_end = datetime(2026, 8, 30, 20, 18, 43, tzinfo=timezone.utc)

        for slot in slots:
            # If slot overlaps the gap, it's a phantom
            overlaps_gap = (
                slot.start < gap_end and slot.end > gap_start
            )

            if overlaps_gap:
                # Verify this slot is actually backed by an event in the gap
                has_backing = any(
                    (e.timestamp < gap_end and e.timestamp + e.duration > gap_start)
                    for e in afk_events + window_events
                )
                assert has_backing, \
                    f"Phantom slot {slot.start}-{slot.end} in gap {gap_start}-{gap_end}"

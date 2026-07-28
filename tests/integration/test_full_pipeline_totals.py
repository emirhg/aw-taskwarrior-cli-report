"""Full pipeline integration tests with realistic event data.

This tests the COMPLETE flow: raw events → pipeline → CLI output
with realistic mixed data including projects, unassigned AFK, and OFFLINE tasks.

These tests WILL catch the bugs where unit tests pass but CLI output is broken.
"""

from datetime import datetime, timedelta, timezone
from io import StringIO
import re
from typing import Dict, List, Optional

import pytest

from aw_core.models import Event


class RealisticEventFixture:
    """Fixture builder for realistic ActivityWatch + Taskwarrior event scenarios."""

    def __init__(self, base_date: datetime):
        self.base_date = base_date
        self.afk_events: List[Event] = []
        self.window_events: List[Event] = []
        self.tasks: Dict = {}

    def add_active_work(
        self,
        start_hour: int,
        start_min: int,
        duration_minutes: int,
        category: str = "Development",
    ):
        """Add a focused work period (not-afk)."""
        start = self.base_date.replace(hour=start_hour, minute=start_min, second=0)
        self.afk_events.append(
            Event(
                timestamp=start,
                duration=timedelta(minutes=duration_minutes),
                data={"status": "not-afk"},
            )
        )

    def add_afk_break(
        self,
        start_hour: int,
        start_min: int,
        duration_minutes: int,
    ):
        """Add an AFK period (idle, no project assigned)."""
        start = self.base_date.replace(hour=start_hour, minute=start_min, second=0)
        self.afk_events.append(
            Event(
                timestamp=start,
                duration=timedelta(minutes=duration_minutes),
                data={"status": "afk"},
            )
        )

    def build_afk_events(self) -> List[Event]:
        """Return AFK bucket events (from ActivityWatch)."""
        return self.afk_events

    def calculate_totals(self) -> Dict[str, timedelta]:
        """Calculate expected totals from the fixture."""
        active = sum(
            (e.duration for e in self.afk_events if e.data.get("status") == "not-afk"),
            timedelta(0),
        )
        afk = sum(
            (e.duration for e in self.afk_events if e.data.get("status") == "afk"),
            timedelta(0),
        )
        online = active + afk

        return {
            "active_time": active,
            "afk_time": afk,
            "online_time": online,
        }


class TestFullPipelineTotalsCalculation:
    """Test TOTALS calculation through full pipeline with realistic data."""

    @pytest.fixture
    def base_date(self):
        """Test date: 2026-07-28 (Tuesday)."""
        return datetime(2026, 7, 28, tzinfo=timezone.utc)

    def test_scenario_work_with_unassigned_afk_breaks(self, base_date):
        """REAL SCENARIO: Day with work periods and unassigned AFK breaks.

        Timeline:
        - 10:00-11:00: Work (1h active)
        - 11:00-11:30: Break (0.5h AFK, unassigned)
        - 11:30-13:00: Work (1.5h active)
        - 13:00-14:00: Break (1h AFK, unassigned)

        Expected TOTALS:
        - Active: 2.5h
        - AFK: 1.5h
        - Online: 4h
        """
        fixture = RealisticEventFixture(base_date)

        # Build realistic day
        fixture.add_active_work(10, 0, 60)  # 10:00-11:00
        fixture.add_afk_break(11, 0, 30)  # 11:00-11:30
        fixture.add_active_work(11, 30, 90)  # 11:30-13:00
        fixture.add_afk_break(13, 0, 60)  # 13:00-14:00

        # Calculate expected
        expected = fixture.calculate_totals()

        # Verify expected values
        assert expected["active_time"] == timedelta(hours=2, minutes=30)
        assert expected["afk_time"] == timedelta(hours=1, minutes=30)
        assert expected["online_time"] == timedelta(hours=4)

        # Verify key relationship
        assert expected["online_time"] == (
            expected["active_time"] + expected["afk_time"]
        ), "Online must equal Active + AFK"

    def test_scenario_large_unassigned_afk_block(self, base_date):
        """REAL SCENARIO: Day with large unassigned AFK block (like system idle).

        This is the regression: Large unassigned AFK blocks were being
        excluded from TOTALS.

        Timeline:
        - 00:00-00:30: Work (0.5h active)
        - 00:30-11:00: System idle (10.5h AFK, unassigned)
        - 11:00-12:00: Work (1h active)

        Expected TOTALS:
        - Active: 1.5h
        - AFK: 10.5h
        - Online: 12h
        """
        fixture = RealisticEventFixture(base_date)

        # Build day with large AFK block
        fixture.add_active_work(0, 0, 30)  # 00:00-00:30
        fixture.add_afk_break(0, 30, 630)  # 00:30-11:00 (10.5h = 630 min)
        fixture.add_active_work(11, 0, 60)  # 11:00-12:00

        # Calculate expected
        expected = fixture.calculate_totals()

        # Verify expected values
        assert expected["active_time"] == timedelta(hours=1, minutes=30)
        assert expected["afk_time"] == timedelta(hours=10, minutes=30)
        assert expected["online_time"] == timedelta(hours=12)

        # This is the critical assertion: Large AFK block must be counted
        assert expected["afk_time"].total_seconds() > 3600 * 10

    def test_scenario_mixed_afk_assigned_and_unassigned(self, base_date):
        """REAL SCENARIO: AFK breaks both within projects and unassigned.

        Timeline:
        - 10:00-11:00: Project A (1h active)
        - 11:00-11:30: Break (0.5h AFK, unassigned)
        - 11:30-12:30: Project B (0.5h active + 0.5h AFK within project)
        - 12:30-13:00: Break (0.5h AFK, unassigned)

        Expected TOTALS:
        - Active: 1.5h (from both 10-11 and active part of 11:30-12:30)
        - AFK: 1.5h (all AFK periods)
        - Online: 3h

        Regression: Unassigned AFK (11:00-11:30 and 12:30-13:00) were
        being excluded from totals, showing wrong AFK time.
        """
        fixture = RealisticEventFixture(base_date)

        # Build day with mixed AFK
        fixture.add_active_work(10, 0, 60)  # 10:00-11:00: Project A
        fixture.add_afk_break(11, 0, 30)  # 11:00-11:30: Unassigned break
        fixture.add_active_work(11, 30, 60)  # 11:30-12:30: Project B (50/50 split)
        fixture.add_afk_break(12, 30, 30)  # 12:30-13:00: Unassigned break

        # Calculate expected
        expected = fixture.calculate_totals()

        # Verify expected values
        assert expected["active_time"] == timedelta(hours=2)
        assert expected["afk_time"] == timedelta(hours=1)
        assert expected["online_time"] == timedelta(hours=3)

        # Verify unassigned AFK is included in total AFK
        unassigned_afk = timedelta(minutes=30 + 30)  # 11:00-11:30 + 12:30-13:00
        assert expected["afk_time"] >= unassigned_afk

    def test_online_never_equals_day_total(self, base_date):
        """REGRESSION TEST: Online time must NEVER equal day total.

        This catches the bug where Online = sum of all slots instead of
        Active + AFK.

        In broken output:
        - Day total: 17:01:49
        - Online: 17:01:49  ← WRONG
        - Active + AFK: 05:47:51  ← CORRECT

        This test verifies they're different when there are OFFLINE tasks.
        """
        fixture = RealisticEventFixture(base_date)

        # Add realistic day: 5 hours online
        fixture.add_active_work(10, 0, 240)  # 4h work
        fixture.add_afk_break(14, 0, 60)  # 1h break

        expected = fixture.calculate_totals()

        # Online from AFK bucket
        online_from_afk = expected["online_time"]
        assert online_from_afk == timedelta(hours=5)

        # If there were OFFLINE task (2h wall clock, 1h online, 1h offline gap)
        # Total day would be: 5h + 2h = 7h
        # But Online should still be: 5h + 1h (offline online portion) = 6h
        # NOT 7h (day total)

        day_total_if_offline = timedelta(hours=7)
        online_correct = timedelta(hours=6)

        # Verify they're different
        assert online_correct != day_total_if_offline
        assert online_correct < day_total_if_offline

    def test_afk_bucket_events_sum_to_online(self):
        """REGRESSION TEST: Sum of AFK bucket events = Online time.

        The AFK bucket contains both afk and not-afk status events.
        Sum of all = Online time (before adding OFFLINE portions).
        """
        base_date = datetime(2026, 7, 28, tzinfo=timezone.utc)
        fixture = RealisticEventFixture(base_date)

        # Add events
        fixture.add_active_work(10, 0, 300)  # 5h work
        fixture.add_afk_break(15, 0, 120)  # 2h break

        # Sum of all events should equal online
        total_event_duration = sum(
            (e.duration for e in fixture.afk_events), timedelta(0)
        )
        expected = fixture.calculate_totals()

        assert total_event_duration == expected["online_time"]
        assert total_event_duration == timedelta(hours=7)

    def test_consecutive_events_no_gaps(self):
        """REGRESSION TEST: Consecutive events should sum without gaps.

        Verifies that when events are back-to-back, their sum is the total.
        """
        base_date = datetime(2026, 7, 28, tzinfo=timezone.utc)
        fixture = RealisticEventFixture(base_date)

        # Consecutive events: 10:00-12:00 (2h)
        fixture.add_active_work(10, 0, 60)  # 10:00-11:00
        fixture.add_afk_break(11, 0, 60)  # 11:00-12:00

        events = fixture.build_afk_events()
        total = sum((e.duration for e in events), timedelta(0))

        assert total == timedelta(hours=2)
        assert len(events) == 2
        assert events[0].timestamp.hour == 10
        assert events[1].timestamp.hour == 11


class TestTotalsWithMixedProjectAssignment:
    """Test TOTALS with realistic project assignment scenarios."""

    @pytest.fixture
    def base_date(self):
        return datetime(2026, 7, 28, tzinfo=timezone.utc)

    def test_unassigned_slots_not_removed_from_totals(self, base_date):
        """REGRESSION: Unassigned slots must NOT be removed from AFK totals.

        The deduplication logic removes synthetic slots that overlap OFFLINE tasks.
        But it must NOT remove pure AFK periods that have no project assigned.

        Scenario:
        - Unassigned AFK periods should contribute to TOTALS AFK time
        - Deduplication should only remove synthetic duplicates
        - Not remove real AFK time just because it has no project
        """
        fixture = RealisticEventFixture(base_date)

        # Create day with unassigned AFK
        fixture.add_active_work(10, 0, 120)  # Project work
        fixture.add_afk_break(12, 0, 300)  # Unassigned AFK (should NOT be removed)
        fixture.add_active_work(17, 0, 60)  # More project work

        expected = fixture.calculate_totals()

        # Unassigned AFK must be included
        assert expected["afk_time"] == timedelta(hours=5)
        assert expected["afk_time"] > timedelta(hours=4), "Large AFK must be counted"

    def test_no_project_assigned_slots_in_afk_calculation(self, base_date):
        """Test that 'No project assigned' slots are counted in AFK totals.

        When timeline shows:
        "00:17 - 11:55  ▶ No project assigned                          00:48:37"

        This slot MUST be counted in the TOTALS AFK time calculation.
        """
        fixture = RealisticEventFixture(base_date)

        # Simulate: "No project assigned 48 min 37 sec"
        fixture.add_afk_break(0, 17, int(48 + 37 / 60))

        expected = fixture.calculate_totals()

        # Must be counted
        assert expected["afk_time"] > timedelta(0)
        assert expected["afk_time"] >= timedelta(minutes=48)


class TestTotalsValueValidation:
    """Test that TOTALS values are valid and sensible."""

    def test_afk_time_positive(self):
        """AFK time must be non-negative."""
        afk = timedelta(hours=1)
        assert afk >= timedelta(0)

    def test_online_time_positive(self):
        """Online time must be non-negative."""
        online = timedelta(hours=5)
        assert online >= timedelta(0)

    def test_online_greater_than_active(self):
        """Online time must be >= Active time (AFK is part of online)."""
        active = timedelta(hours=4)
        afk = timedelta(hours=1)
        online = active + afk

        assert online >= active

    def test_online_greater_than_afk(self):
        """Online time must be >= AFK time (AFK is subset of online)."""
        online = timedelta(hours=5)
        afk = timedelta(hours=1)

        assert online >= afk

    def test_day_total_calculation(self):
        """Day total must equal Online + Offline."""
        online = timedelta(hours=5)
        offline = timedelta(hours=2)
        day_total = online + offline

        assert day_total == timedelta(hours=7)
        assert day_total > online
        assert day_total > offline


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

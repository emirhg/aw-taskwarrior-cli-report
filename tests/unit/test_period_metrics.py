"""Unit tests for PeriodMetrics data class and accumulation logic."""

import pytest
from datetime import timedelta
from tw_report.pipeline.models import PeriodMetrics, TimeslotDuration


class TestPeriodMetricsAdd:
    """Test PeriodMetrics.add() method."""

    def test_add_online_only(self):
        """Test adding only online time."""
        metrics = PeriodMetrics()
        metrics.add(online=timedelta(hours=5))
        
        assert metrics.online_duration == timedelta(hours=5)
        assert metrics.afk_duration == timedelta(0)
        assert metrics.offline_gap == timedelta(0)
        assert metrics.productive_duration == timedelta(0)

    def test_add_online_and_afk(self):
        """Test adding online time with AFK portion."""
        metrics = PeriodMetrics()
        metrics.add(online=timedelta(hours=5), afk=timedelta(hours=1))
        
        assert metrics.online_duration == timedelta(hours=5)
        assert metrics.afk_duration == timedelta(hours=1)
        assert metrics.offline_gap == timedelta(0)

    def test_add_online_and_offline(self):
        """Test adding online and offline time."""
        metrics = PeriodMetrics()
        metrics.add(online=timedelta(hours=10), offline=timedelta(hours=2))
        
        assert metrics.online_duration == timedelta(hours=10)
        assert metrics.offline_gap == timedelta(hours=2)
        assert metrics.total_duration == timedelta(hours=12)

    def test_add_all_metrics(self):
        """Test adding all metric types together."""
        metrics = PeriodMetrics()
        metrics.add(
            online=timedelta(hours=10),
            afk=timedelta(hours=2),
            offline=timedelta(hours=3),
            productive=timedelta(hours=8)
        )
        
        assert metrics.online_duration == timedelta(hours=10)
        assert metrics.afk_duration == timedelta(hours=2)
        assert metrics.offline_gap == timedelta(hours=3)
        assert metrics.productive_duration == timedelta(hours=8)
        assert metrics.total_duration == timedelta(hours=13)
        assert metrics.active_duration == timedelta(hours=8)

    def test_add_multiple_calls_accumulate(self):
        """Test that multiple add() calls accumulate correctly."""
        metrics = PeriodMetrics()
        
        metrics.add(online=timedelta(hours=2), afk=timedelta(minutes=30))
        metrics.add(online=timedelta(hours=3), afk=timedelta(minutes=30))
        
        assert metrics.online_duration == timedelta(hours=5)
        assert metrics.afk_duration == timedelta(hours=1)

    def test_add_ignores_zero_values(self):
        """Test that zero/None values are ignored in add()."""
        metrics = PeriodMetrics()
        metrics.add(online=timedelta(0), afk=None, offline=timedelta(0))
        
        assert metrics.online_duration == timedelta(0)
        assert metrics.afk_duration == timedelta(0)
        assert metrics.offline_gap == timedelta(0)

    def test_add_respects_negative_check(self):
        """Test that only positive durations are added."""
        metrics = PeriodMetrics()
        # The add() method checks `if value and value.total_seconds() > 0`
        metrics.add(online=timedelta(seconds=-1))  # Should be ignored
        
        assert metrics.online_duration == timedelta(0)


class TestPeriodMetricsAddTimeslot:
    """Test PeriodMetrics.add_timeslot() convenience method."""

    def test_add_timeslot_with_online_and_afk(self):
        """Test adding a timeslot with online and AFK portions."""
        metrics = PeriodMetrics()
        slot = TimeslotDuration(
            online_duration=timedelta(hours=5),
            afk_portion=timedelta(hours=1),
            offline_gap=None
        )
        metrics.add_timeslot(slot, productive=timedelta(hours=4))
        
        assert metrics.online_duration == timedelta(hours=5)
        assert metrics.afk_duration == timedelta(hours=1)
        assert metrics.productive_duration == timedelta(hours=4)

    def test_add_timeslot_with_offline_gap(self):
        """Test adding a timeslot with offline gap (offline task scenario)."""
        metrics = PeriodMetrics()
        slot = TimeslotDuration(
            online_duration=timedelta(minutes=30),
            afk_portion=None,
            offline_gap=timedelta(hours=1, minutes=30)
        )
        metrics.add_timeslot(slot)
        
        assert metrics.online_duration == timedelta(minutes=30)
        assert metrics.offline_gap == timedelta(hours=1, minutes=30)
        assert metrics.total_duration == timedelta(hours=2)

    def test_add_timeslot_multiple_accumulation(self):
        """Test accumulating multiple timeslots."""
        metrics = PeriodMetrics()
        
        slot1 = TimeslotDuration(
            online_duration=timedelta(hours=2),
            afk_portion=timedelta(minutes=15),
            offline_gap=None
        )
        slot2 = TimeslotDuration(
            online_duration=timedelta(hours=3),
            afk_portion=timedelta(minutes=45),
            offline_gap=timedelta(hours=1)
        )
        
        metrics.add_timeslot(slot1, productive=timedelta(hours=1, minutes=45))
        metrics.add_timeslot(slot2, productive=timedelta(hours=2, minutes=30))
        
        assert metrics.online_duration == timedelta(hours=5)
        assert metrics.afk_duration == timedelta(hours=1)
        assert metrics.offline_gap == timedelta(hours=1)
        assert metrics.productive_duration == timedelta(hours=4, minutes=15)


class TestPeriodMetricsTotalDuration:
    """Test PeriodMetrics.total_duration property."""

    def test_total_duration_online_only(self):
        """Test total_duration with only online time."""
        metrics = PeriodMetrics(
            online_duration=timedelta(hours=10)
        )
        assert metrics.total_duration == timedelta(hours=10)

    def test_total_duration_online_plus_offline(self):
        """Test total_duration combines online and offline."""
        metrics = PeriodMetrics(
            online_duration=timedelta(hours=10),
            offline_gap=timedelta(hours=2)
        )
        assert metrics.total_duration == timedelta(hours=12)

    def test_total_duration_does_not_include_afk_twice(self):
        """Test that total_duration doesn't double-count AFK.
        
        Critical: AFK is a subset of online_duration, not additive.
        """
        metrics = PeriodMetrics(
            online_duration=timedelta(hours=10),  # Includes AFK
            afk_duration=timedelta(hours=2),       # Subset of online
            offline_gap=timedelta(hours=3)
        )
        # Should be: online + offline = 10 + 3, NOT 10 + 2 + 3
        assert metrics.total_duration == timedelta(hours=13)
        
    def test_total_duration_formula(self):
        """Test the total_duration formula: online_duration + offline_gap."""
        metrics = PeriodMetrics()
        metrics.add(
            online=timedelta(hours=8),
            afk=timedelta(hours=2),
            offline=timedelta(hours=4),
            productive=timedelta(hours=6)
        )
        
        # total_duration should ONLY be online + offline, not include AFK separately
        expected = timedelta(hours=8) + timedelta(hours=4)  # 12 hours
        assert metrics.total_duration == expected


class TestPeriodMetricsActiveDuration:
    """Test PeriodMetrics.active_duration property."""

    def test_active_duration_no_afk(self):
        """Test active_duration when no AFK time."""
        metrics = PeriodMetrics(
            online_duration=timedelta(hours=8)
        )
        assert metrics.active_duration == timedelta(hours=8)

    def test_active_duration_with_afk(self):
        """Test active_duration subtracts AFK from online."""
        metrics = PeriodMetrics(
            online_duration=timedelta(hours=8),
            afk_duration=timedelta(hours=2)
        )
        assert metrics.active_duration == timedelta(hours=6)

    def test_active_duration_does_not_include_offline(self):
        """Test that active_duration ignores offline_gap."""
        metrics = PeriodMetrics(
            online_duration=timedelta(hours=8),
            afk_duration=timedelta(hours=2),
            offline_gap=timedelta(hours=4)
        )
        # Should be: online - afk = 8 - 2 = 6, NOT affected by offline
        assert metrics.active_duration == timedelta(hours=6)


class TestPeriodMetricsDisplayCorrectness:
    """Test that metrics calculate correctly for display purposes."""

    def test_day_total_display_formula(self):
        """Test the correct formula for day total display.
        
        CORRECT: online_duration + offline_gap = total
        WRONG: total_duration (already includes both)
        """
        metrics = PeriodMetrics()
        metrics.add(
            online=timedelta(hours=17, minutes=28, seconds=51),
            offline=timedelta(hours=2, minutes=45, seconds=10)
        )
        
        # Display should show:
        # base_duration = online_duration = 17:28:51
        # gaps_str = offline_gap = (02:45:10 OFF)
        # Visual: (02:45:10 OFF)  17:28:51 = 20:14:01 total
        
        assert metrics.online_duration == timedelta(hours=17, minutes=28, seconds=51)
        assert metrics.offline_gap == timedelta(hours=2, minutes=45, seconds=10)
        assert metrics.total_duration == timedelta(hours=20, minutes=14, seconds=1)

    def test_metrics_accumulation_example_yesterday(self):
        """Test metrics accumulation with realistic data from :yesterday report.
        
        Simulates:
        - 3 offline_task slots with embedded AFK
        - Regular work slots
        """
        metrics = PeriodMetrics()
        
        # Offline task 1: 73 min wall-clock, 21:47 online, 51:16 offline
        metrics.add_timeslot(TimeslotDuration(
            online_duration=timedelta(minutes=21, seconds=47),
            offline_gap=timedelta(minutes=51, seconds=16),
            afk_portion=None
        ))
        
        # Offline task 2: 19 min wall-clock, 8:13 online, 10:53 offline
        metrics.add_timeslot(TimeslotDuration(
            online_duration=timedelta(minutes=8, seconds=13),
            offline_gap=timedelta(minutes=10, seconds=53),
            afk_portion=None
        ))
        
        # Regular work with embedded AFK: 330 min, 5:29:28 online, 56:34 AFK
        metrics.add(
            online=timedelta(hours=5, minutes=29, seconds=28),
            afk=timedelta(minutes=56, seconds=34)
        )
        
        # Check totals
        online_total = (
            timedelta(minutes=21, seconds=47) +
            timedelta(minutes=8, seconds=13) +
            timedelta(hours=5, minutes=29, seconds=28)
        )
        offline_total = (
            timedelta(minutes=51, seconds=16) +
            timedelta(minutes=10, seconds=53)
        )
        
        assert metrics.online_duration == online_total
        assert metrics.offline_gap == offline_total
        assert metrics.afk_duration == timedelta(minutes=56, seconds=34)
        
        # Day total should be online + offline
        day_total = online_total + offline_total
        assert metrics.total_duration == day_total


class TestPeriodMetricsEdgeCases:
    """Test edge cases and error conditions."""

    def test_zero_metrics(self):
        """Test metrics initialized with zero values."""
        metrics = PeriodMetrics()
        assert metrics.online_duration == timedelta(0)
        assert metrics.afk_duration == timedelta(0)
        assert metrics.offline_gap == timedelta(0)
        assert metrics.productive_duration == timedelta(0)
        assert metrics.total_duration == timedelta(0)
        assert metrics.active_duration == timedelta(0)

    def test_afk_exceeding_online_treated_as_anomaly(self):
        """Test behavior when AFK > online (should not happen but verify handling)."""
        metrics = PeriodMetrics(
            online_duration=timedelta(hours=2),
            afk_duration=timedelta(hours=3)  # Impossible case
        )
        # active_duration would be negative, but PeriodMetrics doesn't validate this
        # This test documents current behavior
        assert metrics.active_duration == timedelta(hours=-1)

    def test_large_durations(self):
        """Test with realistic large durations (full year)."""
        metrics = PeriodMetrics()
        metrics.add(
            online=timedelta(days=250),  # ~250 working days
            afk=timedelta(days=50),      # ~50 days AFK
            offline=timedelta(days=65),  # ~65 days system off
        )
        
        assert metrics.online_duration == timedelta(days=250)
        assert metrics.total_duration == timedelta(days=315)


class TestDayTotalDisplayLogic:
    """Test the specific day total display calculation used in timeline_render.py."""

    def test_display_uses_online_not_total_duration(self):
        """Test that day total display uses online_duration, not total_duration.
        
        This is the CRITICAL fix for Bug #1: Double-counting offline time.
        
        WRONG (before fix):
            total_day_with_afk = daily_metrics.total_duration  # = online + offline
            gaps_str = f"({format_duration(offline)})"
            Display: (OFF) total_duration = (02:45:10 OFF) 22:59:12
            Result: Offline counted twice!
        
        CORRECT (after fix):
            total_day_with_afk = daily_metrics.online_duration  # = online only
            gaps_str = f"({format_duration(offline)})"
            Display: (OFF) online_duration = (02:45:10 OFF) 17:28:51
            Result: online + offline = total ✓
        """
        metrics = PeriodMetrics()
        metrics.add(
            online=timedelta(hours=17, minutes=28, seconds=51),
            offline=timedelta(hours=2, minutes=45, seconds=10)
        )
        
        # WRONG approach (before fix): using total_duration
        total_day_wrong = metrics.total_duration
        # Would display: total_day_wrong = 20:14:01
        # Then separately show: (02:45:10 OFF)
        # User sees: 20:14:01 + (02:45:10 OFF) = appears to be 22:59:12 (WRONG!)
        
        # CORRECT approach (after fix): using online_duration
        total_day_correct = metrics.online_duration
        # Displays: total_day_correct = 17:28:51
        # Then separately show: (02:45:10 OFF)  
        # User sees: 17:28:51 + (02:45:10 OFF) = 20:14:01 ✓ (CORRECT!)
        
        # Verify the fix
        assert total_day_correct == timedelta(hours=17, minutes=28, seconds=51)
        assert total_day_wrong == timedelta(hours=20, minutes=14, seconds=1)
        assert total_day_correct != total_day_wrong  # They should be different!
        
        # The correct display formula
        displayed_online = total_day_correct
        displayed_offline = metrics.offline_gap
        actual_total = displayed_online + displayed_offline
        
        assert actual_total == timedelta(hours=20, minutes=14, seconds=1)
        assert actual_total == metrics.total_duration

    def test_three_component_metrics_display(self):
        """Test display with online, AFK, and offline components.
        
        Total = Online + Offline
        Active = Online - AFK
        """
        metrics = PeriodMetrics()
        metrics.add(
            online=timedelta(hours=10),      # 10 hours online (includes AFK)
            afk=timedelta(hours=2),           # 2 hours AFK (subset of online)
            offline=timedelta(hours=3)        # 3 hours system off
        )
        
        # For display purposes:
        base_duration = metrics.online_duration  # 10 hours
        active_time = metrics.active_duration     # 10 - 2 = 8 hours
        offline_time = metrics.offline_gap        # 3 hours
        total_time = metrics.total_duration       # 10 + 3 = 13 hours
        
        # Display would show:
        # Online: 10 hours
        # - Active: 8 hours  
        # - AFK: 2 hours
        # Offline: 3 hours
        # Total: 13 hours
        
        assert base_duration == timedelta(hours=10)
        assert active_time == timedelta(hours=8)
        assert offline_time == timedelta(hours=3)
        assert total_time == timedelta(hours=13)

    def test_timeline_rendering_metric_sequence(self):
        """Test the sequence of metric values during timeline rendering.
        
        Simulates what happens in print_timeline_report:
        1. Create daily_metrics = PeriodMetrics()
        2. For each group: daily_metrics.add(online=..., afk=..., offline=...)
        3. For each offline_task: daily_metrics.add_timeslot(slot)
        4. Display: use daily_metrics.online_duration (NOT total_duration)
        """
        daily_metrics = PeriodMetrics()
        
        # Step 1: Add first group (regular work with AFK)
        daily_metrics.add(
            online=timedelta(hours=5),
            afk=timedelta(minutes=30)
        )
        assert daily_metrics.online_duration == timedelta(hours=5)
        assert daily_metrics.afk_duration == timedelta(minutes=30)
        
        # Step 2: Add offline_task
        slot = TimeslotDuration(
            online_duration=timedelta(hours=1),
            offline_gap=timedelta(hours=2),
            afk_portion=None
        )
        daily_metrics.add_timeslot(slot)
        assert daily_metrics.online_duration == timedelta(hours=6)
        assert daily_metrics.offline_gap == timedelta(hours=2)
        
        # Step 3: Display (use online_duration, not total_duration)
        display_base = daily_metrics.online_duration  # Correct!
        display_total = daily_metrics.total_duration  # Wrong approach
        
        assert display_base == timedelta(hours=6)      # What should be displayed
        assert display_total == timedelta(hours=8)     # Wrong if used for base
        
        # Verify formula
        assert display_total == display_base + daily_metrics.offline_gap

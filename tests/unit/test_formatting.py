"""
Unit tests for formatting utilities (tw_report.utils.formatting).

Tests verify duration formatting, title sanitization, and timeline line formatting.
All tested functions are pure (no I/O side effects).
"""

from datetime import timedelta
from unittest.mock import patch

import pytest

from tw_report.utils.formatting import (
    abbreviate_project_path,
    format_afk_label,
    format_duration,
    format_duration_tracked_prod,
    format_duration_with_afk,
    format_duration_with_gaps,
    format_offline_label,
    format_offline_task_duration,
    format_timeline_line,
    get_terminal_width,
    normalize_title,
    sanitize_title,
    truncate_title,
)


class TestFormatDuration:
    """Test basic duration formatting."""

    def test_zero_duration(self):
        """Zero duration formats as 0:00:00."""
        assert format_duration(timedelta(0)) == "0:00:00"

    def test_sub_minute(self):
        """Sub-minute duration formats correctly."""
        assert format_duration(timedelta(seconds=30)) == "0:00:30"
        assert format_duration(timedelta(seconds=59)) == "0:00:59"

    def test_one_minute(self):
        """One minute duration."""
        assert format_duration(timedelta(minutes=1)) == "0:01:00"

    def test_hours_and_minutes(self):
        """Multi-hour duration formats with zero-padding."""
        assert format_duration(timedelta(hours=1, minutes=30)) == "1:30:00"
        assert format_duration(timedelta(hours=2, minutes=5, seconds=45)) == "2:05:45"

    def test_large_duration(self):
        """Large duration formats correctly."""
        assert format_duration(timedelta(hours=24)) == "24:00:00"
        assert format_duration(timedelta(hours=100)) == "100:00:00"

    def test_negative_duration(self):
        """Negative duration is handled."""
        result = format_duration(timedelta(seconds=-100))
        # timedelta converts to negative total_seconds
        assert ":" in result


class TestFormatDurationTrackedProd:
    """Test duration formatting with productivity percentage."""

    def test_full_productive(self):
        """100% productive time."""
        result = format_duration_tracked_prod(
            timedelta(hours=1), timedelta(hours=1)
        )
        assert "0:01:00:00" not in result  # Should use format_duration
        assert "[prod 100%]" in result

    def test_half_productive(self):
        """50% productive time."""
        result = format_duration_tracked_prod(
            timedelta(hours=2), timedelta(hours=1)
        )
        assert "[prod  50%]" in result

    def test_low_productivity(self):
        """Low productivity percentage."""
        result = format_duration_tracked_prod(
            timedelta(hours=10), timedelta(minutes=30)
        )
        # 30 minutes / 10 hours = 0.5 / 10 = 0.05 = 5%
        assert "[prod   5%]" in result

    def test_zero_tracked_duration(self):
        """Zero tracked duration returns just duration."""
        result = format_duration_tracked_prod(timedelta(0), timedelta(0))
        assert result == "0:00:00"

    def test_zero_productive_duration(self):
        """Zero productive duration shows 0% productivity."""
        result = format_duration_tracked_prod(timedelta(hours=1), timedelta(0))
        assert "[prod   0%]" in result

    def test_alignment(self):
        """Percentage label should be consistently aligned."""
        result1 = format_duration_tracked_prod(timedelta(hours=1), timedelta(0))
        result2 = format_duration_tracked_prod(
            timedelta(hours=1), timedelta(hours=1)
        )
        # Both should end with the bracket label
        assert result1.endswith("]")
        assert result2.endswith("]")
        # Both should contain the prod label
        assert "[prod" in result1
        assert "[prod" in result2


class TestFormatAfkLabel:
    """Test AFK label formatting."""

    def test_afk_format(self):
        """AFK label should have consistent width."""
        result = format_afk_label(timedelta(minutes=30))
        assert "[   AFK   ]" in result
        assert "0:30:00" in result

    def test_alignment(self):
        """AFK label should be right-aligned."""
        result = format_afk_label(timedelta(hours=1))
        # Should end with 11-char label
        assert result.endswith("[   AFK   ]")


class TestFormatOfflineLabel:
    """Test OFFLINE label formatting."""

    def test_offline_format(self):
        """OFFLINE label should have consistent width."""
        result = format_offline_label(timedelta(hours=2))
        assert "[ OFFLINE ]" in result
        assert "2:00:00" in result

    def test_alignment(self):
        """OFFLINE label should be right-aligned."""
        result = format_offline_label(timedelta(minutes=15))
        assert result.endswith("[ OFFLINE ]")


class TestFormatDurationWithAfk:
    """Test duration formatting with optional AFK notation."""

    def test_without_afk(self):
        """Without AFK duration, uses standard format."""
        result = format_duration_with_afk(timedelta(hours=1), timedelta(hours=1))
        assert "AFK" not in result
        assert "[prod 100%]" in result

    def test_with_afk(self):
        """With AFK duration, includes AFK notation."""
        result = format_duration_with_afk(
            timedelta(hours=2),
            timedelta(hours=1),
            afk_duration=timedelta(minutes=30),
        )
        assert "(0:30:00 AFK)" in result
        assert "[prod  50%]" in result

    def test_zero_afk_duration(self):
        """Zero AFK duration is ignored."""
        result = format_duration_with_afk(
            timedelta(hours=1), timedelta(hours=1), afk_duration=timedelta(0)
        )
        assert "AFK" not in result


class TestFormatDurationWithGaps:
    """Test duration formatting with multiple gap types."""

    def test_without_gaps(self):
        """Without gaps, uses standard format."""
        result = format_duration_with_gaps(timedelta(hours=1), timedelta(hours=1))
        assert "AFK" not in result
        assert "OFFLINE" not in result

    def test_with_afk_only(self):
        """With only AFK, shows AFK notation."""
        result = format_duration_with_gaps(
            timedelta(hours=2),
            timedelta(hours=1),
            afk_duration=timedelta(minutes=30),
        )
        assert "(0:30:00 AFK)" in result
        assert "OFFLINE" not in result

    def test_with_offline_only(self):
        """With only offline extension, shows OFFLINE notation."""
        result = format_duration_with_gaps(
            timedelta(hours=2),
            timedelta(hours=1),
            offline_extension_duration=timedelta(minutes=15),
        )
        assert "(0:15:00 OFFLINE)" in result
        assert "AFK" not in result

    def test_with_both_gaps(self):
        """With both AFK and OFFLINE, shows both."""
        result = format_duration_with_gaps(
            timedelta(hours=3),
            timedelta(hours=2),
            afk_duration=timedelta(minutes=30),
            offline_extension_duration=timedelta(minutes=15),
        )
        assert "0:30:00 AFK" in result
        assert "0:15:00 OFFLINE" in result
        assert ", " in result  # Both shown together


class TestFormatOfflineTaskDuration:
    """Test offline task duration formatting.

    Tests now validate unified productivity calculation: productivity is based on
    measured activity scores (productive_duration), not on offline time heuristics.
    """

    def test_full_offline_time_no_productivity_data(self):
        """When all time was offline with no productivity data, don't show productivity."""
        result = format_offline_task_duration(
            timedelta(hours=2), timedelta(0)
        )
        assert "(02:00:00 OFF)" in result
        assert "00:00:00" in result
        assert "[prod" not in result  # No productivity data shown

    def test_half_offline_time_no_productivity_data(self):
        """When half the time was offline with no productivity data, don't show productivity."""
        result = format_offline_task_duration(
            timedelta(hours=2), timedelta(hours=1)
        )
        assert "(01:00:00 OFF)" in result
        assert "01:00:00" in result
        assert "[prod" not in result  # No productivity data shown

    def test_online_with_productivity_data(self):
        """When showing productivity based on measured data."""
        result = format_offline_task_duration(
            timedelta(hours=2), timedelta(hours=2),
            productive_duration=timedelta(hours=1)  # 50% productive
        )
        assert "(00:00:00 OFF)" in result
        assert "[prod  50%]" in result

    def test_zero_wall_clock_duration(self):
        """Zero duration should handle gracefully."""
        result = format_offline_task_duration(
            timedelta(0), timedelta(0)
        )
        assert "(00:00:00 OFF)" in result
        assert "[prod" not in result  # No productivity data


class TestGetTerminalWidth:
    """Test terminal width detection."""

    def test_get_terminal_width_mocked(self):
        """Terminal width should return columns."""
        with patch("shutil.get_terminal_size") as mock_size:
            mock_size.return_value.columns = 120
            assert get_terminal_width() == 120

    def test_fallback_to_80(self):
        """Should fall back to 80 on OSError."""
        with patch("shutil.get_terminal_size", side_effect=OSError):
            assert get_terminal_width() == 80


class TestNormalizeTitle:
    """Test title normalization (notification counter removal)."""

    def test_counter_at_start(self):
        """Remove counter at start: '(7) WhatsApp' → 'WhatsApp'."""
        assert normalize_title("(7) WhatsApp") == "WhatsApp"

    def test_counter_at_end(self):
        """Remove counter at end: 'Inbox (2)' → 'Inbox'."""
        assert normalize_title("Inbox (2)") == "Inbox"

    def test_counter_in_middle(self):
        """Remove counter in middle: 'Inbox (2) - Gmail' → 'Inbox - Gmail'."""
        assert normalize_title("Inbox (2) - Gmail") == "Inbox - Gmail"

    def test_multiple_counters(self):
        """Remove multiple counters."""
        assert normalize_title("(1) App (5) More") == "App More"

    def test_no_counter(self):
        """Title without counters unchanged."""
        assert normalize_title("GitHub") == "GitHub"

    def test_empty_title(self):
        """Empty title returns empty."""
        assert normalize_title("") == ""

    def test_whitespace_handling(self):
        """Extra whitespace is cleaned up."""
        assert normalize_title("Text  (3)  More") == "Text More"


class TestSanitizeTitle:
    """Test title sanitization (emoji/symbol removal)."""

    def test_ascii_only(self):
        """ASCII-only titles pass through unchanged."""
        assert sanitize_title("Visual Studio Code") == "Visual Studio Code"

    def test_accented_characters_preserved(self):
        """Latin accented characters are preserved."""
        result_ñ = sanitize_title("Configuración")
        result_á = sanitize_title("Análisis")
        result_é = sanitize_title("Programación")
        # These should contain the accented characters (Latin-1 range)
        assert result_ñ == "Configuración"
        assert result_á == "Análisis"
        assert result_é == "Programación"

    def test_emoji_removed(self):
        """Emoji should be removed."""
        result = sanitize_title("Chat 💬 Application")
        assert "💬" not in result
        assert "Chat" in result
        assert "Application" in result

    def test_unicode_symbols_removed(self):
        """Unicode symbols outside Latin-1 should be removed."""
        # Symbols in higher ranges (like bullet U+2022) should be filtered
        result = sanitize_title("Item • Bullet")
        assert "•" not in result  # Bullet is not in Latin-1
        assert "Item" in result
        assert "Bullet" in result

    def test_calls_normalize(self):
        """sanitize_title should call normalize_title."""
        result = sanitize_title("App (5) Name")
        assert "(5)" not in result


class TestTruncateTitle:
    """Test title truncation."""

    def test_short_title_unchanged(self):
        """Short titles unchanged."""
        title = "Short"
        assert truncate_title(title) == title

    def test_long_title_truncated(self):
        """Long title is truncated with ellipsis."""
        long_title = "A" * 100
        result = truncate_title(long_title, max_length=60)
        assert len(result) == 60
        assert result.endswith("…")

    def test_exact_max_length(self):
        """Title at max_length is unchanged."""
        title = "A" * 60
        assert truncate_title(title, max_length=60) == title

    def test_empty_title(self):
        """Empty title returns empty."""
        assert truncate_title("") == ""


class TestAbbreviateProjectPath:
    """Test project path abbreviation."""

    def test_single_level_project(self):
        """Single-level project unchanged."""
        assert abbreviate_project_path("Project") == "Project"

    def test_multi_level_short_project(self):
        """Multi-level project with short root unchanged."""
        result = abbreviate_project_path("App > Web > Frontend")
        assert "App" in result
        assert "Frontend" in result

    def test_multi_level_long_root(self):
        """Multi-level project with long root is abbreviated."""
        result = abbreviate_project_path(
            "VeryLongProjectName > Web > Frontend"
        )
        assert "VeryL..." in result
        assert "Frontend" in result

    def test_two_level_project(self):
        """Two-level project abbreviation."""
        result = abbreviate_project_path("Platform > Frontend")
        assert "Platform" in result or "Platf..." in result
        assert "Frontend" in result

    def test_with_task(self):
        """Abbreviation considers task length."""
        result = abbreviate_project_path(
            "VeryLongProjectName > Web > Frontend",
            task="VeryLongTaskName",
            max_content_width=100,
        )
        # Should abbreviate project
        assert "..." in result


class TestFormatTimelineLine:
    """Test timeline line formatting."""

    def test_short_content(self):
        """Short content without truncation."""
        result = format_timeline_line("Project > Task", "1:23:45")
        assert "Project > Task" in result
        assert "1:23:45" in result

    def test_duration_right_aligned(self):
        """Duration should be right-aligned."""
        with patch("tw_report.utils.formatting.get_terminal_width", return_value=80):
            result = format_timeline_line("Short", "1:00:00")
            # Duration should be near the end
            assert result.endswith("1:00:00")

    def test_long_content_truncated(self):
        """Content longer than max_left_width is truncated."""
        long_content = "A" * 150
        result = format_timeline_line(long_content, "1:00:00", max_left_width=100)
        assert "..." in result

    def test_no_duration(self):
        """Without duration, just returns content."""
        result = format_timeline_line("Project > Task", "")
        assert result == "Project > Task"

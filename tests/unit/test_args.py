"""
Unit tests for CLI argument parsing (tw_report.cli.args).

Tests verify parse_args, reorder_arguments, and parse_positional_args
correctly handle all flag combinations, orderings, and edge cases.

This is the first-ever test coverage for CLI parsing (previously zero coverage).
"""

import pytest

from tw_report.cli.args import parse_args, parse_positional_args, reorder_arguments


class TestReorderArguments:
    """Test argument reordering to put flags before positional args."""

    def test_empty_argv(self):
        """Empty argv should return empty list."""
        assert reorder_arguments([]) == []

    def test_flags_only(self):
        """Only flags, no positional args."""
        argv = ["--by-day", "--exclude-afk"]
        assert reorder_arguments(argv) == ["--by-day", "--exclude-afk"]

    def test_positional_only(self):
        """Only positional args, no flags."""
        argv = [":today", "Climb"]
        assert reorder_arguments(argv) == [":today", "Climb"]

    def test_flags_then_positional(self):
        """Flags already before positional args."""
        argv = ["--by-day", "--project", "Climb", ":today"]
        result = reorder_arguments(argv)
        # Flags first, then positionals
        assert result[:3] == ["--by-day", "--project", "Climb"]
        assert result[3:] == [":today"]

    def test_positional_then_flags(self):
        """Positional args before flags (should be reordered)."""
        argv = [":today", "Climb", "--by-week"]
        result = reorder_arguments(argv)
        # Should reorder to flags first
        assert result[0] == "--by-week"
        assert ":today" in result
        assert "Climb" in result

    def test_mixed_ordering_complex(self):
        """Complex mixed ordering with multiple flags and values."""
        argv = [
            ":month",
            "--by-month",
            "Climb",
            "--project",
            "Personal",
            "--detail-level",
            "3",
        ]
        result = reorder_arguments(argv)
        # Flags with their values should come first
        assert result[0] == "--by-month"
        assert "--project" in result
        assert "Personal" in result[result.index("--project") + 1]
        assert "--detail-level" in result


class TestParsePositionalArgs:
    """Test period vs. search term disambiguation."""

    def test_empty_args(self):
        """Empty args list should return defaults."""
        period, search_term = parse_positional_args([])
        assert period == ":today"
        assert search_term is None

    def test_period_only(self):
        """Only a period specification."""
        period, search_term = parse_positional_args([":week"])
        assert period == ":week"
        assert search_term is None

    def test_search_term_only(self):
        """Only a search term (no period)."""
        period, search_term = parse_positional_args(["Climb"])
        assert period == ":today"  # Default
        assert search_term == "Climb"

    def test_period_and_search(self):
        """Both period and search term."""
        period, search_term = parse_positional_args([":month", "Climb"])
        assert period == ":month"
        assert search_term == "Climb"

    def test_iso_date_format(self):
        """ISO date as period specification."""
        period, search_term = parse_positional_args(["2026-06-15", "Climb"])
        assert period == "2026-06-15"
        assert search_term == "Climb"

    def test_iso_date_with_time(self):
        """ISO date with time as period."""
        period, search_term = parse_positional_args(["2026-06-15T10:00", "Climb"])
        assert period == "2026-06-15T10:00"
        assert search_term == "Climb"

    def test_multiple_periods_first_wins(self):
        """Multiple period specs; first one wins."""
        period, search_term = parse_positional_args([":week", ":month", "Climb"])
        assert period == ":week"  # First period
        assert search_term == "Climb"

    def test_multiple_search_terms_first_wins(self):
        """Multiple search terms; first one is used."""
        period, search_term = parse_positional_args([":today", "Climb", "Personal"])
        assert period == ":today"
        assert search_term == "Climb"  # First search term


class TestParseArgs:
    """Test high-level argument parsing."""

    def test_no_args_defaults(self):
        """No arguments should use defaults."""
        args = parse_args([])
        assert args.args == []
        assert args.by_project is False
        assert args.by_day is False
        assert args.by_week is False
        assert args.by_month is False
        assert args.by_year is False
        assert args.detail_level == 2
        assert args.exclude_afk is False
        assert args.include_afk is False

    def test_period_argument(self):
        """Period as positional arg."""
        args = parse_args([":week"])
        assert args.args == [":week"]

    def test_by_project_flag(self):
        """--by-project flag (hierarchical report)."""
        args = parse_args(["--by-project", ":today"])
        assert args.by_project is True
        assert args.args == [":today"]

    def test_by_day_flag(self):
        """--by-day flag (period consolidation)."""
        args = parse_args(["--by-day", ":today"])
        assert args.by_day is True

    def test_by_week_flag(self):
        """--by-week flag (period consolidation)."""
        args = parse_args(["--by-week", ":week"])
        assert args.by_week is True

    def test_by_month_flag(self):
        """--by-month flag (period consolidation)."""
        args = parse_args(["--by-month", ":month"])
        assert args.by_month is True

    def test_by_year_flag(self):
        """--by-year flag (period consolidation)."""
        args = parse_args(["--by-year", ":year"])
        assert args.by_year is True

    def test_detail_level(self):
        """--detail-level with value."""
        args = parse_args(["--detail-level", "3"])
        assert args.detail_level == 3

    def test_project_filter(self):
        """--project filter (repeatable)."""
        args = parse_args(["--project", "Climb", "--project", "Personal"])
        assert args.project == ["Climb", "Personal"]

    def test_exclude_afk(self):
        """--exclude-afk flag."""
        args = parse_args(["--exclude-afk"])
        assert args.exclude_afk is True
        assert args.include_afk is False

    def test_include_afk(self):
        """--include-afk flag."""
        args = parse_args(["--include-afk"])
        assert args.include_afk is True
        assert args.exclude_afk is False

    def test_exact_matching(self):
        """--exact flag for case-insensitive exact matching."""
        args = parse_args(["--exact", "--project", "Climb"])
        assert args.exact is True
        assert args.project == ["Climb"]

    def test_min_max_score(self):
        """--min-score and --max-score with floats."""
        args = parse_args(["--min-score", "5.0", "--max-score", "10.0"])
        assert args.min_score == 5.0
        assert args.max_score == 10.0

    def test_exclude_project(self):
        """--exclude-project (repeatable)."""
        args = parse_args(["--exclude-project", "Temp", "--exclude-project", "Test"])
        assert args.exclude_project == ["Temp", "Test"]

    def test_combined_flags(self):
        """Multiple flags combined."""
        args = parse_args([
            "--by-week",
            "--detail-level",
            "2",
            "--exclude-afk",
            "--project",
            "Climb",
            ":week",
        ])
        assert args.by_week is True
        assert args.detail_level == 2
        assert args.exclude_afk is True
        assert args.project == ["Climb"]
        assert args.args == [":week"]

    def test_no_taskwarrior(self):
        """--no-taskwarrior flag."""
        args = parse_args(["--no-taskwarrior"])
        assert args.no_taskwarrior is True

    def test_sort_by_duration(self):
        """--sort-by-duration flag."""
        args = parse_args(["--sort-by-duration"])
        assert args.sort_by_duration is True

    def test_sort_alphabetically(self):
        """--sort-alphabetically flag."""
        args = parse_args(["--sort-alphabetically"])
        assert args.sort_alphabetically is True

    def test_exclude_offline(self):
        """--exclude-offline flag."""
        args = parse_args(["--exclude-offline"])
        assert args.exclude_offline is True

    def test_exclude_non_project(self):
        """--exclude-non-project flag."""
        args = parse_args(["--exclude-non-project"])
        assert args.exclude_non_project is True

    def test_deduplicate_categories(self):
        """--deduplicate-categories flag."""
        args = parse_args(["--deduplicate-categories"])
        assert args.deduplicate_categories is True

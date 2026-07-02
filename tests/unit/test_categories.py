"""
Unit tests for category loading and scoring (tw_report.core.categories).

Tests verify category rule loading, regex compilation, categorization logic,
and score inheritance.
"""

import re
from datetime import datetime, timezone

import pytest
from aw_core.models import Event

from tw_report.core.categories import (
    categorize_event,
    compile_category_rules,
    get_category_score,
    load_categories,
)
from tw_report.exceptions import ConfigParsingError, CategoryValidationError


class TestLoadCategories:
    """Test category file loading."""

    def test_load_nonexistent_file(self):
        """Loading a nonexistent file should return empty list (not error)."""
        result = load_categories("/nonexistent/path/categories.json")
        assert result == []

    def test_load_malformed_json(self, tmp_path):
        """Malformed JSON should raise ConfigParsingError."""
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{invalid json")

        with pytest.raises(ConfigParsingError) as exc_info:
            load_categories(str(bad_json))
        assert "Malformed JSON" in str(exc_info.value)

    def test_load_valid_json_no_classes(self, tmp_path):
        """Valid JSON without 'classes' key should return empty list."""
        config = tmp_path / "config.json"
        config.write_text('{"other_field": []}')

        result = load_categories(str(config))
        assert result == []

    def test_load_valid_json_with_classes(self, tmp_path):
        """Valid JSON with 'classes' key should return that list."""
        config = tmp_path / "config.json"
        classes = [
            {
                "name": ["Work", "Coding"],
                "rule": {"type": "regex", "regex": "vim|code"},
                "data": {"score": 10.0},
            }
        ]
        import json

        config.write_text(json.dumps({"classes": classes}))

        result = load_categories(str(config))
        assert result == classes


class TestCompileCategoryRules:
    """Test category rule compilation."""

    def test_empty_rules(self):
        """Empty rule list should return empty compiled rules and score map."""
        compiled, scores = compile_category_rules([])
        assert compiled == []
        assert scores == {}

    def test_compile_simple_regex_rule(self):
        """Simple regex rule should compile and appear in score map."""
        rules = [
            {
                "name": ["Work", "Coding"],
                "rule": {"type": "regex", "regex": "vim|code"},
                "data": {"score": 10.0},
            }
        ]

        compiled, scores = compile_category_rules(rules)

        assert len(compiled) == 1
        cat_list, pattern, score = compiled[0]
        assert cat_list == ["Work", "Coding"]
        assert pattern.pattern == "vim|code"
        assert score == 10.0
        assert scores["Work > Coding"] == 10.0

    def test_invalid_regex(self):
        """Invalid regex should raise CategoryValidationError."""
        rules = [
            {
                "name": ["Test"],
                "rule": {"type": "regex", "regex": "[invalid(regex"},
                "data": {"score": 5.0},
            }
        ]

        with pytest.raises(CategoryValidationError) as exc_info:
            compile_category_rules(rules)
        assert "Invalid regex" in str(exc_info.value)

    def test_score_inheritance(self):
        """Child categories should inherit parent scores."""
        rules = [
            {
                "name": ["Work"],
                "rule": {"type": "none"},
                "data": {"score": 5.0},
            },
            {
                "name": ["Work", "Coding"],
                "rule": {"type": "regex", "regex": "vim"},
                "data": {"score": 10.0},
            },
        ]

        compiled, scores = compile_category_rules(rules)

        # Both parent and child should have scores
        assert scores["Work"] == 5.0
        assert scores["Work > Coding"] == 10.0


class TestGetCategoryScore:
    """Test category score lookup with inheritance."""

    def test_exact_match(self):
        """Exact match should return score directly."""
        scores = {"Work > Coding": 10.0}
        result = get_category_score("Work > Coding", scores)
        assert result == 10.0

    def test_missing_category_defaults_to_zero(self):
        """Missing category should default to 0.0."""
        scores = {"Work > Coding": 10.0}
        result = get_category_score("Unknown > Category", scores)
        assert result == 0.0

    def test_parent_inheritance(self):
        """Child with no score should inherit from parent."""
        scores = {
            "Work": 5.0,
            "Work > Coding": 10.0,
        }
        # "Work > Coding > Python" has no direct score, should inherit from "Work > Coding"
        result = get_category_score("Work > Coding > Python", scores)
        assert result == 10.0

    def test_multiple_level_inheritance(self):
        """Deep hierarchy should walk up to find parent score."""
        scores = {
            "Work": 3.0,
        }
        # "Work > A > B > C" has no direct score, should find "Work"
        result = get_category_score("Work > A > B > C", scores)
        assert result == 3.0

    def test_no_hierarchy_separator(self):
        """Simple category name without separator should do exact match."""
        scores = {"Coding": 10.0, "Work": 5.0}
        assert get_category_score("Coding", scores) == 10.0
        assert get_category_score("Unknown", scores) == 0.0


class TestCategorizeEvent:
    """Test event categorization by regex matching."""

    def test_categorize_by_app(self):
        """Event with matching app should be categorized."""
        event = Event(
            timestamp=datetime.now(timezone.utc),
            duration=__import__("datetime").timedelta(seconds=60),
            data={"app": "vim", "title": "file.txt"},
        )
        rules = [
            (["Work", "Coding"], re.compile("vim", re.IGNORECASE), 10.0),
        ]

        categorize_event(event, rules)

        assert event.data.get("$category") == ["Work > Coding"]

    def test_categorize_by_title(self):
        """Event with matching title should be categorized."""
        event = Event(
            timestamp=datetime.now(timezone.utc),
            duration=__import__("datetime").timedelta(seconds=60),
            data={"app": "unknown", "title": "Gmail - Inbox"},
        )
        rules = [
            (["Communication", "Email"], re.compile("gmail", re.IGNORECASE), 3.0),
        ]

        categorize_event(event, rules)

        assert event.data.get("$category") == ["Communication > Email"]

    def test_categorize_by_app_and_title(self):
        """Matching app+title should take precedence."""
        event = Event(
            timestamp=datetime.now(timezone.utc),
            duration=__import__("datetime").timedelta(seconds=60),
            data={"app": "vim", "title": "code.py"},
        )
        rules = [
            (["Work", "Coding"], re.compile("code", re.IGNORECASE), 10.0),
            (["Work", "Coding", "Python"], re.compile("vim.*code", re.IGNORECASE), 15.0),
        ]

        categorize_event(event, rules)

        # Most specific (longest path) should win
        assert event.data.get("$category") == ["Work > Coding > Python"]

    def test_categorize_no_match(self):
        """Event with no matching rule should not be categorized."""
        event = Event(
            timestamp=datetime.now(timezone.utc),
            duration=__import__("datetime").timedelta(seconds=60),
            data={"app": "unknown", "title": "random"},
        )
        rules = [
            (["Work", "Coding"], re.compile("vim", re.IGNORECASE), 10.0),
        ]

        categorize_event(event, rules)

        assert "$category" not in event.data

    def test_categorize_specificity_ordering(self):
        """Most specific (longest) matching category should win."""
        event = Event(
            timestamp=datetime.now(timezone.utc),
            duration=__import__("datetime").timedelta(seconds=60),
            data={"app": "code", "title": "test"},
        )
        rules = [
            (["Work"], re.compile("code", re.IGNORECASE), 5.0),
            (["Work", "Coding"], re.compile("code", re.IGNORECASE), 10.0),
            (["Work", "Coding", "Python"], re.compile("code", re.IGNORECASE), 15.0),
        ]

        categorize_event(event, rules)

        # Most specific (3 levels) should win
        assert event.data.get("$category") == ["Work > Coding > Python"]

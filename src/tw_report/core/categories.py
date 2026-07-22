"""
Category loading, compilation, and scoring for ActivityWatch categorization.

Loads regex-based categorization rules from ActivityWatch settings JSON,
compiles them into reusable patterns, and provides scoring/lookup utilities.
"""

import json
import logging
import os
import re
from datetime import timedelta
from typing import Dict, List, Optional, Pattern, Tuple

from aw_core.models import Event

from tw_report.exceptions import ConfigParsingError, CategoryValidationError

logger = logging.getLogger(__name__)


def load_categories(filepath: str) -> List[Dict]:
    """Load categorization rules from ActivityWatch settings file.

    Args:
        filepath: Path to ActivityWatch settings JSON file

    Returns:
        List of category rule dictionaries, or empty list if file not found/invalid

    Raises:
        ConfigParsingError: If the file exists but is malformed JSON
    """
    if not os.path.exists(filepath):
        logger.warning(f"Categories file not found at '{filepath}', using no rules")
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            settings = json.load(f)
            return settings.get("classes", [])
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse categories JSON from '{filepath}': {e}")
        raise ConfigParsingError(
            f"Malformed JSON in categories file '{filepath}': {e}"
        ) from e
    except IOError as e:
        logger.error(f"Failed to read categories file '{filepath}': {e}")
        raise ConfigParsingError(
            f"Cannot read categories file '{filepath}': {e}"
        ) from e


def compile_category_rules(
    category_rules: List[Dict],
) -> Tuple[List[Tuple[List[str], Pattern, float]], Dict[str, float]]:
    """Compile regex-based category rules into reusable patterns.

    Takes a list of category rule dictionaries (from ActivityWatch settings),
    validates them, compiles the regex patterns, and builds a score lookup map
    with inheritance support (child categories inherit parent scores).

    Args:
        category_rules: List of rule dicts with 'name', 'rule', 'data' keys

    Returns:
        Tuple of (compiled_rules, score_map) where:
        - compiled_rules: List of (category_path, pattern, score) tuples
        - score_map: Dict mapping category paths to productivity scores

    Raises:
        CategoryValidationError: If regex compilation fails
    """
    compiled_rules = []
    cat_score_map = {}

    if not category_rules:
        return [], {}

    # First pass: collect explicit category scores (for inheritance lookup)
    explicit_scores: Dict[str, Optional[float]] = {}
    for rule_item in category_rules:
        cat_list = rule_item.get("name", ["Unknown"])
        if cat_list:
            full_path = " > ".join(cat_list)
            score_val = rule_item.get("data", {}).get("score")
            explicit_scores[full_path] = (
                float(score_val) if score_val is not None else None
            )
            # Add parent categories with type: "none" and explicit scores
            rule = rule_item.get("rule", {})
            if rule.get("type") == "none" and score_val is not None:
                cat_score_map[full_path] = float(score_val)

    # Second pass: compile regex rules and build score map with inheritance
    for rule_item in category_rules:
        rule = rule_item.get("rule", {})
        if rule.get("type") == "regex" and rule.get("regex"):
            try:
                cat_list = rule_item.get("name", ["Unknown"])
                score_val = rule_item.get("data", {}).get("score")
                score = float(score_val) if score_val is not None else 0.0
                ignore_case = rule.get("ignore_case", True)
                flags = re.IGNORECASE if ignore_case else 0
                pattern = re.compile(rule["regex"], flags)
                compiled_rules.append((cat_list, pattern, score))

                # Store in score map for lookup
                if cat_list:
                    full_path = " > ".join(cat_list)
                    if score_val is not None:
                        cat_score_map[full_path] = score
                        # Also store leaf category for backward compatibility
                        cat_score_map[cat_list[-1]] = score

                    # Store parent paths for inheritance lookup
                    for i in range(len(cat_list) - 1, 0, -1):
                        parent_path = " > ".join(cat_list[:i])
                        if (
                            parent_path in explicit_scores
                            and explicit_scores[parent_path] is not None
                        ):
                            parent_score = explicit_scores[parent_path]
                            if parent_path not in cat_score_map:
                                cat_score_map[parent_path] = parent_score
            except re.error as e:
                logger.error(f"Failed to compile regex for rule {rule_item}: {e}")
                raise CategoryValidationError(
                    f"Invalid regex in category rule {rule_item}: {e}"
                ) from e
            except (ValueError, TypeError) as e:
                logger.error(f"Invalid category rule structure: {rule_item}: {e}")
                raise CategoryValidationError(
                    f"Invalid category rule structure: {e}"
                ) from e

    return compiled_rules, cat_score_map


def get_category_score(category: str, cat_score_map: Dict[str, float]) -> float:
    """Get productivity score for a category with inheritance support.

    If the category has no direct score, tries progressively shorter paths
    to find a parent category score. E.g., for "Work > Coding > Python":
    tries → full path → "Work > Coding" → "Work" → defaults to 0.

    Args:
        category: Category path (e.g., "Work > Coding > Python")
        cat_score_map: Score lookup dictionary

    Returns:
        Productivity score (float), defaults to 0.0 if not found
    """
    # Try exact match first
    if category in cat_score_map:
        return cat_score_map[category]

    # Try parent categories if category contains hierarchy separator
    if " > " in category:
        parts = category.split(" > ")
        # Work backwards from most specific to most general
        for i in range(len(parts) - 1, 0, -1):
            parent = " > ".join(parts[:i])
            if parent in cat_score_map:
                return cat_score_map[parent]

    return 0.0


def categorize_event(
    event: Event, categories: List[Tuple[List[str], Pattern, float]]
) -> None:
    """Categorize a window event by matching against regex rules.

    Mutates event.data["$category"] in-place with the most specific matching
    category. Tries to match against: (app + title), app, then title, in that order.

    Args:
        event: Window event to categorize (mutated in-place)
        categories: Compiled category rules from compile_category_rules()
    """
    app_name = event.data.get("app", "")
    title = event.data.get("title", "")
    match_strings = [
        app_name + " " + title,
        app_name,
        title,
    ]

    matched_cats = []
    for cat_list, pattern, _ in categories:
        if any(pattern.search(s) for s in match_strings):
            if cat_list:
                full_path = " > ".join(cat_list)
                # Store (specificity, path) for sorting by most-specific first
                matched_cats.append((len(cat_list), full_path))

    if matched_cats:
        # Sort by specificity (descending), then alphabetically
        matched_cats.sort(key=lambda x: (-x[0], x[1]))
        # Store the most specific matching category
        event.data["$category"] = [matched_cats[0][1]]


def build_categories_from_window_events(
    window_events: List[Event],
    period_start,
    period_end,
) -> List[Dict]:
    """Aggregate window events overlapping a time period into categories > apps > titles.

    Extracts ActivityWatch window categorization data from events that overlap a given
    time period, builds a nested structure of category > app > title > events, and
    flattens it into the TimelineSlot.categories list format.

    This is a shared helper used by:
    - generate_gap_entries(): Extract categories from window events during AFK periods
    - OfflineTaskProcessor: Extract categories from window events during OFFLINE periods

    Args:
        window_events: List of ActivityWatch window events
        period_start: Start of the time period to aggregate (datetime)
        period_end: End of the time period to aggregate (datetime)

    Returns:
        List of category dicts with structure:
        [{
            "category": "string",
            "duration": timedelta,
            "start": datetime,
            "end": datetime,
            "apps": [{
                "app": "string",
                "duration": timedelta,
                "start": datetime,
                "end": datetime,
                "titles": [{
                    "title": "string",
                    "duration": timedelta,
                    "start": datetime,
                    "end": datetime,
                    "events": [Event, ...]
                }, ...]
            }, ...]
        }, ...]
        Returns empty list if no window events overlap the period.
    """
    if not window_events:
        return []

    categories = {}

    for window_event in window_events:
        window_start = window_event.timestamp
        window_end = window_event.timestamp + window_event.duration

        # Check if window event overlaps with the period
        if window_start < period_end and window_end > period_start:
            # Calculate overlap duration
            overlap_start = max(window_start, period_start)
            overlap_end = min(window_end, period_end)
            overlap_duration = overlap_end - overlap_start

            # Extract categories from this window event
            event_categories = window_event.data.get("$category", [])
            # Only process if there's actual categorization - don't create fake categories
            # for uncategorized window events

            for cat in event_categories:
                if cat not in categories:
                    categories[cat] = {
                        "category": cat,
                        "duration": timedelta(0),
                        "start": overlap_start,
                        "end": overlap_end,
                        "apps": {},
                    }
                else:
                    # Expand time window (don't accumulate duration here, do it from apps later)
                    cat_data = categories[cat]
                    if overlap_start < cat_data["start"]:
                        cat_data["start"] = overlap_start
                    if overlap_end > cat_data["end"]:
                        cat_data["end"] = overlap_end

                # Extract app name (window title) if available
                app_name = window_event.data.get("app", "Unknown")
                if app_name not in categories[cat]["apps"]:
                    categories[cat]["apps"][app_name] = {
                        "app": app_name,
                        "duration": timedelta(0),
                        "start": overlap_start,
                        "end": overlap_end,
                        "titles": {},
                    }
                else:
                    app_data = categories[cat]["apps"][app_name]
                    app_data["duration"] += overlap_duration
                    if overlap_start < app_data["start"]:
                        app_data["start"] = overlap_start
                    if overlap_end > app_data["end"]:
                        app_data["end"] = overlap_end

                # Extract title if available
                title = window_event.data.get("title", "Unknown")
                if title not in categories[cat]["apps"][app_name]["titles"]:
                    categories[cat]["apps"][app_name]["titles"][title] = {
                        "title": title,
                        "duration": overlap_duration,
                        "start": overlap_start,
                        "end": overlap_end,
                        "events": [window_event],
                    }
                else:
                    title_data = categories[cat]["apps"][app_name]["titles"][title]
                    title_data["duration"] += overlap_duration
                    if overlap_start < title_data["start"]:
                        title_data["start"] = overlap_start
                    if overlap_end > title_data["end"]:
                        title_data["end"] = overlap_end
                    if "events" not in title_data:
                        title_data["events"] = []
                    title_data["events"].append(window_event)

                categories[cat]["apps"][app_name]["duration"] += overlap_duration

    # Convert categories dict to list format for consistency with regular slots
    merged_categories = []
    for cat, cat_data in categories.items():
        # Compute category duration from sum of app durations (to avoid double-counting)
        cat_duration = sum(
            (app_data["duration"] for app_data in cat_data["apps"].values()),
            timedelta(0),
        )

        # Recalculate category start/end from app children's actual times
        cat_start = None
        cat_end = None
        for app_data in cat_data["apps"].values():
            app_start = app_data.get("start")
            app_end = app_data.get("end")
            if app_start and (cat_start is None or app_start < cat_start):
                cat_start = app_start
            if app_end and (cat_end is None or app_end > cat_end):
                cat_end = app_end

        cat_info = {
            "category": cat,
            "duration": cat_duration,
            "start": cat_start,
            "end": cat_end,
        }
        if cat_data["apps"]:
            # Build apps list with recalculated start/end from title children
            apps_list = []
            for app_name, app_data in cat_data["apps"].items():
                # Recalculate app start/end from title children's actual times
                app_start = None
                app_end = None
                for title_data in app_data.get("titles", {}).values():
                    title_start = title_data.get("start")
                    title_end = title_data.get("end")
                    if title_start and (app_start is None or title_start < app_start):
                        app_start = title_start
                    if title_end and (app_end is None or title_end > app_end):
                        app_end = title_end

                # If no titles, use the app's existing start/end
                if app_start is None:
                    app_start = app_data.get("start")
                if app_end is None:
                    app_end = app_data.get("end")

                app_info = {
                    "app": app_name,
                    "duration": app_data["duration"],
                    "start": app_start,
                    "end": app_end,
                    "titles": [
                        {
                            "title": t,
                            "duration": title_data["duration"],
                            "start": title_data.get("start"),
                            "end": title_data.get("end"),
                            "events": title_data.get("events", []),
                        }
                        for t, title_data in app_data["titles"].items()
                    ]
                    if app_data["titles"]
                    else [],
                }
                apps_list.append(app_info)

            cat_info["apps"] = apps_list
        merged_categories.append(cat_info)

    return merged_categories

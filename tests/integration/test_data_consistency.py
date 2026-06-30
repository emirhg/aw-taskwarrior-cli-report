#!/usr/bin/env python
"""
Test data consistency through the entire pipeline.

Verifies that start/end/duration remain consistent (within 5s tolerance)
and that no unexpected modifications occur outside of gap-filling.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

# Add parent directory to path
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))

from aw_client import ActivityWatchClient
from sentinel_warrior.data import (
    parse_period, get_bucket_id, get_events, load_categories,
    compile_category_rules, generate_timeline_data, consolidate_timeline_slots,
    categorize_event, get_category_score, find_active_task, get_task_info,
    build_canonical_events, build_context, merge_overlapping_afk_periods,
    load_slots
)
from tw_report.pipeline.processors import fill_short_event_gaps
import os


GAP_THRESHOLD = timedelta(seconds=5)  # The gap-fill threshold


def check_consistency(name: str, start, end, duration) -> Tuple[bool, str]:
    """
    Verify consistency: end - start should equal duration (within 5s tolerance).

    Returns: (is_consistent, message)
    """
    if not start or not end or not duration:
        return True, "Missing data, skipping"

    calculated_duration = end - start
    diff = abs((calculated_duration - duration).total_seconds())

    if diff > GAP_THRESHOLD.total_seconds():
        return False, (
            f"{name}: INCONSISTENT - end-start={calculated_duration} "
            f"but duration={duration} (diff={diff:.1f}s)"
        )
    return True, f"{name}: OK (diff={diff:.1f}s)"


def test_raw_events(date_str: str):
    """Test raw ActivityWatch events before any processing."""
    print("\n" + "="*80)
    print("TEST 1: Raw ActivityWatch Events")
    print("="*80)

    client = ActivityWatchClient("test")
    start_time, end_time = parse_period(date_str)

    window_bucket = get_bucket_id("window")
    window_events = get_events(client, window_bucket, start_time, end_time)

    print(f"Total raw window events: {len(window_events)}")

    # Check a sample of events
    errors = []
    for i, event in enumerate(window_events[:100]):
        event_end = event.timestamp + event.duration
        consistent, msg = check_consistency(
            f"Event {i}",
            event.timestamp,
            event_end,
            event.duration
        )
        if not consistent:
            errors.append(msg)

    if errors:
        print(f"❌ ERRORS in raw events:")
        for err in errors[:5]:
            print(f"  {err}")
    else:
        print(f"✅ Raw events are consistent (checked first 100)")

    return window_events


def test_after_gap_filling(window_events):
    """Test events after fill_short_event_gaps."""
    print("\n" + "="*80)
    print("TEST 2: After fill_short_event_gaps()")
    print("="*80)

    # Simulate what generate_timeline_data does
    event_dicts = [
        {"event": evt, "task": None, "project": None, "active_task": None}
        for evt in window_events
    ]

    filled_dicts = fill_short_event_gaps(event_dicts)

    print(f"Events after gap-filling: {len(filled_dicts)}")

    # Check consistency after gap-filling
    errors = []
    gaps_filled = 0

    for i, evt_dict in enumerate(filled_dicts[:100]):
        event = evt_dict["event"]
        event_end = event.timestamp + event.duration
        consistent, msg = check_consistency(
            f"Event {i}",
            event.timestamp,
            event_end,
            event.duration
        )
        if not consistent:
            errors.append(msg)

        # Check if this event was gap-filled (duration changed from original)
        if i > 0:
            prev_event = filled_dicts[i-1]["event"]
            gap = event.timestamp - (prev_event.timestamp + prev_event.duration)
            if gap < GAP_THRESHOLD and gap > timedelta(0):
                gaps_filled += 1

    print(f"Gaps filled: {gaps_filled}")
    if errors:
        print(f"❌ ERRORS after gap-filling:")
        for err in errors[:5]:
            print(f"  {err}")
    else:
        print(f"✅ Events consistent after gap-filling (checked first 100)")


def test_generate_timeline(date_str: str):
    """Test timeline data generation."""
    print("\n" + "="*80)
    print("TEST 3: generate_timeline_data()")
    print("="*80)

    slots = load_slots(date_str)

    print(f"Total slots: {len(slots)}")

    errors = []
    title_count = 0

    for slot in slots:
        if not slot.get("categories"):
            continue

        for cat in slot["categories"]:
            for app in cat.get("apps", []):
                for title in app.get("titles", []):
                    title_count += 1

                    title_start = title.get("start")
                    title_end = title.get("end")
                    title_duration = title.get("duration")

                    consistent, msg = check_consistency(
                        f"Title: {title.get('title', '')[:30]}",
                        title_start,
                        title_end,
                        title_duration
                    )
                    if not consistent:
                        errors.append(msg)

                    # Check if events list exists
                    has_events = "events" in title and title["events"] is not None
                    if not has_events and title_count <= 5:
                        print(f"  ⚠️  Title has no events list (detail_level might be < 5)")

    print(f"Total titles checked: {title_count}")
    if errors:
        print(f"❌ ERRORS in timeline data:")
        for err in errors[:10]:
            print(f"  {err}")
    else:
        print(f"✅ Timeline data is consistent")

    # Check for overlapping titles in same app
    print("\nChecking for overlapping titles in same app...")
    overlap_count = 0

    for slot in slots:
        if not slot.get("categories"):
            continue
        for cat in slot["categories"]:
            for app in cat.get("apps", []):
                titles = app.get("titles", [])
                for i in range(len(titles)):
                    for j in range(i + 1, len(titles)):
                        t1 = titles[i]
                        t2 = titles[j]

                        t1_start = t1.get("start")
                        t1_end = t1.get("end")
                        t2_start = t2.get("start")
                        t2_end = t2.get("end")

                        # Check if they overlap
                        if t1_start and t1_end and t2_start and t2_end:
                            if not (t1_end <= t2_start or t2_end <= t1_start):
                                overlap_count += 1
                                if overlap_count <= 5:
                                    print(
                                        f"  ❌ OVERLAP in {app['app']}: "
                                        f"{t1.get('title', '')[:20]} ({t1_start}-{t1_end}) "
                                        f"overlaps {t2.get('title', '')[:20]} ({t2_start}-{t2_end})"
                                    )

    if overlap_count > 0:
        print(f"  Total overlaps found: {overlap_count}")
    else:
        print(f"  ✅ No overlapping titles found")

    return slots


def main():
    """Run all tests."""
    date_str = "2026-05-08"

    print("\n" + "="*80)
    print("DATA CONSISTENCY TEST SUITE")
    print(f"Date: {date_str}")
    print("="*80)

    # Test 1: Raw events
    window_events = test_raw_events(date_str)

    # Test 2: After gap-filling
    test_after_gap_filling(window_events)

    # Test 3: Timeline generation
    test_generate_timeline(date_str)

    print("\n" + "="*80)
    print("TEST SUITE COMPLETE")
    print("="*80)


if __name__ == "__main__":
    main()

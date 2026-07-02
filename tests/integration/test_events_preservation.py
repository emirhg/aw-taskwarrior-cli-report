#!/usr/bin/env python
"""
Test where the events list is being lost in the pipeline.

REQUIRES: Running ActivityWatch server on localhost:5600
"""

import sys
import os
from pathlib import Path

import pytest

repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))

from sentinel_warrior.data import (
    parse_period, get_bucket_id, get_events, load_categories,
    compile_category_rules, generate_timeline_data, consolidate_timeline_slots,
    categorize_event, get_category_score, find_active_task, get_task_info,
    build_canonical_events, build_context, merge_overlapping_afk_periods,
    generate_gap_entries
)
from aw_client import ActivityWatchClient


@pytest.mark.live_server
def test_events_preservation(date_str: str):
    """Trace events list through each pipeline stage."""
    print("\n" + "="*80)
    print("EVENTS LIST PRESERVATION TEST")
    print("="*80)

    client = ActivityWatchClient("sentinel-warrior")
    start_time, end_time = parse_period(date_str)

    window_bucket = get_bucket_id("window")
    afk_bucket = get_bucket_id("afk")
    taskwarrior_bucket = get_bucket_id("taskwarrior")

    window_events = get_events(client, window_bucket, start_time, end_time)
    afk_events = get_events(client, afk_bucket, start_time, end_time)
    task_events = get_events(client, taskwarrior_bucket, start_time, end_time)

    if not task_events:
        task_events = None

    categories_file = os.path.expanduser("~/.config/activitywatch/aw-server/settings.json")
    categories_json = load_categories(categories_file)
    compiled_categories, cat_score_map = compile_category_rules(categories_json)

    if afk_events:
        afk_events = merge_overlapping_afk_periods(afk_events)

    class Args:
        search = None
        project = None
        task = None
        app = None
        exact = False
        exclude_project = None
        exclude_task = None
        exclude_app = None
        exclude_non_productive = False
        exclude_non_project = False
        min_score = float('-inf')
        max_score = float('inf')
        min_duration = 0

    args = Args()

    canonical_events = build_canonical_events(
        window_events=window_events,
        not_afk_events=afk_events,
        include_afk=False,
        task_events=task_events,
        args=args,
        no_project_label="No project assigned",
        no_task_label="No task assigned",
        categorize_event=categorize_event,
        compiled_categories=compiled_categories,
        get_category_score=get_category_score,
        cat_score_map=cat_score_map,
        find_active_task=find_active_task,
        get_task_info=get_task_info,
        matches_any=lambda *_: True,
        excluded=lambda *_: False,
    )

    context = build_context(
        canonical_events=canonical_events,
        task_events=task_events,
        afk_events=afk_events,
        cat_score_map=cat_score_map,
        is_task_based_report=(task_events is not None),
        metrics=None,
    )

    timeline_events = [
        {
            "event": rep.event,
            "active_task": rep.active_task,
            "task": rep.task,
            "project": rep.project,
        }
        for rep in context.canonical_events
    ]

    # STAGE 1: After generate_timeline_data
    print("\n1. After generate_timeline_data(detail_level=5):")
    slots_1 = generate_timeline_data(
        timeline_events,
        context.afk_events,
        cat_score_map=cat_score_map,
        detail_level=5,
    )

    titles_with_events_1 = 0
    titles_without_events_1 = 0
    for slot in slots_1:
        if 'categories' in slot:
            for cat in slot['categories']:
                for app in cat.get('apps', []):
                    for title in app.get('titles', []):
                        if 'events' in title and title['events']:
                            titles_with_events_1 += 1
                        else:
                            titles_without_events_1 += 1

    print(f"   Titles WITH events: {titles_with_events_1}")
    print(f"   Titles WITHOUT events: {titles_without_events_1}")

    # STAGE 2: After generate_gap_entries
    print("\n2. After generate_gap_entries():")
    gap_entries = generate_gap_entries(context.afk_events, context.task_events, window_events=window_events)
    slots_2 = sorted(slots_1 + gap_entries, key=lambda s: s["start"])

    titles_with_events_2 = 0
    titles_without_events_2 = 0
    for slot in slots_2:
        if 'categories' in slot:
            for cat in slot['categories']:
                for app in cat.get('apps', []):
                    for title in app.get('titles', []):
                        if 'events' in title and title['events']:
                            titles_with_events_2 += 1
                        else:
                            titles_without_events_2 += 1

    print(f"   Titles WITH events: {titles_with_events_2}")
    print(f"   Titles WITHOUT events: {titles_without_events_2}")

    # STAGE 3: After consolidate_timeline_slots
    print("\n4. After consolidate_timeline_slots():")
    slots_4 = consolidate_timeline_slots(slots_2, ignore_offline=False)

    titles_with_events_4 = 0
    titles_without_events_4 = 0
    for slot in slots_4:
        if 'categories' in slot:
            for cat in slot['categories']:
                for app in cat.get('apps', []):
                    for title in app.get('titles', []):
                        if 'events' in title and title['events']:
                            titles_with_events_4 += 1
                        else:
                            titles_without_events_4 += 1

    print(f"   Titles WITH events: {titles_with_events_4}")
    print(f"   Titles WITHOUT events: {titles_without_events_4}")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY:")
    print("="*80)
    if titles_with_events_4 == 0:
        print("❌ PROBLEM: Events list is being lost!")
        print(f"   Stage 1: {titles_with_events_1} with events")
        print(f"   Stage 4: {titles_with_events_4} with events")
        print("\n   This prevents centinel from using accurate time calculations.")
    else:
        print(f"✅ Events list preserved: {titles_with_events_4} titles have events")


if __name__ == "__main__":
    test_events_preservation("2026-05-08")

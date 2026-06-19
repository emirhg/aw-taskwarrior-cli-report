#!/usr/bin/env python
"""
Identify exactly where overlapping titles are being created in the pipeline.
"""

import sys
import os
from pathlib import Path

repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))

from sentinel_warrior.data import (
    parse_period, get_bucket_id, get_events, load_categories,
    compile_category_rules, generate_timeline_data, consolidate_timeline_slots,
    categorize_event, get_category_score, find_active_task, get_task_info,
    build_canonical_events, build_context, merge_overlapping_afk_periods,
)
from aw_client import ActivityWatchClient


def check_overlaps_in_list(titles_list, stage_name):
    """Check for overlaps in a list of titles."""
    overlaps = []

    for i in range(len(titles_list)):
        for j in range(i + 1, len(titles_list)):
            t1 = titles_list[i]
            t2 = titles_list[j]

            t1_start = t1.get("start")
            t1_end = t1.get("end")
            t2_start = t2.get("start")
            t2_end = t2.get("end")

            if t1_start and t1_end and t2_start and t2_end:
                # Check if they overlap
                if not (t1_end <= t2_start or t2_end <= t1_start):
                    overlaps.append({
                        'title1': t1.get('title', '')[:30],
                        'title1_range': f"{t1_start} - {t1_end}",
                        'title2': t2.get('title', '')[:30],
                        'title2_range': f"{t2_start} - {t2_end}",
                    })

    return overlaps


def test_where_overlaps_come_from():
    """Trace overlaps from raw events through the pipeline."""

    print("\n" + "="*80)
    print("OVERLAP SOURCE DETECTION")
    print("="*80)

    client = ActivityWatchClient("sentinel-warrior")
    date_str = "2026-05-08"
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

    # Check STAGE 0: Raw window events
    print("\nSTAGE 0: Raw ActivityWatch window events")
    print("-" * 80)
    brave_events = [e for e in window_events if 'brave' in e.data.get('app', '').lower()]
    print(f"Total window events: {len(window_events)}")
    print(f"Brave-browser events: {len(brave_events)}")

    # Group by title to see if there are actual concurrent events
    titles_to_events = {}
    for evt in brave_events:
        title = evt.data.get('title', 'Unknown')
        if title not in titles_to_events:
            titles_to_events[title] = []
        titles_to_events[title].append({
            'start': evt.timestamp,
            'end': evt.timestamp + evt.duration
        })

    print(f"\nUnique Brave titles: {len(titles_to_events)}")

    # Check for overlaps in raw events
    raw_overlaps = 0
    for title, events in titles_to_events.items():
        for i in range(len(events)):
            for j in range(i + 1, len(events)):
                evt1 = events[i]
                evt2 = events[j]
                if not (evt1['end'] <= evt2['start'] or evt2['end'] <= evt1['start']):
                    raw_overlaps += 1

    print(f"Overlapping raw events FOR SAME TITLE: {raw_overlaps}")

    # Check for overlaps between different titles in raw data
    different_title_overlaps = 0
    brave_titles = list(titles_to_events.items())
    for i in range(len(brave_titles)):
        for j in range(i + 1, len(brave_titles)):
            title1, events1 = brave_titles[i]
            title2, events2 = brave_titles[j]
            for evt1 in events1:
                for evt2 in events2:
                    if not (evt1['end'] <= evt2['start'] or evt2['end'] <= evt1['start']):
                        different_title_overlaps += 1
                        break
                if different_title_overlaps > 0:
                    break

    print(f"Different titles with overlapping raw events: {different_title_overlaps}")

    # Now process through pipeline
    print("\n" + "-" * 80)
    print("STAGE 1: After generate_timeline_data()")
    print("-" * 80)

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

    slots = generate_timeline_data(
        timeline_events,
        context.afk_events,
        cat_score_map=cat_score_map,
        detail_level=5,
    )

    # Check overlaps in generate_timeline_data output
    timeline_overlaps = 0
    for slot in slots:
        if 'categories' in slot:
            for cat in slot['categories']:
                for app in cat.get('apps', []):
                    if 'brave' in app.get('app', '').lower():
                        titles = app.get('titles', [])
                        overlaps = check_overlaps_in_list(titles, "timeline_data")
                        timeline_overlaps += len(overlaps)

                        if overlaps:
                            print(f"\nBrave-browser in slot {slot['start']}:")
                            print(f"  {len(titles)} titles, {len(overlaps)} overlaps")
                            for ov in overlaps[:2]:
                                print(f"    {ov['title1']:30} {ov['title1_range']}")
                                print(f"    {ov['title2']:30} {ov['title2_range']}")

    print(f"\nTotal overlaps in timeline_data: {timeline_overlaps}")

    # STAGE 2: After consolidation
    print("\n" + "-" * 80)
    print("STAGE 2: After consolidate_timeline_slots()")
    print("-" * 80)

    slots_consolidated = consolidate_timeline_slots(slots, ignore_offline=False)

    consolidated_overlaps = 0
    for slot in slots_consolidated:
        if 'categories' in slot:
            for cat in slot['categories']:
                for app in cat.get('apps', []):
                    if 'brave' in app.get('app', '').lower():
                        titles = app.get('titles', [])
                        overlaps = check_overlaps_in_list(titles, "consolidated")
                        consolidated_overlaps += len(overlaps)

    print(f"Total overlaps after consolidation: {consolidated_overlaps}")

    # Summary
    print("\n" + "="*80)
    print("FINDINGS:")
    print("="*80)
    print(f"Raw events with overlapping titles: {different_title_overlaps}")
    print(f"Overlaps in timeline_data: {timeline_overlaps}")
    print(f"Overlaps after consolidation: {consolidated_overlaps}")

    if different_title_overlaps == 0 and timeline_overlaps > 0:
        print("\n❌ PROBLEM: Overlaps are being CREATED by generate_timeline_data!")
    elif different_title_overlaps > 0 and timeline_overlaps == different_title_overlaps:
        print("\n✅ Overlaps are from raw ActivityWatch data (not a pipeline bug)")
    else:
        print("\n⚠️ Overlaps state is unclear - investigate further")


if __name__ == "__main__":
    test_where_overlaps_come_from()

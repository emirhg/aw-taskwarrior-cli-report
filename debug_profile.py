#!/usr/bin/env python3
"""
Debug profiler for tw-report execution.

Instruments the main flow to show timing and bottlenecks stage-by-stage.

Usage:
    python debug_profile.py --task-id 48 :all --timesheet --consolidate
"""

import sys
import time
from datetime import datetime
import logging

# Setup detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s] %(name)s: %(message)s'
)

class Stage:
    """Context manager to time a stage."""
    def __init__(self, name, show_count=False):
        self.name = name
        self.show_count = show_count
        self.start = None
        self.result = None

    def __enter__(self):
        self.start = time.perf_counter()
        print(f"\n⏱️  {self.name}...", flush=True)
        return self

    def __exit__(self, *args):
        elapsed = time.perf_counter() - self.start
        msg = f"✓ {self.name}: {elapsed*1000:.1f}ms"
        if self.show_count and self.result is not None:
            if isinstance(self.result, (list, tuple)):
                msg += f" ({len(self.result)} items)"
            elif isinstance(self.result, dict):
                msg += f" ({len(self.result)} keys)"
        print(msg, flush=True)

def main():
    """Profile tw-report execution."""

    print("\n" + "="*60)
    print("TW-REPORT EXECUTION PROFILE")
    print("="*60)

    # Parse arguments
    with Stage("1. Parse command-line arguments") as s1:
        from tw_report.cli.args import parse_args, parse_positional_args
        args = parse_args()
        period, search_term = parse_positional_args(args.args)
        args.search = search_term
        s1.result = args
        print(f"   Period: {period}, Search: {search_term}")
        print(f"   Task ID: {getattr(args, 'task_id', None)}")
        print(f"   Timesheet: {args.timesheet}, Consolidate: {args.consolidate}")

    # UUID lookup (if --task-id)
    task_uuid = None
    if getattr(args, 'task_id', None):
        with Stage("2. Lookup TaskWarrior task UUID", show_count=False) as s2:
            from tw_report.core.task_uuid_filtering import get_task_uuid
            task_uuid = get_task_uuid(args.task_id)
            if not task_uuid:
                print(f"   ❌ Task {args.task_id} not found")
                return 1
            s2.result = task_uuid
            print(f"   UUID: {task_uuid[:8]}...")

    # Parse period
    with Stage("3. Parse time period") as s3:
        from tw_report.core.period import parse_period
        start_time, end_time = parse_period(period)
        s3.result = (start_time, end_time)
        print(f"   Range: {start_time} to {end_time}")
        print(f"   Duration: {(end_time - start_time).total_seconds() / 86400:.1f} days")

    # Load categories
    with Stage("4. Load category rules") as s4:
        from tw_report.core.categories import load_categories, compile_category_rules
        categories_json = load_categories(args.categories)
        compiled_categories, cat_score_map = compile_category_rules(categories_json)
        s4.result = compiled_categories
        print(f"   Loaded {len(compiled_categories)} category rules")

    # Create ActivityWatch client
    with Stage("5. Initialize ActivityWatch client") as s5:
        from aw_client import ActivityWatchClient
        client = ActivityWatchClient("tw-report-debug")
        s5.result = client

    # Fetch window bucket
    window_events = []
    if not task_uuid:
        with Stage("6. Fetch window bucket events", show_count=True) as s6:
            from tw_report.core.events import get_bucket_id, get_events
            window_bucket = get_bucket_id("window")
            window_events = get_events(client, window_bucket, start_time, end_time)
            s6.result = window_events
            print(f"   Bucket: {window_bucket}")
    else:
        print(f"\n⏭️  6. Skipping window bucket (--task-id specified)")

    # Categorize events
    if window_events:
        with Stage("7. Categorize window events", show_count=False) as s7:
            from tw_report.core.categories import categorize_event
            for event in window_events:
                categorize_event(event, compiled_categories)
            print(f"   Categorized {len(window_events)} events")
    else:
        print(f"\n⏭️  7. Skipping categorization (no window events)")

    # Fetch AFK bucket
    afk_events = []
    if not task_uuid:
        with Stage("8. Fetch AFK bucket events", show_count=True) as s8:
            from tw_report.core.events import get_bucket_id, get_events
            afk_bucket = get_bucket_id("afk")
            afk_events = get_events(client, afk_bucket, start_time, end_time)
            s8.result = afk_events
            print(f"   Bucket: {afk_bucket}")
    else:
        print(f"\n⏭️  8. Skipping AFK bucket (--task-id specified)")

    # Fetch TaskWarrior bucket
    with Stage("9. Fetch TaskWarrior bucket events", show_count=True) as s9:
        from tw_report.core.events import get_bucket_id
        from tw_report.core.task_uuid_filtering import get_events_by_uuid
        tw_bucket = get_bucket_id("taskwarrior")
        task_events = get_events_by_uuid(client, tw_bucket, start_time, end_time, task_uuid)
        s9.result = task_events
        print(f"   Bucket: {tw_bucket}")
        if task_uuid:
            print(f"   Filtered by UUID: {task_uuid[:8]}...")

    # Merge overlapping AFK periods
    if afk_events:
        with Stage("10. Merge overlapping AFK periods", show_count=False) as s10:
            from tw_report.pipeline.processors import merge_overlapping_afk_periods
            afk_events = merge_overlapping_afk_periods(afk_events)
            print(f"   Merged to {len(afk_events)} AFK events")
    else:
        print(f"\n⏭️  10. Skipping AFK merge (no AFK events)")

    # Calculate metrics
    with Stage("11. Calculate basic metrics (non-AFK time, session times)") as s11:
        from aw_transform import filter_keyvals
        from datetime import timedelta
        not_afk_events = filter_keyvals(afk_events, "status", ["not-afk"])
        non_afk_time = sum((event.duration for event in not_afk_events), timedelta(0))
        print(f"   Non-AFK events: {len(not_afk_events)}")
        print(f"   Non-AFK time: {non_afk_time.total_seconds()/3600:.1f} hours")

    # Build canonical events
    with Stage("12. Build canonical events (correlate window→tasks)", show_count=True) as s12:
        from tw_report.pipeline.processors import build_canonical_events
        from tw_report.core.filtering import NO_PROJECT, NO_TASK
        from tw_report.core.categories import get_category_score
        from tw_report.core.task_matching import find_active_task, get_task_info

        canonical_events = build_canonical_events(
            window_events=window_events,
            not_afk_events=not_afk_events,
            include_afk=args.include_afk,
            task_events=task_events if task_events else None,
            args=args,
            no_project_label=NO_PROJECT,
            no_task_label=NO_TASK,
            categorize_event=lambda *a, **k: None,  # Already done
            compiled_categories=compiled_categories,
            get_category_score=get_category_score,
            cat_score_map=cat_score_map,
            find_active_task=find_active_task,
            get_task_info=get_task_info,
            matches_any=lambda *a, **k: True,
            excluded=lambda *a, **k: False,
        )
        s12.result = canonical_events
        print(f"   Built {len(canonical_events)} canonical events")

    # Process OFFLINE tasks
    with Stage("13. Process OFFLINE tasks", show_count=False) as s13:
        from tw_report.core.offline import OfflineTaskProcessor
        offline_processor = None
        if task_events:
            offline_processor = OfflineTaskProcessor(
                task_events=task_events,
                window_events=window_events,
                afk_events=afk_events,
                event_filter=None,  # Skip for debug
                end_time=end_time,
            )
            offline_task_durations, offline_event_durations, offline_event_groups, offline_task_real_durations = offline_processor.process()
            print(f"   Found {len(offline_task_durations)} OFFLINE tasks")
        else:
            print(f"   Skipped (no task events)")

    # Generate timeline data
    with Stage("14. Generate timeline data", show_count=True) as s14:
        from tw_report.pipeline.generation import generate_timeline_data
        timeline_data = generate_timeline_data(
            canonical_events=canonical_events,
            afk_events=afk_events,
            args=args,
        )
        s14.result = timeline_data
        print(f"   Generated {len(timeline_data)} timeline slots")

    # Apply consolidation (if --consolidate)
    if args.consolidate:
        with Stage("15. Consolidate timeline slots (merge consecutive sessions)", show_count=True) as s15:
            from tw_report.core.consolidation import TimelineSlotManager
            manager = TimelineSlotManager(timeline_data)
            timeline_data = manager.consolidate()
            s15.result = timeline_data
            print(f"   Consolidated to {len(timeline_data)} slots")
    else:
        print(f"\n⏭️  15. Skipping consolidation (--consolidate not specified)")

    # Compute metrics
    with Stage("16. Compute report metrics (AFK time, productivity %, focus time)", show_count=False) as s16:
        from tw_report.pipeline.processors import compute_metrics
        metrics = compute_metrics(
            timeline_data=timeline_data,
            afk_events=afk_events,
        )
        print(f"   AFK time: {metrics.get('total_afk_time', '?')}")
        print(f"   Productivity: {metrics.get('productivity_percentage', '?')}%")

    # Render report
    with Stage("17. Render timesheet report", show_count=False) as s17:
        from tw_report.pipeline.timeline_render import print_timeline_report
        print(f"   Formatting {len(timeline_data)} slots for display...")
        # Don't actually print to avoid clutter

    print("\n" + "="*60)
    print("PROFILE COMPLETE")
    print("="*60)
    print("\n📊 Summary:")
    print(f"   Total stages: 17")
    print(f"   Bottlenecks to check:")
    print(f"   - Stage 9 (TaskWarrior bucket fetch): Network roundtrip")
    print(f"   - Stage 12 (Canonical events): Window→task correlation")
    print(f"   - Stage 14 (Timeline generation): Data transformation")
    print(f"   - Stage 15 (Consolidation): Merging logic (if large dataset)")
    print()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

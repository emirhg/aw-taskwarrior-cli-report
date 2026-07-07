#!/usr/bin/env python3
"""
Full pipeline debug for --task-id mode.

Shows exactly where events are being lost.
"""

import sys
import json
import subprocess
from datetime import datetime
from aw_client import ActivityWatchClient
import platform

# Patch sys.argv for parse_args
sys.argv = ["tw-report", "--task-id", "48", ":month", "--timesheet"]

from tw_report.cli.args import parse_args, parse_positional_args
from tw_report.core.period import parse_period
from tw_report.core.events import get_bucket_id, get_events
from tw_report.core.task_uuid_filtering import get_task_uuid, get_events_by_uuid
from tw_report.core.task_matching import get_task_info
from tw_report.pipeline.models import ReportEvent
from tw_report.pipeline.generation import generate_timeline_data
from tw_report.core.consolidation import TimelineSlotManager

print("\n" + "="*80)
print("FULL PIPELINE DEBUG - Task 48 :month")
print("="*80)

# Step 1: Parse args
args = parse_args()
period, search_term = parse_positional_args(args.args)
args.search = search_term

print(f"\n✓ Step 1: Parsed args")
print(f"  - task_id: {args.task_id}")
print(f"  - period: {period}")
print(f"  - timesheet: {args.timesheet}")
print(f"  - consolidate: {args.consolidate}")

# Step 2: Get UUID
task_uuid = get_task_uuid(args.task_id)
print(f"\n✓ Step 2: Got UUID from taskwarrior")
print(f"  - UUID: {task_uuid[:8]}...")

# Step 3: Parse period
start_time, end_time = parse_period(period)
print(f"\n✓ Step 3: Parsed period")
print(f"  - Start: {start_time}")
print(f"  - End: {end_time}")

# Step 4: Get AW client
client = ActivityWatchClient("tw-report-debug")
print(f"\n✓ Step 4: Created AW client")

# Step 5: Fetch taskwarrior events
tw_bucket = get_bucket_id("taskwarrior")
task_events = get_events_by_uuid(client, tw_bucket, start_time, end_time, task_uuid)
print(f"\n✓ Step 5: Fetched taskwarrior events")
print(f"  - Bucket: {tw_bucket}")
print(f"  - Events found: {len(task_events)}")

if task_events:
    for i, e in enumerate(task_events[:5]):  # Show first 5
        print(f"    {i+1}. {e.timestamp.date()} {e.timestamp.time()} - {e.duration} - {e.data.get('title', 'N/A')}")
    if len(task_events) > 5:
        print(f"    ... and {len(task_events) - 5} more")

# Step 6: Build canonical events (TASK-ONLY MODE)
print(f"\n✓ Step 6: Build canonical events (task-only mode)")
canonical_events = []
if task_uuid and task_events:
    for task_event in task_events:
        task_name, project = get_task_info(task_event)
        canonical_events.append(
            ReportEvent(
                event=task_event,
                project=project,
                task=task_name,
                active_task=task_event,
            )
        )
print(f"  - Canonical events created: {len(canonical_events)}")

if canonical_events:
    for i, rep in enumerate(canonical_events[:5]):
        print(f"    {i+1}. {rep.event.timestamp.date()} - {rep.project} / {rep.task}")

# Step 7: Generate timeline data
print(f"\n✓ Step 7: Generate timeline data")

# Build timeline_events format
timeline_events = [
    {
        "event": rep.event,
        "project": rep.project,
        "task": rep.task,
        "active_task": rep.active_task,
    }
    for rep in canonical_events
]

timeline_data = generate_timeline_data(
    timeline_events,
    afk_events=[],
    cat_score_map={},
    detail_level=2,
    deduplicate_categories=False,
)

print(f"  - Timeline slots generated: {len(timeline_data)}")
if timeline_data:
    for i, slot in enumerate(timeline_data[:5]):
        print(f"    {i+1}. {slot.get('start')} to {slot.get('end')} - {slot.get('task')}")

# Step 8: Consolidate (if requested)
if args.consolidate:
    print(f"\n✓ Step 8: Consolidate timeline slots")
    manager = TimelineSlotManager(timeline_data)
    consolidated = manager.consolidate()
    print(f"  - Before consolidation: {len(timeline_data)}")
    print(f"  - After consolidation: {len(consolidated)}")
    timeline_data = consolidated
else:
    print(f"\n⏭️  Step 8: Skipping consolidation (--consolidate not set)")

# Step 9: Check for empty report
print(f"\n{'='*80}")
if not timeline_data:
    print("❌ EMPTY TIMELINE DATA")
    print(f"\nDEBUG INFO:")
    print(f"  - task_uuid: {task_uuid}")
    print(f"  - task_events fetched: {len(task_events)}")
    print(f"  - canonical_events created: {len(canonical_events)}")
    print(f"  - timeline_data generated: {len(timeline_data)}")

    print(f"\nPossible causes:")
    if not task_events:
        print(f"  1. No taskwarrior events in bucket for UUID")
    elif not canonical_events:
        print(f"  1. Failed to create canonical events from task events")
    else:
        print(f"  1. generate_timeline_data returned empty list")
        print(f"     (check event format or filtering)")
else:
    print(f"✓ TIMELINE DATA GENERATED ({len(timeline_data)} slots)")
    print(f"\nFirst 3 slots:")
    for i, slot in enumerate(timeline_data[:3]):
        print(f"  {i+1}. {slot.get('start')} → {slot.get('end')}")
        print(f"     Task: {slot.get('task')}")
        print(f"     Project: {slot.get('project')}")

print(f"\n{'='*80}\n")

#!/usr/bin/env python3
"""Debug script to find duplicate task events."""

import logging

# Configure logging to see all debug messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s:%(name)s:%(message)s'
)

from aw_client import ActivityWatchClient
from tw_report.core.period import parse_period
from tw_report.core.project_filtering import get_events_by_project

# Setup
client = ActivityWatchClient("tw-report")
task_bucket = "aw-watcher-taskwarrior_HerreraMonroy"

# Parse :today period first (faster for diagnosis)
# User can run with :all later if needed
start_time, end_time = parse_period(":today")
print(f"Period: {start_time} to {end_time}")
print("(Using :today for quick diagnosis - user can modify to :all if needed)")

# Fetch Higuera events (same as user's command)
print("\nFetching events for project 'Higuera'...")
task_events = get_events_by_project(client, task_bucket, start_time, end_time, "Higuera")
print(f"Total events fetched: {len(task_events)}")

# Check for duplicates
print("\nChecking for exact duplicate events...")
event_signatures = {}  # (timestamp, duration, task_name) -> count
for event in task_events:
    sig = (event.timestamp, event.duration, event.task)
    event_signatures[sig] = event_signatures.get(sig, 0) + 1

duplicates = {sig: count for sig, count in event_signatures.items() if count > 1}
if duplicates:
    print(f"Found {len(duplicates)} sets of duplicate events:")
    for (ts, dur, task), count in list(duplicates.items())[:5]:  # Show first 5
        print(f"  {ts}: {task} (duration {dur}) appears {count} times")
else:
    print("No exact duplicates found.")

# Check for overlapping events (same task, same timestamp, different UUIDs)
print("\nChecking for overlapping events (same name/time, different UUIDs)...")
by_time_and_name = {}  # (timestamp, task_name) -> [events]
for event in task_events:
    key = (event.timestamp, event.task)
    if key not in by_time_and_name:
        by_time_and_name[key] = []
    by_time_and_name[key].append(event)

overlapping = {k: v for k, v in by_time_and_name.items() if len(v) > 1}
if overlapping:
    print(f"Found {len(overlapping)} overlapping event sets:")
    for (ts, task), events in list(overlapping.items())[:5]:  # Show first 5
        print(f"\n  {ts}: '{task}'")
        for e in events:
            print(f"    UUID: {e.uuid}, Duration: {e.duration}")
else:
    print("No overlapping events found.")

print("\n✓ Debug complete. Check the logs above for 'Multiple task events' warnings.")

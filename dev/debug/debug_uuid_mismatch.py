#!/usr/bin/env python3
"""
Debug UUID mismatch between TaskWarrior export and ActivityWatch bucket.

Usage:
    python debug_uuid_mismatch.py 48
"""

import sys
import json
import subprocess
from datetime import datetime, timedelta
from aw_client import ActivityWatchClient

def get_taskwarrior_uuid(task_id):
    """Get UUID from taskwarrior export."""
    try:
        result = subprocess.run(
            ["task", str(task_id), "export"],
            capture_output=True,
            text=True,
            check=True,
        )
        tasks = json.loads(result.stdout)
        if tasks:
            return tasks[0].get("uuid")
    except Exception as e:
        print(f"Error exporting task: {e}")
    return None

def get_bucket_events(client, bucket_id, start, end):
    """Get events from bucket."""
    try:
        events = client.get_events(bucket_id, start=start, end=end, limit=-1)
        return events
    except Exception as e:
        print(f"Error fetching bucket: {e}")
        return []

def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_uuid_mismatch.py <task_id>")
        sys.exit(1)

    task_id = int(sys.argv[1])

    print("\n" + "="*70)
    print(f"UUID MISMATCH DEBUG - Task {task_id}")
    print("="*70)

    # Step 1: Get UUID from taskwarrior
    print(f"\n1️⃣  Getting UUID from taskwarrior export...")
    tw_uuid = get_taskwarrior_uuid(task_id)
    if tw_uuid:
        print(f"   ✓ TaskWarrior UUID: {tw_uuid}")
    else:
        print(f"   ✗ Could not get UUID from taskwarrior")
        return 1

    # Step 2: Connect to ActivityWatch
    print(f"\n2️⃣  Connecting to ActivityWatch...")
    try:
        client = ActivityWatchClient("debug-uuid-mismatch")
        print(f"   ✓ Connected")
    except Exception as e:
        print(f"   ✗ Connection failed: {e}")
        return 1

    # Step 3: Get taskwarrior bucket events
    print(f"\n3️⃣  Fetching ALL taskwarrior bucket events (last 90 days)...")
    import platform
    hostname = platform.node()
    tw_bucket = f"aw-watcher-taskwarrior_{hostname}"

    start = datetime.now() - timedelta(days=90)
    end = datetime.now()

    tw_events = get_bucket_events(client, tw_bucket, start, end)
    print(f"   Found {len(tw_events)} events in taskwarrior bucket")

    # Step 4: Analyze UUIDs in bucket
    print(f"\n4️⃣  Analyzing UUIDs in bucket...")
    uuids_in_bucket = {}
    for event in tw_events:
        uuid = event.data.get("uuid")
        if uuid:
            uuids_in_bucket[uuid] = uuids_in_bucket.get(uuid, 0) + 1

    print(f"   Unique UUIDs in bucket: {len(uuids_in_bucket)}")

    # Show all UUIDs
    if uuids_in_bucket:
        print(f"\n   All UUIDs in bucket:")
        for uuid, count in sorted(uuids_in_bucket.items(), key=lambda x: -x[1]):
            match = "✓ MATCHES" if uuid == tw_uuid else "✗ different"
            print(f"   - {uuid}: {count} events {match}")
    else:
        print(f"   ✗ No UUID field found in any event!")
        if tw_events:
            print(f"\n   First event data: {tw_events[0].data}")

    # Step 5: Check if taskwarrior UUID is in bucket
    print(f"\n5️⃣  Checking for TaskWarrior UUID in bucket...")
    if tw_uuid in uuids_in_bucket:
        count = uuids_in_bucket[tw_uuid]
        print(f"   ✓ Found {count} events with UUID {tw_uuid}")
    else:
        print(f"   ✗ UUID {tw_uuid} NOT found in bucket!")
        print(f"\n   PROBLEM: TaskWarrior export shows this UUID,")
        print(f"            but ActivityWatch bucket has different UUIDs")
        print(f"\n   Possible causes:")
        print(f"   1. ActivityWatch events are stale (from before UUID changed)")
        print(f"   2. Task UUID was modified in TaskWarrior")
        print(f"   3. Different taskwarrior instance/config")

    # Step 6: Show task info
    print(f"\n6️⃣  TaskWarrior task {task_id} details:")
    try:
        result = subprocess.run(
            ["task", str(task_id), "export"],
            capture_output=True,
            text=True,
            check=True,
        )
        task = json.loads(result.stdout)[0]
        print(f"   Title: {task.get('description', 'N/A')}")
        print(f"   Project: {task.get('project', 'N/A')}")
        print(f"   UUID: {task.get('uuid', 'N/A')}")
        print(f"   Status: {task.get('status', 'N/A')}")
    except Exception as e:
        print(f"   Error: {e}")

    print("\n" + "="*70)

if __name__ == "__main__":
    main()

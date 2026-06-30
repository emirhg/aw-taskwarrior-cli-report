#!/usr/bin/env python3
"""
TEST: Chronological Consistency - Tree represents pure timeline

Requirement: Both projects and categories trees represent a timeline.
When flattened to leaves, each leaf must:
1. Have a unique time window (start, end)
2. Follow the previous leaf chronologically
3. Never overlap with any other leaf
4. Create a continuous non-overlapping timeline

This ensures no artificial overlaps from incorrect grouping.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))

from sentinel_warrior.data import load_slots


def flatten_leaves(slots):
    """Extract all leaf nodes from tree structure with their time ranges."""
    leaves = []

    for slot in slots:
        for cat in slot.get("categories", []):
            for app in cat.get("apps", []):
                for title_info in app.get("titles", []):
                    events = title_info.get("events", [])
                    if events:
                        # Each event is a leaf node
                        for event in events:
                            start = event.get("start")
                            end = event.get("end")
                            if start and end:
                                leaves.append({
                                    "category": cat.get("category"),
                                    "app": app.get("app"),
                                    "title": title_info.get("title", "unknown"),
                                    "start": start,
                                    "end": end,
                                })

    return leaves


def test_no_overlaps():
    """Verify no leaf nodes overlap in time."""
    date_str = "2026-05-09"
    slots = load_slots(date_str)

    leaves = flatten_leaves(slots)

    if not leaves:
        raise AssertionError("❌ No leaf nodes found")

    # Sort by start time
    leaves.sort(key=lambda l: l["start"])

    overlaps = []
    for i in range(len(leaves) - 1):
        current = leaves[i]
        next_leaf = leaves[i + 1]

        # Check if current leaf ends after next leaf starts
        if current["end"] > next_leaf["start"]:
            overlaps.append({
                "leaf_1": f"{current['title']} ({current['start']} - {current['end']})",
                "leaf_2": f"{next_leaf['title']} ({next_leaf['start']} - {next_leaf['end']})",
                "overlap": f"{next_leaf['start']} to {current['end']}",
            })

    assert len(overlaps) == 0, f"❌ Found {len(overlaps)} overlapping leaves:\n" + \
        "\n".join(f"  {o['leaf_1']} overlaps {o['leaf_2']} at {o['overlap']}" for o in overlaps)

    print(f"✓ No overlaps found in {len(leaves)} leaf nodes")
    return leaves


def test_chronological_order(leaves):
    """Verify leaves are in strict chronological order."""
    for i in range(len(leaves) - 1):
        current = leaves[i]
        next_leaf = leaves[i + 1]

        assert current["start"] <= next_leaf["start"], \
            f"❌ Chronological violation: {current['title']} starts after {next_leaf['title']}"

        assert current["end"] <= next_leaf["start"], \
            f"❌ Gap violation: {current['title']} ends after {next_leaf['title']} starts"

    print(f"✓ All {len(leaves)} leaves are in strict chronological order")


def test_unique_time_windows(leaves):
    """Verify each leaf has unique time window (no duplicates or contained ranges)."""
    windows = [(l["start"], l["end"]) for l in leaves]

    # Check for exact duplicates
    if len(windows) != len(set(windows)):
        duplicates = []
        seen = set()
        for w in windows:
            if w in seen:
                duplicates.append(w)
            seen.add(w)
        raise AssertionError(f"❌ Found {len(duplicates)} duplicate time windows")

    # Check for one window contained in another
    for i in range(len(leaves)):
        for j in range(len(leaves)):
            if i == j:
                continue

            li, lj = leaves[i], leaves[j]
            # Check if li is contained in lj
            if li["start"] >= lj["start"] and li["end"] <= lj["end"] and (li["start"] != lj["start"] or li["end"] != lj["end"]):
                raise AssertionError(
                    f"❌ Window contained: {li['title']} ({li['start']}-{li['end']}) "
                    f"contained in {lj['title']} ({lj['start']}-{lj['end']})"
                )

    print(f"✓ All {len(leaves)} time windows are unique and non-contained")


def test_complete_timeline():
    """Verify complete timeline consistency."""
    date_str = "2026-05-09"
    slots = load_slots(date_str)

    leaves = flatten_leaves(slots)

    if not leaves:
        raise AssertionError("❌ No leaf nodes found in tree")

    # Sort by start time for checking
    leaves.sort(key=lambda l: l["start"])

    print("\n" + "=" * 80)
    print("CHRONOLOGICAL CONSISTENCY TEST")
    print("=" * 80)
    print()

    test_no_overlaps()
    test_chronological_order(leaves)
    test_unique_time_windows(leaves)

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"✓ Timeline spans: {leaves[0]['start']} to {leaves[-1]['end']}")
    print(f"✓ Total leaf nodes: {len(leaves)}")
    print(f"✓ No overlaps")
    print(f"✓ Strict chronological order")
    print(f"✓ Unique time windows")
    print()
    print("CONCLUSION: Tree represents a valid timeline with zero overlapping windows")


if __name__ == "__main__":
    try:
        test_complete_timeline()
        print("\n✓✓✓ TEST PASSED ✓✓✓")
        print("Both projects and categories trees are chronologically consistent.")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌❌❌ TEST FAILED ❌❌❌")
        print(str(e))
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

#!/usr/bin/env python
"""
Investigate the correct approach to calculate title times without creating overlaps.

The key question: What should start/end represent for a title?
- Option A: The actual time window of all events (min start, max end) - allows gaps
- Option B: A continuous range from start to start+duration - can create overlaps
- Option C: Don't track time ranges for titles, only for apps

Current approach: Option B (causes overlaps)
"""

from datetime import datetime, timedelta, timezone


def demonstrate_issue():
    """Show the issue with current approach."""

    print("\n" + "="*80)
    print("THE OVERLAP CREATION ISSUE")
    print("="*80)

    print("\nScenario: Two titles with interleaved events in Brave-browser")
    print("-" * 80)

    # Raw events (actual times from ActivityWatch)
    events = {
        "One Piece 1160": [
            {"start": datetime(2026, 5, 8, 0, 25, 5, tzinfo=timezone.utc),
             "end": datetime(2026, 5, 8, 0, 25, 30, tzinfo=timezone.utc)},
            {"start": datetime(2026, 5, 8, 0, 26, 0, tzinfo=timezone.utc),
             "end": datetime(2026, 5, 8, 0, 26, 45, tzinfo=timezone.utc)},
        ],
        "My 18 Year Old": [
            {"start": datetime(2026, 5, 8, 0, 26, 34, tzinfo=timezone.utc),
             "end": datetime(2026, 5, 8, 0, 27, 18, tzinfo=timezone.utc)},
        ]
    }

    # Calculate metrics
    for title, evts in events.items():
        start = min(e["start"] for e in evts)
        end = max(e["end"] for e in evts)
        duration = sum((e["end"] - e["start"] for e in evts), timedelta())

        print(f"\n{title}:")
        print(f"  Events: {len(evts)}")
        print(f"  Event times: {start} to {end}")
        print(f"  Actual duration (sum): {duration}")
        print(f"  Current approach end: {start + duration}")
        print(f"  Actual event span: {end - start}")

    print("\n" + "-" * 80)
    print("OVERLAP DETECTION:")
    print("-" * 80)

    title1_end_current = datetime(2026, 5, 8, 0, 27, 26, tzinfo=timezone.utc)  # start + duration
    title2_start = datetime(2026, 5, 8, 0, 26, 34, tzinfo=timezone.utc)

    print(f"\nCurrent approach:")
    print(f"  Title 1 end: {title1_end_current}")
    print(f"  Title 2 start: {title2_start}")
    print(f"  Overlap? {title2_start < title1_end_current} ❌")

    print(f"\nCorrect approach (using actual event times):")
    title1_end_actual = datetime(2026, 5, 8, 0, 26, 45, tzinfo=timezone.utc)  # max(event_ends)
    print(f"  Title 1 end: {title1_end_actual}")
    print(f"  Title 2 start: {title2_start}")
    print(f"  Overlap? {title2_start < title1_end_actual} ✅")


def analyze_approaches():
    """Analyze different approaches to fix the issue."""

    print("\n" + "="*80)
    print("APPROACHES TO FIX OVERLAPS")
    print("="*80)

    approaches = [
        {
            "name": "Option A: Use actual event times (min/max)",
            "formula": "start = min(event_starts), end = max(event_ends)",
            "pros": [
                "✅ No overlaps (events are actual times)",
                "✅ Shows when title was 'active' (considering gaps)",
                "✅ Preserves event data accuracy",
            ],
            "cons": [
                "❌ end - start ≠ duration (includes gaps)",
                "❌ Visual display shows gaps within time range",
                "❌ Breaks our consistency requirement",
            ],
            "affected_fields": "Violates: end = start + duration"
        },
        {
            "name": "Option B: Use duration-based calculation (current)",
            "formula": "start = min(event_starts), end = start + duration",
            "pros": [
                "✅ end - start == duration (consistent)",
                "✅ Shows only actual work time",
            ],
            "cons": [
                "❌ Creates overlaps with other titles ← BUG",
                "❌ Misleading time ranges when events are interleaved",
                "❌ Breaks the assumption titles are sequential",
            ],
            "affected_fields": "Violates: No overlaps"
        },
        {
            "name": "Option C: Only track app-level times, not title times",
            "formula": "titles don't have start/end, use app's start/end",
            "pros": [
                "✅ No overlaps (no title-level ranges)",
                "✅ Simple (titles are just duration)",
                "✅ Avoids the problem entirely",
            ],
            "cons": [
                "❌ Loss of granular timing in centinel",
                "❌ Can't show when each title was active",
                "❌ Centinel needs to use app's time range for all titles",
            ],
            "affected_fields": "Changes data structure"
        },
        {
            "name": "Option D: Split titles with interleaved events",
            "formula": "When titles overlap, split into sequential segments",
            "pros": [
                "✅ No overlaps",
                "✅ Maintains granular timing",
                "✅ Accurate representation",
            ],
            "cons": [
                "❌ Complex logic to detect and split",
                "❌ Changes data structure (titles can appear multiple times)",
                "❌ Breaks user's title naming expectations",
            ],
            "affected_fields": "Changes output format"
        },
    ]

    for approach in approaches:
        print(f"\n{approach['name']}")
        print("-" * 80)
        print(f"Formula: {approach['formula']}")
        print(f"\nPros:")
        for pro in approach['pros']:
            print(f"  {pro}")
        print(f"\nCons:")
        for con in approach['cons']:
            print(f"  {con}")
        print(f"\nImpact: {approach['affected_fields']}")


def recommend_fix():
    """Recommend the best approach."""

    print("\n" + "="*80)
    print("RECOMMENDATION")
    print("="*80)

    print("""
The root cause is that we're trying to fit a square peg in a round hole:
- Raw ActivityWatch data has discrete events that can be interleaved by title
- We're trying to assign continuous time ranges to titles
- When events are interleaved, this creates overlaps

The best fix depends on the use case:

1. FOR CENTINEL'S PURPOSES:
   - Centinel needs to show which time range to reassign
   - It doesn't need per-title granularity - it needs APP granularity
   - RECOMMENDATION: Use Option C
   - Instead of title-level start/end, use app-level times for reassignment
   - This matches the actual user workflow (reassign an app's time to a task)

2. FOR DATA ACCURACY:
   - We need to preserve the events list (✅ done)
   - We need consistency: end - start == duration (current approach)
   - CONFLICT: Can't have both with interleaved events
   - RECOMMENDATION: Accept that some titles will have gaps
     - Use actual event times: start = min, end = max
     - Document that end - start might > duration
     - Centinel can show: "active period 10:00-10:30 (with gaps), actual work: 5 min"

3. IF WE MUST MAINTAIN CURRENT STRUCTURE:
   - Keep title-level start/end/duration
   - Fix the overlap by using actual event times for start/end
   - Accept that centinel will need to handle gaps in display

BEST OVERALL FIX: Option A + Option C
- Use actual event times in data (Option A)
- Don't use title-level times for reassignment in centinel (Option C)
- Show in centinel: app-level time range, title-level duration only
""")


if __name__ == "__main__":
    demonstrate_issue()
    analyze_approaches()
    recommend_fix()

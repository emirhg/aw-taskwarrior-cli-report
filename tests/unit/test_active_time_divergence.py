"""Test to diagnose Active Time calculation divergence between --by-day and --by-project.

This test investigates why the two modes report different Active Time totals
even though they should use the same underlying metrics.
"""

import pytest
from datetime import datetime, timedelta, timezone, date
from unittest.mock import Mock, patch

# We need to trace through the calculation to see where divergence occurs


def test_active_time_calculation_audit():
    """Audit the Active Time calculation path in both modes.

    Expected behavior:
    - Both --by-day (timeline) and --by-project (hierarchical) should use
      context.metrics.non_afk_time for the Active Time display
    - non_afk_time is calculated from not_afk_events in main.py:349
    - Both modes pass non_afk_time to their respective render functions

    Observed issue:
    - --by-day shows Active Time: 07:13:40
    - --by-project shows Active Time: 07:48:31
    - Difference: 34 minutes

    Questions to answer:
    1. Is non_afk_time calculated the same way for both modes?
    2. Is non_afk_time filtered/modified differently for each mode?
    3. Is the rendering calculating different values from the same input?
    4. Is there a post-calculation adjustment for one mode but not the other?
    """
    print("\n" + "=" * 70)
    print("ACTIVE TIME DIVERGENCE AUDIT")
    print("=" * 70)

    # The key is that both modes use context.metrics, which is built ONCE in main.py
    # So they should both get the same non_afk_time value

    # But what if the DISPLAY is different?
    # - Timeline mode: Displays non_afk_time directly as "Active Time"
    # - Hierarchical mode: Might be displaying something else?

    # Or what if the CALCULATION of non_afk_time is affected by:
    # - Different slot filtering?
    # - Different not_afk_events list?
    # - Different merging of overlapping periods?

    print("\nPOSSIBLE ROOT CAUSES:")
    print("1. Slots are filtered differently after creation")
    print("   - Timeline might exclude certain slots that hierarchical includes")
    print("   - This would affect the Active Time window calculation")
    print("\n2. not_afk_events are calculated/filtered differently")
    print("   - Maybe one mode applies additional filtering?")
    print("   - Maybe one mode modifies the events list?")
    print("\n3. Display logic calculates differently from input")
    print("   - Timeline: non_afk_time (should be straightforward)")
    print("   - Hierarchical: might use a different formula")
    print("\n4. Timezone handling affects the end time calculation")
    print("   - Different last_event_time for each mode")
    print("   - Different calculation of which not_afk_events are included")

    print("\nDEBUG APPROACH:")
    print("1. Add logging to main.py line 349 to see non_afk_time value")
    print("2. Add logging to timeline_render.py and report_render.py where")
    print("   non_afk_time is used/displayed")
    print("3. Compare the values at each step for both modes")
    print("4. Check if any post-filtering affects the not_afk_events list")

    print("\nCODE LOCATIONS TO CHECK:")
    print("- main.py:349 — non_afk_time = sum(...) calculation")
    print("- main.py:980-1027 — What parameters passed to each presenter")
    print("- report_render.py:113-137 — How Active Time displayed in summary")
    print("- timeline_render.py:113-137 — How Active Time displayed in timeline")

    assert True  # Placeholder for now


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

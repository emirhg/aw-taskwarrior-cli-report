# Project Tracking Percentage Inconsistency

## Issue

Project Tracking percentage doesn't match expected calculation:

```
Total Time                                      13:40:32
Project Tracking                90.4% (12:02:20)
```

### Calculation Analysis

If we verify the percentage: 12:02:20 / 13:40:32 = 88.0%, not 90.4%

Working backwards from 90.4%: 
- 12:02:20 / 0.904 ≈ 13:18:45

**The denominator being used (13:18:45) is neither:**
- Total Time (13:40:32)
- Online Time only (10:55:22)

### Expected Behavior

Project Tracking should show what fraction of total time (online + offline) was spent on projects with assigned names.

**Correct calculation should be:**
- Project time: 12:02:20
- Total time: 13:40:32
- Percentage: 12:02:20 / 13:40:32 = 88.0%

### Actual Calculation

Currently using `total_time_all` which may be:
- Before rendering filters? (10:55:22 online)
- After some filtering? (13:18:45 unknown)
- Or something else?

### Root Cause

In report_render.py line 112:
```python
task_time_pct = (total_duration / total_tracking_time) * 100
```

Where:
- total_duration = 12:02:20 (project-tracked time)
- total_tracking_time = depends on what total_time_all contains

The denominator should be the full Total Time (online + offline), but the comment says "online + offline" while the code might be using only online or some intermediate value.

### Solution

Need to verify:
1. What is total_time_all actually containing when passed to print_report_summary?
2. Should we pass a separate total_time_including_offline parameter?
3. Or fix the calculation to use the correct denominator?

## Related Issues

This is part of the broader architectural issue where multiple code paths use different duration values. See SESSION_SUMMARY_2026_07_24.md for other related bugs.

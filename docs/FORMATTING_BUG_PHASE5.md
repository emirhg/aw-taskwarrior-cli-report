# Timeline Formatting Bug — Phase 5 Regression

**Issue Date:** 2026-07-02 (after Phase 5 completion)
**Status:** NEEDS FIX
**Severity:** HIGH (timeline report output is unreadable)

---

## Problem Description

After Phase 5 refactoring (commit 12def2d), the timeline report formatting is broken. Lines are excessively long, columns don't align, and the output is difficult to read.

### Current Broken Output

```
==========================================================================
Period: :yesterday (2026-07-01 to 2026-07-01)
Active Time: 8:27:21 (2026-07-01 00:00 to 2026-07-02 00:00)
  • Project Tracking: 0.0% (0:00:00)
  • Untracked productivity: 5.5% (0:27:50)
  • Overall productivity: 32.7% (2:46:02)
  • Overall distracting time: 18.5% (1:33:44)
  • Unscored time: 11.9% (1:00:37)
Current Session: 0:04:54 (23:55 to 00:00)
Last Break: 0:18:12 (23:36 to 23:55)
---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Wk  Date       Day
W27 2026-07-01 Wed
       00:00-...  ▶ Organización.Comunicación.Reporte > Corregir el reporte de tiempos conso...                                                                                                               4:36:02
       04:36-...  ▶ No project assigned > No task assigned                                                                                                                                                    0:13:47
       04:51-...  ▶ Anarcademia.Investigación > Elimina archivos en Android con ADB (pull)                                                                                                                    0:06:45
       04:57-...  ▶ No project assigned > No task assigned                                                                                                                                                    0:09:12
             11:05  ▶ Ecosistema > Cultivo > Higuera > Control de plagas                                                                                                          (0:00:05 OFF)  0:16:22  [prod   1%]
       12:57-...  ▶ No project assigned > No task assigned                                                                                                                                                    0:10:40
             13:38  ▶ Ecosistema > Tratamiento de residuos > Reciclaje > Lavar y compactar PET                                                                                    (6:51:00 OFF)  2:16:46  [prod  75%]
       22:46-...  ▶ No project assigned > No task assigned                                                                                                                                                    0:47:39
             23:36  ▶ Ecosistema > Tratamiento de residuos > Reciclaje > Polímeros > Recicla...                                                                                   (0:18:11 OFF)  0:00:00  [prod 100%]
       23:56-...  ▶ No project assigned > No task assigned                                                                                                                                                    0:03:04
                                                                                                                                                                                               ----------------------
                                                                                                                                                                                    Day total:   6:07:12  [prod  45%]
                                                                                                                                                                          Week total (tracked):  6:07:12  [prod  45%]
                                                                                                                                                                                                  Total Time: 0:00:00
=============================================================================================================================================================================
```

### Problems Identified

1. **Line Length:** Lines exceed terminal width, causing wrapping in display
2. **Column Alignment:** Duration column doesn't align vertically - no consistent column position
3. **Offline Duration Format:** `(HH:MM:SS OFF)` is displaying with excessive spaces before it
4. **Separator Line:** The dashed line `----...----` is too long and fills the entire screen
5. **Total Lines:** Summary lines (Day total, Week total) are right-aligned incorrectly

---

## Root Cause Analysis

### File: `src/tw_report/utils/formatting.py:format_timeline_line()`

```python
def format_timeline_line(
    left_part: str, duration_str: str = "", max_left_width: int = 100
) -> str:
    width = get_terminal_width()
    
    if len(left_part) > max_left_width:
        left_part = left_part[: max_left_width - 3] + "..."
    
    # PROBLEM: ljust() assumes width is correct, but the alignment is wrong
    if duration_str:
        return left_part.ljust(width - len(duration_str) - 1) + " " + duration_str
    return left_part
```

**Issue:** The calculation `ljust(width - len(duration_str) - 1)` is incorrect when `len(left_part)` approaches terminal width. It should preserve a consistent column position for the duration, not try to fill the entire width.

### File: `src/tw_report/pipeline/timeline_render.py:print_timeline_report()`

Lines 268-356: The formatting calls are correct, but they rely on `format_timeline_line()` which has the bug.

---

## Expected Behavior (Before Phase 5)

The timeline report should look like this:

```
==========================================================================
Period: :yesterday (2026-07-01 to 2026-07-01)
Active Time: 8:27:21 (2026-07-01 00:00 to 2026-07-02 00:00)
  • Project Tracking: 0.0% (0:00:00)
  • Untracked productivity: 5.5% (0:27:50)
  • Overall productivity: 32.7% (2:46:02)
  • Overall distracting time: 18.5% (1:33:44)
  • Unscored time: 11.9% (1:00:37)
Current Session: 0:04:54 (23:55 to 00:00)
Last Break: 0:18:12 (23:36 to 23:55)
-----------------------------
Wk  Date       Day
W27 2026-07-01 Wed
       00:00-...  ▶ Organización > Comunicación > Reporte > Corregir reporte  4:36:02
       04:36-...  ▶ No project assigned > No task assigned                     0:13:47
       04:51-...  ▶ Anarcademia > Investigación > Elimina archivos Android    0:06:45
       04:57-...  ▶ No project assigned > No task assigned                     0:09:12
             11:05  ▶ Ecosistema > Cultivo > Higuera > Control de plagas (0:00:05 OFF)  0:16:22  [prod   1%]
       12:57-...  ▶ No project assigned > No task assigned                     0:10:40
             13:38  ▶ Ecosistema > Tratamiento de residuos > Reciclaje  (6:51:00 OFF)  2:16:46  [prod  75%]
       22:46-...  ▶ No project assigned > No task assigned                     0:47:39
             23:36  ▶ Ecosistema > Tratamiento de residuos > Reciclaje > Pol... (0:18:11 OFF)  0:00:00  [prod 100%]
       23:56-...  ▶ No project assigned > No task assigned                     0:03:04
                                                                                  ----------------------
                                                                                  Day total:   6:07:12  [prod  45%]
                                                                                  Week total (tracked):  6:07:12  [prod  45%]
                                                                                  Total Time: 0:00:00
==========================================================================
```

### Key Formatting Properties (CORRECT)

1. **Time Prefix:** `       HH:MM-...  ` (7 spaces + time + dash + 2 spaces) = consistent width
2. **For Offline Tasks:** `       HH:MM  ` (7 spaces + time + 2 spaces, no dash)
3. **Content:** `▶ Project > Task` (left-aligned after time prefix)
4. **Duration Column:** Right-aligned, positioned consistently
5. **Separator Lines:** `-----` × (terminal_width // width_unit) to reach terminal width naturally

---

## Required Fixes

### Fix 1: Update `format_timeline_line()` logic

The function should:
- Keep the left content at a fixed column position (e.g., 50 chars max)
- Right-align the duration in the remaining space
- NOT try to fill the entire terminal width with padding

```python
def format_timeline_line(
    left_part: str, duration_str: str = "", max_left_width: int = 50
) -> str:
    """Format timeline line with proper column alignment.
    
    Left-aligns content (truncated to max_left_width), then adds duration
    right-aligned with proper spacing.
    """
    if len(left_part) > max_left_width:
        left_part = left_part[: max_left_width - 3] + "..."
    
    if duration_str:
        # Pad left part to fixed column, then add duration
        # Example: "       00:00-...  ▶ Project > Task" (padded to 50) + "4:36:02"
        padding = " " * (max_left_width - len(left_part))
        return left_part + padding + duration_str
    return left_part
```

### Fix 2: Adjust offline task formatting

The offline task line should format like:
```
       11:05  ▶ Project > Task > Details  (6:51:00 OFF)  2:16:46  [prod  75%]
```

Not:
```
             11:05  ▶ Ecosistema > Tratamiento... (6:51:00 OFF)  2:16:46  [prod  75%]
```

### Fix 3: Separator line calculation

The separator should be:
```python
separator_width = min(100, width)  # Cap at 100 chars
print("-" * separator_width)
```

---

## Files to Modify

1. **`src/tw_report/utils/formatting.py`** — Fix `format_timeline_line()` logic
2. **`src/tw_report/pipeline/timeline_render.py`** — Adjust max_left_width parameter in calls
3. **`tests/unit/test_formatting.py`** — Add tests for format_timeline_line() with long content
4. **`tests/unit/test_timeline_render.py`** — Add visual regression tests

---

## Testing Strategy

### Golden Output Tests

Before fix:
```bash
tw-report 2026-07-01 --timesheet > /tmp/broken.txt
```

After fix, should match:
```bash
tw-report 2026-07-01 --timesheet > /tmp/fixed.txt
diff /tmp/broken.txt /tmp/fixed.txt
```

### Unit Tests

```python
def test_format_timeline_line_truncation():
    """Test that long project names are truncated correctly."""
    long_content = "▶ " + "Very.Long.Project.Name" * 5 + " > Task"
    result = format_timeline_line(long_content, "4:36:02", max_left_width=50)
    assert len(result.split("4:36:02")[0]) <= 50  # Left part respects max_left_width
    assert "4:36:02" in result  # Duration is preserved

def test_format_timeline_line_alignment():
    """Test that durations align at consistent column."""
    line1 = format_timeline_line("▶ Project A", "1:23:45", max_left_width=50)
    line2 = format_timeline_line("▶ Very Long Project Name Here", "0:45:30", max_left_width=50)
    
    # Find position of duration in each line
    pos1 = line1.rfind("1:23:45")
    pos2 = line2.rfind("0:45:30")
    
    # Durations should start at same column (within 1 char due to rounding)
    assert abs(pos1 - pos2) <= 1
```

---

## Timeline

- **Phase 5 (2026-07-02):** Formatting broke during timeline_render refactoring
- **Now:** Document the issue for fix in next session
- **Next:** Fix format_timeline_line() and verify golden output

---

## Notes for Next Session

- This is a **regression**, not a new feature
- The code was working before Phase 5
- Focus on the column alignment algorithm, not on major refactoring
- Keep `format_timeline_line()` simple — just handle truncation and spacing correctly
- Don't over-engineer; the fix should be 20 lines of code

---

## References

- **Git Commit:** 12def2d (Phase 5)
- **Previous Commit:** b6fbd8e (working timeline_render extraction)
- **Code Files:** 
  - `src/tw_report/utils/formatting.py:312-336`
  - `src/tw_report/pipeline/timeline_render.py:338, 353`
  - `tests/unit/test_formatting.py:*`
  - `tests/unit/test_timeline_render.py:*`

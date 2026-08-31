"""
Pure formatting utilities for duration, titles, and timeline display.

All functions are pure (no I/O side effects). Formatting is separated from
presentation to enable testing and reuse across different output formats.
"""

import re
import shutil
import unicodedata
from datetime import timedelta
from typing import TYPE_CHECKING, Optional, Any

if TYPE_CHECKING:
    from tw_report.pipeline.models import TimeslotDuration


def _get_timeslot_duration_class() -> type:
    """Lazy import TimeslotDuration to avoid circular dependencies.

    Returns the TimeslotDuration class for runtime use in formatting functions.
    """
    from tw_report.pipeline.models import TimeslotDuration
    return TimeslotDuration


def display_width(text: str) -> int:
    """Calculate visual display width of text, accounting for multi-byte UTF-8 characters.

    CRITICAL FUNCTION for timeline alignment (2026-07-28):
    ======================================================
    Terminal columns are based on VISUAL WIDTH, not byte count. Multi-byte UTF-8
    characters (like ▶, ñ, é, emoji) occupy multiple bytes but take up only 1-2
    visual columns. Using len() instead of display_width() causes alignment to break.

    Real-world examples from tw-report:
    - "▶ Mercado" uses 9 bytes but displays in 9 columns (▶ is 3 bytes, 1 visual)
    - "diseño" uses 7 bytes but displays in 6 columns (ñ is 2 bytes, 1 visual)
    - If you pad with ljust() to 28 bytes, it may only be 27 visual columns
    - Result: columns misaligned by 1+ positions

    How it works:
    - East Asian Width property ('F'=Fullwidth, 'W'=Wide) → 2 visual columns
    - Everything else ('A', 'H', 'N', default) → 1 visual column
    - This matches terminal rendering behavior (xterm, iTerm, VS Code, etc.)

    USAGE:
    - Always use display_width() to calculate visual column count
    - Always pair with ljust_display() for padding (never ljust())
    - For alignment calculations: use display_width() not len()

    DO NOT:
    - Use len(text) for column width calculations
    - Mix display_width() with ljust() padding
    - Assume UTF-8 bytes == visual columns

    Example of bug that display_width() prevents:
    ```python
    # Wrong: Uses byte length (11), but ▶ takes 3 bytes, 1 column
    text = "▶ Mercado"  # 9 bytes, 9 visual columns
    ljust(text, 28)     # Pads to 28 bytes, but only ~27 visual columns
    # Result: Column misaligned by 1 position

    # Right: Uses visual width (9), accounting for ▶
    display_width(text)  # Returns 9 (correct visual)
    ljust_display(text, 28)  # Pads to 28 visual columns
    # Result: Proper alignment
    ```

    Wide characters (e.g., CJK, emoji) count as 2. Normal characters count as 1.
    This is essential for proper column alignment when strings contain Unicode.

    Args:
        text: String to measure

    Returns:
        Visual display width in columns
    """
    width = 0
    for char in text:
        # Get East Asian Width property
        char_width = unicodedata.east_asian_width(char)
        if char_width in ('F', 'W'):  # Fullwidth or Wide
            width += 2
        elif char_width in ('A', 'H'):  # Ambiguous or Halfwidth
            # Treat ambiguous/halfwidth as single width in terminal context
            width += 1
        else:  # Narrow, Not East Asian
            width += 1
    return width


def ljust_display(text: str, width: int, fillchar: str = ' ') -> str:
    """Left-justify string to visual display width, padding with fillchar.

    CRITICAL FUNCTION for timeline alignment (2026-07-28):
    ======================================================
    This is the ONLY safe way to pad strings when aligning terminal columns.
    Never use str.ljust() when alignment depends on visual column positions.

    Why ljust() is broken for alignment:
    - str.ljust() counts BYTES, not VISUAL COLUMNS
    - With UTF-8, bytes ≠ visual columns (multi-byte chars like ▶, ñ take 2-3 bytes, 1 visual column)
    - Result: ljust(text, 28) may create 28 bytes but only 27 visual columns
    - This breaks column alignment, causing misaligned headers/data rows

    CRITICAL DEPENDENCY in DisplayColumns.format():
    - DisplayColumns uses ljust_display() for ALL padding
    - Header construction in timeline_render.py MUST use ljust_display()
    - Day total formatting MUST use ljust_display()
    - If you use ljust() anywhere, columns WILL be misaligned

    Example of the alignment failure ljust_display() prevents:
    ```python
    # Using ljust() (WRONG):
    text = "▶ Project"  # 9 bytes, 9 visual columns
    padded = text.ljust(28)  # 28 bytes total, but only ~27 visual columns
    # When rendered in terminal column width 28:
    #   Visual: [▶ Project____________]  (17 padding spaces, 27 visual total)
    #   Next column starts at visual position 28, but padded string ends at ~27
    #   Result: 1-column misalignment

    # Using ljust_display() (CORRECT):
    padded = ljust_display(text, 28)  # 28 visual columns
    # When rendered:
    #   Visual: [▶ Project________________]  (18 padding spaces, 28 visual total)
    #   Next column starts at visual position 29 (correct)
    #   Result: Proper alignment
    ```

    USAGE RULES:
    1. Whenever padding text for column alignment, use ljust_display()
    2. Always pass the TARGET VISUAL WIDTH (not byte count)
    3. For column construction (DisplayColumns, headers), ALWAYS ljust_display()
    4. Never mix ljust() and display_width() — use ljust_display() for both

    DO NOT:
    - Use str.ljust() for anything related to terminal columns
    - Mix ljust() and display_width() in alignment calculations
    - Assume padding_width is correct if you calculated it with len()

    Unlike str.ljust() which counts bytes, this accounts for multi-byte UTF-8
    characters to ensure proper visual alignment.

    Args:
        text: String to pad
        width: Target display width (in columns, not bytes)
        fillchar: Character to pad with (default space)

    Returns:
        String padded to specified display width
    """
    current_width = display_width(text)
    if current_width >= width:
        return text
    padding_needed = width - current_width
    return text + (fillchar * padding_needed)


def format_duration(duration: timedelta) -> str:
    """Format timedelta as HH:MM:SS string.

    Args:
        duration: Time interval to format

    Returns:
        String in HH:MM:SS format, zero-padded (e.g., "01:23:45", "00:05:30")
    """
    total_seconds = int(duration.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def format_duration_tracked_prod(
    tracked_duration: timedelta, productive_within: timedelta
) -> str:
    """Format duration with optional [prod NN%] for tracked-slot totals.

    Shows the duration with productivity percentage only if productivity exists.
    If no productive activity, returns just the duration (no placeholder).

    Args:
        tracked_duration: Total time tracked in this slot
        productive_within: Time spent on productive activities within the tracked duration

    Returns:
        String formatted as "HH:MM:SS  [prod XXX%]" if productive > 0,
        or just "HH:MM:SS" if no productivity data (no placeholder)
    """
    base = format_duration(tracked_duration)
    if tracked_duration.total_seconds() <= 0:
        return base

    # Only show productivity percentage if there's actual productive time
    if productive_within.total_seconds() > 0:
        pct = productive_within.total_seconds() / tracked_duration.total_seconds() * 100
        label = f"[prod {pct:>3.0f}%]"
        return f"{base}  {label:>11}"
    else:
        # No productive time measured - return duration only
        return base


def format_afk_label(duration: timedelta) -> str:
    """Format AFK duration label with fixed-width padding.

    Matches the width of format_duration_tracked_prod output for visual alignment.

    Args:
        duration: AFK time to format

    Returns:
        String formatted as "HH:MM:SS  [   AFK   ]" (11-char label for alignment)
    """
    base = format_duration(duration)
    label = "[   AFK   ]"
    return f"{base}  {label:>11}"


def format_offline_label(duration: timedelta) -> str:
    """Format OFFLINE duration label with fixed-width padding.

    Matches the width of AFK labels for visual alignment.

    Args:
        duration: Offline time to format

    Returns:
        String formatted as "HH:MM:SS  [ OFFLINE ]" (11-char label for alignment)
    """
    base = format_duration(duration)
    label = "[ OFFLINE ]"
    return f"{base}  {label:>11}"


def format_duration_with_afk(
    tracked_duration: timedelta,
    productive_within: timedelta,
    afk_duration: Optional[timedelta] = None,
) -> str:
    """Format duration with optional AFK notation for consolidated display.

    When afk_duration is present (consolidation with AFK breaks), includes
    AFK time notation. Otherwise, standard productivity format.

    DEPRECATED: This function now delegates to format_timeslot_duration() for
    new code. For backward compatibility, it still accepts raw timedelta parameters.

    Args:
        tracked_duration: Total time tracked in this slot (online_duration)
        productive_within: Time spent on productive activities
        afk_duration: Optional time spent away from keyboard (if present, included in output)

    Returns:
        String formatted as:
        - With AFK: "(HH:MM:SS AFK)  HH:MM:SS  [prod XX%]"
        - Without AFK: "HH:MM:SS  [prod XX%]"
    """
    # Delegate to new TimeslotDuration-based formatter
    TimeslotDuration = _get_timeslot_duration_class()
    slot_duration = TimeslotDuration(
        online_duration=tracked_duration if tracked_duration.total_seconds() > 0 else None,
        offline_gap=None,
        afk_portion=afk_duration if (afk_duration and afk_duration.total_seconds() > 0) else None,
    )
    return format_timeslot_duration(slot_duration, productive_within)


def format_duration_with_gaps(
    tracked_duration: timedelta,
    productive_within: timedelta,
    afk_duration: Optional[timedelta] = None,
    offline_extension_duration: Optional[timedelta] = None,
) -> str:
    """Format duration with optional AFK and OFFLINE extension notation.

    For consolidation with multiple break types, shows all gap components in
    a single notation. Falls back to format_duration_with_afk if no gaps.

    DEPRECATED: This function now delegates to format_timeslot_duration() for
    new code. For backward compatibility, it still accepts raw timedelta parameters.

    Args:
        tracked_duration: Total time tracked (online_duration)
        productive_within: Time spent on productive activities
        afk_duration: Optional time away from keyboard
        offline_extension_duration: Optional offline (system not running) time

    Returns:
        String formatted as:
        - With gaps: "(HH:MM:SS AFK, HH:MM:SS OFFLINE)  HH:MM:SS  [prod XX%]"
        - Without gaps: "HH:MM:SS  [prod XX%]"
    """
    # For now, keep original logic since format_timeslot_duration doesn't yet
    # support combined AFK+OFFLINE notation in single gap string
    # TODO: Enhance format_timeslot_duration to support combined gap notation
    base_format = format_duration_tracked_prod(tracked_duration, productive_within)

    gap_parts = []
    if afk_duration and afk_duration.total_seconds() > 0:
        gap_parts.append(f"{format_duration(afk_duration)} AFK")
    if offline_extension_duration and offline_extension_duration.total_seconds() > 0:
        gap_parts.append(f"{format_duration(offline_extension_duration)} OFFLINE")

    if gap_parts:
        gaps_str = ", ".join(gap_parts)
        return f"({gaps_str})  {base_format}"

    return base_format


def split_gaps_and_duration(
    tracked_duration: timedelta,
    productive_within: timedelta,
    afk_duration: Optional[timedelta] = None,
    offline_extension_duration: Optional[timedelta] = None,
) -> tuple:
    """Format duration and gaps as separate components for column-based layout.

    Returns gaps and duration as separate strings for flexible formatting,
    allowing gaps to be displayed in a dedicated column.

    Args:
        tracked_duration: Total time tracked
        productive_within: Time spent on productive activities
        afk_duration: Optional time away from keyboard
        offline_extension_duration: Optional offline (system not running) time

    Returns:
        Tuple of (gaps_str, duration_str) where:
        - gaps_str: Normalized gap notation like "(HH:MM:SS AFK)" (empty if no gaps)
        - duration_str: Duration + productivity like "HH:MM:SS  [prod XX%]"
    """
    base_format = format_duration_tracked_prod(tracked_duration, productive_within)

    gap_parts = []
    if afk_duration and afk_duration.total_seconds() > 0:
        gap_parts.append(f"{format_duration(afk_duration)} AFK")
    if offline_extension_duration and offline_extension_duration.total_seconds() > 0:
        gap_parts.append(f"{format_duration(offline_extension_duration)} OFFLINE")

    if gap_parts:
        gaps_str = ", ".join(gap_parts)
        return (f"({gaps_str})", base_format)

    return ("", base_format)


def format_offline_task_duration(
    wall_clock_duration: timedelta, event_duration: timedelta, productive_duration: Optional[timedelta] = None
) -> str:
    """Format duration for offline tasks showing offline/online time split.

    For tasks tagged as offline: shows time system was off (untracked) and time
    that was tracked while system was running, plus actual productivity data if available.

    Productivity % = productive_duration / event_duration × 100
    (Productivity is based on measured activity scores, NOT on offline time heuristics)

    DEPRECATED: This function now delegates to format_timeslot_duration() for
    new code. For backward compatibility, it still accepts raw timedelta parameters.

    Args:
        wall_clock_duration: Total time period (system on + off)
        event_duration: Time tracked while system was on (online_duration)
        productive_duration: Time on productive activities (if None, no prod % shown)

    Returns:
        String formatted as "(HH:MM:SS OFF)  HH:MM:SS  [prod XX%]"
        where first time is offline period, second is online/tracked time,
        and productivity is based on actual measured data (not offline heuristic)
    """
    # Delegate to new TimeslotDuration-based formatter
    TimeslotDuration = _get_timeslot_duration_class()
    offline_gap = wall_clock_duration - event_duration
    slot_duration = TimeslotDuration(
        online_duration=event_duration if event_duration.total_seconds() > 0 else None,
        offline_gap=offline_gap if offline_gap.total_seconds() > 0 else None,
        afk_portion=None,
    )
    return format_timeslot_duration(slot_duration, productive_duration)


# TimeslotDuration-aware format functions (new API)
# These functions accept TimeslotDuration for clear, type-safe duration formatting


def format_timeslot_duration(
    slot_duration: Any,  # TimeslotDuration (late import to avoid circular deps)
    productive_duration: Optional[timedelta] = None,
) -> str:
    """Format a TimeslotDuration for display, handling all duration types.

    This is the primary formatting function for TimeslotDuration. It handles:
    - Online-only slots (no offline gap)
    - Offline slots (system powered off for part)
    - Slots with AFK time detected (shown in gap notation)

    Args:
        slot_duration: TimeslotDuration object with online/offline/afk breakdown
        productive_duration: Optional productive time (for [prod XX%] display)

    Returns:
        Formatted string:
        - For online-only: "HH:MM:SS  [prod XX%]"
        - For offline: "(HH:MM:SS OFF)  HH:MM:SS  [prod XX%]"
        - For AFK: "(HH:MM:SS AFK)  HH:MM:SS  [prod XX%]"
    """
    if slot_duration.has_offline() and not slot_duration.has_online():
        # Offline-only slot (rare case): show gap with zero online time
        offline_gap = slot_duration.offline_gap or timedelta(0)
        offline_str = format_duration(offline_gap)
        online_str = "00:00:00"  # No online time
        if productive_duration and productive_duration.total_seconds() > 0:
            label = "[prod   0%]"  # No online time to measure productivity against
            return f"({offline_str} OFF)  {online_str}  {label:>11}"
        return f"({offline_str} OFF)  {online_str}"

    # Has online_duration (possibly with offline_gap and/or afk_portion)
    online_duration = slot_duration.online_duration or timedelta(0)
    prod_duration = productive_duration or timedelta(0)
    base_format = format_duration_tracked_prod(online_duration, prod_duration)

    if slot_duration.has_offline():
        # Both online and offline: show as "(OFFLINE) ONLINE"
        offline_gap = slot_duration.offline_gap or timedelta(0)
        offline_str = format_duration(offline_gap)
        return f"({offline_str} OFF)  {base_format}"

    if slot_duration.afk_portion:
        # Online with AFK: show as "(AFK) ONLINE"
        afk_str = format_duration(slot_duration.afk_portion)
        return f"({afk_str} AFK)  {base_format}"

    # Online only, no gaps
    return base_format


def get_terminal_width() -> int:
    """Get current terminal width, with graceful fallback.

    Returns:
        Terminal width in columns, or 80 if unable to determine
    """
    try:
        return shutil.get_terminal_size().columns
    except OSError:
        return 80


def normalize_title(title: str) -> str:
    """Remove notification counters from window titles.

    Removes patterns like:
    - "(7)" at start: "(7) WhatsApp" → "WhatsApp"
    - "(1)" at end: "Work/Job Hunting (1)" → "Work/Job Hunting"
    - "(2)" in middle: "Inbox (2) - Gmail" → "Inbox - Gmail"

    Used to aggregate similar window events across time by removing transient
    notification badges.

    Args:
        title: Original window title

    Returns:
        Title with notification counters removed and whitespace normalized
    """
    if not title:
        return title
    normalized = re.sub(r"\s*\(\d+\)\s*", " ", title)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def sanitize_title(title: str) -> str:
    """Clean window titles by removing emoji and unwanted Unicode.

    Preserves accented Latin characters (ñ, á, é, etc.) common in international
    window titles while filtering emoji and decorative symbols.

    Strategy:
    - ASCII (< 128): keep printable characters and whitespace
    - Latin-1 Supplement (0x0080-0x00FF): keep all (covers ñ, á, é, etc.)
    - Other ranges: keep only letters (Unicode category L*) and numbers (N*)

    Args:
        title: Window title potentially containing emoji/unwanted Unicode

    Returns:
        Cleaned title with emoji and symbols removed, accented chars preserved
    """
    if not title:
        return title
    title = normalize_title(title)
    result = []
    for c in title:
        code_point = ord(c)
        if code_point < 128:
            if c.isprintable() or c.isspace():
                result.append(c)
        elif 0x0080 <= code_point <= 0x00FF:
            result.append(c)
        else:
            category = unicodedata.category(c)
            if category[0] in ("L", "N"):
                result.append(c)
    return "".join(result)


def truncate_title(title: str, max_length: int = 60) -> str:
    """Truncate title to max_length with ellipsis if needed.

    Args:
        title: Title to truncate
        max_length: Maximum length before truncation (default 60)

    Returns:
        Original title if shorter than max_length, otherwise truncated with "…"
    """
    if not title:
        return title
    if len(title) <= max_length:
        return title
    return title[: max_length - 1] + "…"


def abbreviate_project_path(
    project: str, task: str = "", max_content_width: int = 100
) -> str:
    """Abbreviate hierarchical project path while preserving task description.

    For multi-level projects (e.g., "Platform > Web > Frontend"), keeps the
    most specific level (leaf) and abbreviates the root only when necessary.
    Abbreviation uses first 10 chars to be more readable than 5-char limit.
    Single-level projects are returned unchanged.

    Args:
        project: Project path, potentially with " > " separators (hierarchical)
        task: Optional task name (used to decide abbreviation length)
        max_content_width: Maximum width before truncation (default 100)

    Returns:
        Abbreviated project path (e.g., "Ecosystem... > Frontend" or full path if short enough)
    """
    if " > " not in project:
        return project

    parts = project.split(" > ")
    leaf = parts[-1]

    if len(parts) > 1:
        root = parts[0]
        # Only abbreviate if the full project is longer than 20 chars
        # This gives us better readability without abbreviating short projects
        full_project = f"{root} > {leaf}"
        if len(full_project) > 20:
            root_abbrev = root[:10] + "..." if len(root) > 10 else root
            abbreviated = f"{root_abbrev} > {leaf}"
        else:
            abbreviated = full_project
    else:
        abbreviated = leaf

    if task:
        full = f"{abbreviated} ▶▶ {task}"
        if len(full) <= max_content_width:
            return abbreviated

    return abbreviated


def format_timeline_columns(
    time_range: str,
    project: str,
    task: str,
    gaps: str,
    duration: str,
    project_width: int = 28,
    task_width: int = 35,
    no_project_sentinel: str = "No project assigned",
    right_align: bool = True,
) -> str:
    """Format timeline entry as fixed-width columns for alignment.

    Creates a columnar layout where project and task are in fixed-width columns,
    ensuring that gaps and duration stay aligned even when descriptions vary in length.
    Duration is right-aligned to terminal width when right_align=True.

    For "No project" entries, omits the task column decorator.

    Args:
        time_range: Time range like "00:00-11:30"
        project: Project name (e.g., "No project assigned" or "Ecosistema > Cultivo")
        task: Task name (e.g., "Revisar semillero" or "" for no project entries)
        gaps: Gap notation like "(3:48:32 AFK)" or "" if no gaps
        duration: Duration with productivity like "10:48:56  [prod  7%]"
        project_width: Fixed width for project column (default 28 chars, reduced from 33)
        task_width: Fixed width for task column (default 35 chars, reduced from 40)
        no_project_sentinel: Value that indicates "no project" (default "No project assigned")
        right_align: Right-align duration to terminal width (default True)

    Returns:
        Single-line formatted entry with fixed-width columns
    """
    # Build the line with fixed-width columns
    # Format: "time  ▶project_col   ▶▶task_col  gaps [padded to terminal width] duration"

    time_part = f"       {time_range}"  # Indent + time (7 spaces to align with date lines)

    # Project column: "▶ project_name" padded to fixed width
    project_part = f"▶ {project}".ljust(project_width + 2)  # +2 for "▶ "

    # Task column: "▶▶ task_name" padded to fixed width
    # IMPORTANT: Always pad to task_width to maintain column alignment
    # Special case: if project is "no project", skip task decorator (just padding)
    if project == no_project_sentinel:
        task_part = " " * (task_width + 4)
    elif task:
        # Pad the decorated task to the fixed column width
        task_part = f"▶▶ {task}".ljust(task_width + 4)  # +4 for "▶▶ "
    else:
        task_part = " " * (task_width + 4)

    # Build the complete line with fixed columns and right-aligned right section
    # Format: "time  project  task  [right-aligned: gaps  duration]"

    left_part = f"{time_part}  {project_part}  {task_part}"
    gaps_part = gaps if gaps else ""

    # Build the right section (gaps + duration) and right-align it
    if gaps_part:
        right_part = f"{gaps_part}  {duration}"
    else:
        right_part = duration

    # Right-align the right section to terminal width
    if right_align:
        width = get_terminal_width()
        # Pad left_part to push right_part to the right edge
        # Subtract 2 to account for the 2-space separator
        full_line = left_part.ljust(width - len(right_part) - 2) + "  " + right_part
    else:
        full_line = left_part + "  " + right_part

    # Trim excessive trailing spaces only at the very end
    return full_line.rstrip()


def format_timeline_line(
    left_part: str, duration_str: str = "", max_left_width: int = 100
) -> str:
    """Format timeline line with truncated content and right-aligned duration.

    CRITICAL DESIGN CHOICE (Phase 5 regression fix, 2026-07-02):
    ============================================================

    This function uses terminal-width based padding (ljust(width - len(duration) - 1))
    rather than fixed-column padding. This was chosen after a failed attempt to use
    fixed-column alignment (max_left_width=70), which:
      - Created 0-padding when content was already at max width
      - Resulted in duration appearing immediately after truncated content
      - Broke consolidated rendering with extra padding spaces

    The terminal-width approach works correctly for ALL rendering paths:
      1. Simple timeline (non-consolidated): Dynamic padding fills to screen width
      2. Consolidated+detail rendering: Works with varied content lengths
      3. Multi-day spanning: Handles proportional duration allocation

    ALGORITHM:
    ==========
    1. Truncate left_part to max_left_width chars if needed (add "..." if truncated)
    2. Pad left_part to (terminal_width - duration_length - 1) chars using ljust()
    3. Append single space + duration string

    EXAMPLE (terminal width 120, content 50 chars, duration "4:36:02" = 7 chars):
      left_part (before):   "     00:00 - 04:36  ▶ Project > Task"  (50 chars)
      left_part (after):    "     00:00 - 04:36  ▶ Project > Task                                         "  (padded to 112)
      final:                "     00:00 - 04:36  ▶ Project > Task                                          4:36:02"
                                                                    ^~112 chars padding~^1 space^duration

    PARAMETERS:
      left_part:        Pre-formatted content (time range + project/task + details)
      duration_str:     Duration string to right-align (e.g., "4:36:02", "0:13:47")
      max_left_width:   Maximum chars before truncation (default 100, used by consolidated rendering)

    RETURNS:
      Formatted line with left_part padded to terminal width and duration right-aligned

    NOTE:
      - Truncation adds "..." (3 chars) when left_part exceeds max_left_width
      - Terminal width fallback is 80 if detection fails
      - Lines naturally fit within terminal width by design
    """
    width = get_terminal_width()

    # Truncate left part if it exceeds max width
    if len(left_part) > max_left_width:
        left_part = left_part[: max_left_width - 3] + "..."

    # Right-align duration
    if duration_str:
        return left_part.ljust(width - len(duration_str) - 1) + " " + duration_str
    return left_part

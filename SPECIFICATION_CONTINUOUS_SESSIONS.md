# Specification: Continuous Session Grouping for Events

## Requirement

Events of the same title MUST only be grouped together if they are **time-continuous**. 

When different titles (or other activity) occur between events of the same title, this breaks continuity and creates separate sessions.

## Definition: Continuous Session

A **continuous session** of a title is a sequence of events with NO interruptions from other titles.

```
Timeline:
00:00-00:00:56  Title A, Event 1
00:00:56-00:01:00  [GAP - no activity]
00:01:00-00:02:00  Title B, Event 1       ← BREAKS continuity of Title A
00:02:00-00:02:29  [GAP - no activity]
00:02:29-00:05:31  Title A, Event 2       ← NEW SESSION (different from Event 1)
00:05:31-00:05:40  [GAP - no activity]
00:05:40-00:05:44  Title C, Event 1       ← BREAKS continuity of Title A
00:05:44-00:05:45  [GAP - no activity]
00:05:45-00:05:46  Title A, Event 3       ← NEW SESSION (different from Event 2)
```

## Display Structure

Events must be grouped by continuous sessions, not by title alone:

```
Category: Work
  App: kitty
    Title A - Session 1 (00:00:00 - 00:00:56)
      Event 1: 00:00:00 - 00:00:56 (raw data)
    Title B (00:01:00 - 00:02:00)
      Event 1: 00:01:00 - 00:02:00 (raw data)
    Title A - Session 2 (00:02:29 - 00:05:31)
      Event 2: 00:02:29 - 00:05:31 (raw data)
    Title C (00:05:40 - 00:05:44)
      Event 1: 00:05:40 - 00:05:44 (raw data)
    Title A - Session 3 (00:05:45 - 00:05:46)
      Event 3: 00:05:45 - 00:05:46 (raw data)
```

NOT:
```
Title A (grouped, hiding interruptions)
  Event 1: 00:00:00 - 00:00:56
  Event 2: 00:02:29 - 00:05:31
  Event 3: 00:05:45 - 00:05:46
Title B
  Event 1: 00:01:00 - 00:02:00
Title C
  Event 1: 00:05:40 - 00:05:44
```

## Why This Matters

1. **Transparency:** Shows the actual sequence of activities
2. **Accuracy:** Doesn't hide context switches and task interruptions
3. **Analysis:** Reveals when user switched away from a task and came back
4. **Reassignment:** Allows selecting specific continuous sessions, not scattered fragments
5. **Honesty:** Represents ActivityWatch data as it was actually recorded

## Implementation Requirements

When building the tree display:
1. Events must be sorted chronologically across ALL titles in an app
2. When the same title appears non-consecutively, assign a session number
3. Group events only when the previous event is from the same title
4. Break grouping whenever ANY other title appears between events

## Examples

### Example 1: Multiple Interruptions
```
Raw events (chronological):
  00:00-00:01  File Editor "main.py"
  00:01-00:02  Browser "Gmail"       ← Breaks File Editor continuity
  00:02-00:03  File Editor "main.py" ← NEW session of File Editor
  00:03-00:04  Browser "Gmail"       ← Breaks File Editor continuity
  00:04-00:05  File Editor "main.py" ← NEW session of File Editor

Display:
  File Editor "main.py" - Session 1 (00:00-00:01)
  Browser "Gmail" (00:01-00:02)
  File Editor "main.py" - Session 2 (00:02-00:03)
  Browser "Gmail" (00:03-00:04)
  File Editor "main.py" - Session 3 (00:04-00:05)
```

### Example 2: Single Continuous Session
```
Raw events (chronological):
  00:00-00:01  IDE "function.py"
  00:01-00:02  IDE "function.py"    ← Same title, continuous
  00:02-00:03  IDE "function.py"    ← Same title, continuous

Display:
  IDE "function.py" - Session 1 (00:00-00:03)  ← Single session, continuous
    Event 1: 00:00-00:01
    Event 2: 00:01-00:02
    Event 3: 00:02-00:03
```

## Algorithm

```python
def group_events_by_continuous_sessions(all_events_chronological):
    """
    Group events by continuous sessions.
    Events are grouped only if:
    1. Same title as previous event
    2. No other titles between them
    """
    sessions = []
    current_session = None
    
    for event in all_events_chronological:
        title = event['title']
        
        if current_session is None or current_session['title'] != title:
            # Start new session (different title or first event)
            if current_session is not None:
                sessions.append(current_session)
            current_session = {
                'title': title,
                'session_num': count_previous_sessions_of_title(title, sessions),
                'events': [event],
                'start': event['start'],
                'end': event['end'],
            }
        else:
            # Continue current session (same title)
            current_session['events'].append(event)
            current_session['end'] = event['end']
    
    if current_session:
        sessions.append(current_session)
    
    return sessions
```

## Compliance with "DO NOT MODIFY TIMINGS" Rule

✓ This requirement respects the core rule:
- Individual event times are NEVER modified
- Session grouping is organizational, not time-manipulation
- Raw event start/end times are preserved exactly
- Only the PRESENTATION changes (chronological ordering + session breaks)

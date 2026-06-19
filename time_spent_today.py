#!/bin/env python3
# NOTE: Might not treat timezones correctly.

from datetime import datetime, time, timedelta
import socket

import aw_client, aw_transform
import json
import pytz

if __name__ == "__main__":
    # Set this to your AFK bucket
    bucket_id = f"aw-watcher-window_{socket.gethostname()}"
    bucket_tmux_id = f"aw-watcher-tmux"
    bucket_tasks_id = f"aw-watcher-warrior_{socket.gethostname()}"
    bucket_afk_id = f"aw-watcher-afk_{socket.gethostname()}"

    local_timezone = pytz.timezone('America/Mexico_City')

    daystart = datetime.combine(datetime.now(local_timezone).date(), time(4, tzinfo=local_timezone)).astimezone(pytz.utc)
    dayend = daystart + timedelta(days=1)
    # dayend = datetime.combine(datetime.now(local_timezone).date(), time(4,0,0, tzinfo=local_timezone)).astimezone(pytz.utc)
    # daystart = dayend - timedelta(days=1)

    awc = aw_client.ActivityWatchClient("TimeReportClient")

    windows = awc.get_events(bucket_id, start=daystart, end=dayend)
    tmux_sessions = awc.get_events(bucket_tmux_id, start=daystart, end=dayend)
    tasks = awc.get_events(bucket_tasks_id, start=daystart, end=dayend)
    events_nafk = awc.get_events(bucket_afk_id, start=daystart, end=dayend)

    events_nafk = [e for e in events_nafk if e.data["status"] == "not-afk"]
    total_duration_on_keyboard = sum((e.duration for e in events_nafk), timedelta())

    events = windows+tmux_sessions
    events = aw_transform.filter_period_intersect(events, tasks)
#    events = aw_transform.period_union(windows,tmux_sessions)

    tasks = aw_transform.sort_by_timestamp(tasks)
    events = aw_transform.sort_by_timestamp(events)

    print(f"Timeframe {daystart.astimezone(local_timezone)} - {dayend.astimezone(local_timezone)}")
    total_tasks_duration = sum((e.duration for e in tasks), timedelta())
    total_duration = timedelta(0)


    sidx =0
    for t in tasks:
        if 'project' in t.data:
            print(f"{t.timestamp.astimezone(local_timezone).time()} {t.data['project']}:\t{t.data['title']}")
        else:
            print(f"{t.timestamp.astimezone(local_timezone).time()} {t.data['title']}")
        
        tend = t.timestamp + t.duration
        online_duration= timedelta(0)
        while sidx < len(events) and events[sidx].timestamp < t.timestamp:
            sidx=sidx+1

        eidx = sidx
        while eidx < len(events) and events[eidx].timestamp < tend:
            online_duration += events[eidx].duration
            eidx=eidx+1

        total_duration += online_duration
        framed_events = events[sidx:eidx]
        sidx=eidx

        events_compendium = aw_transform.merge_events_by_keys(framed_events, ["app", "title", "pane_title","pane_current_command",  "pane_current_path"])
        for e in events_compendium:
            #print(json.dumps(e, default=str))
            print(f"\t\t{e.data.get('app', '[' + e.data.get('pane_current_path', '') + '] [' + e.data.get('pane_current_command', '') + '] ' + e.data.get('pane_title','') ) + ' ' + e.data.get('title',''):<100} {str(e.duration):>20}")

        print(f"{str(online_duration):>120}")
        print(f"{t.data['status'].upper():>20} {str(t.duration):>110}\n")


#    events = tasks
    #events = [e for e in events if e.data["status"] == "not-afk"]
    print(f"{'Total time working on computer (billable sessions)':<120} {total_duration}")
    print(f"{'Total time on tasks (offline)':<120} {total_tasks_duration}")
    print(f"{'Total time spent on computer today':<120} {total_duration_on_keyboard}")

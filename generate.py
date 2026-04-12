#!/usr/bin/env python3
"""
Hourly booking page generator.
Uses events().list() on each calendar — proven to work with readonly scope.
Applies freebusy logic: any non-transparent timed event blocks that slot.
"""

import os, json, re, sys
from datetime import datetime, timedelta, date

def get_gcal_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds_data = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    token_data  = json.loads(os.environ["GOOGLE_TOKEN_JSON"])

    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=creds_data["installed"]["token_uri"],
        client_id=creds_data["installed"]["client_id"],
        client_secret=creds_data["installed"]["client_secret"],
        scopes=token_data.get("scopes", ["https://www.googleapis.com/auth/calendar.readonly"]),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("calendar", "v3", credentials=creds)


CALENDARS = [
    "dory.ellis@gmail.com",
    "michaelsgarfinkle@gmail.com",
    "crk94q56n8o7fkj12h8880valiieinss@import.calendar.google.com",
    "family03093285931532505689@group.calendar.google.com",
    "cdiog0aatmbjq9l3tkefnif53a3h5dno@import.calendar.google.com",
]
HOLIDAY_CAL    = "en.usa#holiday@group.v.calendar.google.com"
CHIEF_KEYWORDS = ["13 e 19", "flatiron district clubhouse", "chief"]
TRAVEL_BUFFER  = timedelta(minutes=30)
EARLIEST_HOUR  = 10
LATEST_HOUR    = 18
DAYS_AHEAD     = 28


def parse_et(dt_str):
    """Parse a dateTime string, stripping UTC offset, treating result as ET local."""
    return datetime.fromisoformat(re.sub(r"[+-]\d{2}:\d{2}$|Z$", "", dt_str))


def fetch_all_events(service, cal_id, time_min, time_max):
    events, page_token = [], None
    while True:
        try:
            r = service.events().list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=250,
                singleEvents=True,
                orderBy="startTime",
                timeZone="America/New_York",
                pageToken=page_token,
            ).execute()
        except Exception as e:
            print(f"  ⚠ Could not fetch {cal_id}: {e}")
            break
        events.extend(r.get("items", []))
        page_token = r.get("nextPageToken")
        if not page_token:
            break
    return events


def build_busy_and_allday(service, today, end_date):
    time_min = today.isoformat() + "T00:00:00"
    time_max = end_date.isoformat() + "T23:59:59"

    busy   = []  # list of {s, e} strings
    allday = set()

    for cal_id in CALENDARS:
        events = fetch_all_events(service, cal_id, time_min, time_max)
        print(f"  {cal_id[:40]}: {len(events)} events")

        for ev in events:
            transparency = ev.get("transparency", "")
            summary = (ev.get("summary") or "").strip()
            status  = ev.get("status", "confirmed")

            if status == "cancelled":
                continue
            if transparency == "transparent":
                continue
            if summary.lower() in ("free", ""):
                continue

            start_info = ev.get("start", {})
            end_info   = ev.get("end",   {})

            # All-day event
            if start_info.get("date"):
                s = date.fromisoformat(start_info["date"])
                e = date.fromisoformat(end_info["date"])
                d = s
                while d < e:
                    allday.add(d.isoformat())
                    d += timedelta(days=1)
                continue

            # Timed event
            if start_info.get("dateTime"):
                s = parse_et(start_info["dateTime"])
                e = parse_et(end_info["dateTime"])

                # Apply Chief/Flatiron travel buffer
                loc = (ev.get("location") or "").lower()
                if any(k in loc for k in CHIEF_KEYWORDS):
                    s -= TRAVEL_BUFFER
                    e += TRAVEL_BUFFER

                busy.append({
                    "s": s.strftime("%Y-%m-%dT%H:%M"),
                    "e": e.strftime("%Y-%m-%dT%H:%M"),
                })

    return busy, sorted(allday)


def get_holidays(service, today, end_date):
    holidays = {}
    time_min = today.isoformat() + "T00:00:00"
    time_max = end_date.isoformat() + "T23:59:59"
    events = fetch_all_events(service, HOLIDAY_CAL, time_min, time_max)
    for ev in events:
        if ev.get("start", {}).get("date"):
            holidays[ev["start"]["date"]] = ev.get("summary", "")
    return holidays


def render_html(busy, allday, holidays, today):
    today_str   = today.isoformat()
    updated     = datetime.now().strftime("%B %-d, %Y at %-I:%M %p ET")
    busy_js     = json.dumps(busy,     separators=(",", ":"))
    allday_js   = json.dumps(allday,   separators=(",", ":"))
    holidays_js = json.dumps(holidays, separators=(",", ":"))

    template_path = os.path.join(os.path.dirname(__file__), "template.html")
    with open(template_path) as f:
        html = f.read()

    html = html.replace("__BUSY_JS__",     busy_js)
    html = html.replace("__ALLDAY_JS__",   allday_js)
    html = html.replace("__HOLIDAYS_JS__", holidays_js)
    html = html.replace("__TODAY_STR__",   today_str)
    html = html.replace("__UPDATED__",     updated)
    html = html.replace("__EARLIEST__",    str(EARLIEST_HOUR))
    html = html.replace("__LATEST__",      str(LATEST_HOUR))

    # Verify all placeholders filled
    for p in ["__BUSY_JS__", "__ALLDAY_JS__", "__HOLIDAYS_JS__", "__TODAY_STR__", "__UPDATED__"]:
        if p in html:
            print(f"  ⚠ Placeholder not filled: {p}")

    return html


if __name__ == "__main__":
    print("Connecting to Google Calendar...")
    service  = get_gcal_service()
    today    = date.today()
    end_date = today + timedelta(days=DAYS_AHEAD)
    print(f"Window: {today} → {end_date}")

    print("Fetching events from all calendars...")
    busy, allday = build_busy_and_allday(service, today, end_date)
    print(f"Total: {len(busy)} busy blocks, {len(allday)} all-day dates")

    if len(busy) == 0:
        print("⚠ WARNING: zero busy blocks — something may be wrong with auth or calendar access")

    print("Fetching holidays...")
    holidays = get_holidays(service, today, end_date)
    print(f"  {len(holidays)} holidays")

    html = render_html(busy, allday, holidays, today)
    with open("index.html", "w") as f:
        f.write(html)
    print(f"✓ Written index.html ({len(html):,} bytes) with {len(busy)} busy blocks")

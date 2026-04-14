#!/usr/bin/env python3
"""
Hourly booking page generator.
Fetches events from all calendars and applies smart filtering:
- Skips transparent/free events
- Skips events belonging to Michael, Ted, Graciela, kids etc.
- Applies Chief/Flatiron +30min travel buffer
- Applies Ganz +30min buffer
- Respects transparency changes in real-time
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
GANZ_KEYWORDS  = ["ganz"]
TRAVEL_BUFFER  = timedelta(minutes=30)
EARLIEST_HOUR  = 10
LATEST_HOUR    = 17
DAYS_AHEAD     = 142

# All-day events whose summaries indicate they are NOT Dory's constraint.
# If the event summary contains any of these, skip it for all-day blocking.
ALLDAY_SKIP_KEYWORDS = [
    "graciela",          # nanny — Dory is free
    "m in toronto",      # Michael traveling
    "m in ",             # Michael traveling (generic)
    "m: ",               # Michael's events
    "m&w in",            # Michael + Wendy
    "m presenting",      # Michael at conference
    "ted in",            # Ted traveling
    "ted out",           # Ted's plans
    "wendy",             # Wendy/kids schedule
    "kids",              # Kids schedule (transparent anyway but just in case)
    "school",            # School schedule
    "himare",            # Albania cities — Michael with kids
    "lezhë",             # Albania
    "theth",             # Albania
    "tirana",            # Albania (Michael)
    "holiday in",        # Michael family holidays
    "awesome on",        # Michael's boat
    "blood donation",    # Michael
    "dr sarasohn",       # Michael's therapy (not Dory's constraint)
    "block for kids",    # Kids overnight block (timed, handled separately)
    "free press",        # Free Press events (transparent)
]

# All-day events that DO block Dory regardless of who organized them
ALLDAY_KEEP_KEYWORDS = [
    "lily and chad",
    "nada",
    "katz reunion",
    "hudson overnight",
    "dory",              # anything with "dory" in it is hers
    "out",               # OUT days
    "governors ball",
    "rhinebeck",
    "stay",              # hotel/airbnb stays that are hers
    "paris",
    "london",
    "cannes",
    "albania",
]


def should_skip_allday(summary):
    """Return True if this all-day event should NOT block Dory's calendar."""
    s = summary.lower().strip()
    # Empty or "free" always skip
    if s in ("free", ""):
        return True
    # If it matches a keep keyword, never skip
    if any(k in s for k in ALLDAY_KEEP_KEYWORDS):
        return False
    # If it matches a skip keyword, skip it
    if any(k in s for k in ALLDAY_SKIP_KEYWORDS):
        return True
    # Default: block (conservative — better to be busy than show false availability)
    return False


def parse_et(dt_str):
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
    time_min = today.isoformat() + "T00:00:00Z"
    time_max = end_date.isoformat() + "T23:59:59Z"

    busy   = []
    allday = set()

    for cal_id in CALENDARS:
        events = fetch_all_events(service, cal_id, time_min, time_max)
        print(f"  {cal_id[:44]}: {len(events)} events")

        for ev in events:
            transparency = ev.get("transparency", "")
            summary      = (ev.get("summary") or "").strip()
            status       = ev.get("status", "confirmed")

            if status == "cancelled":
                continue
            if transparency == "transparent":
                continue
            if summary.lower() in ("free", ""):
                continue

            start_info = ev.get("start", {})
            end_info   = ev.get("end",   {})

            # ── All-day event ────────────────────────────────────────
            if start_info.get("date"):
                if should_skip_allday(summary):
                    print(f"    SKIP all-day: {start_info['date']} [{summary}]")
                    continue
                s = date.fromisoformat(start_info["date"])
                e = date.fromisoformat(end_info["date"])
                d = s
                while d < e:
                    allday.add(d.isoformat())
                    d += timedelta(days=1)
                print(f"    BLOCK all-day: {start_info['date']}→{end_info['date']} [{summary}]")
                continue

            # ── Timed event ──────────────────────────────────────────
            if start_info.get("dateTime"):
                s = parse_et(start_info["dateTime"])
                e = parse_et(end_info["dateTime"])

                # Chief/Flatiron travel buffer
                loc = (ev.get("location") or "").lower()
                if any(k in loc for k in CHIEF_KEYWORDS):
                    s -= TRAVEL_BUFFER
                    e += TRAVEL_BUFFER

                # Ganz buffer
                if any(k in summary.lower() for k in GANZ_KEYWORDS):
                    s -= TRAVEL_BUFFER
                    e += TRAVEL_BUFFER

                busy.append({
                    "s": s.strftime("%Y-%m-%dT%H:%M"),
                    "e": e.strftime("%Y-%m-%dT%H:%M"),
                })

    return busy, sorted(allday)


def get_holidays(service, today, end_date):
    holidays = {}
    time_min = today.isoformat() + "T00:00:00Z"
    time_max = end_date.isoformat() + "T23:59:59Z"
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
        print("⚠ WARNING: zero busy blocks — auth or calendar access issue")

    print("Fetching holidays...")
    holidays = get_holidays(service, today, end_date)
    print(f"  {len(holidays)} holidays")

    # Fallback: if fetch is thin, merge with cached data for future months
    try:
        if os.path.exists("busy_data.json"):
            with open("busy_data.json") as cf:
                cached = json.load(cf)
            cached_busy   = cached.get("busy", [])
            cached_allday = cached.get("allday", [])
            if len(busy) < 200 and len(cached_busy) > len(busy):
                print(f"  ↩ Thin fetch ({len(busy)}) — merging with {len(cached_busy)} cached blocks")
                cutoff = (today + timedelta(days=14)).isoformat()
                fresh      = [b for b in busy        if b["s"][:10] <= cutoff]
                old_cached = [b for b in cached_busy if b["s"][:10] >  cutoff]
                busy   = fresh + old_cached
                # For allday: use freshly-fetched for near term, cached for far future
                fresh_allday  = {d for d in allday        if d <= cutoff}
                old_allday    = {d for d in cached_allday if d >  cutoff}
                allday = sorted(fresh_allday | old_allday)
                print(f"  ✓ Merged: {len(busy)} busy, {len(allday)} allday")
    except Exception as ex:
        print(f"  Warning: fallback merge failed: {ex}")

    # Save best data
    with open("busy_data.json", "w") as f:
        json.dump({"busy": busy, "allday": allday, "holidays": holidays}, f)

    html = render_html(busy, allday, holidays, today)
    with open("index.html", "w") as f:
        f.write(html)
    print(f"✓ Written index.html ({len(html):,} bytes) — {len(busy)} busy, {len(allday)} allday")

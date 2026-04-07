#!/usr/bin/env python3
"""
Hourly booking page generator.
Uses Google Calendar API directly with OAuth2 credentials.

Required env vars (stored as GitHub Secrets):
  ANTHROPIC_API_KEY       - your Anthropic API key (for future AI features)
  GOOGLE_CREDENTIALS_JSON - contents of credentials.json from Google Cloud
  GOOGLE_TOKEN_JSON       - contents of token.json from local OAuth flow
"""

import os, json, re, sys
from datetime import datetime, timedelta, date

# ── Google Calendar via API ────────────────────────────────────────────
def get_gcal_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds_json  = os.environ["GOOGLE_CREDENTIALS_JSON"]
    token_json  = os.environ["GOOGLE_TOKEN_JSON"]

    creds_data  = json.loads(creds_json)
    token_data  = json.loads(token_json)

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

CALENDARS = {
    "primary": "dory.ellis@gmail.com",
    "dm":      "michaelsgarfinkle@gmail.com",
    "ec":      "crk94q56n8o7fkj12h8880valiieinss@import.calendar.google.com",
    "holiday": "en.usa#holiday@group.v.calendar.google.com",
    "family":  "family03093285931532505689@group.calendar.google.com",
    "work":    "cdiog0aatmbjq9l3tkefnif53a3h5dno@import.calendar.google.com",
}

CHIEF_KEYWORDS = ["19th st", "flatiron", "chief", "13 e 19"]
TRAVEL_BUFFER  = timedelta(minutes=30)
EARLIEST_HOUR  = 10
LATEST_HOUR    = 18
DAYS_AHEAD     = 28


def fetch_events(service, cal_id, time_min, time_max):
    events = []
    page_token = None
    while True:
        result = service.events().list(
            calendarId=cal_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=250,
            singleEvents=True,
            orderBy="startTime",
            timeZone="America/New_York",
            pageToken=page_token,
        ).execute()
        events.extend(result.get("items", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return events


def is_chief(ev):
    loc = (ev.get("location") or "").lower()
    summary = (ev.get("summary") or "").lower()
    return any(k in loc or k in summary for k in CHIEF_KEYWORDS)


def build_busy_blocks(service, today, end_date):
    time_min = today.isoformat() + "T00:00:00"
    time_max = end_date.isoformat() + "T23:59:59"

    busy   = []   # {s, e} datetime pairs
    allday = set()
    holidays = {}

    for key, cal_id in CALENDARS.items():
        try:
            events = fetch_events(service, cal_id, time_min, time_max)
        except Exception as e:
            print(f"  Warning: could not fetch {key}: {e}")
            continue

        for ev in events:
            transparency = ev.get("transparency", "")
            summary = (ev.get("summary") or "").strip()

            # Skip free/transparent events
            if transparency == "transparent":
                continue
            if summary.lower() in ("free", ""):
                continue

            start_info = ev.get("start", {})
            end_info   = ev.get("end", {})

            # All-day events
            if start_info.get("date"):
                if key == "holiday":
                    holidays[start_info["date"]] = summary
                    continue
                # Mark each date in the all-day range as blocked
                s = date.fromisoformat(start_info["date"])
                e = date.fromisoformat(end_info["date"])
                d = s
                while d < e:
                    allday.add(d.isoformat())
                    d += timedelta(days=1)
                continue

            # Timed events
            if start_info.get("dateTime"):
                def parse_dt(s):
                    # Remove offset, parse as naive
                    s = re.sub(r"[+-]\d{2}:\d{2}$", "", s)
                    return datetime.fromisoformat(s)

                ev_s = parse_dt(start_info["dateTime"])
                ev_e = parse_dt(end_info["dateTime"])

                if is_chief(ev):
                    ev_s -= TRAVEL_BUFFER
                    ev_e += TRAVEL_BUFFER

                busy.append({"s": ev_s.strftime("%Y-%m-%dT%H:%M"),
                             "e": ev_e.strftime("%Y-%m-%dT%H:%M")})

    return busy, sorted(allday), holidays


def render_html(busy, allday, holidays, today):
    today_str = today.isoformat()
    updated   = datetime.now().strftime("%B %-d, %Y at %-I:%M %p ET")
    busy_js     = json.dumps(busy,     separators=(",", ":"))
    allday_js   = json.dumps(allday,   separators=(",", ":"))
    holidays_js = json.dumps(holidays, separators=(",", ":"))

    # Read template and inject data
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

    return html


if __name__ == "__main__":
    print("Connecting to Google Calendar...")
    service = get_gcal_service()

    today    = date.today()
    end_date = today + timedelta(days=DAYS_AHEAD)
    print(f"Fetching events {today} → {end_date}")

    busy, allday, holidays = build_busy_blocks(service, today, end_date)
    print(f"  {len(busy)} busy blocks, {len(allday)} all-day blocks, {len(holidays)} holidays")

    html = render_html(busy, allday, holidays, today)

    with open("index.html", "w") as f:
        f.write(html)
    print(f"Written index.html ({len(html):,} bytes)")

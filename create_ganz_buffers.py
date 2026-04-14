#!/usr/bin/env python3
"""
One-time script: creates 30-min travel buffer events before each Ganz Thursday.
Runs via GitHub Actions using existing Google credentials.
"""

import os, json
from datetime import date, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

GANZ_DATES = [
    "2026-04-23","2026-04-30",
    "2026-05-07","2026-05-14","2026-05-21","2026-05-28",
    "2026-06-04","2026-06-11","2026-06-18","2026-06-25",
    "2026-07-02","2026-07-09","2026-07-16","2026-07-23",
]
# Skip when Dory is traveling (Albania/Europe Aug trip)

def get_service():
    creds_data = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    token_data  = json.loads(os.environ["GOOGLE_TOKEN_JSON"])
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=creds_data["installed"]["token_uri"],
        client_id=creds_data["installed"]["client_id"],
        client_secret=creds_data["installed"]["client_secret"],
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("calendar", "v3", credentials=creds)

if __name__ == "__main__":
    service = get_service()
    today = date.today()
    created = 0

    for d in GANZ_DATES:
        if date.fromisoformat(d) < today:
            print(f"  SKIP (past): {d}")
            continue

        event = {
            "summary": "🚇 Travel to Ganz",
            "location": "41 Union Square W, New York, NY 10003",
            "start": {"dateTime": f"{d}T15:30:00", "timeZone": "America/New_York"},
            "end":   {"dateTime": f"{d}T16:00:00", "timeZone": "America/New_York"},
            "transparency": "opaque",
        }
        r = service.events().insert(calendarId="dory.ellis@gmail.com", body=event).execute()
        print(f"  ✓ {d} 3:30-4:00pm — id:{r['id'][:20]}")
        created += 1

    print(f"\nCreated {created} travel buffers on dory.ellis@gmail.com")

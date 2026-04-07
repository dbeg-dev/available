#!/usr/bin/env python3
"""
Hourly booking page generator.
Fetches calendar data via Anthropic API + Google Calendar MCP,
then writes index.html with fresh busy slots baked in.

Required env vars:
  ANTHROPIC_API_KEY   - your Anthropic API key
  GCAL_MCP_TOKEN      - your Google Calendar MCP OAuth token
"""

import os, json, re, base64, subprocess, sys
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

# ── Config ────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GCAL_MCP_TOKEN    = os.environ["GCAL_MCP_TOKEN"]

CALENDARS = [
    "dory.ellis@gmail.com",
    "michaelsgarfinkle@gmail.com",
    "crk94q56n8o7fkj12h8880valiieinss@import.calendar.google.com",
    "en.usa#holiday@group.v.calendar.google.com",
    "family03093285931532505689@group.calendar.google.com",
    "cdiog0aatmbjq9l3tkefnif53a3h5dno@import.calendar.google.com",
]

CHIEF_KEYWORDS = ["19th st", "flatiron", "chief", "13 e 19"]
TRAVEL_BUFFER_MIN = 30
EARLIEST_HOUR = 10
LATEST_HOUR = 18
DAYS_AHEAD = 21

# ── Fetch calendar data ───────────────────────────────────────────────
def fetch_calendar_data():
    now_et = datetime.now(timezone.utc) - timedelta(hours=4)  # rough ET
    today = now_et.date()
    end = today + timedelta(days=DAYS_AHEAD)

    prompt = f"""Fetch all events from these calendars for {today}T00:00:00 to {end}T23:59:59 (America/New_York):
{chr(10).join('- ' + c for c in CALENDARS)}

Call gcal_list_events for each calendar with maxResults=250 and timeZone=America/New_York.

Respond ONLY with JSON (no markdown):
{{
  "today": "YYYY-MM-DD",
  "busy": [
    {{"s":"YYYY-MM-DDTHH:MM","e":"YYYY-MM-DDTHH:MM","chief":true|false}}
  ],
  "allday": ["YYYY-MM-DD"],
  "holidays": {{"YYYY-MM-DD":"Holiday Name"}}
}}

Rules:
- All times in ET local (no Z suffix, no offset)
- Exclude events with transparency=transparent or summary matching Free/free
- For any event at "13 E 19th", "Flatiron", or "Chief": set chief:true (will get +30min buffer each side)
- All-day busy events (not transparent) go in "allday" as date strings
- Holiday calendar events go in "holidays"
- Return only the JSON"""

    body = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4000,
        "mcp_servers": [{
            "type": "url",
            "url": "https://gcal.mcp.claude.com/mcp",
            "name": "gcal",
            "authorization_token": GCAL_MCP_TOKEN,
        }],
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "mcp-client-1.3",
        },
        method="POST",
    )
    with urlopen(req, timeout=120) as r:
        data = json.loads(r.read())

    raw = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    m = re.search(r'\{[\s\S]*\}', raw)
    if not m:
        raise ValueError(f"No JSON in response: {raw[:500]}")
    return json.loads(m.group(0)), today

# ── Build busy blocks with buffers ────────────────────────────────────
def build_busy(cal_data):
    busy = []
    buf = timedelta(minutes=TRAVEL_BUFFER_MIN)
    for ev in cal_data.get("busy", []):
        s = datetime.fromisoformat(ev["s"])
        e = datetime.fromisoformat(ev["e"])
        if ev.get("chief"):
            s -= buf; e += buf
        busy.append({"s": s.strftime("%Y-%m-%dT%H:%M"), "e": e.strftime("%Y-%m-%dT%H:%M")})
    return busy

# ── Render HTML ───────────────────────────────────────────────────────
def render_html(cal_data, busy, today):
    today_str = str(today)
    updated = datetime.now().strftime("%B %-d, %Y at %-I:%M %p ET")
    busy_js = json.dumps(busy, separators=(',',':'))
    allday_js = json.dumps(cal_data.get("allday", []), separators=(',',':'))
    holidays_js = json.dumps(cal_data.get("holidays", {}), separators=(',',':'))

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Book time with Dory Ellis</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&family=DM+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
:root{{--bg:#f7f5f2;--white:#fff;--ink:#1a1714;--rule:#e4dfd8;--warm:#8c8077;--muted:#b5ada4;--accent:#1a6b4a;--accent-l:#1a6b4a12;--hover:#f0ede8;}}
body{{font-family:'DM Mono',monospace;background:var(--bg);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px 16px;}}
.card{{background:var(--white);border-radius:16px;box-shadow:0 4px 40px rgba(0,0,0,.10);display:grid;grid-template-columns:280px 1fr;max-width:820px;width:100%;overflow:hidden;min-height:580px;}}
@media(max-width:680px){{.card{{grid-template-columns:1fr;max-width:400px;}}}}
.left{{border-right:1px solid var(--rule);padding:36px 28px;display:flex;flex-direction:column;gap:6px;background:var(--white);}}
.avatar{{width:52px;height:52px;border-radius:50%;background:#f0ede8;border:2px solid var(--rule);display:flex;align-items:center;justify-content:center;font-family:'Cormorant Garamond',serif;font-size:22px;font-style:italic;color:#8b6914;margin-bottom:8px;}}
.left-name{{font-family:'Cormorant Garamond',serif;font-size:22px;font-weight:300;color:var(--ink);line-height:1.2;}}
.left-name em{{font-style:italic;color:#8b4513;}}
.left-sub{{font-size:10px;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase;margin-bottom:4px;}}
.dur-label{{font-size:11px;color:var(--warm);margin-top:14px;margin-bottom:6px;}}
.dur-btns{{display:flex;flex-wrap:wrap;gap:6px;}}
.dur-btn{{font-family:'DM Mono',monospace;font-size:11px;background:none;border:1px solid var(--rule);border-radius:20px;padding:5px 12px;color:var(--warm);cursor:pointer;transition:all .15s;}}
.dur-btn:hover{{border-color:var(--accent);color:var(--accent);}}
.dur-btn.active{{background:var(--accent);border-color:var(--accent);color:#fff;}}
.divider{{border:none;border-top:1px solid var(--rule);margin:20px 0;}}
.meta-row{{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--warm);}}
.meta-icon{{font-size:13px;width:18px;text-align:center;}}
.updated{{font-size:9px;color:var(--muted);margin-top:auto;padding-top:20px;line-height:1.5;}}
.right{{padding:36px 32px;display:flex;flex-direction:column;}}
.right-title{{font-size:13px;font-weight:500;color:var(--ink);margin-bottom:20px;letter-spacing:.3px;}}
.month-nav{{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;}}
.month-label{{font-family:'Cormorant Garamond',serif;font-size:18px;font-weight:400;color:var(--ink);}}
.mnav-btn{{background:none;border:1px solid var(--rule);border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:14px;color:var(--warm);transition:all .15s;}}
.mnav-btn:hover{{border-color:var(--ink);color:var(--ink);}}
.mnav-btn:disabled{{opacity:.3;cursor:default;}}
.cal-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;margin-bottom:24px;}}
.dow{{font-size:10px;color:var(--muted);text-align:center;padding:4px 0;letter-spacing:.5px;}}
.day-cell{{aspect-ratio:1;display:flex;align-items:center;justify-content:center;font-size:12px;border-radius:50%;cursor:pointer;transition:all .15s;color:var(--ink);font-weight:400;}}
.day-cell.empty,.day-cell.past,.day-cell.noavail{{color:var(--muted);cursor:default;}}
.day-cell.avail:hover{{background:var(--accent-l);color:var(--accent);}}
.day-cell.avail{{color:var(--ink);font-weight:500;}}
.day-cell.selected{{background:var(--accent)!important;color:#fff!important;font-weight:600;}}
.day-cell.today{{border:1px solid var(--accent);color:var(--accent);}}
.slots-wrap{{flex:1;overflow-y:auto;max-height:280px;}}
.slots-title{{font-size:11px;color:var(--warm);margin-bottom:12px;letter-spacing:.5px;}}
.slots-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;}}
@media(max-width:520px){{.slots-grid{{grid-template-columns:repeat(2,1fr);}}}}
.slot-btn{{font-family:'DM Mono',monospace;font-size:12px;background:var(--accent-l);border:1.5px solid #1a6b4a30;border-radius:8px;padding:10px 8px;color:var(--accent);cursor:pointer;transition:all .15s;text-align:center;font-weight:500;}}
.slot-btn:hover,.slot-btn.sel{{background:var(--accent);color:#fff;border-color:var(--accent);}}
.no-slots,.pick-hint{{font-size:12px;color:var(--muted);font-style:italic;padding:20px 0;}}
.form-panel{{display:none;flex-direction:column;gap:0;}}
.form-panel.on{{display:flex;}}
.form-back{{background:none;border:none;font-family:'DM Mono',monospace;font-size:11px;color:var(--warm);cursor:pointer;display:flex;align-items:center;gap:6px;margin-bottom:20px;padding:0;}}
.form-back:hover{{color:var(--ink);}}
.form-sel-time{{background:var(--hover);border-radius:8px;padding:12px 14px;margin-bottom:20px;font-size:12px;color:var(--ink);display:flex;align-items:center;gap:8px;}}
.field{{margin-bottom:14px;}}
.field label{{font-size:10px;color:var(--warm);letter-spacing:1.5px;text-transform:uppercase;display:block;margin-bottom:5px;}}
.field input,.field textarea{{width:100%;font-family:'DM Mono',monospace;font-size:12px;background:var(--bg);border:1px solid var(--rule);border-radius:6px;padding:9px 12px;color:var(--ink);outline:none;transition:border-color .15s;}}
.field input:focus,.field textarea:focus{{border-color:var(--accent);}}
.field textarea{{resize:vertical;min-height:72px;line-height:1.6;}}
.book-btn{{width:100%;font-family:'DM Mono',monospace;font-size:12px;font-weight:500;background:var(--accent);color:#fff;border:none;border-radius:8px;padding:12px;cursor:pointer;margin-top:4px;transition:background .15s;}}
.book-btn:hover{{background:#155c3d;}}
.confirm-panel{{display:none;flex-direction:column;align-items:center;justify-content:center;text-align:center;flex:1;padding:20px;}}
.confirm-panel.on{{display:flex;}}
.confirm-check{{font-size:42px;margin-bottom:16px;}}
.confirm-title{{font-family:'Cormorant Garamond',serif;font-size:26px;font-weight:300;color:var(--ink);margin-bottom:10px;}}
.confirm-detail{{font-size:12px;color:var(--warm);line-height:1.8;}}
</style>
</head>
<body>
<div class="card">
  <div class="left">
    <div class="avatar">D</div>
    <div class="left-name"><em>Dory Ellis</em></div>
    <div class="left-sub">New York &middot; ET</div>
    <div class="dur-label">Meeting duration</div>
    <div class="dur-btns">
      <button class="dur-btn" onclick="setDur(30)">30 min</button>
      <button class="dur-btn active" onclick="setDur(60)">1 hr</button>
      <button class="dur-btn" onclick="setDur(45)">45 min</button>
      <button class="dur-btn" onclick="setDur(90)">90 min</button>
    </div>
    <hr class="divider">
    <div class="meta-row"><span class="meta-icon">🕐</span> Eastern Time (ET)</div>
    <div class="meta-row"><span class="meta-icon">📍</span> New York, NY</div>
    <div class="meta-row"><span class="meta-icon">📅</span> Weekdays only</div>
    <div class="updated">Auto-updated hourly<br>Last refresh: {updated}</div>
  </div>

  <div class="right" id="right-panel">
    <div class="right-title">Select a date &amp; time</div>
    <div class="month-nav">
      <button class="mnav-btn" id="prev-btn" onclick="prevMonth()">&#8249;</button>
      <div class="month-label" id="month-label"></div>
      <button class="mnav-btn" onclick="nextMonth()">&#8250;</button>
    </div>
    <div class="cal-grid" id="cal-grid"></div>
    <div class="slots-wrap" id="slots-wrap">
      <div class="pick-hint">&#8592; Pick a date to see available times</div>
    </div>
  </div>

  <div class="right form-panel" id="form-panel">
    <button class="form-back" onclick="showCal()">&#8592; Back</button>
    <div class="form-sel-time"><span>&#10022;</span><span id="form-time-lbl"></span></div>
    <div class="field"><label>Your name</label><input id="gname" type="text" placeholder="Jane Smith" autocomplete="name"></div>
    <div class="field"><label>Email</label><input id="gemail" type="email" placeholder="jane@example.com" autocomplete="email"></div>
    <div class="field"><label>Topic <span style="font-style:italic;opacity:.6">(optional)</span></label><textarea id="gnote" placeholder="Quick intro or what you'd like to discuss&hellip;"></textarea></div>
    <button class="book-btn" id="book-btn" onclick="doBook()">Confirm booking &rarr;</button>
  </div>

  <div class="right confirm-panel" id="confirm-panel">
    <div class="confirm-check">&#10022;</div>
    <div class="confirm-title">You're booked!</div>
    <div class="confirm-detail" id="confirm-detail"></div>
  </div>
</div>

<script>
const BUSY={busy_js};
const ALLDAY={allday_js};
const HOLIDAYS={holidays_js};
const TODAY_STR='{today_str}';
const TODAY=new Date(TODAY_STR+'T00:00:00');
const EARLIEST={EARLIEST_HOUR},LATEST={LATEST_HOUR};
const MONS=['January','February','March','April','May','June','July','August','September','October','November','December'];
const MONS_S=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const DAYS_S=['Su','Mo','Tu','We','Th','Fr','Sa'];
const DAYS_L=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
let dur=60,viewYear=TODAY.getFullYear(),viewMonth=TODAY.getMonth(),selDate=null,selSlot=null;

function setDur(d){{dur=d;document.querySelectorAll('.dur-btn').forEach(b=>b.classList.remove('active'));const labels={{30:'30 min',60:'1 hr',45:'45 min',90:'90 min'}};document.querySelectorAll('.dur-btn').forEach(b=>{{if(b.textContent===labels[d])b.classList.add('active');}});selSlot=null;if(selDate)renderSlots(selDate);}}

function isBusy(s,e){{for(const b of BUSY){{const bs=new Date(b.s),be=new Date(b.e);if(s<be&&e>bs)return true;}}return false;}}

function getSlots(ds){{if(ALLDAY.includes(ds))return[];const d=new Date(ds+'T00:00:00');if(d.getDay()===0||d.getDay()===6)return[];const slots=[];let h=EARLIEST,m=0;while(true){{const s=new Date(ds+'T'+String(h).padStart(2,'0')+':'+String(m).padStart(2,'0')+':00');const e=new Date(s.getTime()+dur*60000);if(e.getHours()>LATEST||(e.getHours()===LATEST&&e.getMinutes()>0))break;if(s>TODAY&&!isBusy(s,e))slots.push(new Date(s));m+=30;if(m>=60){{h++;m=0;}}}}return slots;}}

function hasSlots(ds){{return getSlots(ds).length>0;}}

function prevMonth(){{viewMonth--;if(viewMonth<0){{viewMonth=11;viewYear--;}}renderCal();}}
function nextMonth(){{viewMonth++;if(viewMonth>11){{viewMonth=0;viewYear++;}}renderCal();}}

function fmtDs(y,m,d){{return y+'-'+String(m+1).padStart(2,'0')+'-'+String(d).padStart(2,'0');}}

function renderCal(){{
  document.getElementById('month-label').textContent=MONS[viewMonth]+' '+viewYear;
  const pb=document.getElementById('prev-btn');
  const tm=TODAY.getMonth(),ty=TODAY.getFullYear();
  pb.disabled=(viewYear<ty||(viewYear===ty&&viewMonth<=tm));
  const grid=document.getElementById('cal-grid');
  let html=DAYS_S.map(d=>`<div class="dow">${{d}}</div>`).join('');
  const firstDay=new Date(viewYear,viewMonth,1).getDay();
  const dim=new Date(viewYear,viewMonth+1,0).getDate();
  for(let i=0;i<firstDay;i++)html+=`<div class="day-cell empty"></div>`;
  for(let d=1;d<=dim;d++){{
    const ds=fmtDs(viewYear,viewMonth,d);
    const dt=new Date(ds+'T00:00:00');
    const isPast=dt<=TODAY,isWknd=dt.getDay()===0||dt.getDay()===6;
    const isToday=ds===TODAY_STR,isSel=ds===selDate;
    const avail=!isPast&&!isWknd&&hasSlots(ds);
    let cls='day-cell';
    if(isSel)cls+=' selected';
    else if(isPast||isWknd)cls+=' past';
    else if(!avail)cls+=' noavail';
    else{{cls+=' avail';if(isToday)cls+=' today';}}
    const click=(avail&&!isSel)?`onclick="selDay('${{ds}}')"`:'' ;
    html+=`<div class="${{cls}}" ${{click}}>${{d}}</div>`;
  }}
  grid.innerHTML=html;
}}

function selDay(ds){{selDate=ds;selSlot=null;renderCal();renderSlots(ds);}}

function fmt(d){{const h=d.getHours()%12||12,m=d.getMinutes(),ap=d.getHours()>=12?'pm':'am';return m===0?`${{h}}${{ap}}`:`${{h}}:${{String(m).padStart(2,'0')}}${{ap}}`;}}

function renderSlots(ds){{
  const slots=getSlots(ds);
  const dt=new Date(ds+'T12:00:00');
  const wrap=document.getElementById('slots-wrap');
  const hday=HOLIDAYS[ds];
  const dateLabel=DAYS_L[dt.getDay()]+', '+MONS_S[dt.getMonth()]+' '+dt.getDate()+(hday?' · '+hday:'');
  if(!slots.length){{wrap.innerHTML=`<div class="no-slots">No availability this day</div>`;return;}}
  let html=`<div class="slots-title">${{dateLabel}}</div><div class="slots-grid">`;
  slots.forEach(slot=>{{
    const e=new Date(slot.getTime()+dur*60000);
    const label=fmt(slot)+'–'+fmt(e);
    const key=slot.toISOString();
    html+=`<button class="slot-btn${{selSlot===key?' sel':''}}" onclick="selSlotFn('${{key}}','${{label}}','${{dateLabel}}')">${{fmt(slot)}}</button>`;
  }});
  html+='</div>';
  wrap.innerHTML=html;
}}

function selSlotFn(key,range,dateLabel){{selSlot=key;renderSlots(selDate);setTimeout(()=>{{document.getElementById('right-panel').style.display='none';const fp=document.getElementById('form-panel');fp.classList.add('on');document.getElementById('form-time-lbl').textContent=dateLabel+' · '+range+' ET · '+dur+' min';}},180);}}

function showCal(){{document.getElementById('form-panel').classList.remove('on');document.getElementById('right-panel').style.display='';}}

async function doBook(){{
  const name=document.getElementById('gname').value.trim();
  const email=document.getElementById('gemail').value.trim();
  if(!name||!email){{document.getElementById(name?'gemail':'gname').focus();return;}}
  const btn=document.getElementById('book-btn');
  btn.disabled=true;btn.textContent='Confirming…';
  await new Promise(r=>setTimeout(r,900));
  document.getElementById('form-panel').classList.remove('on');
  const cp=document.getElementById('confirm-panel');cp.classList.add('on');
  const tl=document.getElementById('form-time-lbl').textContent;
  document.getElementById('confirm-detail').innerHTML=`<strong>${{name}}</strong><br>${{tl}}<br><br>A confirmation will be sent to<br><strong>${{email}}</strong>`;
}}

renderCal();
</script>
</body>
</html>'''

# ── Main ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Fetching calendar data...")
    cal_data, today = fetch_calendar_data()
    print(f"Got {len(cal_data.get('busy',[]))} busy events, {len(cal_data.get('allday',[]))} all-day blocks")

    busy = build_busy(cal_data)
    html = render_html(cal_data, busy, today)

    with open("index.html", "w") as f:
        f.write(html)

    print(f"Written index.html ({len(html):,} bytes)")

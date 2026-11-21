import json, os, time, random, uuid, datetime as dt
import requests
from playwright.sync_api import sync_playwright

CFG = {"movie": "godzilla",
       "dates": ["2026-11-21"],        # TEST DATE. Change to Mon/Tue/Wed after the test.
       "format": "IMAX"}
API_SOURCE = "district"
BOT, CHAT = os.getenv("TG_BOT"), os.getenv("TG_CHAT")
STATE = "seen.json"
DEADLINE = time.time() + 5 * 3600 + 40 * 60
PAGE = "https://www.district.in/movies/pvr-palazzo-the-nexus-vijaya-mall-chennai-CD1022274"
API = ("https://www.district.in/gw/consumer/movies/v1/cinema/sessions?meta=1&reqData=1&version=3"
       "&site_id=1&channel=mweb&child_site_id=1&platform=district&cinemaId=1022274&date=")

captured = {}
def on_req(req):
    if "/gw/" in req.url:
        for k in ("x-guest-token", "x-app-type", "x-app-version"):
            if k in req.headers:
                captured[k] = req.headers[k]

def notify(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage",
                      data={"chat_id": CHAT, "text": msg}, timeout=15)
    except Exception as e:
        print("telegram err", e)

def open_page(page):
    captured.clear()
    page.goto(PAGE, wait_until="networkidle")
    page.wait_for_timeout(3000)
    if "x-guest-token" not in captured:
        raise RuntimeError("no guest token captured")

def call(page, date):
    hdrs = dict(captured, api_source=API_SOURCE,
                **{"x-request-id": str(uuid.uuid4()), "x-trace-id": str(uuid.uuid4())})
    return page.evaluate("""async ([u, h]) => {
        const r = await fetch(u, {headers: h, credentials: 'include'});
        return {status: r.status, body: await r.text()};
    }""", [API + date, hdrs])

def fetch(page, date):
    res = call(page, date)
    if res["status"] in (401, 403):
        open_page(page)
        res = call(page, date)
    if res["status"] != 200:
        raise RuntimeError(f"{res['status']} {res['body'][:120]}")
    return json.loads(res["body"])

def is_target(s, names):
    return (CFG["movie"] in names.get(s["mid"], "").lower()
            and CFG["format"].lower() in (s.get("scrnFmt", "") + s.get("premiumLabel", "")).lower())

def check(page, state):
    open_dates = fetch(page, dt.date.today().isoformat())["data"]["sessionDates"]
    for d in CFG["dates"]:
        if d not in open_dates:
            continue
        if d not in state["dates"]:
            state["dates"].append(d)
            notify(f"Palazzo opened bookings for {d}")
        j = fetch(page, d)
        names = {m["id"]: m["name"] for m in j["meta"]["movies"]}
        for s in j["pageData"]["sessions"]:
            if s["sid"] not in state["sessions"] and is_target(s, names):
                state["sessions"].append(s["sid"])
                notify(f"{names[s['mid']]} {s['scrnFmt']} ({s['lang']})\n"
                       f"{s['showTimeText']} on {s['showDate']} - {s['avail']} seats free\n"
                       f"Open District and book now!")

def main():
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {}
    state.setdefault("dates", [])
    state.setdefault("sessions", [])
    json.dump(state, open(STATE, "w"))
    fails = 0
    with sync_playwright() as p:
        b = p.chromium.launch(headless=False)
        page = b.new_context(locale="en-IN", timezone_id="Asia/Kolkata").new_page()
        page.on("request", on_req)
        open_page(page)
        while time.time() < DEADLINE:
            try:
                check(page, state)
                fails = 0
                json.dump(state, open(STATE, "w"))
            except Exception as e:
                fails += 1
                print("err", e, flush=True)
                if fails == 3:
                    try:
                        open_page(page)
                    except Exception as e2:
                        print("reload err", e2, flush=True)
                if fails == 10:
                    notify(f"Poller failing: {e}")
            time.sleep(60 + random.uniform(0, 10))
        b.close()

main()
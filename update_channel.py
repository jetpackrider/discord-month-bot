# update_channel_stdlib.py  (no external deps)
import os
import math
import json
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from datetime import datetime

# config
COMPUPRO_URL = "https://compupro.github.io/rp-time-calculator/?daysperyear=7&lastdatechange=1757721600000&lastdateepoch=-4449513600000&fixedyears=true"
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "1417630872924061846"))
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN not set")

DISCORD_API_BASE = "https://discord.com/api/v10"
MONTH_NAMES = ["January","February","March","April","May","June","July","August","September","October","November","December"]

def rp_from_compupro_url(url):
    qs = parse_qs(urlparse(url).query)
    daysperyear = int(qs.get("daysperyear", ["7"])[0])
    lastdatechange_ms = int(qs.get("lastdatechange")[0])
    lastdateepoch_ms = int(qs.get("lastdateepoch")[0])
    MONTHS_PER_YEAR = 12
    hours_per_month = (daysperyear * 24) / MONTHS_PER_YEAR
    month_ms = hours_per_month * 3600 * 1000
    now_ms = datetime.utcnow().timestamp() * 1000.0
    elapsed_ms = now_ms - lastdatechange_ms
    total_months = math.floor(elapsed_ms / month_ms)
    years_elapsed = total_months // MONTHS_PER_YEAR
    anchor_rp_dt = datetime.utcfromtimestamp(lastdateepoch_ms / 1000.0)
    current_year = anchor_rp_dt.year + years_elapsed
    current_month = (total_months % MONTHS_PER_YEAR) + 1
    ms_into_month = elapsed_ms - (total_months * month_ms)
    return int(current_year), int(current_month), int(ms_into_month), int(month_ms)

def compute_channel_name():
    year, month, ms_into, month_len = rp_from_compupro_url(COMPUPRO_URL)
    return f"📅 {MONTH_NAMES[(month-1)%12]} {year}"

def http_get(url, token=None):
    req = Request(url, headers=(("Authorization", f"Bot {token}"),) if token else ())
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8"), resp.getcode()

def http_patch_json(url, token, data):
    body = json.dumps(data).encode("utf-8")
    req = Request(url, data=body, headers={
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json"
    }, method="PATCH")
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8"), resp.getcode()

def main():
    # log exact UTC execution time for diagnostics
    print("Run UTC:", datetime.utcnow().isoformat())
    new_name = compute_channel_name()
    print("Computed name:", new_name)
    # GET channel info
    try:
        info_text, code = http_get(f"{DISCORD_API_BASE}/channels/{CHANNEL_ID}", TOKEN)
    except Exception as e:
        print("GET failed:", e)
        return
    if code != 200:
        print("GET channel returned", code, info_text)
        return
    info = json.loads(info_text)
    current_name = info.get("name")
    print("Current name:", current_name)
    if current_name == new_name:
        print("Already up to date.")
        return
    # PATCH
    try:
        resp_text, resp_code = http_patch_json(f"{DISCORD_API_BASE}/channels/{CHANNEL_ID}", TOKEN, {"name": new_name})
    except Exception as e:
        print("PATCH failed:", e)
        return
    print("PATCH code:", resp_code, "resp:", resp_text)

if __name__ == "__main__":
    main()

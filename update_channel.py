# update_channel.py
import os
import math
import requests
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

# ----- CONFIG (edit only if you want to change behavior) -----
COMPUPRO_URL = "https://compupro.github.io/rp-time-calculator/?daysperyear=7&lastdatechange=1757721600000&lastdateepoch=-4449513600000&fixedyears=true"
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "1417630872924061846"))
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN environment variable not set. Add it to GitHub Secrets.")

DISCORD_API_BASE = "https://discord.com/api/v10"
MONTH_NAMES = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
]

def rp_from_compupro_url(url):
    qs = parse_qs(urlparse(url).query)
    daysperyear = int(qs.get("daysperyear", ["7"])[0])
    lastdatechange_ms = int(qs.get("lastdatechange")[0])
    lastdateepoch_ms = int(qs.get("lastdateepoch")[0])

    MONTHS_PER_YEAR = 12
    hours_per_month = (daysperyear * 24) / MONTHS_PER_YEAR
    month_ms = hours_per_month * 3600 * 1000

    anchor_real_ms = lastdatechange_ms
    anchor_rp_epoch_ms = lastdateepoch_ms

    now_ms = datetime.now().timestamp() * 1000.0
    elapsed_ms = now_ms - anchor_real_ms

    total_months = math.floor(elapsed_ms / month_ms)
    years_elapsed = total_months // MONTHS_PER_YEAR
    anchor_rp_dt = datetime.utcfromtimestamp(anchor_rp_epoch_ms / 1000.0)

    current_year = anchor_rp_dt.year + years_elapsed
    current_month = (total_months % MONTHS_PER_YEAR) + 1
    ms_into_month = elapsed_ms - (total_months * month_ms)

    return int(current_year), int(current_month), int(ms_into_month), int(month_ms)

def compute_channel_name():
    year, month, ms_into, month_len_ms = rp_from_compupro_url(COMPUPRO_URL)
    month_name = MONTH_NAMES[(month - 1) % 12]
    return f"📅 {month_name} {year}"

def get_channel_info(channel_id, token):
    url = f"{DISCORD_API_BASE}/channels/{channel_id}"
    headers = {"Authorization": f"Bot {token}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return resp.json()
    else:
        raise RuntimeError(f"Failed GET channel: {resp.status_code} {resp.text}")

def patch_channel_name(channel_id, token, new_name):
    url = f"{DISCORD_API_BASE}/channels/{channel_id}"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json"
    }
    payload = {"name": new_name}
    resp = requests.patch(url, json=payload, headers=headers)
    return resp

def main():
    new_name = compute_channel_name()
    print("Computed channel name:", new_name)
    try:
        info = get_channel_info(CHANNEL_ID, TOKEN)
    except Exception as e:
        print("Error fetching channel info:", e)
        return

    current_name = info.get("name")
    print("Current channel name:", current_name)
    if current_name == new_name:
        print("Channel name already up to date; nothing to do.")
        return

    print("Attempting to update channel name...")
    resp = patch_channel_name(CHANNEL_ID, TOKEN, new_name)
    if resp.ok:
        print("Channel successfully updated.")
    else:
        print(f"Failed to update channel: {resp.status_code} {resp.text}")

if __name__ == "__main__":
    main()

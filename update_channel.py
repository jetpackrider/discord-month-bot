#!/usr/bin/env python3
# update_channel.py — improved debug/logging (stdlib only)

import os, math, json
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone, timedelta

COMPUPRO_URL = "https://compupro.github.io/rp-time-calculator/?daysperyear=7&lastdatechange=1757721600000&lastdateepoch=-4449513600000&fixedyears=true"
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "1417630872924061846"))
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN environment variable not set.")

DISCORD_API_BASE = "https://discord.com/api/v10"
MONTH_NAMES = ["January","February","March","April","May","June","July","August","September","October","November","December"]

def now_ms_utc():
    return datetime.now(timezone.utc).timestamp() * 1000.0

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

    now_ms = now_ms_utc()
    elapsed_ms = now_ms - anchor_real_ms

    total_months = math.floor(elapsed_ms / month_ms)
    years_elapsed = total_months // MONTHS_PER_YEAR
    anchor_rp_dt = datetime.utcfromtimestamp(anchor_rp_epoch_ms / 1000.0)

    current_year = anchor_rp_dt.year + years_elapsed
    current_month = (total_months % MONTHS_PER_YEAR) + 1
    ms_into_month = elapsed_ms - (total_months * month_ms)

    # Compute next month start (real ms) and next year rollover (real ms)
    next_month_boundary_months = total_months + 1
    next_month_start_ms = anchor_real_ms + next_month_boundary_months * month_ms

    # find the next time the RP year label increases (every 12 months)
    months_until_year_end = MONTHS_PER_YEAR - ( (total_months % MONTHS_PER_YEAR) + 1 ) + 1
    # months_until_year_end = number of months remaining until next year boundary (>=1)
    next_year_start_ms = anchor_real_ms + (total_months + months_until_year_end) * month_ms

    return {
        "current_year": int(current_year),
        "current_month": int(current_month),
        "ms_into_month": int(ms_into_month),
        "month_ms": int(month_ms),
        "next_month_start_ms": int(next_month_start_ms),
        "next_year_start_ms": int(next_year_start_ms),
        "anchor_real_ms": int(anchor_real_ms),
    }

def compute_channel_name():
    info = rp_from_compupro_url(COMPUPRO_URL)
    mname = MONTH_NAMES[(info["current_month"] - 1) % 12]
    return f"📅 {mname} {info['current_year']}", info

def http_get(url, token=None, timeout=15):
    headers = {}
    if token:
        headers["Authorization"] = f"Bot {token}"
    req = Request(url, headers=headers, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8"), resp.getcode()

def http_patch_json(url, token, data, timeout=15):
    body = json.dumps(data).encode("utf-8")
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    req = Request(url, data=body, headers=headers, method="PATCH")
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8"), resp.getcode()

def iso_ms(ms):
    return datetime.fromtimestamp(ms/1000.0, tz=timezone.utc).isoformat()

def main():
    run_time = datetime.now(timezone.utc)
    print("=== Action run UTC:", run_time.isoformat())
    new_name, info = compute_channel_name()
    print("Computed channel name:", new_name)
    print("  current_year:", info["current_year"], "current_month:", info["current_month"])
    print("  ms into month:", info["ms_into_month"], "month length ms:", info["month_ms"])
    print("  next_month_start (UTC):", iso_ms(info["next_month_start_ms"]))
    print("  next_year_start (UTC):", iso_ms(info["next_year_start_ms"]))
    print("  anchor real ms (UTC):", iso_ms(info["anchor_real_ms"]))

    channel_url = f"{DISCORD_API_BASE}/channels/{CHANNEL_ID}"
    try:
        info_text, code = http_get(channel_url, TOKEN)
    except HTTPError as e:
        print("GET channel HTTPError:", e.code, e.reason)
        return
    except URLError as e:
        print("GET channel URLError:", e)
        return
    except Exception as e:
        print("GET channel unexpected error:", e)
        return

    if code != 200:
        print("GET channel returned non-200:", code, info_text)
        return

    try:
        channel_info = json.loads(info_text)
    except Exception as e:
        print("Failed parse JSON:", e)
        return

    current_name = channel_info.get("name")
    print("Current channel name:", current_name)

    if current_name == new_name:
        print("Channel name already up to date; nothing to do.")
        return

    try:
        resp_text, resp_code = http_patch_json(channel_url, TOKEN, {"name": new_name})
    except HTTPError as e:
        print("PATCH HTTPError:", e.code, e.reason)
        try:
            print("Response:", e.read().decode("utf-8"))
        except:
            pass
        return
    except URLError as e:
        print("PATCH URLError:", e)
        return
    except Exception as e:
        print("PATCH unexpected error:", e)
        return

    print("PATCH returned:", resp_code, resp_text)

if __name__ == "__main__":
    main()

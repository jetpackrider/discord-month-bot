#!/usr/bin/env python3
"""
update_channel.py - stdlib-only, with safer headers and simple retry for Cloudflare 1010 blocks.

- Computes RP month/year from the Compupro URL anchor parameters.
- Uses urllib to GET the channel and PATCH the name only when needed.
- Sets a realistic User-Agent and Accept headers (helps avoid Cloudflare WAF 1010).
- If Discord returns a 403 with 'error code: 1010' in the body, the script will retry a few times with backoff.
- Read DISCORD_TOKEN (required) and optional CHANNEL_ID from environment variables.
"""

import os
import math
import json
import time
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone

# ---------------- CONFIG ----------------
COMPUPRO_URL = (
    "https://compupro.github.io/rp-time-calculator/"
    "?daysperyear=7&lastdatechange=1757721600000&lastdateepoch=-4449513600000&fixedyears=true"
)

CHANNEL_ID = int(os.getenv("CHANNEL_ID", "1417630872924061846"))
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN environment variable not set. Add it to GitHub Secrets or env.")

DISCORD_API_BASE = "https://discord.com/api/v10"
MONTH_NAMES = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
]

# User-Agent string: replace URL with your repo if you like
USER_AGENT = "DiscordBot (https://github.com/yourname/discord-month-bot, v1.0)"

# Retry config for 1010 Cloudflare WAF responses
RETRY_COUNT = 3
RETRY_BACKOFF_SEC = [2, 6, 20]  # seconds


# ---------------- Helpers ----------------
def now_ms_utc():
    return datetime.now(timezone.utc).timestamp() * 1000.0


def rp_from_compupro_url(url):
    """Parse compupro URL query params and compute current RP year/month."""
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
    ms_into_month = int(elapsed_ms - (total_months * month_ms))

    # next month & next year real timestamps (ms)
    next_month_start_ms = int(anchor_real_ms + (total_months + 1) * month_ms)
    months_until_year_end = MONTHS_PER_YEAR - ((total_months % MONTHS_PER_YEAR) + 1) + 1
    next_year_start_ms = int(anchor_real_ms + (total_months + months_until_year_end) * month_ms)

    return {
        "current_year": int(current_year),
        "current_month": int(current_month),
        "ms_into_month": ms_into_month,
        "month_ms": int(month_ms),
        "anchor_real_ms": int(anchor_real_ms),
        "anchor_rp_epoch_ms": int(anchor_rp_epoch_ms),
        "next_month_start_ms": next_month_start_ms,
        "next_year_start_ms": next_year_start_ms,
    }


def compute_channel_name():
    info = rp_from_compupro_url(COMPUPRO_URL)
    month_name = MONTH_NAMES[(info["current_month"] - 1) % 12]
    return f"📅 {month_name} {info['current_year']}", info


# --------- HTTP helpers with headers + retry for 1010 ----------
def _build_headers(token=None, extra=None):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bot {token}"
    if extra:
        headers.update(extra)
    return headers


def http_get_with_retries(url, token=None, retries=RETRY_COUNT):
    """GET with retry when Cloudflare 1010 is encountered."""
    attempt = 0
    last_exc = None
    while attempt <= retries:
        headers = _build_headers(token)
        req = Request(url, headers=headers, method="GET")
        try:
            with urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8"), resp.getcode()
        except HTTPError as e:
            body = None
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                body = ""
            # Detect Cloudflare 1010 block pattern in response body
            if "error code: 1010" in (body or "") and attempt < retries:
                wait = RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC)-1)]
                print(f"GET received 1010 block; attempt {attempt+1}/{retries}. backing off {wait}s and retrying...")
                time.sleep(wait)
                attempt += 1
                continue
            # otherwise re-raise the HTTPError with body info
            raise HTTPError(e.url, e.code, f"{e.reason} - body: {body}", e.headers, None)
        except URLError as e:
            last_exc = e
            # URLError is probably network; retry a couple times
            if attempt < retries:
                wait = RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC)-1)]
                print(f"GET URLError: {e}. attempt {attempt+1}/{retries}. waiting {wait}s...")
                time.sleep(wait)
                attempt += 1
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("GET failed after retries")


def http_patch_json_with_retries(url, token, data, retries=RETRY_COUNT):
    """PATCH JSON with retry on 1010 or transient network errors."""
    attempt = 0
    last_exc = None
    body_bytes = json.dumps(data).encode("utf-8")
    while attempt <= retries:
        headers = _build_headers(token, extra={"Content-Type": "application/json"})
        req = Request(url, data=body_bytes, headers=headers, method="PATCH")
        try:
            with urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8"), resp.getcode()
        except HTTPError as e:
            body = None
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                body = ""
            if "error code: 1010" in (body or "") and attempt < retries:
                wait = RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC)-1)]
                print(f"PATCH received 1010 block; attempt {attempt+1}/{retries}. backing off {wait}s and retrying...")
                time.sleep(wait)
                attempt += 1
                continue
            raise HTTPError(e.url, e.code, f"{e.reason} - body: {body}", e.headers, None)
        except URLError as e:
            last_exc = e
            if attempt < retries:
                wait = RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC)-1)]
                print(f"PATCH URLError: {e}. attempt {attempt+1}/{retries}. waiting {wait}s...")
                time.sleep(wait)
                attempt += 1
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("PATCH failed after retries")


# ---------------- Main ----------------
def iso_from_ms(ms):
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def main():
    print("=== Run UTC:", datetime.now(timezone.utc).isoformat())
    new_name, info = compute_channel_name()
    print("Computed channel name:", new_name)
    print(f"  current_year: {info['current_year']} current_month: {info['current_month']}")
    print(f"  ms into month: {info['ms_into_month']} month length ms: {info['month_ms']}")
    print("  next_month_start (UTC):", iso_from_ms(info["next_month_start_ms"]))
    print("  next_year_start (UTC):", iso_from_ms(info["next_year_start_ms"]))
    print("  anchor real ms (UTC):", iso_from_ms(info["anchor_real_ms"]))

    channel_url = f"{DISCORD_API_BASE}/channels/{CHANNEL_ID}"
    try:
        body, status = http_get_with_retries(channel_url, TOKEN)
    except HTTPError as e:
        # HTTPError raised with enriched message
        print(f"GET channel HTTPError: {e.code} {e.msg if hasattr(e, 'msg') else e.reason}")
        try:
            print("GET error body (if any):", e.msg)
        except Exception:
            pass
        return
    except URLError as e:
        print("GET channel URLError:", e)
        return
    except Exception as e:
        print("GET channel unexpected error:", e)
        return

    if status != 200:
        print("GET channel returned non-200:", status, body)
        return

    try:
        info_json = json.loads(body)
    except Exception as e:
        print("Failed to parse channel JSON:", e)
        return

    current_name = info_json.get("name")
    print("Current channel name:", current_name)

    if current_name == new_name:
        print("Channel name already up to date; nothing to do.")
        return

    # Attempt patch
    try:
        resp_text, resp_code = http_patch_json_with_retries(channel_url, TOKEN, {"name": new_name})
    except HTTPError as e:
        print(f"PATCH HTTPError: {e.code} {e.msg if hasattr(e, 'msg') else e.reason}")
        try:
            print("PATCH error body (if any):", e.msg)
        except Exception:
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

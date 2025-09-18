#!/usr/bin/env python3
"""
debug_channel_perms.py

Fetches channel, guild roles, bot member info and computes effective channel permissions
for the running bot user to help explain 403 Forbidden errors.
No external deps (stdlib only).
"""

import os
import json
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone

DISCORD_API_BASE = "https://discord.com/api/v10"

# Permission bits
PERM_ADMIN = 0x00000008
PERM_MANAGE_CHANNELS = 0x00000010
PERM_VIEW_CHANNEL = 0x00000400

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "1417630872924061846")

if not TOKEN:
    raise SystemExit("Set DISCORD_TOKEN environment variable before running this script.")

def http_get(path):
    url = urljoin(DISCORD_API_BASE, path)
    req = Request(url, headers={"Authorization": f"Bot {TOKEN}"}, method="GET")
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8"), resp.getcode()

def log(msg):
    print(msg)

def iso_now():
    return datetime.now(timezone.utc).isoformat()

def to_int(s):
    try:
        return int(s)
    except:
        return 0

def compute_effective_perms(base_perms, overwrites, member_role_ids, member_id, guild_id):
    """
    base_perms: int (role union)
    overwrites: list of dicts with keys id, type, allow, deny
    member_role_ids: list[str]
    returns: effective_perms int, and details dict
    """
    perms = base_perms

    # find @everyone overwrite (role overwrite with id == guild_id)
    everyone_allow = everyone_deny = 0
    role_allow = role_deny = 0
    member_allow = member_deny = 0

    for ow in overwrites:
        oid = str(ow.get("id"))
        otype = ow.get("type")  # "role" or "member" in REST (sometimes 0/1)
        # allow/deny come as strings in some responses
        allow = to_int(ow.get("allow", 0))
        deny = to_int(ow.get("deny", 0))
        # Normalize type: sometimes 'type' is int (0 role, 1 member) or strings 'role'/'member'.
        role_type = None
        if isinstance(otype, int):
            role_type = "role" if otype == 0 else "member"
        else:
            role_type = str(otype)

        if role_type == "role" and oid == str(guild_id):
            everyone_allow |= allow
            everyone_deny |= deny
        elif role_type == "role" and oid in member_role_ids:
            role_allow |= allow
            role_deny |= deny
        elif role_type == "member" and oid == str(member_id):
            member_allow |= allow
            member_deny |= deny

    # apply everyone overwrite
    perms = (perms & ~everyone_deny) | everyone_allow
    # apply role overwrites (aggregated)
    perms = (perms & ~role_deny) | role_allow
    # apply member overwrite
    perms = (perms & ~member_deny) | member_allow

    details = {
        "everyone_allow": everyone_allow, "everyone_deny": everyone_deny,
        "role_allow": role_allow, "role_deny": role_deny,
        "member_allow": member_allow, "member_deny": member_deny
    }
    return perms, details

def main():
    print("=== Debug run UTC:", iso_now())
    print("Channel ID:", CHANNEL_ID)

    # 1) GET channel
    try:
        body, code = http_get(f"/channels/{CHANNEL_ID}")
    except HTTPError as e:
        print("GET channel HTTPError:", e.code, e.reason)
        try:
            print("Body:", e.read().decode("utf-8"))
        except:
            pass
        return
    except URLError as e:
        print("GET channel URLError:", e)
        return
    except Exception as e:
        print("GET channel unexpected error:", e)
        return

    if code != 200:
        print("GET channel returned:", code, body)
        return

    channel = json.loads(body)
    print("Channel object fetched. name:", channel.get("name"), "type:", channel.get("type"))
    guild_id = channel.get("guild_id")
    if not guild_id:
        print("Channel has no guild_id (maybe it's a DM or invalid).")
        return
    print("Guild ID for channel:", guild_id)

    overwrites = channel.get("permission_overwrites", []) or channel.get("permission_overwrites", [])
    print("Permission overwrites count:", len(overwrites))
    # print raw overwrites
    for ow in overwrites:
        print("  overwrite:", ow)

    # 2) GET bot user info
    try:
        me_body, me_code = http_get("/users/@me")
    except Exception as e:
        print("GET @me failed:", e)
        return
    me = json.loads(me_body)
    bot_id = str(me.get("id"))
    print("Bot user id:", bot_id, "username:", me.get("username"))

    # 3) GET guild roles
    try:
        roles_body, roles_code = http_get(f"/guilds/{guild_id}/roles")
    except HTTPError as e:
        print("GET roles HTTPError:", e.code, e.reason)
        try:
            print("Body:", e.read().decode("utf-8"))
        except:
            pass
        return
    except Exception as e:
        print("GET roles failed:", e)
        return

    roles = json.loads(roles_body)
    # find @everyone role (id == guild_id)
    everyone_role = None
    role_map = {}
    for r in roles:
        role_map[str(r.get("id"))] = r
        if str(r.get("id")) == str(guild_id):
            everyone_role = r

    if not everyone_role:
        print("Couldn't find @everyone role in guild roles!")
        # but continue

    # 4) GET member info (bot as a guild member)
    try:
        member_body, member_code = http_get(f"/guilds/{guild_id}/members/{bot_id}")
    except HTTPError as e:
        # show helpful body
        print("GET member HTTPError:", e.code, e.reason)
        try:
            print("Body:", e.read().decode("utf-8"))
        except:
            pass
        return
    except Exception as e:
        print("GET member failed:", e)
        return

    member = json.loads(member_body)
    member_roles = [str(r) for r in member.get("roles", [])]
    print("Bot has member roles:", member_roles)

    # 5) Compute base perms: union of @everyone + each role the bot has
    base_perms = 0
    if everyone_role:
        base_perms |= int(everyone_role.get("permissions", "0"))
    for rid in member_roles:
        r = role_map.get(rid)
        if r:
            base_perms |= int(r.get("permissions", "0"))

    print("Base perms (bitmask):", base_perms)
    print("  ADMINISTRATOR bit set:", bool(base_perms & PERM_ADMIN))

    # 6) Compute effective channel perms using overwrites
    # Overwrites format: {id, type, allow, deny}
    # Normalize overwrites if type sometimes is number
    norm_ows = []
    for ow in overwrites:
        # some responses use allow/deny as ints or strings; cast to int
        norm = {
            "id": str(ow.get("id")),
            "type": ow.get("type"),
            "allow": str(ow.get("allow", "0")),
            "deny": str(ow.get("deny", "0"))
        }
        norm_ows.append(norm)

    eff_perms, details = compute_effective_perms(base_perms, norm_ows, member_roles, bot_id, guild_id)
    print("Effective perms (bitmask):", eff_perms)
    print("  ADMIN:", bool(eff_perms & PERM_ADMIN))
    print("  VIEW_CHANNEL:", bool(eff_perms & PERM_VIEW_CHANNEL))
    print("  MANAGE_CHANNELS:", bool(eff_perms & PERM_MANAGE_CHANNELS))
    print("Overwrite detail (everyone_allow/deny, role_allow/deny, member_allow/deny):", details)

    # extra: print any explicit deny for the bot via overwrites
    # Check member-specific overwrite
    for ow in norm_ows:
        if ow["id"] == bot_id and (int(ow["deny"]) != 0 or int(ow["allow"]) != 0):
            print("Member-specific overwrite exists:", ow)
    # role overwrites relevant to bot
    for ow in norm_ows:
        if ow["id"] in member_roles:
            if int(ow["deny"]) != 0 or int(ow["allow"]) != 0:
                print("Role overwrite relevant to bot:", ow)

    print("Done. If VIEW_CHANNEL or MANAGE_CHANNELS is False, fix role/channel overrides in Discord.")
    return

if __name__ == "__main__":
    main()

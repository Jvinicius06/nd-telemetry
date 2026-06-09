"""Optional Discord webhook alerts for crashes / abnormal boots.

Enabled by setting ND_DISCORD_WEBHOOK. The POST is fire-and-forget (stdlib
urllib, in a daemon thread) so device ingest never blocks, and it is throttled
per device (ND_DISCORD_MIN_INTERVAL seconds, default 60) so a crash loop does
not flood the channel. If ND_DASHBOARD_URL is set, a device link is appended.

No-op (and zero cost) when the webhook env var is unset.
"""
import json
import os
import threading
import time
import urllib.request

from .models import reason_name, exc_name

WEBHOOK = os.environ.get("ND_DISCORD_WEBHOOK", "").strip()
MIN_INTERVAL = int(os.environ.get("ND_DISCORD_MIN_INTERVAL", "60") or 60)
DASH_URL = os.environ.get("ND_DASHBOARD_URL", "").strip().rstrip("/")

# Abnormal reasons worth alerting on: HW WDT, Exception, SW WDT.
_ALERT_REASONS = {1, 2, 3}

_last = {}            # device_id -> last alert epoch (throttle)
_lock = threading.Lock()


def _hex(v):
    try:
        return f"{int(v):#010x}"
    except (TypeError, ValueError):
        return None


def _post(content):
    try:
        body = json.dumps({"content": content[:1900]}).encode()
        req = urllib.request.Request(
            WEBHOOK, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass   # best-effort: never let alerting affect ingest


def notify_boot(data, ip):
    """Send a Discord alert for an abnormal boot (crash). No-op otherwise."""
    if not WEBHOOK:
        return
    try:
        reason = int(data.get("reason"))
    except (TypeError, ValueError):
        return
    if reason not in _ALERT_REASONS:
        return

    dev = data.get("dev") or "?"
    now = time.time()
    with _lock:
        if now - _last.get(dev, 0) < MIN_INTERVAL:
            return                       # throttled
        _last[dev] = now

    head = reason_name(reason) or f"reason {reason}"
    ec = data.get("exccause")
    if reason == 2 and ec is not None:
        head += f" · {exc_name(ec)} (ec={ec})"

    # Show only non-zero addresses — for an epc1=0 (null-jump) crash, epc3 and
    # rtn (caller return address) are the decodable ones; zeros are just noise.
    regs = []
    for k in ("epc1", "epc3", "excvaddr", "rtn"):
        v = data.get(k)
        if v:
            regs.append(f"{k}={_hex(v)}")
    if data.get("tag"):
        regs.append(f"tag={data['tag']}")
    if data.get("heap") is not None:
        regs.append(f"heap={data['heap']}")

    lines = [f"\U0001F534 **Crash** `{dev}`  fw=`{data.get('fw') or '?'}`", head]
    if regs:
        lines.append("  ".join(regs))
    lines.append(f"IP {ip}")
    if DASH_URL:
        lines.append(f"{DASH_URL}/device/{dev}")

    threading.Thread(target=_post, args=("\n".join(lines),), daemon=True).start()

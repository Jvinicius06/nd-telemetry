"""SQLite storage for boots (resets) and events. stdlib only, WAL mode."""
import json
import os
import threading
import time

from .models import reason_name, exc_name, is_abnormal
from . import notify

DB_PATH = os.environ.get("ND_DB_PATH", "data/telemetry.db")


def fmt_duration(s):
    """Seconds -> 'HH:MM:SS' (or 'Nd HH:MM:SS' when >= 1 day)."""
    try:
        s = int(s)
    except (TypeError, ValueError):
        return "-"
    if s < 0:
        s = 0
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, sec = divmod(r, 60)
    if d:
        return f"{d}d {h:02d}:{m:02d}:{sec:02d}"
    return f"{h:02d}:{m:02d}:{sec:02d}"


_lock = threading.Lock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id          TEXT PRIMARY KEY,
    first_seen  INTEGER NOT NULL,
    last_seen   INTEGER NOT NULL,
    fw          TEXT,
    last_ip     TEXT,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS boots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT NOT NULL,
    ts          INTEGER NOT NULL,
    reason      INTEGER,
    reason_name TEXT,
    exccause    INTEGER,
    epc1        INTEGER,
    epc2        INTEGER,
    epc3        INTEGER,
    excvaddr    INTEGER,
    depc        INTEGER,
    rtn         INTEGER,
    tag         TEXT,
    heap_free   INTEGER,
    prev_uptime INTEGER,
    rssi        INTEGER,
    fw          TEXT,
    ip          TEXT,
    raw         TEXT
);
CREATE INDEX IF NOT EXISTS idx_boots_dev_ts ON boots(device_id, ts);
CREATE INDEX IF NOT EXISTS idx_boots_ts     ON boots(ts);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT NOT NULL,
    ts          INTEGER NOT NULL,
    type        TEXT NOT NULL,
    message     TEXT,
    heap_free   INTEGER,
    rssi        INTEGER,
    ip          TEXT,
    raw         TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_dev_ts ON events(device_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_ts     ON events(ts);
"""


def init_db():
    global _conn
    import sqlite3
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA busy_timeout=5000")
    with _lock:
        _conn.executescript(SCHEMA)
        # Migrate older DBs that predate later columns (add as needed).
        cols = {r["name"] for r in _conn.execute("PRAGMA table_info(boots)")}
        if "tag" not in cols:
            _conn.execute("ALTER TABLE boots ADD COLUMN tag TEXT")
        if "rtn" not in cols:
            _conn.execute("ALTER TABLE boots ADD COLUMN rtn INTEGER")
        _conn.commit()


def _upsert_device(dev, ts, fw, ip):
    _conn.execute(
        """INSERT INTO devices(id, first_seen, last_seen, fw, last_ip)
           VALUES(?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
               last_seen = excluded.last_seen,
               fw        = COALESCE(excluded.fw, devices.fw),
               last_ip   = COALESCE(excluded.last_ip, devices.last_ip)""",
        (dev, ts, ts, fw, ip),
    )


# ---------------------------------------------------------------- ingest

def record_boot(data, ip):
    dev = data.get("dev")
    if not dev:
        return False
    ts = int(time.time())
    reason = data.get("reason")
    with _lock:
        _upsert_device(dev, ts, data.get("fw"), ip)
        _conn.execute(
            """INSERT INTO boots(device_id, ts, reason, reason_name, exccause,
                   epc1, epc2, epc3, excvaddr, depc, rtn, tag, heap_free,
                   prev_uptime, rssi, fw, ip, raw)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (dev, ts, reason, reason_name(reason), data.get("exccause"),
             data.get("epc1"), data.get("epc2"), data.get("epc3"),
             data.get("excvaddr"), data.get("depc"), data.get("rtn"),
             data.get("tag"), data.get("heap"), data.get("uptime"),
             data.get("rssi"), data.get("fw"), ip, json.dumps(data, default=str)),
        )
        _conn.commit()
    notify.notify_boot(data, ip)   # Discord alert on crashes (best-effort)
    return True


def record_event(data, ip):
    dev = data.get("dev")
    if not dev:
        return False
    ts = int(time.time())
    with _lock:
        _upsert_device(dev, ts, data.get("fw"), ip)
        _conn.execute(
            """INSERT INTO events(device_id, ts, type, message, heap_free, rssi, ip, raw)
               VALUES(?,?,?,?,?,?,?,?)""",
            (dev, ts, data.get("type", "event"), data.get("msg"),
             data.get("heap"), data.get("rssi"), ip,
             json.dumps(data, default=str)),
        )
        _conn.commit()
    return True


# ---------------------------------------------------------------- queries

def _rows(sql, params=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, params).fetchall()]


def _one(sql, params=()):
    with _lock:
        r = _conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def get_overview(now=None):
    now = now or int(time.time())
    day, week = now - 86400, now - 7 * 86400
    total_devices = _one("SELECT COUNT(*) c FROM devices")["c"]
    boots_24 = _one("SELECT COUNT(*) c FROM boots WHERE ts>=?", (day,))["c"]
    boots_7 = _one("SELECT COUNT(*) c FROM boots WHERE ts>=?", (week,))["c"]
    crashes_24 = _one(
        "SELECT COUNT(*) c FROM boots WHERE ts>=? AND reason IN (1,2,3)", (day,))["c"]
    wifi_24 = _one(
        "SELECT COUNT(*) c FROM events WHERE ts>=? AND type LIKE 'wifi%'", (day,))["c"]
    # devices not heard from in > 10 min
    stale = _one("SELECT COUNT(*) c FROM devices WHERE last_seen < ?", (now - 600,))["c"]
    by_reason = _rows(
        """SELECT reason, reason_name, COUNT(*) c FROM boots
           WHERE ts>=? GROUP BY reason ORDER BY c DESC""", (week,))
    return {
        "total_devices": total_devices,
        "boots_24": boots_24,
        "boots_7": boots_7,
        "crashes_24": crashes_24,
        "wifi_24": wifi_24,
        "stale": stale,
        "by_reason": by_reason,
    }


def list_devices(now=None):
    now = now or int(time.time())
    day = now - 86400
    return _rows(
        """SELECT d.*,
              (SELECT COUNT(*) FROM boots b
                 WHERE b.device_id=d.id AND b.ts>=:day) AS boots_24,
              (SELECT COUNT(*) FROM boots b
                 WHERE b.device_id=d.id AND b.ts>=:day AND b.reason IN (1,2,3)) AS crashes_24,
              (SELECT COUNT(*) FROM events e
                 WHERE e.device_id=d.id AND e.ts>=:day AND e.type LIKE 'wifi%') AS wifi_24,
              (SELECT reason_name FROM boots b
                 WHERE b.device_id=d.id ORDER BY b.ts DESC LIMIT 1) AS last_reason,
              (SELECT reason FROM boots b
                 WHERE b.device_id=d.id ORDER BY b.ts DESC LIMIT 1) AS last_reason_code,
              (SELECT ts FROM boots b
                 WHERE b.device_id=d.id ORDER BY b.ts DESC LIMIT 1) AS last_boot_ts,
              (SELECT heap_free FROM boots b
                 WHERE b.device_id=d.id ORDER BY b.ts DESC LIMIT 1) AS last_heap
           FROM devices d ORDER BY d.last_seen DESC""",
        {"day": day},
    )


def get_device(dev):
    return _one("SELECT * FROM devices WHERE id=?", (dev,))


def device_boots(dev, limit=200):
    return _rows(
        "SELECT * FROM boots WHERE device_id=? ORDER BY ts DESC LIMIT ?", (dev, limit))


def device_events(dev, limit=200):
    return _rows(
        "SELECT * FROM events WHERE device_id=? ORDER BY ts DESC LIMIT ?", (dev, limit))


def device_reason_breakdown(dev):
    return _rows(
        """SELECT reason, reason_name, COUNT(*) c FROM boots
           WHERE device_id=? GROUP BY reason ORDER BY c DESC""", (dev,))


def build_timeline(dev, limit=200):
    """Merge boots + events into one reverse-chronological list for the UI."""
    items = []
    for b in device_boots(dev, limit):
        detail = []
        tag = b.get("tag")
        if tag:
            detail.append(f"tag={tag}")
        if b["reason"] == 2 and b["exccause"] is not None:
            detail.append(f"{exc_name(b['exccause'])} (ec={b['exccause']})")
            # Dump every crash register, raw hex, always — even 0x0 (a zero
            # epc1 means the CPU jumped to a null/bad address: corrupted return
            # or NULL function pointer). The dashboard only shows data; decode
            # offline with addr2line + the matching firmware ELF.
            for label, key in (("epc1", "epc1"), ("epc2", "epc2"),
                               ("epc3", "epc3"), ("excvaddr", "excvaddr"),
                               ("depc", "depc"), ("rtn", "rtn")):
                detail.append(f"{label}={(b.get(key) or 0):#010x}")
        if b["heap_free"] is not None:
            detail.append(f"heap={b['heap_free']}")
        if b["prev_uptime"] is not None:
            detail.append(f"uptime={fmt_duration(b['prev_uptime'])}")
        items.append({
            "ts": b["ts"], "kind": "boot",
            "abnormal": is_abnormal(b["reason"]),
            "title": b["reason_name"] or "Boot",
            "detail": "  ".join(detail),
            "fw": b["fw"], "ip": b["ip"],
        })
    for e in device_events(dev, limit):
        detail = []
        if e["heap_free"] is not None:
            detail.append(f"heap={e['heap_free']}")
        if e["rssi"] is not None:
            detail.append(f"rssi={e['rssi']}")
        items.append({
            "ts": e["ts"], "kind": "event",
            "abnormal": str(e["type"]).startswith("wifi"),
            "title": e["type"],
            "detail": (e["message"] or "") + ("  " + "  ".join(detail) if detail else ""),
            "fw": None, "ip": e["ip"],
        })
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:limit]

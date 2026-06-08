"""Admin dashboard (port 8081). Server-rendered, HTTP Basic auth, auto-refresh."""
import os
import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from . import db

app = FastAPI(title="ND Device Telemetry — Dashboard", docs_url=None,
              redoc_url=None, openapi_url=None)

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

ADMIN_USER = os.environ.get("ND_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ND_ADMIN_PASS", "admin")
_security = HTTPBasic()


def require_admin(creds: HTTPBasicCredentials = Depends(_security)):
    ok = (secrets.compare_digest(creds.username, ADMIN_USER)
          and secrets.compare_digest(creds.password, ADMIN_PASS))
    if not ok:
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "Basic"})
    return creds.username


# ----- Jinja filters ---------------------------------------------------------

def _fmt_dt(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else "-"


def _fmt_ago(t):
    if not t:
        return "-"
    s = int(time.time()) - int(t)
    if s < 0:
        s = 0
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def _fmt_hex(v):
    try:
        return f"{int(v):#010x}"
    except (TypeError, ValueError):
        return "-"


_TEMPLATES.env.filters["dt"] = _fmt_dt
_TEMPLATES.env.filters["ago"] = _fmt_ago
_TEMPLATES.env.filters["hexa"] = _fmt_hex


# ----- routes ----------------------------------------------------------------

@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def index(request: Request, _: str = Depends(require_admin)):
    now = int(time.time())
    return _TEMPLATES.TemplateResponse("index.html", {
        "request": request,
        "now": now,
        "stale_after": 600,
        "overview": db.get_overview(now),
        "devices": db.list_devices(now),
    })


@app.get("/device/{dev}")
def device(dev: str, request: Request, _: str = Depends(require_admin)):
    d = db.get_device(dev)
    if not d:
        raise HTTPException(status_code=404, detail="device not found")
    return _TEMPLATES.TemplateResponse("device.html", {
        "request": request,
        "now": int(time.time()),
        "device": d,
        "reasons": db.device_reason_breakdown(dev),
        "timeline": db.build_timeline(dev),
    })


@app.get("/api/overview")
def api_overview(_: str = Depends(require_admin)):
    return db.get_overview()


@app.get("/api/devices")
def api_devices(_: str = Depends(require_admin)):
    return db.list_devices()


@app.get("/api/device/{dev}")
def api_device(dev: str, _: str = Depends(require_admin)):
    d = db.get_device(dev)
    if not d:
        raise HTTPException(status_code=404, detail="device not found")
    return {
        "device": d,
        "reasons": db.device_reason_breakdown(dev),
        "boots": db.device_boots(dev),
        "events": db.device_events(dev),
    }

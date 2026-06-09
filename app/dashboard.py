"""Admin dashboard (port 8081). Server-rendered, HTTP Basic auth, auto-refresh."""
import os
import re
import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from . import db, symbolize

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
_TEMPLATES.env.filters["dur"] = db.fmt_duration


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
    now = int(time.time())
    last_boots = db.device_boots(dev, 1)
    last_boot = last_boots[0] if last_boots else None
    return _TEMPLATES.TemplateResponse("device.html", {
        "request": request,
        "now": now,
        "device": d,
        "uptime": (now - last_boot["ts"]) if last_boot else None,
        "last_reason": last_boot["reason_name"] if last_boot else None,
        "last_reason_code": last_boot["reason"] if last_boot else None,
        "reasons": db.device_reason_breakdown(dev),
        "timeline": db.build_timeline(dev),
        "has_elf": symbolize.have_elf(d.get("fw")),
    })


@app.put("/elf/{fw}")
async def upload_elf(fw: str, request: Request, _: str = Depends(require_admin)):
    """Upload a firmware ELF (with DWARF) so crash addresses get decoded to
    func (file:line). Body = raw ELF bytes. Example:
        curl -u admin:pass --data-binary @firmware.elf http://host:8081/elf/3.0.5
    """
    if not re.fullmatch(r"[0-9A-Za-z._-]{1,32}", fw):
        raise HTTPException(status_code=400, detail="bad fw name")
    data = await request.body()
    if len(data) < 4 or data[:4] != b"\x7fELF":
        raise HTTPException(status_code=400, detail="not an ELF file")
    os.makedirs(symbolize.elf_dir(), exist_ok=True)
    path = os.path.join(symbolize.elf_dir(), f"{fw}.elf")
    with open(path, "wb") as fh:
        fh.write(data)
    symbolize.clear_cache()
    return PlainTextResponse(f"OK {len(data)} bytes -> {path}")


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

"""Low-cost ingest API for the ESP8266 devices (plain HTTP, no auth).

Designed to be trivial for a memory-starved device:
  * POST JSON  -> /v1/boot , /v1/event      (rich payloads)
  * GET  query -> /v1/i?d=..&k=boot&...      (cheapest: no body, no headers fuss)
Responses are tiny ("OK") to keep the device's RX buffer small.
"""
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from . import db

app = FastAPI(title="ND Device Telemetry — Ingest", docs_url="/docs",
              redoc_url=None, openapi_url="/openapi.json")


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


def _int(v):
    """Parse int, accepting decimal or 0x-hex; None/blank -> None."""
    if v is None or v == "":
        return None
    try:
        s = str(v).strip()
        return int(s, 16) if s.lower().startswith("0x") else int(s)
    except (ValueError, TypeError):
        return None


class BootReport(BaseModel):
    model_config = ConfigDict(extra="allow")
    dev: str = Field(..., description="device id / MAC")
    fw: Optional[str] = None
    reason: Optional[int] = Field(None, description="ESP8266 rst_info.reason 0..6")
    exccause: Optional[int] = None
    epc1: Optional[int] = None
    epc2: Optional[int] = None
    epc3: Optional[int] = None
    excvaddr: Optional[int] = None
    depc: Optional[int] = None
    tag: Optional[str] = None
    heap: Optional[int] = Field(None, description="free heap at boot")
    uptime: Optional[int] = Field(None, description="previous session uptime (s)")
    rssi: Optional[int] = None


class EventReport(BaseModel):
    model_config = ConfigDict(extra="allow")
    dev: str
    type: str = Field(..., description="e.g. wifi_disconnect, wifi_reconnect, heap_low")
    msg: Optional[str] = None
    heap: Optional[int] = None
    rssi: Optional[int] = None


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/v1/boot")
async def post_boot(rep: BootReport, request: Request):
    db.record_boot(rep.model_dump(), _client_ip(request))
    return PlainTextResponse("OK")


@app.post("/v1/event")
async def post_event(rep: EventReport, request: Request):
    db.record_event(rep.model_dump(), _client_ip(request))
    return PlainTextResponse("OK")


@app.get("/v1/i")
async def ingest_get(request: Request):
    """Compact GET ingest for the most constrained devices.

    Boot:   /v1/i?d=MAC&k=boot&r=2&ec=28&epc1=0x40201abc&va=0x0&h=4200&up=37&fw=1.2&rssi=-70
    Event:  /v1/i?d=MAC&k=event&t=wifi_disconnect&m=reason202&h=4200&rssi=-80
    """
    q = request.query_params
    dev = q.get("d") or q.get("dev")
    if not dev:
        return PlainTextResponse("ERR no dev", status_code=400)
    ip = _client_ip(request)
    kind = q.get("k", "event")
    if kind == "boot":
        db.record_boot({
            "dev": dev, "fw": q.get("fw"), "reason": _int(q.get("r")),
            "exccause": _int(q.get("ec")), "epc1": _int(q.get("epc1")),
            "epc2": _int(q.get("epc2")), "epc3": _int(q.get("epc3")),
            "excvaddr": _int(q.get("va")), "depc": _int(q.get("depc")),
            "tag": (q.get("tag") or None),
            "heap": _int(q.get("h")), "uptime": _int(q.get("up")),
            "rssi": _int(q.get("rssi")),
        }, ip)
    else:
        db.record_event({
            "dev": dev, "type": q.get("t", "event"), "msg": q.get("m"),
            "heap": _int(q.get("h")), "rssi": _int(q.get("rssi")),
        }, ip)
    return PlainTextResponse("OK")

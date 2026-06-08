"""Entry point: run BOTH servers in one process / one container.

  * device ingest API -> ND_DEVICE_PORT    (default 8080, no auth)
  * admin dashboard   -> ND_DASHBOARD_PORT  (default 8081, HTTP Basic)
"""
import asyncio
import os

import uvicorn

from . import db
from .dashboard import app as dashboard_app
from .device_api import app as device_app


async def _serve():
    db.init_db()
    dev_port = int(os.environ.get("ND_DEVICE_PORT", "8080"))
    dash_port = int(os.environ.get("ND_DASHBOARD_PORT", "8081"))

    device_cfg = uvicorn.Config(
        device_app, host="0.0.0.0", port=dev_port,
        log_level="info", access_log=False)        # quiet: high-frequency ingest
    dash_cfg = uvicorn.Config(
        dashboard_app, host="0.0.0.0", port=dash_port,
        log_level="info", access_log=True)

    print(f"[nd-telemetry] device API  -> http://0.0.0.0:{dev_port}")
    print(f"[nd-telemetry] dashboard   -> http://0.0.0.0:{dash_port}")

    await asyncio.gather(
        uvicorn.Server(device_cfg).serve(),
        uvicorn.Server(dash_cfg).serve(),
    )


def main():
    asyncio.run(_serve())


if __name__ == "__main__":
    main()

import asyncio
import time
import aiohttp

import alerts
import events as ev
from database import (
    close_incident,
    get_latest_check,
    get_services,
    open_incident,
    record_check,
)

_last_status: dict[int, int] = {}  # service_id → last known status (0 or 1)
_service_pause_until: dict[int, float] = {}  # service_id → wall-clock timestamp when pause expires


def pause_service(service_id: int, seconds: int) -> dict:
    _service_pause_until[service_id] = time.time() + seconds
    return get_service_pause_state(service_id)


def resume_service(service_id: int) -> dict:
    _service_pause_until.pop(service_id, None)
    return get_service_pause_state(service_id)


def get_service_pause_state(service_id: int) -> dict:
    until = _service_pause_until.get(service_id)
    if until is None:
        return {"paused": False, "remaining_seconds": 0}
    remaining = until - time.time()
    if remaining <= 0:
        _service_pause_until.pop(service_id, None)
        return {"paused": False, "remaining_seconds": 0}
    return {"paused": True, "remaining_seconds": int(remaining)}


async def warm_up_status_cache():
    """Pre-populate from DB on startup to avoid false alerts after restart."""
    for svc in await get_services():
        latest = await get_latest_check(svc["id"])
        if latest:
            _last_status[svc["id"]] = latest[0]


def clear_status_cache(service_id: int):
    """Remove a service from the status cache so re-enable doesn't fire false alerts."""
    _last_status.pop(service_id, None)


async def check_http(url: str, verify_ssl: bool = True, timeout: int = 10):
    """Return (status 0/1, response_ms, error_str)."""
    start = time.monotonic()
    try:
        connector = aiohttp.TCPConnector(ssl=False) if not verify_ssl else None
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
            ) as resp:
                ms = int((time.monotonic() - start) * 1000)
                # Treat anything below 500 as "up" (401, 403 mean service is running)
                if resp.status < 500:
                    return 1, ms, None
                return 0, ms, f"HTTP {resp.status}"
    except asyncio.TimeoutError:
        return 0, None, "Timeout"
    except Exception as exc:
        return 0, None, str(exc)[:120]


async def check_tcp(host: str, port: int, timeout: int = 5):
    """Return (status 0/1, response_ms, error_str)."""
    start = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        ms = int((time.monotonic() - start) * 1000)
        writer.close()
        await writer.wait_closed()
        return 1, ms, None
    except asyncio.TimeoutError:
        return 0, None, "Timeout"
    except Exception as exc:
        return 0, None, str(exc)[:120]


async def check_service(service: dict):
    check_type = service["check_type"]
    host = service["host"]
    port = service["port"]

    if check_type in ("http", "https"):
        url = service.get("url") or f"{check_type}://{host}:{port}"
        # Disable SSL verification for known self-signed certs (Ubiquiti router)
        verify_ssl = not (check_type == "https" and host == "192.168.13.1")
        return await check_http(url, verify_ssl=verify_ssl)

    if check_type == "tcp":
        return await check_tcp(host, port)

    return 0, None, f"Unknown check type: {check_type}"


async def _check_and_record(service: dict):
    sid = service["id"]

    # Skip check if this service is paused
    pause_state = get_service_pause_state(sid)
    if pause_state["paused"]:
        return

    try:
        status, response_ms, error = await check_service(service)
        await record_check(sid, status, response_ms, error)
    except Exception as exc:
        status, response_ms, error = 0, None, str(exc)[:120]
        await record_check(sid, status, response_ms, error)

    # Detect status transitions and trigger incidents/alerts
    prev = _last_status.get(sid)
    if prev is not None and prev != status:
        if status == 0:
            await open_incident(sid)
            await alerts.send_alert("down", service, error)
        else:
            await close_incident(sid)
            await alerts.send_alert("recovered", service, None)
    _last_status[sid] = status

    # Broadcast live update to SSE subscribers
    await ev.broadcast("check_result", {
        "id": sid,
        "current_status": status,
        "current_response_ms": response_ms,
    })


async def run_checks():
    """Check all enabled services concurrently."""
    services = await get_services()
    await asyncio.gather(*[_check_and_record(s) for s in services], return_exceptions=True)

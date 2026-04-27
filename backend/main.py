import asyncio
import csv
import io
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

import alerts
import events as ev
from database import (
    DATABASE_PATH,
    cleanup_old_checks,
    close_incident,
    create_service,
    delete_service,
    get_all_settings,
    get_incidents,
    get_latest_check,
    get_services,
    get_setting,
    get_sparkline_data,
    get_uptime_buckets,
    init_db,
    open_incident,
    seed_default_services,
    set_service_enabled,
    set_setting,
    update_service,
)
from monitor import clear_status_cache, get_service_pause_state, pause_service, resume_service, run_checks, warm_up_status_cache

scheduler = AsyncIOScheduler()
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise database and seed default services
    await init_db()
    await seed_default_services()

    # Pre-populate status cache to avoid false alerts on restart
    await warm_up_status_cache()

    # Kick off an immediate check
    asyncio.create_task(run_checks())

    # Schedule checks every minute, cleanup every hour
    scheduler.add_job(run_checks, "interval", minutes=1, id="checks")
    scheduler.add_job(cleanup_old_checks, "interval", hours=1, id="cleanup")
    scheduler.start()

    yield

    scheduler.shutdown()


app = FastAPI(title="Home Monitoring Dashboard", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ServiceBody(BaseModel):
    name: str
    host: str
    port: int | None = None
    check_type: str = "http"
    url: str | None = None
    group_name: str = "General"


class PatchServiceBody(BaseModel):
    enabled: bool


class SettingsBody(BaseModel):
    webhook_url: str | None = None
    webhook_type: str = "discord"


class TestAlertBody(BaseModel):
    webhook_url: str
    webhook_type: str = "discord"


class ImportServiceItem(BaseModel):
    name: str
    host: str
    port: int | None = None
    check_type: str = "http"
    url: str | None = None
    group_name: str = "General"
    enabled: int = 1


class ImportBody(BaseModel):
    version: int = 1
    services: list[ImportServiceItem] = []
    settings: dict | None = None


class ServicePauseBody(BaseModel):
    duration_seconds: int


# ---------------------------------------------------------------------------
# API routes — services
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def api_health():
    return {"status": "ok"}


@app.get("/api/services")
async def api_services():
    services = await get_services()
    result = []
    for svc in services:
        latest = await get_latest_check(svc["id"])
        result.append({
            **svc,
            "current_status": latest[0] if latest else None,
            "current_response_ms": latest[1] if latest else None,
            "last_checked": latest[2] if latest else None,
        })
    return result


@app.post("/api/services", status_code=201)
async def api_create_service(body: ServiceBody):
    svc = await create_service(
        body.name, body.host, body.port, body.check_type, body.url, body.group_name
    )
    return svc


@app.put("/api/services/{id}")
async def api_update_service(id: int, body: ServiceBody):
    svc = await update_service(
        id, body.name, body.host, body.port, body.check_type, body.url, body.group_name
    )
    if svc is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return svc


@app.patch("/api/services/{id}")
async def api_patch_service(id: int, body: PatchServiceBody):
    services = await get_services(enabled_only=False)
    svc = next((s for s in services if s["id"] == id), None)
    if svc is None:
        raise HTTPException(status_code=404, detail="Service not found")

    await set_service_enabled(id, body.enabled)

    if body.enabled:
        # Closing the "disabled" incident; clear cache so first check isn't a false alert
        await close_incident(id, note="Re-enabled")
        clear_status_cache(id)
    else:
        # Close any open monitoring incident, then log the manual disable
        await close_incident(id)
        await open_incident(id, note="Manually disabled")

    await ev.broadcast("service_updated", {"id": id, "enabled": 1 if body.enabled else 0})
    return {"ok": True}


@app.delete("/api/services/{id}", status_code=204)
async def api_delete_service(id: int):
    ok = await delete_service(id)
    if not ok:
        raise HTTPException(status_code=404, detail="Service not found")


@app.get("/api/services/{id}/sparkline")
async def api_sparkline(id: int):
    data = await get_sparkline_data(id)
    return data


@app.get("/api/services/{id}/incidents")
async def api_incidents(id: int):
    data = await get_incidents(id)
    return data


# ---------------------------------------------------------------------------
# API routes — uptime
# ---------------------------------------------------------------------------

@app.get("/api/uptime")
async def api_uptime():
    services = await get_services(enabled_only=False)
    hours = 168  # 7 days

    result = []
    for svc in services:
        db_buckets = await get_uptime_buckets(svc["id"], hours)
        latest = await get_latest_check(svc["id"])

        total_checks = sum(b["total"] for b in db_buckets.values())
        up_checks = sum(b["up_count"] or 0 for b in db_buckets.values())
        uptime_pct = round(up_checks / total_checks * 100, 2) if total_checks else 0.0

        pause_info = get_service_pause_state(svc["id"])
        result.append({
            "id": svc["id"],
            "name": svc["name"],
            "group_name": svc["group_name"],
            "host": svc["host"],
            "port": svc["port"],
            "check_type": svc["check_type"],
            "url": svc["url"],
            "enabled": svc["enabled"],
            "current_status": latest[0] if latest else None,
            "current_response_ms": latest[1] if latest else None,
            "uptime_7d": uptime_pct,
            "paused": pause_info["paused"],
            "paused_remaining_seconds": pause_info["remaining_seconds"],
        })

    return result


# ---------------------------------------------------------------------------
# API routes — export
# ---------------------------------------------------------------------------

@app.get("/api/export")
async def api_export():
    services = await get_services(enabled_only=False)
    rows = []
    for svc in services:
        latest = await get_latest_check(svc["id"])
        db_buckets = await get_uptime_buckets(svc["id"], 168)
        total_checks = sum(b["total"] for b in db_buckets.values())
        up_checks = sum(b["up_count"] or 0 for b in db_buckets.values())
        uptime_pct = round(up_checks / total_checks * 100, 2) if total_checks else 0.0
        rows.append({
            "name": svc["name"],
            "group": svc["group_name"],
            "host": svc["host"],
            "port": svc["port"] or "",
            "check_type": svc["check_type"],
            "url": svc["url"] or "",
            "enabled": "yes" if svc["enabled"] else "no",
            "current_status": "up" if latest and latest[0] == 1 else ("down" if latest else "unknown"),
            "response_ms": latest[1] if latest and latest[1] is not None else "",
            "uptime_7d_pct": uptime_pct,
            "last_checked": latest[2] if latest else "",
        })

    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=services.csv"},
    )


# ---------------------------------------------------------------------------
# API routes — SSE
# ---------------------------------------------------------------------------

@app.get("/api/events")
async def api_events():
    async def event_stream():
        q = ev.subscribe()
        try:
            while True:
                # Send keepalive comment every 25s to prevent proxy timeouts
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            ev.unsubscribe(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# API routes — settings
# ---------------------------------------------------------------------------

@app.get("/api/settings")
async def api_get_settings():
    all_s = await get_all_settings()
    return {
        "webhook_url": all_s.get("webhook_url", ""),
        "webhook_type": all_s.get("webhook_type", "discord"),
    }


@app.put("/api/settings")
async def api_save_settings(body: SettingsBody):
    await set_setting("webhook_url", body.webhook_url or "")
    await set_setting("webhook_type", body.webhook_type)
    return {"ok": True}


@app.post("/api/settings/test")
async def api_test_alert(body: TestAlertBody):
    ok, message = await alerts.send_test_alert(body.webhook_url, body.webhook_type)
    return {"ok": ok, "message": message}


# ---------------------------------------------------------------------------
# API routes — JSON config export / import
# ---------------------------------------------------------------------------

@app.get("/api/export/config")
async def api_export_config():
    services = await get_services(enabled_only=False)
    settings = await get_all_settings()
    config = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "services": [
            {
                "name": s["name"],
                "host": s["host"],
                "port": s["port"],
                "check_type": s["check_type"],
                "url": s["url"],
                "group_name": s["group_name"],
                "enabled": s["enabled"],
            }
            for s in services
        ],
        "settings": {
            "webhook_url": settings.get("webhook_url", ""),
            "webhook_type": settings.get("webhook_type", "discord"),
        },
    }
    import json as _json
    return StreamingResponse(
        iter([_json.dumps(config, indent=2)]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=home-monitor-config.json"},
    )


@app.post("/api/import")
async def api_import(body: ImportBody):
    existing = await get_services(enabled_only=False)
    existing_keys = {(s["host"], s["port"]) for s in existing}

    imported = 0
    skipped = 0
    for item in body.services:
        if (item.host, item.port) in existing_keys:
            skipped += 1
        else:
            await create_service(
                item.name, item.host, item.port,
                item.check_type, item.url, item.group_name,
            )
            existing_keys.add((item.host, item.port))
            imported += 1

    if body.settings:
        if body.settings.get("webhook_url"):
            await set_setting("webhook_url", body.settings["webhook_url"])
        if body.settings.get("webhook_type"):
            await set_setting("webhook_type", body.settings["webhook_type"])

    return {"imported": imported, "skipped": skipped}


# ---------------------------------------------------------------------------
# API routes — per-service pause
# ---------------------------------------------------------------------------

@app.post("/api/services/{id}/pause")
async def api_pause_service(id: int, body: ServicePauseBody):
    services = await get_services(enabled_only=False)
    if not any(s["id"] == id for s in services):
        raise HTTPException(status_code=404, detail="Service not found")
    state = pause_service(id, body.duration_seconds)
    await ev.broadcast("service_updated", {
        "id": id,
        "paused": state["paused"],
        "paused_remaining_seconds": state["remaining_seconds"],
    })
    return state


@app.delete("/api/services/{id}/pause")
async def api_resume_service(id: int):
    services = await get_services(enabled_only=False)
    if not any(s["id"] == id for s in services):
        raise HTTPException(status_code=404, detail="Service not found")
    state = resume_service(id)
    await ev.broadcast("service_updated", {
        "id": id,
        "paused": state["paused"],
        "paused_remaining_seconds": state["remaining_seconds"],
    })
    return state


# ---------------------------------------------------------------------------
# API routes — check-now
# ---------------------------------------------------------------------------

@app.post("/api/check-now")
async def api_check_now():
    asyncio.create_task(run_checks())
    return {"message": "Checks triggered"}


# ---------------------------------------------------------------------------
# Serve React SPA (must be last)
# ---------------------------------------------------------------------------

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if STATIC_DIR.exists():
        # Serve real files (JS/CSS/images)
        candidate = STATIC_DIR / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        # Fall back to index.html for client-side routing
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
    return JSONResponse({"error": "Frontend not built"}, status_code=404)

import os
import aiosqlite

DATABASE_PATH = os.getenv("DATABASE_PATH", "/app/data/monitoring.db")

DEFAULT_SERVICES: list[tuple] = [
    # name, host, port, check_type, url, group_name
    # Add your own services here or use the web UI.
    # Example:
    # ("Router", "192.168.1.1", 443, "https", "https://192.168.1.1", "Network"),
    # ("Pi SSH", "my-pi", 22, "tcp", None, "Servers"),
]


async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS services (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                host       TEXT NOT NULL,
                port       INTEGER,
                check_type TEXT NOT NULL DEFAULT 'http',
                url        TEXT,
                group_name TEXT DEFAULT 'General',
                enabled    INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS checks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id  INTEGER NOT NULL,
                checked_at  TEXT NOT NULL,
                status      INTEGER NOT NULL,
                response_ms INTEGER,
                error       TEXT,
                FOREIGN KEY (service_id) REFERENCES services(id)
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_checks_service_time
            ON checks(service_id, checked_at)
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS discovered_ports (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                host          TEXT NOT NULL,
                port          INTEGER NOT NULL,
                service_hint  TEXT,
                discovered_at TEXT DEFAULT (datetime('now')),
                UNIQUE(host, port)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id   INTEGER NOT NULL,
                started_at   TEXT NOT NULL DEFAULT (datetime('now')),
                recovered_at TEXT,
                FOREIGN KEY (service_id) REFERENCES services(id)
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_service
            ON incidents(service_id, started_at DESC)
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Migration: add note column to incidents if it doesn't exist yet
        try:
            await db.execute("ALTER TABLE incidents ADD COLUMN note TEXT")
        except Exception:
            pass  # Column already exists

        await db.commit()


async def seed_default_services():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        for name, host, port, check_type, url, group in DEFAULT_SERVICES:
            cur = await db.execute(
                "SELECT id FROM services WHERE host = ? AND port = ?", (host, port)
            )
            if not await cur.fetchone():
                await db.execute(
                    "INSERT INTO services (name, host, port, check_type, url, group_name) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (name, host, port, check_type, url, group),
                )
        await db.commit()


async def record_check(service_id: int, status: int, response_ms: int = None, error: str = None):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO checks (service_id, checked_at, status, response_ms, error) "
            "VALUES (?, datetime('now'), ?, ?, ?)",
            (service_id, status, response_ms, error),
        )
        await db.commit()


async def get_services(enabled_only: bool = True):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = "WHERE enabled = 1 " if enabled_only else ""
        cur = await db.execute(
            f"SELECT * FROM services {where}ORDER BY group_name, name"
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_uptime_buckets(service_id: int, hours: int = 168):
    """Return hourly aggregated uptime for the last N hours."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute(
            """
            SELECT
                strftime('%Y-%m-%dT%H:00:00', checked_at) AS hour_start,
                COUNT(*)    AS total,
                SUM(status) AS up_count
            FROM checks
            WHERE service_id = ?
              AND checked_at >= datetime('now', ? || ' hours')
            GROUP BY hour_start
            ORDER BY hour_start
            """,
            (service_id, f"-{hours}"),
        )
        rows = await cur.fetchall()
        return {r[0]: {"total": r[1], "up_count": r[2]} for r in rows}


async def get_latest_check(service_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute(
            "SELECT status, response_ms, checked_at FROM checks "
            "WHERE service_id = ? ORDER BY checked_at DESC LIMIT 1",
            (service_id,),
        )
        return await cur.fetchone()


async def cleanup_old_checks():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM checks WHERE checked_at < datetime('now', '-7 days')")
        await db.commit()


async def add_service_if_missing(name: str, host: str, port: int,
                                  check_type: str, url: str, group_name: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM services WHERE host = ? AND port = ?", (host, port)
        )
        if not await cur.fetchone():
            await db.execute(
                "INSERT INTO services (name, host, port, check_type, url, group_name) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, host, port, check_type, url, group_name),
            )
            await db.commit()


async def save_discovered_port(host: str, port: int, service_hint: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO discovered_ports (host, port, service_hint, discovered_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (host, port, service_hint),
        )
        await db.commit()


async def get_discovered_ports():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute(
            "SELECT host, port, service_hint, discovered_at FROM discovered_ports ORDER BY host, port"
        )
        rows = await cur.fetchall()
        return [{"host": r[0], "port": r[1], "service_hint": r[2], "discovered_at": r[3]} for r in rows]


# ── New service CRUD helpers ────────────────────────────────────────────────

async def create_service(name: str, host: str, port: int,
                          check_type: str, url: str, group_name: str) -> dict:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "INSERT INTO services (name, host, port, check_type, url, group_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, host, port, check_type, url or None, group_name),
        )
        row_id = cur.lastrowid
        await db.commit()
        cur2 = await db.execute("SELECT * FROM services WHERE id = ?", (row_id,))
        row = await cur2.fetchone()
        return dict(row)


async def update_service(id: int, name: str, host: str, port: int,
                          check_type: str, url: str, group_name: str) -> dict | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "UPDATE services SET name=?, host=?, port=?, check_type=?, url=?, group_name=? "
            "WHERE id=? AND enabled=1",
            (name, host, port, check_type, url or None, group_name, id),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM services WHERE id=? AND enabled=1", (id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def delete_service(id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Hard-delete so the service doesn't reappear as a dimmed disabled row
        await db.execute("DELETE FROM incidents WHERE service_id=?", (id,))
        await db.execute("DELETE FROM checks WHERE service_id=?", (id,))
        cur = await db.execute("DELETE FROM services WHERE id=?", (id,))
        await db.commit()
        return cur.rowcount > 0


async def set_service_enabled(id: int, enabled: bool) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute(
            "UPDATE services SET enabled=? WHERE id=?", (1 if enabled else 0, id)
        )
        await db.commit()
        return cur.rowcount > 0


# ── Sparkline ───────────────────────────────────────────────────────────────

async def get_sparkline_data(service_id: int) -> list[dict]:
    """5-minute buckets over the last 24 hours, returning avg_ms and up ratio."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute(
            """
            SELECT
                strftime('%Y-%m-%dT%H:', checked_at) ||
                    printf('%02d', (CAST(strftime('%M', checked_at) AS INTEGER) / 5) * 5) || ':00'
                    AS bucket,
                AVG(response_ms) AS avg_ms,
                AVG(status)      AS up_ratio
            FROM checks
            WHERE service_id = ?
              AND checked_at >= datetime('now', '-24 hours')
            GROUP BY bucket
            ORDER BY bucket
            """,
            (service_id,),
        )
        rows = await cur.fetchall()
        return [
            {
                "bucket": r[0],
                "avg_ms": round(r[1]) if r[1] is not None else None,
                "up": r[2] >= 0.5 if r[2] is not None else None,
            }
            for r in rows
        ]


# ── Incident helpers ────────────────────────────────────────────────────────

async def open_incident(service_id: int, note: str = None) -> int:
    """Open a new incident. Manual events (note provided) always insert; monitoring deduplicates."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        if note is None:
            # Monitoring-triggered: avoid duplicate open incidents
            cur = await db.execute(
                "SELECT id FROM incidents WHERE service_id=? AND recovered_at IS NULL AND note IS NULL",
                (service_id,),
            )
            existing = await cur.fetchone()
            if existing:
                return existing[0]
        cur2 = await db.execute(
            "INSERT INTO incidents (service_id, note) VALUES (?, ?)", (service_id, note)
        )
        await db.commit()
        return cur2.lastrowid


async def close_incident(service_id: int, note: str = None):
    """Close any open incident for this service, optionally adding a closing note."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        if note:
            await db.execute(
                "UPDATE incidents SET recovered_at=datetime('now'), note=? "
                "WHERE service_id=? AND recovered_at IS NULL",
                (note, service_id),
            )
        else:
            await db.execute(
                "UPDATE incidents SET recovered_at=datetime('now') "
                "WHERE service_id=? AND recovered_at IS NULL",
                (service_id,),
            )
        await db.commit()


async def get_incidents(service_id: int, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute(
            "SELECT id, started_at, recovered_at, note FROM incidents "
            "WHERE service_id=? ORDER BY started_at DESC LIMIT ?",
            (service_id, limit),
        )
        rows = await cur.fetchall()
        return [
            {"id": r[0], "started_at": r[1], "recovered_at": r[2], "note": r[3]}
            for r in rows
        ]


# ── Settings helpers ────────────────────────────────────────────────────────

async def get_setting(key: str, default=None) -> str | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


async def get_all_settings() -> dict:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute("SELECT key, value FROM settings")
        rows = await cur.fetchall()
        return {r[0]: r[1] for r in rows}

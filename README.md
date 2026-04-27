# Home Monitoring Dashboard

A self-hosted network monitoring dashboard built with **FastAPI + React**, packaged as a single Docker container. Monitors HTTP, HTTPS, and TCP services on your local network with live updates, 7-day uptime history, incident tracking, and webhook alerts.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![React](https://img.shields.io/badge/React-18-61dafb)
![License](https://img.shields.io/badge/License-MIT-green)

## Quick Start

### Option A — Pull the prebuilt image from GHCR (recommended)

A multi-arch image (`linux/amd64` + `linux/arm64`) is published to the GitHub Container Registry on every push to `master`. No build toolchain required on the host — works on x86 servers, Raspberry Pi, and Apple Silicon.

Create a `docker-compose.yml` next to a `data/` directory:

```yaml
services:
  dashboard:
    image: ghcr.io/vipervndm/home-monitoring-dashboard:latest
    ports:
      - "8888:8080"
    volumes:
      - ./data:/app/data
    environment:
      - DATABASE_PATH=/app/data/monitoring.db
      - PORT=8080
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

Then:

```bash
docker compose pull
docker compose up -d
```

Open `http://localhost:8888` in your browser.

> If the package is private, run `docker login ghcr.io` once on each host first (use a GitHub PAT with `read:packages` scope as the password).

To upgrade to a new release: `docker compose pull && docker compose up -d`.

### Option B — Build from source

```bash
git clone https://github.com/ViperVnDm/home-monitoring-dashboard.git
cd home-monitoring-dashboard
docker compose up --build -d
```

Open `http://localhost:8888` in your browser.

```bash
# View live logs
docker compose logs -f

# Stop
docker compose down
```

> **Why port 8888?** Windows/Hyper-V reserves the 8076–8175 range for WSL2, which includes 8080. The compose file maps host port 8888 to the container's internal 8080 to avoid the conflict. On Linux you can change this back to `"8080:8080"` if preferred.

## Features

- **Live status updates** -- Server-Sent Events push check results to the browser instantly (no polling)
- **Response time sparkline** -- 24-hour inline chart per service (5-minute buckets)
- **7-day uptime grid** -- 168 hourly boxes colour-coded green/orange/red/grey with hover tooltips
- **7-day uptime percentage** -- colour thresholds: >=99% green, 95-98% orange, <95% red
- **Port scanner** -- auto-discovers open ports on configured hosts at startup (20 common ports including SSH, HTTP, Prometheus, Home Assistant, Node-RED, Jupyter, Portainer, etc.)
- **Service management** -- add, edit, delete, and enable/disable services from the UI
- **Incident history** -- per-service log with start/end times, duration, and status badges
- **Webhook alerts** -- Discord, Slack, or generic JSON POST on status transitions (DOWN / RECOVERED)
- **Export & import** -- CSV export for spreadsheets, JSON config export/import for backup and migration

## How It Works

Every 60 seconds the backend checks all enabled services and records the result in a local SQLite database (persisted in `./data/` via a bind mount). The frontend connects via SSE and updates live -- no page reload needed.

### Check Types

| Type | Method | "Up" means |
|------|--------|------------|
| `http` | GET request | HTTP status < 500 (401/403 = service is running) |
| `https` | GET request (SSL optional) | Same as http |
| `tcp` | TCP connect | Connection accepted |

SSL verification is automatically disabled for HTTPS checks against IP addresses (common for routers and appliances with self-signed certs).

## Adding Hosts

There are three ways to add services to monitor:

### 1. Via the Dashboard UI

Click **+ Add Service** and fill in the name, group, host, port, check type, and optional URL override. This is the easiest approach for one-off additions.

### 2. Via the Port Scanner

The backend includes an auto-discovery scanner that probes 20 common ports on any hosts configured in `backend/scanner.py`. To add a host for scanning, call `scan_and_register("your-hostname")` during startup in `backend/main.py`. Discovered open ports are automatically added as monitored services.

### 3. Via JSON Import

Use the **Import** button in the UI to load a previously exported `home-monitor-config.json` file. Services with the same host+port combination as existing entries are skipped automatically.

## Hostname Resolution

Services are checked from inside the Docker container. `.local` mDNS names **do not** resolve inside containers by default.

**Option A -- Host machine `/etc/hosts` (recommended)**

Add entries to your host machine's hosts file:

```
# /etc/hosts (Linux/macOS) or C:\Windows\System32\drivers\etc\hosts (Windows)
192.168.1.10  my-server
192.168.1.20  my-pi
```

Then set `network_mode: host` in `docker-compose.yml` so the container shares the host's network stack and hosts file.

**Option B -- Docker `extra_hosts`**

Uncomment and fill in the `extra_hosts` block in `docker-compose.yml`:

```yaml
services:
  dashboard:
    # ...
    extra_hosts:
      - "my-server:192.168.1.10"
      - "my-pi:192.168.1.20"
```

This injects the entries into the container's `/etc/hosts` without requiring host network mode.

## Backup & Restore

### What to back up

All persistent state lives in two places:

| Item | Location | Contains |
|------|----------|----------|
| Database | `./data/monitoring.db` | Service definitions, check history, uptime data, incidents, settings |
| Config export | Exported via UI | Service list + webhook settings (JSON) |

### Backup

**Option 1 -- Copy the database file**

```bash
# Stop the container first to avoid copying mid-write
docker compose down
cp ./data/monitoring.db ./data/monitoring.db.bak
docker compose up -d
```

**Option 2 -- Export configuration from the UI**

Click **JSON** in the dashboard header to download `home-monitor-config.json`. This captures all service definitions and webhook settings but **not** check history or uptime data.

**Option 3 -- Automated backup script**

```bash
#!/bin/bash
BACKUP_DIR="./backups"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
cp ./data/monitoring.db "$BACKUP_DIR/monitoring_${TIMESTAMP}.db"
echo "Backed up to $BACKUP_DIR/monitoring_${TIMESTAMP}.db"
```

### Restore

**From a database backup:**

```bash
docker compose down
cp ./data/monitoring.db.bak ./data/monitoring.db
docker compose up -d
```

**From a JSON config export:**

1. Start a fresh instance: `docker compose up --build -d`
2. Open the dashboard and click **Import**
3. Select your `home-monitor-config.json` file
4. Services and webhook settings are restored; duplicate host+port entries are skipped

> **Note:** The JSON export restores service definitions and settings only. Check history, uptime data, and incident logs are stored in the SQLite database and require a database-level backup to preserve.

## Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12 - FastAPI - aiosqlite - APScheduler - aiohttp |
| Frontend | React 18 - Vite (no UI framework, raw CSS) |
| Database | SQLite (`./data/monitoring.db`, bind-mounted volume) |
| Container | Single multi-stage image (Node build -> Python serve) |

## Project Structure

```
Dockerfile                 -- multi-stage: node build -> python serve
docker-compose.yml         -- single service, host port 8888 -> container 8080, ./data volume
.github/workflows/
  docker.yml               -- CI: builds and pushes multi-arch image to ghcr.io
backend/
  main.py                  -- FastAPI app, API routes, SSE, export/import
  database.py              -- schema, migrations, all DB helpers
  monitor.py               -- HTTP/TCP checks, transition detection, SSE broadcast
  scanner.py               -- port scanner and auto-discovery
  alerts.py                -- Discord / Slack / generic webhook notifications
  events.py                -- SSE pub/sub (subscribe / unsubscribe / broadcast)
  requirements.txt
frontend/src/
  App.jsx                  -- all React components
  index.css                -- dark GitHub-style theme
  components/
    ServiceModal.jsx       -- add / edit service modal
    SettingsModal.jsx      -- webhook settings modal
data/
  monitoring.db            -- SQLite database (created on first run)
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Liveness probe (used by the container HEALTHCHECK) |
| `GET` | `/api/services` | List all services with current status |
| `POST` | `/api/services` | Add a new service |
| `PUT` | `/api/services/:id` | Update a service |
| `PATCH` | `/api/services/:id` | Enable/disable a service |
| `DELETE` | `/api/services/:id` | Delete a service and its history |
| `GET` | `/api/services/:id/sparkline` | 24h response time data |
| `GET` | `/api/services/:id/incidents` | Incident history |
| `GET` | `/api/uptime` | 7-day uptime data for all services |
| `GET` | `/api/events` | SSE stream for live updates |
| `GET` | `/api/settings` | Get webhook settings |
| `PUT` | `/api/settings` | Update webhook settings |
| `POST` | `/api/settings/test` | Send a test alert |
| `GET` | `/api/export` | Download CSV export |
| `GET` | `/api/export/config` | Download JSON config |
| `POST` | `/api/import` | Import JSON config |
| `POST` | `/api/check-now` | Trigger an immediate check cycle |

## License

MIT

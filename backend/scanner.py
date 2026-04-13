import asyncio
from database import save_discovered_port, add_service_if_missing

# Common ports to probe and their likely service names
PROBE_PORTS = {
    22:    "SSH",
    80:    "HTTP",
    443:   "HTTPS",
    1880:  "Node-RED",
    1883:  "MQTT",
    3000:  "Grafana/HTTP",
    3001:  "HTTP",
    4000:  "HTTP",
    5000:  "HTTP",
    5900:  "VNC",
    6443:  "Kubernetes API",
    8000:  "HTTP",
    8080:  "HTTP",
    8123:  "Home Assistant",
    8443:  "HTTPS",
    8888:  "Jupyter",
    9000:  "Portainer",
    9090:  "Prometheus",
    9091:  "Transmission",
    51820: "WireGuard",
}

SCAN_TIMEOUT = 1.5  # seconds per port


async def _probe_port(host: str, port: int) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=SCAN_TIMEOUT
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def scan_host(host: str) -> list[dict]:
    """Scan PROBE_PORTS on host concurrently. Returns list of open port dicts."""
    tasks = {port: _probe_port(host, port) for port in PROBE_PORTS}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    open_ports = []
    for port, result in zip(tasks.keys(), results):
        if result is True:
            open_ports.append({"port": port, "service_hint": PROBE_PORTS[port]})
    return open_ports


async def register_discovered(host: str, open_ports: list[dict]):
    """Persist discovered ports and create monitoring services for them."""
    group_name = host.upper()
    for info in open_ports:
        port = info["port"]
        hint = info["service_hint"]

        await save_discovered_port(host, port, hint)

        # Determine protocol for the monitor check
        if port in (22, 51820, 1883):
            check_type = "tcp"
            url = None
        elif port in (443, 8443, 6443):
            check_type = "https"
            url = f"https://{host}:{port}"
        else:
            check_type = "http"
            url = f"http://{host}:{port}"

        name = f"{hint}" if hint else f"Port {port}"
        await add_service_if_missing(name, host, port, check_type, url, group_name)


async def scan_and_register(host: str) -> list[dict]:
    open_ports = await scan_host(host)
    await register_discovered(host, open_ports)
    return open_ports

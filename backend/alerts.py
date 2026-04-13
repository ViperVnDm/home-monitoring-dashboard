import aiohttp

from database import get_setting


def _discord_payload(event: str, service: dict, error: str | None) -> dict:
    if event == "down":
        color = 0xF85149  # red
        title = f"🔴 {service['name']} is DOWN"
        description = f"**Host:** `{service['host']}:{service['port']}`"
        if error:
            description += f"\n**Error:** {error}"
    else:
        color = 0x3FB950  # green
        title = f"🟢 {service['name']} recovered"
        description = f"**Host:** `{service['host']}:{service['port']}`"

    return {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
            }
        ]
    }


def _slack_payload(event: str, service: dict, error: str | None) -> dict:
    host_str = f"`{service['host']}:{service['port']}`"
    if event == "down":
        text = f":red_circle: *{service['name']}* is DOWN — {host_str}"
        if error:
            text += f"\nError: {error}"
    else:
        text = f":large_green_circle: *{service['name']}* recovered — {host_str}"
    return {"text": text}


def _generic_payload(event: str, service: dict, error: str | None) -> dict:
    return {
        "event": event,
        "service": service["name"],
        "host": service["host"],
        "port": service["port"],
        "error": error,
    }


async def send_alert(event: str, service: dict, error: str | None):
    webhook_url = await get_setting("webhook_url")
    if not webhook_url:
        return
    webhook_type = await get_setting("webhook_type", "discord")

    if webhook_type == "slack":
        payload = _slack_payload(event, service, error)
    elif webhook_type == "discord":
        payload = _discord_payload(event, service, error)
    else:
        payload = _generic_payload(event, service, error)

    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            )
    except Exception:
        pass  # Don't let alert failures crash the monitor


async def send_test_alert(webhook_url: str, webhook_type: str) -> tuple[bool, str]:
    test_service = {"name": "Test Service", "host": "localhost", "port": 8080}

    if webhook_type == "slack":
        payload = _slack_payload("down", test_service, "This is a test alert")
    elif webhook_type == "discord":
        payload = _discord_payload("down", test_service, "This is a test alert")
    else:
        payload = _generic_payload("down", test_service, "This is a test alert")

    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            )
            if resp.status < 300:
                return True, "Test alert sent successfully"
            text = await resp.text()
            return False, f"Webhook returned HTTP {resp.status}: {text[:200]}"
    except Exception as exc:
        return False, str(exc)[:200]

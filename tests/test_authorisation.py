"""Every WebSocket command and every service is reserved to administrators."""
from __future__ import annotations

import pytest
import yaml
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized

from custom_components.docker_marketplace.const import DOMAIN

# One valid message per command; the admin check must refuse before the body runs.
WS_COMMANDS: list[dict] = [
    {"type": f"{DOMAIN}/catalog"},
    {"type": f"{DOMAIN}/installed"},
    {"type": f"{DOMAIN}/install", "app_id": "demo"},
    {"type": f"{DOMAIN}/remove", "app_id": "demo"},
    {"type": f"{DOMAIN}/start", "app_id": "demo"},
    {"type": f"{DOMAIN}/stop", "app_id": "demo"},
    {"type": f"{DOMAIN}/restart", "app_id": "demo"},
    {"type": f"{DOMAIN}/logs", "app_id": "demo"},
    {"type": f"{DOMAIN}/app_status", "app_id": "demo"},
    {"type": f"{DOMAIN}/get_config", "app_id": "demo"},
    {"type": f"{DOMAIN}/update_config", "app_id": "demo", "config": {}},
]

SERVICES: list[tuple[str, dict]] = [
    ("install_app", {"app_id": "demo"}),
    ("remove_app", {"app_id": "demo"}),
    ("update_app", {"app_id": "demo"}),
    ("start_app", {"app_id": "demo"}),
    ("stop_app", {"app_id": "demo"}),
    ("restart_app", {"app_id": "demo"}),
]


def test_every_registered_command_is_covered() -> None:
    from custom_components.docker_marketplace import api

    registered = {
        getattr(api, name)._ws_command
        for name in dir(api)
        if name.startswith("websocket_") and hasattr(getattr(api, name), "_ws_command")
    }
    assert registered == {msg["type"] for msg in WS_COMMANDS}


@pytest.mark.parametrize("message", WS_COMMANDS, ids=lambda m: m["type"])
async def test_non_admin_websocket_command_is_refused(
    hass: HomeAssistant,
    integration,
    sdk,
    hass_ws_client,
    hass_read_only_access_token: str,
    message: dict,
) -> None:
    client = await hass_ws_client(hass, hass_read_only_access_token)
    sdk.calls.clear()

    await client.send_json_auto_id(dict(message))
    response = await client.receive_json()
    await hass.async_block_till_done()

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"
    assert sdk.calls == []


@pytest.mark.parametrize("message", WS_COMMANDS, ids=lambda m: m["type"])
async def test_admin_websocket_command_is_handled(
    hass: HomeAssistant, integration, hass_ws_client, message: dict
) -> None:
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(dict(message))
    response = await client.receive_json()
    while response.get("type") == "event":
        response = await client.receive_json()

    # Some commands legitimately fail here (e.g. removing an app that is not
    # installed); what matters is that the handler ran instead of being refused.
    assert response.get("error", {}).get("code") != "unauthorized"


@pytest.mark.parametrize(("service", "data"), SERVICES, ids=lambda s: str(s))
async def test_non_admin_service_call_is_refused(
    hass: HomeAssistant, integration, sdk, hass_read_only_user, service: str, data: dict
) -> None:
    sdk.calls.clear()

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            service,
            dict(data),
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    await hass.async_block_till_done()

    assert sdk.calls == []


async def test_admin_service_call_runs(
    hass: HomeAssistant, integration, sdk, hass_admin_user
) -> None:
    sdk.calls.clear()

    await hass.services.async_call(
        DOMAIN,
        "install_app",
        {"app_id": "demo"},
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )

    assert "containers.run" in sdk.call_names()


async def test_get_config_never_returns_secret_values(
    hass: HomeAssistant, integration, stacks_path, hass_ws_client
) -> None:
    stack_dir = stacks_path / "demo"
    stack_dir.mkdir(parents=True)
    (stack_dir / "docker-compose.yml").write_text(
        yaml.safe_dump({"services": {"demo": {"image": "example/demo:1"}}})
    )
    (stack_dir / "config.yaml").write_text(
        yaml.safe_dump({"env_TZ": "Asia/Tokyo", "env_API_TOKEN": "stored-token-value"})
    )
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": f"{DOMAIN}/get_config", "app_id": "demo"})
    response = await client.receive_json()

    assert response["success"] is True
    config = response["result"]["config"]
    assert config == {"env_TZ": "Asia/Tokyo"}
    assert "stored-token-value" not in str(response)

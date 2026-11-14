"""Application ids and form values are validated before any filesystem or
Docker call, and every stack path stays a direct child of the stacks root."""
from __future__ import annotations

from pathlib import Path

import pytest
import voluptuous as vol
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.docker_marketplace.const import DOMAIN
from .app_ids import BAD_APP_IDS
from .fake_docker import owned_labels

APP_ID_COMMANDS = ["install", "remove", "start", "stop", "restart", "logs", "app_status",
                   "get_config", "update_config"]
APP_ID_SERVICES = ["install_app", "remove_app", "update_app", "start_app", "stop_app",
                   "restart_app"]


def write_stack(stacks_path: Path, app_id: str, services: dict) -> Path:
    stack_dir = stacks_path / app_id
    stack_dir.mkdir(parents=True, exist_ok=True)
    (stack_dir / "docker-compose.yml").write_text(yaml.safe_dump({"services": services}))
    return stack_dir


@pytest.fixture
def outside_dir(tmp_path: Path) -> Path:
    """A directory outside the stacks root holding a compose file."""
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "docker-compose.yml").write_text(
        yaml.safe_dump({"services": {"victim": {"image": "example/x:1",
                                                "container_name": "victim"}}})
    )
    return target


@pytest.mark.parametrize("command", APP_ID_COMMANDS)
@pytest.mark.parametrize("app_id", BAD_APP_IDS)
async def test_websocket_rejects_bad_app_ids(
    hass: HomeAssistant, integration, sdk, hass_ws_client, command: str, app_id: str
) -> None:
    client = await hass_ws_client(hass)
    sdk.calls.clear()
    message = {"type": f"{DOMAIN}/{command}", "app_id": app_id}
    if command == "update_config":
        message["config"] = {}

    await client.send_json_auto_id(message)
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"
    assert sdk.calls == []


@pytest.mark.parametrize("service", APP_ID_SERVICES)
@pytest.mark.parametrize("app_id", ["..", "/abs", "a/b", ""])
async def test_services_reject_bad_app_ids(
    hass: HomeAssistant, integration, sdk, service: str, app_id: str
) -> None:
    sdk.calls.clear()

    with pytest.raises(vol.Invalid, match="app_id"):
        await hass.services.async_call(DOMAIN, service, {"app_id": app_id}, blocking=True)

    assert sdk.calls == []


@pytest.mark.parametrize(
    "method", ["remove_app", "update_app", "start_app", "stop_app", "get_logs",
               "get_app_config"]
)
async def test_coordinator_refuses_a_path_outside_the_stacks_root(
    coordinator, sdk, outside_dir: Path, method: str
) -> None:
    sdk.calls.clear()

    with pytest.raises(ServiceValidationError):
        await getattr(coordinator, method)(str(outside_dir))

    assert sdk.calls == []
    assert (outside_dir / "docker-compose.yml").exists()


async def test_coordinator_refuses_a_symlinked_stack_dir(
    coordinator, sdk, stacks_path: Path, outside_dir: Path
) -> None:
    (stacks_path / "demo").symlink_to(outside_dir, target_is_directory=True)
    sdk.calls.clear()

    with pytest.raises(ServiceValidationError):
        await coordinator.remove_app("demo")

    assert sdk.calls == []
    assert (outside_dir / "docker-compose.yml").exists()


async def test_install_rejects_a_volume_value_containing_a_colon(
    hass: HomeAssistant, integration, sdk, stacks_path: Path, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    sdk.calls.clear()

    await client.send_json_auto_id({
        "type": f"{DOMAIN}/install",
        "app_id": "demo",
        "config": {"volume_data": "/:/host:rw"},
    })
    response = await client.receive_json()
    while response.get("type") == "event":
        response = await client.receive_json()

    assert response["success"] is False
    assert sdk.calls == []
    assert not (stacks_path / "demo").exists()


async def test_update_config_rejects_an_unknown_key(
    coordinator, sdk, stacks_path: Path
) -> None:
    write_stack(stacks_path, "demo", {"demo": {"image": "example/demo:1"}})
    sdk.calls.clear()

    with pytest.raises(ServiceValidationError):
        await coordinator.update_config("demo", {"privileged": "true"})

    assert not (stacks_path / "demo" / "config.yaml").exists()


async def test_install_mounts_the_volume_at_the_catalogue_path(
    coordinator, sdk
) -> None:
    assert await coordinator.install_app("demo", {"volume_data": "/srv/demo"})

    run = next(args for name, args in sdk.calls if name == "containers.run")
    assert run["volumes"] == {"/srv/demo": {"bind": "/data", "mode": "rw"}}


async def test_logs_are_refused_for_an_app_that_is_not_installed(coordinator, sdk) -> None:
    sdk.containers.add("unrelated")
    sdk.calls.clear()

    assert await coordinator.get_logs("unrelated") is None
    assert sdk.calls == []


async def test_logs_are_refused_for_a_container_the_app_does_not_declare(
    coordinator, sdk, stacks_path: Path
) -> None:
    # The stack declares only "other-name": a container named like the app id
    # is not one of its containers.
    write_stack(stacks_path, "demo", {"demo": {"image": "example/demo:1",
                                               "container_name": "other-name"}})
    sdk.containers.add("demo")
    sdk.calls.clear()

    assert await coordinator.get_logs("demo") is None
    assert sdk.calls == []


async def test_logs_of_an_installed_app_are_returned(
    coordinator, sdk, stacks_path: Path
) -> None:
    write_stack(stacks_path, "demo", {"demo": {"image": "example/demo:1",
                                               "container_name": "demo"}})
    sdk.containers.add("demo", labels=owned_labels("demo"))

    assert await coordinator.get_logs("demo", 50) == "log of demo\n"


async def test_logs_tail_is_bounded(hass: HomeAssistant, integration, hass_ws_client) -> None:
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/logs", "app_id": "demo", "tail": 10_000_000}
    )
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"

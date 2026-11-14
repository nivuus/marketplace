"""An installed app without a container is stopped, not "not installed"; an
unreachable Docker daemon fails the refresh and makes the entities unavailable."""
from __future__ import annotations

from pathlib import Path

import pytest
import requests
import yaml
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.docker_marketplace.const import DOMAIN, STATE_STOPPED

from .fake_docker import owned_labels


def write_stack(stacks_path: Path, app_id: str, services: dict) -> None:
    stack_dir = stacks_path / app_id
    stack_dir.mkdir(parents=True, exist_ok=True)
    (stack_dir / "docker-compose.yml").write_text(yaml.safe_dump({"services": services}))


def entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    found = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert found is not None, unique_id
    return found


@pytest.fixture
async def installed_demo(hass: HomeAssistant, coordinator, sdk, stacks_path: Path):
    write_stack(stacks_path, "demo", {"demo": {"image": "example/demo:1",
                                               "container_name": "demo"}})
    sdk.containers.add("demo", labels=owned_labels("demo"))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    return coordinator


async def test_stopped_app_is_stopped_and_controllable(
    hass: HomeAssistant, installed_demo, sdk
) -> None:
    assert await installed_demo.stop_app("demo") is True
    await hass.async_block_till_done()

    assert installed_demo.data.installed_apps["demo"].state == STATE_STOPPED
    assert hass.states.get(entity_id(hass, "switch", f"{DOMAIN}_demo_power")).state == STATE_OFF
    start = hass.states.get(entity_id(hass, "button", f"{DOMAIN}_demo_start"))
    assert start.state != STATE_UNAVAILABLE


async def test_raw_stack_without_containers_is_stopped(
    hass: HomeAssistant, coordinator, stacks_path: Path
) -> None:
    write_stack(stacks_path, "stack", {"stack": {"image": "example/stack:1",
                                                 "container_name": "stack"}})

    await coordinator.async_refresh()

    assert coordinator.data.installed_apps["stack"].state == STATE_STOPPED


async def test_unreachable_docker_fails_the_refresh(
    hass: HomeAssistant, installed_demo, sdk
) -> None:
    sdk.failure = requests.exceptions.ConnectionError("daemon unreachable")

    await installed_demo.async_refresh()
    await hass.async_block_till_done()

    assert installed_demo.last_update_success is False
    switch = hass.states.get(entity_id(hass, "switch", f"{DOMAIN}_demo_power"))
    assert switch.state == STATE_UNAVAILABLE
    for button in ("start", "stop", "restart"):
        state = hass.states.get(entity_id(hass, "button", f"{DOMAIN}_demo_{button}"))
        assert state.state == STATE_UNAVAILABLE, button

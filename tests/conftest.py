"""Shared fixtures: a Home Assistant instance running the integration against
an in-memory Docker daemon (tests/fake_docker.py) and a test catalogue."""
from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

from custom_components.docker_marketplace.const import (
    CONF_CATALOG_PATH,
    CONF_DOCKER_HOST,
    CONF_STACKS_PATH,
    DOMAIN,
)
from custom_components.docker_marketplace.docker_client import DockerClient

from .fake_docker import FakeSdk

CATALOG_DIR = Path(__file__).parent / "fixtures" / "catalog"


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> FakeSdk:
    """Replace the Docker SDK client every DockerClient creates."""
    fake = FakeSdk()
    monkeypatch.setattr(DockerClient, "_create_client", lambda self: fake)
    return fake


@pytest.fixture
def stacks_path(tmp_path: Path) -> Path:
    """Where the integration keeps installed stacks during a test."""
    return tmp_path / "stacks"


@pytest.fixture
def config_entry(hass: HomeAssistant, stacks_path: Path) -> MockConfigEntry:
    """A config entry pointing at the test catalogue and a temporary stacks root."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DOCKER_HOST: "unix:///nonexistent/docker.sock",
            CONF_CATALOG_PATH: str(CATALOG_DIR),
            CONF_STACKS_PATH: str(stacks_path),
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def integration(
    hass: HomeAssistant, sdk: FakeSdk, config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set the integration up and return its loaded config entry."""
    # The panel registration serves static files through the http component.
    assert await async_setup_component(hass, "http", {})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
def coordinator(hass: HomeAssistant, integration: MockConfigEntry):
    """The running coordinator."""
    return hass.data[DOMAIN][integration.entry_id]["coordinator"]

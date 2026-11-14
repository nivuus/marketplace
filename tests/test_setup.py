"""The integration sets up against the fake daemon and the test catalogue."""
from __future__ import annotations

import requests
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.docker_marketplace.catalog import Catalog
from custom_components.docker_marketplace.const import DOMAIN


async def test_setup_loads_entry_and_catalogue(hass: HomeAssistant, integration) -> None:
    assert integration.state is ConfigEntryState.LOADED
    catalog = hass.data[DOMAIN]["catalog"]
    assert set(catalog.apps) == {"demo", "stack"}
    assert hass.services.has_service(DOMAIN, "install_app")


async def test_unreachable_docker_at_setup_is_retried(
    hass: HomeAssistant, sdk, config_entry
) -> None:
    sdk.failure = requests.exceptions.ConnectionError("daemon unreachable")
    assert await async_setup_component(hass, "http", {})

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unreadable_catalogue_at_setup_is_retried(
    hass: HomeAssistant, sdk, config_entry, monkeypatch
) -> None:
    async def failed_load(self) -> bool:
        return False

    monkeypatch.setattr(Catalog, "load", failed_load)
    assert await async_setup_component(hass, "http", {})

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY

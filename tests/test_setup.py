"""The integration sets up against the fake daemon and the test catalogue."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.docker_marketplace.const import DOMAIN


async def test_setup_loads_entry_and_catalogue(hass: HomeAssistant, integration) -> None:
    assert integration.state is ConfigEntryState.LOADED
    catalog = hass.data[DOMAIN]["catalog"]
    assert set(catalog.apps) == {"demo", "stack"}
    assert hass.services.has_service(DOMAIN, "install_app")

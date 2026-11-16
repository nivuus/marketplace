"""The config flow offers the Docker endpoint the foundation actually provides."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.docker_marketplace.const import CONF_DOCKER_HOST, DOMAIN


async def test_default_docker_host_is_the_foundation_socket_proxy(
    hass: HomeAssistant,
) -> None:
    # home-manager's Home Assistant container has no /var/run/docker.sock
    # (removed 2026-07-27); its only Docker API is the filtered proxy it
    # publishes on the loopback (stack/docker-compose.yml, docker-socket-proxy).
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})

    schema = result["data_schema"].schema
    default = next(key for key in schema if key == CONF_DOCKER_HOST).default()
    assert default == "tcp://127.0.0.1:2375"

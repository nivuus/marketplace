"""The shipped catalogue loads, and ships no credential."""
from __future__ import annotations

from pathlib import Path

from custom_components.docker_marketplace.catalog import Catalog

REPO_CATALOG = Path(__file__).parent.parent / "catalog"


async def test_shipped_catalogue_loads_every_entry() -> None:
    catalog = Catalog(str(REPO_CATALOG))

    assert await catalog.load() is True
    shipped = {path.stem for path in (REPO_CATALOG / "apps").glob("*.yaml")}
    assert set(catalog.apps) == shipped


async def test_raw_compose_entries_ship_no_database_password() -> None:
    catalog = Catalog(str(REPO_CATALOG))
    await catalog.load()

    for app in catalog.apps.values():
        for service in (app.compose_raw or {}).get("services", {}).values():
            for item in service.get("environment") or []:
                name, _, value = str(item).partition("=")
                if name == "POSTGRES_PASSWORD":
                    assert value == "", f"{app.id} ships a database password"


async def test_a_broken_app_file_is_reported(tmp_path: Path, caplog) -> None:
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "broken.yaml").write_text("id: broken\nname: [unclosed\n")
    (apps / "empty.yaml").write_text("")

    catalog = Catalog(str(tmp_path))
    await catalog.load()

    assert catalog.apps == {}
    assert str(apps / "broken.yaml") in caplog.text
    assert str(apps / "empty.yaml") in caplog.text


# What the foundation package (nivuus/home-manager, stack/docker-compose.yml)
# already runs on every machine of the suite. The catalogue is laid into that
# same Home Assistant by this package, so an entry duplicating one of these is
# an app that either cannot start (its host ports are taken) or, on the host
# network, starts a second server fighting the first for the same port.
FOUNDATION_IMAGES = {
    "eclipse-mosquitto",                                # mosquitto, pinned 2.1.2
    "ghcr.io/home-assistant-libs/python-matter-server",  # replaced by matterjs-server
    "ghcr.io/matter-js/matterjs-server",
    "ghcr.io/home-assistant/home-assistant",
    "koenkk/zigbee2mqtt",
    "ghcr.io/music-assistant/server",
    "bnutzer/otbr-tcp",
    "tecnativa/docker-socket-proxy",
}
FOUNDATION_HOST_PORTS = {1883, 1884, 8883, 8884, 2375, 4416, 3000}


def _images(app) -> set[str]:
    images = {app.compose.image} if app.compose else set()
    for service in (app.compose_raw or {}).get("services", {}).values():
        images.add(service.get("image", ""))
    return {image.rsplit("@", 1)[0].rsplit(":", 1)[0] for image in images if image}


async def test_no_shipped_app_duplicates_a_foundation_service() -> None:
    catalog = Catalog(str(REPO_CATALOG))
    await catalog.load()

    for app in catalog.apps.values():
        assert not _images(app) & FOUNDATION_IMAGES, (
            f"{app.id} ships a service the foundation already runs")
        assert not {p.host for p in app.ports} & FOUNDATION_HOST_PORTS, (
            f"{app.id} publishes a host port a foundation service holds")

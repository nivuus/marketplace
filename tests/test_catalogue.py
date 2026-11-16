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

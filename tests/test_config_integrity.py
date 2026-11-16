"""An app's saved configuration is never rebuilt from a file that cannot be read,
and the stack files are replaced whole, never rewritten in place."""

from __future__ import annotations

import os
from pathlib import Path

import atomicwrites
import pytest
import yaml
from homeassistant.exceptions import HomeAssistantError

from custom_components.docker_marketplace.const import DOMAIN

SAVED = {
    "port_8080": 28080,
    "volume_data": "/srv/demo",
    "env_TZ": "Europe/Paris",
    "env_API_TOKEN": "kept-secret",
}


@pytest.fixture
def demo_stack(coordinator, stacks_path: Path) -> Path:
    """An installed demo app whose saved configuration differs from the defaults."""
    stack_dir = stacks_path / "demo"
    stack_dir.mkdir(parents=True)
    (stack_dir / "config.yaml").write_text(yaml.safe_dump(SAVED))
    compose = coordinator._generate_compose(coordinator.catalog.get_app("demo"), SAVED)
    (stack_dir / "docker-compose.yml").write_text(yaml.safe_dump(compose))
    return stack_dir


def _snapshot(stack_dir: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in stack_dir.iterdir()}


@pytest.mark.parametrize(
    ("damage", "key"),
    [
        (b"", "stack_file_invalid"),  # truncated to nothing
        (
            b"port_8080: 28080\nvolume_data: [/srv",
            "stack_file_invalid",
        ),  # cut mid-write
        (b"- a list\n- not a mapping\n", "stack_file_invalid"),
        (b"\xff\xfe\x00 not utf-8", "stack_file_unreadable"),
    ],
)
async def test_damaged_config_aborts_the_update_and_changes_nothing(
    coordinator, demo_stack: Path, damage: bytes, key: str
) -> None:
    (demo_stack / "config.yaml").write_bytes(damage)
    before = _snapshot(demo_stack)

    with pytest.raises(HomeAssistantError) as raised:
        await coordinator.update_config("demo", {"env_TZ": "Asia/Tokyo"})

    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == key
    assert _snapshot(demo_stack) == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its mode")
async def test_unreadable_config_aborts_the_update(
    coordinator, demo_stack: Path
) -> None:
    config_file = demo_stack / "config.yaml"
    config_file.chmod(0)
    before = {path.name: path.stat().st_mtime_ns for path in demo_stack.iterdir()}

    with pytest.raises(HomeAssistantError) as raised:
        await coordinator.update_config("demo", {"env_TZ": "Asia/Tokyo"})

    assert raised.value.translation_key == "stack_file_unreadable"
    assert {
        path.name: path.stat().st_mtime_ns for path in demo_stack.iterdir()
    } == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes whatever the mode")
async def test_a_failed_write_is_an_error_not_a_success(
    coordinator, demo_stack: Path
) -> None:
    before = _snapshot(demo_stack)
    demo_stack.chmod(0o500)
    try:
        with pytest.raises(HomeAssistantError) as raised:
            await coordinator.update_config("demo", {"env_TZ": "Asia/Tokyo"})
    finally:
        demo_stack.chmod(0o700)

    assert raised.value.translation_key == "stack_file_unwritable"
    assert _snapshot(demo_stack) == before


async def test_update_keeps_every_saved_value(coordinator, demo_stack: Path) -> None:
    assert await coordinator.update_config("demo", {"env_TZ": "Asia/Tokyo"}) is True

    saved = yaml.safe_load((demo_stack / "config.yaml").read_text())
    assert saved == {**SAVED, "env_TZ": "Asia/Tokyo"}
    service = yaml.safe_load((demo_stack / "docker-compose.yml").read_text())[
        "services"
    ]["demo"]
    assert service["ports"] == ["28080:8080/tcp"]
    assert service["volumes"][0]["source"] == "/srv/demo"
    assert service["environment"]["API_TOKEN"] == "kept-secret"


async def test_absent_config_is_an_empty_one(coordinator, demo_stack: Path) -> None:
    (demo_stack / "config.yaml").unlink()

    assert await coordinator.update_config("demo", {"env_TZ": "Asia/Tokyo"}) is True

    assert yaml.safe_load((demo_stack / "config.yaml").read_text()) == {
        "env_TZ": "Asia/Tokyo"
    }


async def test_reading_a_damaged_config_is_an_error_not_the_defaults(
    coordinator, demo_stack: Path
) -> None:
    (demo_stack / "config.yaml").write_bytes(b"")

    with pytest.raises(HomeAssistantError) as raised:
        await coordinator.get_app_config("demo")

    assert raised.value.translation_key == "stack_file_invalid"


async def test_reading_an_absent_config_gives_an_empty_one(
    coordinator, demo_stack: Path
) -> None:
    (demo_stack / "config.yaml").unlink()

    assert await coordinator.get_app_config("demo") == {}


async def test_get_config_command_reports_the_translated_error(
    hass, coordinator, demo_stack: Path, hass_ws_client
) -> None:
    (demo_stack / "config.yaml").write_bytes(b"")
    client = await hass_ws_client(hass)

    await client.send_json({"id": 1, "type": f"{DOMAIN}/get_config", "app_id": "demo"})
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["translation_key"] == "stack_file_invalid"
    assert response["error"]["translation_domain"] == DOMAIN
    assert str(demo_stack / "config.yaml") in response["error"]["message"]


def test_a_failed_write_leaves_the_previous_file_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from custom_components.docker_marketplace import stack_files

    target = tmp_path / "config.yaml"
    target.write_text(yaml.safe_dump(SAVED))

    def disk_full(fd: int) -> None:
        raise OSError(28, "No space left on device")

    # atomicwrites binds os.fsync at import time: patch the name it calls.
    monkeypatch.setattr(atomicwrites, "_proper_fsync", disk_full)

    with pytest.raises(HomeAssistantError):
        stack_files.write_yaml(target, {"env_TZ": "Asia/Tokyo"})

    assert yaml.safe_load(target.read_text()) == SAVED
    assert [path.name for path in tmp_path.iterdir()] == ["config.yaml"]


def test_writes_are_durable_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from custom_components.docker_marketplace import stack_files

    synced: list[int] = []
    monkeypatch.setattr(
        atomicwrites, "_proper_fsync", lambda fd: (synced.append(fd), os.fsync(fd))
    )
    target = tmp_path / "config.yaml"

    stack_files.write_yaml(target, SAVED)

    assert yaml.safe_load(target.read_text()) == SAVED
    assert len(synced) >= 2  # the file, then its directory
    assert target.stat().st_mode & 0o777 == 0o600

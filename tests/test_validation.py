"""Pure validation logic: application ids, form values, compose generation."""
from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.docker_marketplace.catalog import (
    AppCompose,
    AppDefinition,
    AppEnvironment,
    AppPort,
    AppVolume,
)
from custom_components.docker_marketplace.validation import (
    InvalidAppRequest,
    validate_app_config,
    validate_app_id,
    validate_tail,
)

from .app_ids import BAD_APP_IDS


def make_app() -> AppDefinition:
    return AppDefinition(
        id="demo",
        name="Demo",
        category="web",
        description="",
        ports=[AppPort(container=8080, host=18080)],
        volumes=[AppVolume(name="data", container="/data")],
        environment=[AppEnvironment(name="TZ", default="UTC")],
        compose=AppCompose(image="example/demo:1"),
    )


@pytest.mark.parametrize("value", BAD_APP_IDS)
def test_bad_app_ids_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        validate_app_id(value)


@pytest.mark.parametrize("value", [None, 3, ["demo"]])
def test_non_string_app_ids_are_rejected(value) -> None:
    with pytest.raises(ValueError):
        validate_app_id(value)


@pytest.mark.parametrize("value", ["demo", "matter-server", "app_2", "0x"])
def test_slug_app_ids_are_accepted(value: str) -> None:
    assert validate_app_id(value) == value


@pytest.mark.parametrize("value", [0, -1, 10_001, "many", True])
def test_out_of_range_tail_is_rejected(value) -> None:
    with pytest.raises(ValueError):
        validate_tail(value)


def test_tail_in_range_is_accepted() -> None:
    assert validate_tail(1) == 1
    assert validate_tail("200") == 200


def test_unknown_config_key_is_rejected() -> None:
    with pytest.raises(InvalidAppRequest):
        validate_app_config(make_app(), {"privileged": True})


@pytest.mark.parametrize("value", ["0", "65536", "80/tcp", "8080:80", "abc", True, None])
def test_bad_port_values_are_rejected(value) -> None:
    with pytest.raises(InvalidAppRequest):
        validate_app_config(make_app(), {"port_8080": value})


def test_port_strings_from_the_form_become_integers() -> None:
    assert validate_app_config(make_app(), {"port_8080": "28080"}) == {"port_8080": 28080}


@pytest.mark.parametrize(
    "value",
    ["/:/host:rw", "/srv/a:b", "relative/path", "/srv/a\nb", "/srv/\x00", 5],
)
def test_bad_volume_values_are_rejected(value) -> None:
    with pytest.raises(InvalidAppRequest):
        validate_app_config(make_app(), {"volume_data": value})


@pytest.mark.parametrize("value", ["/srv/demo", "/srv/données/日本", ""])
def test_absolute_volume_paths_are_accepted(value: str) -> None:
    assert validate_app_config(make_app(), {"volume_data": value}) == {"volume_data": value}


@pytest.mark.parametrize("value", ["a\nB=1", "a\rb", "a\x00b"])
def test_env_values_cannot_break_out_of_their_line(value: str) -> None:
    with pytest.raises(InvalidAppRequest):
        validate_app_config(make_app(), {"env_TZ": value})


@pytest.mark.parametrize("value", ["Europe/Paris", "Ásia/東京 — مرحبا", "x=y"])
def test_env_values_in_any_script_are_accepted(value: str) -> None:
    assert validate_app_config(make_app(), {"env_TZ": value}) == {"env_TZ": value}


def test_generated_compose_emits_bind_mounts_as_structured_data(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from custom_components.docker_marketplace.coordinator import (
        DockerMarketplaceCoordinator,
    )

    compose = DockerMarketplaceCoordinator._generate_compose(
        SimpleNamespace(stacks_path=tmp_path), make_app(), {"volume_data": "/srv/demo"}
    )

    assert compose["services"]["demo"]["volumes"] == [
        {"type": "bind", "source": "/srv/demo", "target": "/data"}
    ]

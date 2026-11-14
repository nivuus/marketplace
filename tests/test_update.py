"""Updating an app: a failed pull changes nothing, an unchanged image is not
recreated, and a recreated container keeps its exposed ports."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from docker.errors import APIError
from docker.types import ContainerConfig

from .fake_docker import owned_labels

DESTRUCTIVE = {"container.stop", "container.remove", "api.create_container", "api.start",
               "containers.run"}


@pytest.fixture
def demo_stack(stacks_path: Path) -> Path:
    stack_dir = stacks_path / "demo"
    stack_dir.mkdir(parents=True)
    compose = stack_dir / "docker-compose.yml"
    compose.write_text(yaml.safe_dump(
        {"services": {"demo": {"image": "example/demo:1", "container_name": "demo"}}}
    ))
    return compose


async def test_failed_pull_stops_the_update(coordinator, sdk, demo_stack: Path) -> None:
    container = sdk.containers.add("demo", image="example/demo:1",
                                   labels=owned_labels("demo"))
    sdk.images.pull_error = APIError("registry unreachable")
    sdk.calls.clear()

    assert await coordinator.update_app("demo") is False

    assert [name for name in sdk.call_names() if name in DESTRUCTIVE] == []
    assert sdk.containers.by_name["demo"] is container
    assert container.status == "running"


async def test_unchanged_image_is_not_recreated(coordinator, sdk, demo_stack: Path) -> None:
    container = sdk.containers.add("demo", image="example/demo:1",
                                   labels=owned_labels("demo"))
    sdk.images.pull_changes_image = False
    sdk.calls.clear()

    assert await coordinator.update_app("demo") is True

    assert [name for name in sdk.call_names() if name in DESTRUCTIVE] == []
    assert sdk.containers.by_name["demo"] is container


async def test_recreate_passes_exposed_ports_in_the_sdk_form(
    coordinator, sdk, demo_stack: Path
) -> None:
    exposed = {"1884/tcp": {}, "5353/udp": {}}
    sdk.containers.add("demo", image="example/demo:1", labels=owned_labels("demo"),
                       exposed_ports=exposed)

    assert await coordinator.update_app("demo") is True

    create = next(args for name, args in sdk.calls if name == "api.create_container")
    # Run the captured argument through the SDK's own conversion: the
    # container must expose exactly the ports it exposed before.
    config = ContainerConfig("1.44", create["image"], None, ports=create["ports"])
    assert config["ExposedPorts"] == exposed

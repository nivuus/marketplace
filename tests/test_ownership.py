"""The integration acts only on containers carrying both of its ownership
labels for the application; a same-named container it does not own is never
adopted, stopped, removed or replaced."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from homeassistant.exceptions import HomeAssistantError

from .fake_docker import owned_labels

MUTATING = {"container.start", "container.stop", "container.remove", "containers.run",
            "api.create_container", "api.start"}


def mutations(sdk) -> list[tuple[str, object]]:
    return [(name, args) for name, args in sdk.calls if name in MUTATING]


def write_stack(stacks_path: Path, app_id: str, services: dict) -> Path:
    stack_dir = stacks_path / app_id
    stack_dir.mkdir(parents=True, exist_ok=True)
    compose = stack_dir / "docker-compose.yml"
    compose.write_text(yaml.safe_dump({"services": services}))
    return compose


@pytest.fixture
def demo_stack(stacks_path: Path) -> Path:
    return write_stack(
        stacks_path, "demo", {"demo": {"image": "example/demo:1", "container_name": "demo"}}
    )


async def test_install_refuses_a_foreign_container_with_the_same_name(
    coordinator, sdk, stacks_path: Path
) -> None:
    foreign = sdk.containers.add("demo", status="exited")
    sdk.calls.clear()

    with pytest.raises(HomeAssistantError, match="demo"):
        await coordinator.install_app("demo")

    assert mutations(sdk) == []
    assert foreign.status == "exited"
    assert not (stacks_path / "demo").exists()


async def test_install_refuses_a_container_owned_by_another_app(
    coordinator, sdk, stacks_path: Path
) -> None:
    sdk.containers.add("demo", labels=owned_labels("other"))
    sdk.calls.clear()

    with pytest.raises(HomeAssistantError):
        await coordinator.install_app("demo")

    assert mutations(sdk) == []


async def test_install_labels_raw_compose_services(coordinator, sdk) -> None:
    assert await coordinator.install_app("stack")

    created = {args["name"]: args["labels"] for name, args in sdk.calls
               if name == "containers.run"}
    assert set(created) == {"stack", "stack-db"}
    for labels in created.values():
        assert labels.items() >= owned_labels("stack").items()


@pytest.mark.parametrize("method", ["stop_app", "remove_app", "update_app", "start_app"])
async def test_lifecycle_leaves_a_foreign_container_untouched(
    coordinator, sdk, demo_stack: Path, method: str
) -> None:
    foreign = sdk.containers.add("demo", status="running")
    sdk.calls.clear()

    assert await getattr(coordinator, method)("demo") is False

    assert mutations(sdk) == []
    assert sdk.containers.by_name["demo"] is foreign
    assert foreign.status == "running"
    assert demo_stack.exists()


async def test_logs_of_a_foreign_container_are_refused(
    coordinator, sdk, demo_stack: Path
) -> None:
    sdk.containers.add("demo")

    assert await coordinator.get_logs("demo") is None
    assert "container.logs" not in sdk.call_names()


async def test_stop_removes_an_owned_container(coordinator, sdk, demo_stack: Path) -> None:
    sdk.containers.add("demo", labels=owned_labels("demo"))

    assert await coordinator.stop_app("demo") is True

    assert "demo" not in sdk.containers.by_name


async def test_update_recreates_an_owned_container(coordinator, sdk, demo_stack: Path) -> None:
    sdk.containers.add("demo", labels=owned_labels("demo"))

    assert await coordinator.update_app("demo") is True

    created = [args for name, args in sdk.calls if name == "api.create_container"]
    assert [args["name"] for args in created] == ["demo"]
    assert created[0]["labels"].items() >= owned_labels("demo").items()


async def test_logs_of_an_owned_container_are_returned(
    coordinator, sdk, demo_stack: Path
) -> None:
    sdk.containers.add("demo", labels=owned_labels("demo"))

    assert await coordinator.get_logs("demo") == "log of demo\n"

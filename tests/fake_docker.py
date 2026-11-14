"""In-memory stand-in for the Docker SDK client (`docker.DockerClient`).

The integration's `DockerClient` wrapper is exercised for real; only the SDK
object it creates is replaced, so every test goes through the same code that
talks to a daemon in production. No test ever reaches a real Docker daemon.

Every SDK call is appended to `FakeSdk.calls` as `(name, args)`, so a test can
assert that a refused request touched nothing.
"""
from __future__ import annotations

import itertools
from typing import Any

from docker.errors import NotFound

OWNED_LABELS_KEY_MANAGED = "docker_marketplace.managed"
OWNED_LABELS_KEY_APP = "docker_marketplace.app_id"


def owned_labels(app_id: str) -> dict[str, str]:
    """Labels the integration puts on the containers it creates."""
    return {OWNED_LABELS_KEY_MANAGED: "true", OWNED_LABELS_KEY_APP: app_id}


class FakeImage:
    """A local image."""

    def __init__(self, ref: str, image_id: str) -> None:
        self.id = image_id
        self.tags = [ref]
        self.attrs: dict[str, Any] = {"Config": {"Env": [], "Cmd": None, "Entrypoint": None}}


class FakeContainer:
    """A container known to the fake daemon."""

    def __init__(
        self,
        sdk: FakeSdk,
        name: str,
        image: FakeImage,
        status: str = "running",
        labels: dict[str, str] | None = None,
        exposed_ports: dict[str, dict] | None = None,
    ) -> None:
        self._sdk = sdk
        self.id = f"id-{name}"
        self.name = name
        self.image = image
        self.status = status
        self.labels = dict(labels or {})
        self.attrs: dict[str, Any] = {
            "Name": f"/{name}",
            "Config": {
                "Env": [],
                "Labels": dict(self.labels),
                "ExposedPorts": exposed_ports or {},
            },
            "HostConfig": {"NetworkMode": "bridge"},
            "NetworkSettings": {"Networks": {"bridge": {}}},
        }
        self.ports: dict[str, Any] = {}

    def start(self) -> None:
        self._sdk.record("container.start", self.name)
        self.status = "running"

    def stop(self, timeout: int = 10) -> None:
        self._sdk.record("container.stop", self.name)
        self.status = "exited"

    def remove(self, **kwargs: Any) -> None:
        self._sdk.record("container.remove", self.name)
        self._sdk.containers.by_name.pop(self.name, None)

    def logs(self, **kwargs: Any) -> bytes:
        self._sdk.record("container.logs", self.name)
        return f"log of {self.name}\n".encode()

    def stats(self, stream: bool = False) -> dict[str, Any]:
        self._sdk.record("container.stats", self.name)
        usage = {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 0, "online_cpus": 1}
        return {
            "cpu_stats": usage,
            "precpu_stats": usage,
            "memory_stats": {"usage": 0, "limit": 1},
        }


class FakeContainers:
    """`client.containers`."""

    def __init__(self, sdk: FakeSdk) -> None:
        self._sdk = sdk
        self.by_name: dict[str, FakeContainer] = {}

    def get(self, name: str) -> FakeContainer:
        self._sdk.record("containers.get", name)
        self._sdk.maybe_fail()
        if name not in self.by_name:
            raise NotFound(f"No such container: {name}")
        return self.by_name[name]

    def list(self, all: bool = False, filters: dict | None = None) -> list[FakeContainer]:
        self._sdk.record("containers.list", filters)
        self._sdk.maybe_fail()
        wanted = (filters or {}).get("label")
        found = list(self.by_name.values())
        if wanted:
            key, _, value = wanted.partition("=")
            found = [c for c in found if c.labels.get(key) == value]
        return found

    def run(self, **kwargs: Any) -> FakeContainer:
        self._sdk.record("containers.run", kwargs)
        self._sdk.maybe_fail()
        container = FakeContainer(
            self._sdk,
            kwargs["name"],
            self._sdk.images.local(kwargs["image"]),
            labels=kwargs.get("labels"),
        )
        self.by_name[container.name] = container
        return container

    def add(self, name: str, image: str = "example/app:1", **kwargs: Any) -> FakeContainer:
        """Seed the daemon with a container (not recorded as a call)."""
        container = FakeContainer(self._sdk, name, self._sdk.images.local(image), **kwargs)
        self.by_name[name] = container
        return container


class FakeImages:
    """`client.images`."""

    def __init__(self, sdk: FakeSdk) -> None:
        self._sdk = sdk
        self._local: dict[str, FakeImage] = {}
        self._counter = itertools.count(1)
        self.pull_error: Exception | None = None
        self.pull_changes_image = True

    def local(self, ref: str) -> FakeImage:
        if ref not in self._local:
            self._local[ref] = FakeImage(ref, f"sha256:{next(self._counter)}")
        return self._local[ref]

    def pull(self, ref: str, **kwargs: Any) -> FakeImage:
        self._sdk.record("images.pull", ref)
        self._sdk.maybe_fail()
        if self.pull_error is not None:
            raise self.pull_error
        if self.pull_changes_image or ref not in self._local:
            self._local[ref] = FakeImage(ref, f"sha256:{next(self._counter)}")
        return self._local[ref]

    def get(self, ref: str) -> FakeImage:
        self._sdk.record("images.get", ref)
        self._sdk.maybe_fail()
        return self.local(ref)


class FakeApi:
    """`client.api`, the low-level client used to recreate containers."""

    def __init__(self, sdk: FakeSdk) -> None:
        self._sdk = sdk

    def create_container(self, **kwargs: Any) -> dict[str, str]:
        self._sdk.record("api.create_container", kwargs)
        container = FakeContainer(
            self._sdk,
            kwargs["name"],
            self._sdk.images.local(kwargs["image"]),
            status="created",
            labels=kwargs.get("labels"),
        )
        self._sdk.containers.by_name[container.name] = container
        return {"Id": container.id}

    def start(self, container_id: str) -> None:
        self._sdk.record("api.start", container_id)

    def create_networking_config(self, config: dict) -> dict:
        return config

    def create_endpoint_config(self) -> dict:
        return {}


class FakeSdk:
    """The object `DockerClient._create_client()` returns in tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.failure: Exception | None = None
        self.containers = FakeContainers(self)
        self.images = FakeImages(self)
        self.api = FakeApi(self)

    def record(self, name: str, args: Any) -> None:
        self.calls.append((name, args))

    def maybe_fail(self) -> None:
        """Raise the configured failure, e.g. an unreachable daemon."""
        if self.failure is not None:
            raise self.failure

    def ping(self) -> bool:
        self.record("ping", None)
        self.maybe_fail()
        return True

    def close(self) -> None:
        pass

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]


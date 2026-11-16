"""hooks/install.py lays the integration and the catalogue into the foundation's
Home Assistant configuration, replaces only what it owns, and replays cleanly.

The hook is driven the way the package engine drives it (runner.py): a
subprocess with `--phase install --root <root>` and a JSON context on stdin.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks" / "install.py"
CONFIG_REL = "opt/nivuus/home-manager/config"
COMPONENT = "custom_components/docker_marketplace"


def run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK), "--phase", "install", "--root", str(root)],
        input=json.dumps({"answers": {}}), capture_output=True, text=True,
        check=False)


def foundation(root: Path) -> Path:
    """The configuration directory home-manager would have created."""
    config = root / CONFIG_REL
    config.mkdir(parents=True)
    (config / "configuration.yaml").write_text("homeassistant:\n")
    return config


def test_refuses_without_the_foundation(tmp_path: Path) -> None:
    proc = run(tmp_path)

    assert proc.returncode == 1
    assert "home-manager" in proc.stderr
    assert not (tmp_path / CONFIG_REL).exists()


def test_lays_the_integration_its_panel_and_the_catalogue(tmp_path: Path) -> None:
    config = foundation(tmp_path)

    proc = run(tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert (config / COMPONENT / "manifest.json").is_file()
    assert (config / COMPONENT / "__init__.py").is_file()
    # The built panel: without it the sidebar entry is never registered.
    assert (config / COMPONENT / "frontend" / "main.js").is_file()
    shipped = sorted(p.name for p in (REPO / "catalog" / "apps").glob("*.yaml"))
    assert sorted(p.name for p in (config / "catalog" / "apps").glob("*.yaml")) == shipped
    assert (config / "catalog" / "catalog.yaml").is_file()
    for line in proc.stdout.splitlines():
        assert json.loads(line)["event"] in ("progress", "done")


def test_replaces_the_stale_copy_left_on_the_host(tmp_path: Path) -> None:
    # Measured on the live host (audit 2026-11-16, C-5): the component
    # directory held two June files and no manifest.json.
    config = foundation(tmp_path)
    stale = config / COMPONENT
    stale.mkdir(parents=True)
    (stale / "old_module.py").write_text("# from an older layout\n")
    (stale / "__pycache__").mkdir()
    (stale / "__pycache__" / "old_module.cpython-313.pyc").write_bytes(b"\0")
    (config / "catalog" / "apps").mkdir(parents=True)
    (config / "catalog" / "apps" / "retired.yaml").write_text("id: retired\n")

    assert run(tmp_path).returncode == 0

    assert not (stale / "old_module.py").exists()
    assert not (stale / "__pycache__").exists()
    assert not (config / "catalog" / "apps" / "retired.yaml").exists()
    assert (stale / "manifest.json").is_file()


def test_never_touches_installed_stacks_or_neighbours(tmp_path: Path) -> None:
    config = foundation(tmp_path)
    stack = config / "stacks" / "mealie" / "docker-compose.yml"
    stack.parent.mkdir(parents=True)
    stack.write_text("services: {}\n")
    neighbour = config / "custom_components" / "home_stock" / "__init__.py"
    neighbour.parent.mkdir(parents=True)
    neighbour.write_text("# another integration\n")

    assert run(tmp_path).returncode == 0

    assert stack.read_text() == "services: {}\n"
    assert neighbour.read_text() == "# another integration\n"
    assert (config / "configuration.yaml").read_text() == "homeassistant:\n"


def test_a_symlink_or_a_file_in_place_of_a_tree_is_replaced(tmp_path: Path) -> None:
    config = foundation(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (config / "custom_components").mkdir()
    (config / COMPONENT).symlink_to(elsewhere, target_is_directory=True)
    (config / "catalog").write_text("not a directory")

    proc = run(tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert not (config / COMPONENT).is_symlink()
    assert (config / COMPONENT / "manifest.json").is_file()
    assert (config / "catalog" / "catalog.yaml").is_file()
    assert elsewhere.is_dir() and not any(elsewhere.iterdir())


def test_concurrent_runs_serialise(tmp_path: Path) -> None:
    config = foundation(tmp_path)
    procs = [
        subprocess.Popen(
            [sys.executable, str(HOOK), "--phase", "install", "--root", str(tmp_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True)
        for _ in range(4)
    ]
    for proc in procs:
        proc.communicate(json.dumps({"answers": {}}))

    assert [p.returncode for p in procs] == [0, 0, 0, 0]
    assert (config / COMPONENT / "frontend" / "main.js").is_file()
    assert (config / "catalog" / "catalog.yaml").is_file()
    leftovers = [p.name for p in config.rglob("*") if p.name.endswith((".new", ".old"))]
    assert leftovers == []


def _tree(root: Path) -> dict[str, bytes | None]:
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


def test_replay_changes_nothing(tmp_path: Path) -> None:
    # The package engine's own proof (installer/scripts/idempotence_harness.py)
    # runs in CI and at release; this is the same comparison, kept here so a
    # regression is caught by this repository's own suite.
    foundation(tmp_path)
    assert run(tmp_path).returncode == 0
    first = _tree(tmp_path)

    assert run(tmp_path).returncode == 0

    assert _tree(tmp_path) == first

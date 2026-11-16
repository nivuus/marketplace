"""The package manifest and the integration manifest state the real contract.

nivuus-package.yaml is validated by the package engine's own parser when
NIVUUS_INSTALLER_DIR points at an installer checkout (CI's package job and the
release gate always run that parser through the idempotence harness).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
PACKAGE_MANIFEST = REPO / "nivuus-package.yaml"
HA_MANIFEST = REPO / "custom_components" / "docker_marketplace" / "manifest.json"


def test_package_manifest_declares_a_satellite_of_the_foundation() -> None:
    data = yaml.safe_load(PACKAGE_MANIFEST.read_text())

    assert data["apiVersion"] == "nivuus.dev/v1"
    assert data["name"] == "marketplace"
    assert data["tier"] == "userspace"
    # Writes into the configuration directory home-manager creates: the
    # engine must install home-manager first.
    assert data["requires"] == {"packages": ["home-manager"]}
    assert data["hooks"] == {"install": "hooks/install.py",
                             "activate": "hooks/activate.py"}
    assert data["source"] == {"github": "nivuus/marketplace"}
    # The docker SDK is a pip requirement Home Assistant installs itself
    # from manifest.json, not a system package; nothing is asked.
    assert "apt" not in data
    assert "wizard" not in data


def test_engine_parser_accepts_the_manifest() -> None:
    installer = os.environ.get("NIVUUS_INSTALLER_DIR")
    if not installer:
        pytest.skip("NIVUUS_INSTALLER_DIR is not set")
    sys.path.insert(0, str(Path(installer) / "installer"))
    from packages.manifest import load_manifest  # noqa: PLC0415

    manifest = load_manifest(str(PACKAGE_MANIFEST))

    assert manifest.name == "marketplace"
    assert manifest.packages == ("home-manager",)
    assert manifest.hook_path("install").endswith("hooks/install.py")
    assert manifest.hook_path("activate").endswith("hooks/activate.py")
    assert manifest.source.github == "nivuus/marketplace"


def _test_pin(name: str) -> str:
    for line in (REPO / "requirements.txt").read_text().splitlines():
        match = re.fullmatch(rf"{re.escape(name)}==(\S+)", line.strip())
        if match:
            return match.group(1)
    raise AssertionError(f"requirements.txt does not pin {name}")


def test_integration_requirements_are_exact_pins_the_suite_tests() -> None:
    manifest = json.loads(HA_MANIFEST.read_text())

    # Home Assistant's manifest contract: pip format, pinned to an exact
    # version, and only what Home Assistant does not already ship (PyYAML
    # is one of its own requirements).
    assert manifest["requirements"] == [f"docker=={_test_pin('docker')}"]


def test_integration_points_at_its_own_repository() -> None:
    manifest = json.loads(HA_MANIFEST.read_text())

    assert manifest["documentation"] == "https://github.com/nivuus/marketplace"
    assert manifest["issue_tracker"] == "https://github.com/nivuus/marketplace/issues"

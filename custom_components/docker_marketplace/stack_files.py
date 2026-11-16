"""Reading and writing the files of an installed stack.

An app's `config.yaml` is the only record of what the user chose (ports, data
paths, secrets); its compose file and `.env` are derived from it. So:

- reading tells "absent" (nothing saved yet: None) apart from "present but
  unreadable or invalid", which raises StackFileError and must stop whatever
  was about to rebuild the stack from it;
- writing replaces a file whole and durably (Home Assistant's
  write_utf8_file_atomic: temporary file in the same directory, fsync, rename,
  fsync of the directory), so a crash, a freeze or a full disk leaves either
  the previous file or the new one, never a truncated one.

These functions block: call them through asyncio.to_thread.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.file import WriteError, write_utf8_file_atomic

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class StackFileError(HomeAssistantError):
    """A stack file exists but cannot be read, parsed or written."""

    def __init__(self, key: str, path: Path) -> None:
        super().__init__(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders={"path": str(path)},
        )


def read_yaml_mapping(path: Path) -> dict[str, Any] | None:
    """Return the mapping stored in path, or None when path does not exist.

    Raises StackFileError when the file exists but cannot be read, is not
    valid YAML, or does not hold a mapping. An empty file is invalid: this
    integration never writes one, so it can only be the remains of a write
    that did not complete.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as err:
        _LOGGER.error("Cannot read %s: %s", path, err)
        raise StackFileError("stack_file_unreadable", path) from err

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as err:
        _LOGGER.error("%s is not valid YAML: %s", path, err)
        raise StackFileError("stack_file_invalid", path) from err
    if not isinstance(data, dict):
        _LOGGER.error(
            "%s does not hold a mapping (found %s)", path, type(data).__name__
        )
        raise StackFileError("stack_file_invalid", path)
    return data


def write_text(path: Path, text: str) -> None:
    """Replace path with text atomically and durably, readable by its owner only.

    Stack files carry the app's secrets (config.yaml, .env and the compose
    environment), hence the private mode.
    """
    try:
        write_utf8_file_atomic(str(path), text, private=True)
    except WriteError as err:
        raise StackFileError("stack_file_unwritable", path) from err


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Replace path with data dumped as YAML, atomically and durably."""
    write_text(path, yaml.safe_dump(data, default_flow_style=False))

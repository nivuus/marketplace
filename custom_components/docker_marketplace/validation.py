"""Validation of what callers send: application ids, log bounds, form values.

The schema validators (`validate_app_id`, `validate_tail`) raise ValueError,
which both voluptuous and probatio schemas turn into their own Invalid error,
so they work in the WebSocket and the service schemas alike.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ServiceValidationError

if TYPE_CHECKING:
    from .catalog import AppDefinition

# A conservative slug: it names a directory under the stacks root, a compose
# project and a container, so it may hold no separator, no dot and no space.
APP_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")

MAX_LOG_TAIL = 10_000

# Characters that would let a value escape its line in the .env file or its
# field in a mount specification.
_LINE_BREAKERS = ("\n", "\r", "\x00")


class InvalidAppRequest(ServiceValidationError):
    """A request names an invalid application or carries invalid values."""


def validate_app_id(value: Any) -> str:
    """Return value if it is a valid application id, else raise ValueError."""
    if not isinstance(value, str) or not APP_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "app_id must be 1-64 lowercase letters, digits, '-' or '_', "
            "starting with a letter or a digit"
        )
    return value


def validate_tail(value: Any) -> int:
    """Return the number of log lines requested, bounded to MAX_LOG_TAIL."""
    if isinstance(value, bool):
        raise ValueError("tail must be an integer")
    try:
        tail = int(value)
    except (TypeError, ValueError) as err:
        raise ValueError("tail must be an integer") from err
    if not 1 <= tail <= MAX_LOG_TAIL:
        raise ValueError(f"tail must be between 1 and {MAX_LOG_TAIL}")
    return tail


def require_app_id(value: Any) -> str:
    """validate_app_id for code paths outside a schema."""
    try:
        return validate_app_id(value)
    except ValueError as err:
        raise InvalidAppRequest(str(err)) from err


def _port(key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise InvalidAppRequest(f"{key} must be a port number")
    text = str(value).strip()
    if not text.isascii() or not text.isdigit():
        raise InvalidAppRequest(f"{key} must be a port number")
    port = int(text)
    if not 1 <= port <= 65535:
        raise InvalidAppRequest(f"{key} must be between 1 and 65535")
    return port


def _host_path(key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise InvalidAppRequest(f"{key} must be an absolute path")
    if value == "":
        # Empty means "use the catalogue default", as the form sends it.
        return value
    if ":" in value or any(char in value for char in _LINE_BREAKERS):
        raise InvalidAppRequest(f"{key} must not contain ':' or line breaks")
    if not PurePosixPath(value).is_absolute():
        raise InvalidAppRequest(f"{key} must be an absolute path")
    return value


def _env_value(key: str, value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise InvalidAppRequest(f"{key} must be a text value")
    text = str(value)
    if any(char in text for char in _LINE_BREAKERS):
        raise InvalidAppRequest(f"{key} must not contain line breaks")
    return text


def validate_app_config(app_def: AppDefinition, config: Any) -> dict[str, Any]:
    """Validate form values against the application definition.

    Only the keys the definition declares are accepted: port_<container>,
    volume_<name> and env_<name>. Returns the normalised values.
    """
    if not isinstance(config, dict):
        raise InvalidAppRequest("config must be a mapping")

    fields = {f"port_{port.container}": _port for port in app_def.ports}
    fields.update({f"volume_{vol.name}": _host_path for vol in app_def.volumes})
    fields.update({f"env_{env.name}": _env_value for env in app_def.environment})

    unknown = sorted(str(key) for key in config if key not in fields)
    if unknown:
        raise InvalidAppRequest(
            f"Unknown configuration keys for {app_def.id}: {', '.join(unknown)}"
        )
    return {key: fields[key](key, value) for key, value in config.items()}

"""hooks/activate.py, against a fake `docker` on PATH.

The fake records every call and answers `docker inspect` the way the real one
does in each situation the hook must tell apart.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "activate.py"
FAKE = """#!/bin/sh
echo "$*" >> "$DOCKER_CALLS"
case "$1" in
  inspect) printf '%s' "$INSPECT_OUT"; printf '%s' "$INSPECT_ERR" >&2; exit "$INSPECT_RC" ;;
  restart) exit "$RESTART_RC" ;;
esac
"""


def run(tmp: Path, *, inspect_out="", inspect_err="", inspect_rc=0, restart_rc=0,
        with_docker=True):
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    if with_docker:
        fake = bindir / "docker"
        fake.write_text(FAKE)
        fake.chmod(stat.S_IRWXU)
    calls = tmp / "calls"
    env = dict(os.environ, PATH=str(bindir), DOCKER_CALLS=str(calls),
               INSPECT_OUT=inspect_out, INSPECT_ERR=inspect_err,
               INSPECT_RC=str(inspect_rc), RESTART_RC=str(restart_rc))
    proc = subprocess.run(
        [sys.executable, str(HOOK), "--phase", "activate"],
        input=json.dumps({"package": {}, "hw": {}, "answers": {}}),
        env=env, capture_output=True, text=True, check=False)
    made = calls.read_text().splitlines() if calls.exists() else []
    return proc.returncode, made, proc.stdout, proc.stderr


def test_a_running_home_assistant_is_restarted(tmp_path: Path) -> None:
    code, calls, _, _ = run(tmp_path, inspect_out="true\n")

    assert code == 0
    assert calls == ["inspect -f {{.State.Running}} homeassistant",
                     "restart homeassistant"]


def test_a_stopped_container_is_left_stopped(tmp_path: Path) -> None:
    code, calls, out, _ = run(tmp_path, inspect_out="false\n")

    assert (code, len(calls)) == (0, 1)
    assert "left stopped" in out


@pytest.mark.parametrize("detail", [
    "Error: No such object: homeassistant",
    "Cannot connect to the Docker daemon at unix:///var/run/docker.sock.",
])
def test_no_container_or_no_daemon_is_stated(tmp_path: Path, detail: str) -> None:
    code, calls, out, _ = run(tmp_path, inspect_rc=1, inspect_err=detail)

    assert (code, len(calls)) == (0, 1)
    assert "not running here" in out


def test_no_docker_binary_is_stated(tmp_path: Path) -> None:
    code, calls, out, _ = run(tmp_path, with_docker=False)

    assert (code, calls) == (0, [])
    assert "not running here" in out


def test_an_unexpected_docker_failure_fails_the_phase(tmp_path: Path) -> None:
    code, _, _, err = run(tmp_path, inspect_rc=1, inspect_err="permission denied")

    assert code == 1
    assert "permission denied" in err


def test_a_failed_restart_fails_the_phase(tmp_path: Path) -> None:
    code, _, _, _ = run(tmp_path, inspect_out="true\n", restart_rc=1)

    assert code == 1

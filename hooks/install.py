#!/usr/bin/env python3
"""Install phase of the marketplace package: lay the integration and its
catalogue into the foundation's Home Assistant configuration.

This package is a SATELLITE, like home-stock and home-desk, and this hook is
the shape theirs proved: it owns no deployment directory, it writes into the
one `home-manager` created. Its manifest declares
`requires: packages: [home-manager]`, which makes the engine install the
foundation first.

1. IT REFUSES WHEN THE FOUNDATION IS ABSENT. `requires.packages` already
   blocks that case in the wizard, but the hook also runs standalone
   (`--root /`, a hand-written config.json) where nothing validated it.
   Creating an orphan tree nobody reads would be worse than refusing.

2. IT REPLACES WHAT IT OWNS AND NOTHING ELSE.
   - `custom_components/docker_marketplace/` (the integration, with its built
     panel `frontend/main.js`) and `catalog/` (the application catalogue the
     integration reads at `/config/catalog`) belong to this package: each is
     replaced whole, so a module or a catalogue entry removed between two
     versions does not survive as a ghost Home Assistant would still load or
     offer, and stale bytecode never outlives its source.
   - `stacks/` holds the compose files of the applications the person
     installed from the panel: it is their data, never touched here.
   - configuration.yaml is never written: the integration is set up from the
     UI (config flow).

3. TWO CONCURRENT RUNS SERIALISE. Replaying this hook is how an update is
   laid, and two interleaved passes could leave one exiting 0 while the
   other has already moved a tree aside. See exclusive_deposit().

The install phase is a pure file writer, as the engine's idempotence harness
expects (installer/scripts/idempotence_harness.py): no Docker, no network.
Making a running Home Assistant load the new version is hooks/activate.py.
"""
import argparse
import contextlib
import fcntl
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The configuration directory created by home-manager, mounted at /config in
# its Home Assistant container.
CONFIG_REL = "opt/nivuus/home-manager/config"

# Trees this package owns, laid at the same path under the configuration
# directory: replaced whole (rule 2).
OWNED_TREES = (
    ("custom_components/docker_marketplace", 30,
     "Laying the Docker Marketplace integration"),
    ("catalog", 70, "Laying the application catalogue"),
)

# The built panel. It is committed (frontend/ sources are built by rollup on
# a developer machine), so the release archive carries it; a source tree
# without it would lay an integration with no sidebar entry.
PANEL_BUNDLE = "custom_components/docker_marketplace/frontend/main.js"


def emit(event):
    print(json.dumps(event), flush=True)


def _discard(path):
    """Remove whatever occupies `path`: a directory, a file or a symlink.

    rmtree refuses symlinks and plain files, both plausible here after a
    manual change (a development bind left behind, for instance).
    """
    if not os.path.lexists(path):
        return
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def replace_tree(source, dest):
    """Replace dest with a copy of source, never leaving dest absent.

    Copy to a sibling first (the old tree stays intact until the copy is
    complete), move the old tree aside, switch with os.replace() - atomic on
    one filesystem - and only then delete the old tree. __pycache__ in the
    source (pytest writes one) is not part of the source and is not copied.
    """
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".new"
    old_aside = dest + ".old"
    _discard(tmp)
    _discard(old_aside)

    try:
        shutil.copytree(source, tmp, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    except Exception:
        _discard(tmp)
        raise

    moved_old = os.path.isdir(dest) and not os.path.islink(dest)
    if moved_old:
        os.replace(dest, old_aside)
    else:
        _discard(dest)

    os.replace(tmp, dest)

    if moved_old:
        shutil.rmtree(old_aside)


@contextlib.contextmanager
def exclusive_deposit(config_dir):
    """Serialise concurrent runs of this hook on the same foundation.

    The lock is taken on config_dir itself: it exists at this point (rule 1
    just checked it) and it is the artefact of neither run.
    """
    fd = os.open(config_dir, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--root", default="/")
    args = parser.parse_args()
    json.load(sys.stdin)          # the context is read; nothing here needs it
    root = args.root.rstrip("/") or "/"

    config_dir = os.path.join(root, CONFIG_REL)

    # Rule 1: refuse rather than create an orphan.
    if not os.path.isdir(config_dir):
        print("marketplace install: the home-manager package is not installed "
              f"({config_dir} is missing); this package lays its files into "
              "the Home Assistant configuration that home-manager creates",
              file=sys.stderr)
        return 1

    if not os.path.isfile(os.path.join(HERE, PANEL_BUNDLE)):
        print(f"marketplace install: {PANEL_BUNDLE} is missing from the package; "
              "build it with `npm run build` in frontend/", file=sys.stderr)
        return 1

    with exclusive_deposit(config_dir):
        for rel, pct, msg in OWNED_TREES:
            emit({"event": "progress", "pct": pct, "msg": msg})
            replace_tree(os.path.join(HERE, rel), os.path.join(config_dir, rel))

        emit({"event": "progress", "pct": 95,
              "msg": "Docker Marketplace laid into the Home Assistant configuration"})

    emit({"event": "done"})
    return 0


if __name__ == "__main__":
    sys.exit(main())

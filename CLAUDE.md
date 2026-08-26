# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Instructions for Claude

**IMPORTANT**: Whenever you learn something important about this project (architecture decisions, critical bugs fixed, configuration patterns, etc.), immediately update this CLAUDE.md file. Keep it:
- **Compact**: Dense, relevant information only
- **No duplicates**: Remove redundant information
- **Up-to-date**: Reflect current project state

**BE PROACTIVE**: When working on the codebase, actively look for improvements or issues beyond the current scope. If you spot bugs, performance issues, code smells, security concerns, or optimization opportunities - signal them to the user and fix them. Don't wait to be asked.

## Project Overview

**Docker Marketplace** — Home Assistant custom integration (`docker_marketplace`) plus a
YAML application catalog, deploying self-hostable applications to the host's Docker daemon
via compose, driven from a Lovelace panel.

Extracted from `nivuus/installer` on 2026-08-26. The host infrastructure — Docker daemon
configuration, firewall zones, the HA container — stays documented there.

## Structure

```
custom_components/docker_marketplace/   # The HA integration
├── __init__.py                         # Setup, service registration
├── coordinator.py                      # DataUpdateCoordinator
├── docker_client.py                    # Talks to the socket proxy
├── catalog.py                          # Reads catalog/apps/*.yaml
├── services.py                         # install/remove/update/start/stop/restart
├── {sensor,switch,button,update}.py     # Entity platforms
└── frontend/main.js                    # Built panel bundle

frontend/                               # Lit + TypeScript panel sources (rollup)
catalog/
├── catalog.yaml                        # Categories
└── apps/*.yaml                         # One file per deployable app
hacs.json                               # HACS installability
```

## Critical Implementation Notes

### HA service registration trap — `lambda` silently swallows the coroutine (fixed 2026-08-05)

`hass.services.async_register(DOMAIN, name, lambda call: async_handler(hass, coordinator, call))`
**registers a service that does nothing.** HA classifies the handler in
`get_hassjob_callable_job_type()` (`homeassistant/core.py`): it unwraps `functools.partial`,
then tests `inspect.iscoroutinefunction` → `is_callback` → else **`HassJobType.Executor`**.
A plain lambda is neither, so HA runs it in an executor thread; the coroutine it returns is
discarded (`RuntimeWarning: coroutine ... was never awaited`) and the handler body never
executes. All six services (`install_app`, `remove_app`, `update_app`, `start_app`,
`stop_app`, `restart_app`) were affected.

**Fix: `partial(handler, hass, coordinator)`** — explicitly unwrapped by that same function,
so the job is typed `Coroutinefunction` and awaited on the event loop. Registration is
table-driven in `_async_register_services()`, with a `vol.Schema` per service (they had
none, so a call missing `app_id` raised `KeyError` inside the handler instead of being
rejected), plus `_async_unregister_services()` called from `async_unload_entry` once
`hass.config_entries.async_loaded_entries(DOMAIN)` is empty — services are domain-wide, not
per-entry. Verified against HA 2026.7.4.

### The repository IS the deployed integration

The HA stack's `docker-compose.yml` bind-mounts `custom_components/docker_marketplace` and
`catalog/` straight into `/config/`. **Edits to this repository need only an HA restart**
(module re-import), never a copy step. Beware: a same-named directory may exist under
`/opt/nivuus/HomeAssistant/config/custom_components/` — it is a stale copy shadowed by the
mount, and editing it does nothing.

### Docker access goes through the socket proxy, never the raw socket

`docker_client.py` targets `tcp://127.0.0.1:2375` — the `tecnativa/docker-socket-proxy`
container, not `/var/run/docker.sock`. The proxy is configured `EXEC=0 BUILD=0 SECRETS=0
CONFIGS=0 SWARM=0 SYSTEM=0 AUTH=0` and `ALLOW_START=0 ALLOW_STOP=0 ALLOW_RESTARTS=0`, with
`POST=1 CONTAINERS=1 IMAGES=1`. Keep it that way: widening the proxy is the wrong lever,
and container lifecycle actions must go through compose, not the Docker API.

## Code Style Guidelines

- **File Organization**: Maximum 200 lines per file — split if larger
- **Architecture**: Use classes and inheritance extensively
- **Modularity**: Each file should be self-contained and minimal
- **Comments**: English only
- **Dependencies**: no unnecessary ones — `aiohttp` and `voluptuous` are built into HA

## HA Integration Patterns

- `DataUpdateCoordinator` for periodic data fetching
- `CoordinatorEntity + SensorEntity` for sensors
- `hass.data[DOMAIN][entry.entry_id]` for per-entry state
- `async_get_clientsession(hass)` for HTTP
- `ConfigEntryNotReady` if the backend is unreachable at setup
- `async_unload_entry()` must pop from `hass.data` and unregister services

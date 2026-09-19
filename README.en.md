# Polygon Kilns for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/catrielmuller/ha-polygon-kilns/actions/workflows/validate.yml/badge.svg)](https://github.com/catrielmuller/ha-polygon-kilns/actions/workflows/validate.yml)

**[Español](README.md) | [Français](README.fr.md)**

Custom Home Assistant integration for **Polygon** ceramic kilns. It talks directly to Polygon's Firebase backend: no additional hardware or server is required.

## Features

- **Monitoring** per kiln: temperature, setpoint, state, stage, progress, ETA, elapsed time, energy, cost, WiFi signal, last firing (with history details) and faults (thermocouple, sensor, overheating, connectivity).
- **Control**: buttons and services to start a program and stop the kiln.
- **Scheduled start** (what the official app doesn't have): pick a program + date/time, arm the switch, and the integration triggers the start at that time. Both the scheduled start and the selected program survive Home Assistant restarts.
- **Program CRUD**: services to create, update and delete firing programs (stages with ramp/temperature/hold).
- Supports **owned and shared** kilns.

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ menu → *Custom repositories* → add this repo as *Integration*.
2. Install **Polygon Kilns** and restart Home Assistant.

### Manual

Copy `custom_components/polygon_kilns` into your configuration's `custom_components` directory and restart.

## Configuration

Settings → Devices & services → *Add integration* → **Polygon Kilns**. Use the email and password of your Polygon app account.

> If your account only uses Google/Apple Sign-In, set a password for the account first (the integration uses Firebase's email/password provider).

The polling interval can be adjusted in the integration options (15–120 s, default 30 s).

## Scheduled start

Each kiln exposes three control entities:

1. `select.<kiln>_programa_a_iniciar` — pick the program.
2. `datetime.<kiln>_inicio_programado` — pick date and time.
3. `switch.<kiln>_inicio_programado_activo` — arm the start.

When the time comes, the integration calls the Polygon backend (`requestStart`) and disarms the switch. If the kiln is unavailable or already firing, a persistent notification is created and the start is not executed.

It can also be done via service:

```yaml
action: polygon_kilns.start_schedule
data:
  kiln_id: K1117
  schedule_name: GRES CONO 6
  start_time: "2026-09-20T07:30:00"  # optional; without it, starts now
```

## Services

| Service | Description |
| --- | --- |
| `polygon_kilns.start_schedule` | Starts a program (now or with `start_time`). |
| `polygon_kilns.stop_schedule` | Stops the current firing. |
| `polygon_kilns.create_schedule` | Creates a program with stages `{ramp, temp, hold}`. |
| `polygon_kilns.update_schedule` | Modifies a program's name and/or stages. |
| `polygon_kilns.delete_schedule` | Deletes a program. |

Program creation example:

```yaml
action: polygon_kilns.create_schedule
data:
  kiln_id: K1117
  schedule_name: BIZCOCHO LENTO
  sched_num: 11
  stages:
    - { ramp: 100, temp: 500, hold: 0 }
    - { ramp: 150, temp: 980, hold: 15 }
```

## Known limitations

- If your kiln access is **shared** (you are not the owner), Firestore rules may prevent stopping the kiln or editing programs; the integration reports this with a clear error. Reading always works.
- The backend does not expose a local API: everything goes through the Polygon cloud.

## Development

### Devcontainer

The repo includes a devcontainer ready to test on a real Home Assistant:

1. Open the repo in VS Code → *Reopen in Container*.
2. On build, `scripts/setup` installs the dependencies into `.venv`.
3. Run `bash scripts/develop` → Home Assistant is available at `http://localhost:8123` with the integration loaded.
4. Add the integration from the UI with your real account.

### Tests

```sh
bash scripts/setup
.venv/bin/pytest
```

The tests use fixtures with real (sanitized) documents from kiln `K1117`.

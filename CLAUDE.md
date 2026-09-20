# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup and commands

Requires **Python 3.12** (pygame-ce does not support 3.13+).

```bash
py -3.12 -m venv venv
venv\Scripts\activate          # Windows
python -m pip install --upgrade pip
pip install -r requirements.txt
```

- Run the game (fullscreen Pygame app, starts paused on AM-peak scenario): `python main.py`
- Headless engine validation (no Pygame; runs `setup_debug_one_car` and prints per-second positions): `python debug.py`

There is no test suite, linter, or build step configured. Validate simulation changes by running `python debug.py` and confirming vehicle positions/completions look sane.

## Architecture

Signal Commander is a traffic-signal-timing game: build a signalized grid, edit signal timings and OD demand, run a microsimulation, and get scored 0–100 against Webster-optimal timing.

The codebase is split into a rendering-free simulation core and a Pygame UI. **`simulation.py`, `metrics.py`, and `network.py` must not import Pygame.** All simulation logic runs in world space; pixels only enter at `main.py` render time via `world_to_screen` / `screen_to_world` transform closures built in `main.make_transform` (main.py:49).

### Module boundaries (contracts — do not break silently)

- **`main.py`** — Pygame + pygame_gui fullscreen app. Owns the render loop, sidebar UI, click-to-edit interactions, world/screen transform, signal head rendering, and end-of-run score overlay. Calls into `Simulation` through the fixed contract documented at the top of `simulation.py` (`step`, `pause`, `resume`, `reset_simulation`, `set_speed`, `get_agents`, `get_state`, `spawn_agent`, `schedule_spawn`).
- **`simulation.py`** — `Agent` (car-following + signal compliance), `Signal` phase machine, and `Simulation` (OD spawning, stepping, `SimulationState` schema). The dataclasses at the top of the file are a **frozen schema consumed by `metrics.py`** — add fields freely but do not rename or remove.
- **`metrics.py`** — `MetricsEngine` (rolling-window network metrics + per-intersection Webster delay/LOS) and `compute_network_score` (compares your timing's delay to Webster-optimal delay per intersection, averages to 0–100). Reads only `SimulationState` and `Network`.
- **`network.py`** — Grid geometry, intersections, internal links, perimeter terminal nodes (`T_IN_*` / `T_OUT_*`) and terminal links, plus a NetworkX routing graph. `Network.shortest_path(origin, dest, rng)` re-builds a weighted graph each call and perturbs every edge weight by ±10% before Dijkstra, so per-vehicle routes vary.
- **`debug.py`** — Preset scenarios (`setup_am_peak`, `setup_debug_one_car`), a `SCENARIOS` registry, and a headless runner. Scenarios return `(network, sim)` **paused**; the caller must `sim.resume()`.
- **`config.py`** — Display, network, traffic-engineering, and simulation constants. Note: `DEFAULT_LINK_LENGTH_M` and `FREE_FLOW_SPEED` are each defined twice in this file; the second assignment wins.

### Signal phase model

Each `Intersection` cycles through six phases in fixed order: `NS_GREEN → NS_YELLOW → ALL_RED_1 → EW_GREEN → EW_YELLOW → ALL_RED_2`. Durations come from the intersection's `cycle_length`, `green_ns`, `green_ew`, plus fixed yellow (3 s) and all-red (2 s). `offset` shifts phase start so corridors can be coordinated. Timing edits are applied at the start of NS green so a cycle is never truncated mid-phase.

### Simulation timing

Run duration is 3600 s with a 180 s warmup (excluded from reported metrics) and a 300 s rolling window for the live readouts. `TIMESTEP = 1.0 s`. Speed multipliers (1x/5x/20x/60x) step the sim multiple times per frame; do not conflate wall-clock FPS with sim time.

### Unit conventions

Distance m, time s, speed m/s, flow veh/hr, density veh/km. Angles are radians internally and only converted to degrees at display time. **Do not mix units** — convert at render time only. This convention is asserted at the top of `simulation.py` and in the README.

### Webster scoring

`MetricsEngine` computes optimal cycle length from measured per-cycle flows using equivalent-flow lane groups (`q_eq = q_through + 1.4·q_right + eL·q_left`, saturation 1900 veh/hr per critical lane) and Webster delay, with LOS escalation when queues indicate oversaturation. `compute_network_score` runs this per intersection at end-of-run and averages against user timing to produce the 0–100 score shown in the overlay.

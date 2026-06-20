# Signal Commander

A traffic signal timing game built in Python + Pygame. Load a road network,
tune the signal timing at each intersection, run a live traffic microsimulation,
and get scored on how close your timing comes to the Webster-optimal design.

Built for the University of Texas at Austin Spring 2026 CAEE Hackathon (April 17–19, 2026).

## How it plays

You start with a grid of signalized intersections carrying real traffic demand, and
you can edit it freely: build your own grid, adjust intersections, links, and inflows,
then tune each signal's cycle length and green splits. Press Start, and watch vehicles
move, queue, and clear. When the run finishes, the network is scored from 0 to 100
against Webster-optimal timing for the demand it measured, with a rating from
"Gridlock" up to "Traffic Engineer." Retune and try again to beat your score.

## Unit conventions

Distance: meters (m)<br>
Time: seconds (s)<br>
Speed: meters per second (m/s)<br>
Flow: vehicles per hour (veh/hr)<br>
Density: vehicles per kilometer (veh/km)<br>
Angles: radians internally, degrees only at display

World space: meters, used for all simulation logic.<br>
Screen space: pixels, used only for rendering.<br>
Convert with world_to_screen() and screen_to_world() helpers.

DO NOT mix units. Convert at display time only.

## Overview

Signal Commander generates a rectangular grid of signalized intersections connected
by bidirectional links, with source/sink terminals on every perimeter node so traffic
can enter and leave the network. Demand is driven by an origin–destination matrix and
per-entry inflow rates. Each intersection runs a full fixed-time signal you can retune,
and the simulation moves individual vehicles through the network using car-following
and signal compliance.

All simulation logic runs in world space (meters and seconds). Pixels are used only for
rendering, and conversion happens at display time through the `world_to_screen` /
`screen_to_world` transform helpers in `main.py`.

## Features

- Live traffic microsimulation: per-vehicle car-following, signal compliance at stop
  lines, queue formation, and trip completion.
- Six-phase signal state machine per intersection (NS green, NS yellow, all-red, EW
  green, EW yellow, all-red) with editable cycle length, green splits, and offset.
- Origin–destination demand with editable per-entry inflow (veh/hr) and a demand scale.
- Preset scenarios in `debug.py`, including an AM-peak commute pattern into a notional
  northeast CBD, plus a single-car debug case with a headless terminal runner.
- Build-your-own networks at runtime: set rows, columns, and link length, then
  regenerate the grid.
- Live visualization: animated cars and buses, per-approach signal heads (red/yellow/
  green), color-coded Level of Service badges above each intersection, and an optional
  link-density heatmap.
- Adjustable simulation speed (1x / 5x / 20x / 60x) with Start, Pause, and Reset.
- Live network metrics: completed trips, active vehicles, mean delay, mean and 85th
  percentile travel time, and denied entries.
- End-of-run scoring: each intersection is graded against its Webster-optimal timing,
  averaged into a 0–100 network score with a rating and a per-intersection breakdown.
- CSV export of per-intersection and network-level metrics.

## Project structure

| File | Responsibility |
|------|----------------|
| `main.py` | Pygame + pygame_gui application: fullscreen UI, rendering, world/screen transform, sidebar editing, sim controls, vehicle and signal drawing, and the end-of-run score overlay. |
| `simulation.py` | Traffic microsimulation engine (no Pygame). `Agent` (car-following + signal compliance), `Signal` (six-phase state machine), and `Simulation` (spawning, OD demand, stepping, and the state schema consumed by metrics). |
| `metrics.py` | `MetricsEngine` and scoring: Webster optimal cycle (equivalent-flow lane groups), Webster delay, LOS classification, rolling-window network metrics, CSV export, and `compute_network_score`. |
| `network.py` | Network model. Owns intersections, internal links, terminals, terminal links, grid geometry, and the NetworkX routing graph. |
| `debug.py` | Preset scenarios (`setup_am_peak`, `setup_debug_one_car`), a scenario registry, and a headless validation runner. |
| `config.py` | Window, color, network, traffic, and simulation constants. |
| `requirements.txt` | Pinned dependencies and setup steps. |

## Installation

Requires **Python 3.12**. pygame-ce does not yet support Python 3.13+, so 3.12 is
the supported version.

From the project folder:

```bash
py -3.12 -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Dependencies: `pygame-ce`, `pygame_gui`, `networkx`, `numpy`, `matplotlib`.

## Running

```bash
python main.py
```

The app opens fullscreen and loads the AM-peak scenario, paused. Press Start to run.

To validate the simulation engine on its own, without Pygame:

```bash
python debug.py
```

This runs a small scenario in the terminal and prints vehicle positions each second.

## Controls

The window is split into a canvas (left) and a sidebar (right).

- **Create Network:** set Rows, Columns, and Link Length, then press Create Network to
  rebuild the grid.
- **Edit an intersection:** click it (light circle) to edit Cycle, Green NS, Green EW,
  and Offset, then press Apply.
- **Edit a link:** click it to edit Length and Lanes, then press Apply.
- **Edit demand:** click an inbound terminal to set its Inflow (veh/hr).
- **Run the sim:** Start, Pause, Reset, and speed buttons 1x / 5x / 20x / 60x.
- **Views:** toggle the density Heatmap, and Export CSV at any time.

Invalid edits are rejected with a status message and the previous values are kept.

## Core concepts

**Simulation.** Vehicles follow a routed list of links from an inbound terminal to an
outbound terminal. Each step sets a vehicle's speed from the gap to its leader and from
the next downstream signal, then advances it. The run lasts 3600 s with a 180 s warmup
(excluded from reported metrics) and a 300 s rolling window for live readouts.

**Signals.** Each intersection cycles through six phases with durations from its
`cycle_length`, `green_ns`, and `green_ew`, plus fixed yellow (3 s) and all-red (2 s).
A per-intersection `offset` delays the first phase so corridors can be coordinated.
Timing changes are applied at the start of NS green so a cycle is never cut mid-phase.

**Routing.** `Network.shortest_path(origin, dest, rng)` builds a temporary weighted graph
each call, perturbs every edge weight by ±10%, and runs Dijkstra, giving per-vehicle
route variety while still favoring shorter paths.

**Metrics and scoring.** `MetricsEngine` computes Webster optimal cycles from measured
per-cycle flows using equivalent-flow lane groups (`q_eq = q_through + 1.4·q_right +
eL·q_left`, saturation 1900 veh/hr per critical lane), Webster delay, and LOS (with an
escalation when queues indicate oversaturation). At the end of a run,
`compute_network_score` compares each intersection's delay under your timing against its
delay under Webster-optimal timing and averages the results into a 0–100 score.

## Configuration

Key constants live in `config.py`:

- Display: `WINDOW_WIDTH` 1400, `WINDOW_HEIGHT` 1000, `SIDEBAR_WIDTH` 300, `FPS` 30.
  These are fallbacks; at runtime the app uses the live fullscreen window size.
- Network defaults: `DEFAULT_ROWS` 3, `DEFAULT_COLS` 3, default link length, default lanes.
- Traffic engineering: `SATURATION_FLOW` 1800 veh/hr/lane, `STARTUP_LOST_TIME` 2.0 s,
  free-flow speed.
- Simulation: `TIMESTEP` 1.0 s, `WARMUP_DURATION` 180 s, `ROLLING_WINDOW` 300 s.

Note: a few constants (`DEFAULT_LINK_LENGTH_M`, `FREE_FLOW_SPEED`) are defined twice in
`config.py`; the later definition wins (link length 100 m, free-flow speed 15 m/s). Worth
collapsing to a single source of truth. Also note the run length used by the engine is
3600 s (set in `simulation.py`), which differs from `SIM_DURATION` in `config.py`.

## Status and ideas

The core game is complete: network building, demand, simulation, signals, live metrics,
scoring, and CSV export all work. Possible extensions include signal coordination tools,
additional preset scenarios, transit priority for buses, and a save/load for networks.

## Team

University of Texas at Austin Spring 2026 CAEE Hackathon, April 17–19, 2026. Built by
Ifratul Hoque, Adeeba Naz, Jahin Labiba Chowdhury, and Shantanu Paul.

## License

This project is released under the MIT License. See the LICENSE file for details.

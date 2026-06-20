# Signal Commander

An interactive grid-network traffic signal sandbox built in Python + Pygame.
Build a road grid, edit signal timings and link geometry through a live UI, and
evaluate intersection performance with standard traffic-engineering metrics.

Built for the University of Texas at Austin Spring 2026 CAEE Hackathon (April 17–19, 2026).

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

Signal Commander generates a rectangular grid of signalized intersections connected by
bidirectional links, with source/sink terminals on every perimeter node so traffic
can enter and leave the network. Each intersection runs a fixed-time signal you can
retune, and each link exposes editable length and lane count. The goal is to let a
user experiment with signal timing and network geometry and see how the corridor
responds.

All simulation logic runs in world space (meters and seconds). Pixels are used only
for rendering, and conversion happens at display time through the
`world_to_screen` / `screen_to_world` transform helpers in `main.py`.

## Features

- 3×3 grid network by default, with configurable rows, columns, and link length.
- Click-to-edit UI: select any intersection to retune its cycle length and green
  splits (NS / EW), or select any link to change its length and lane count.
- Input validation on edits (cycle must be positive, green times non-negative, and
  green NS + green EW must not exceed the cycle).
- Geometry-aware link editing: changing a link length shifts the downstream rows or
  columns as a block so the grid stays structured.
- Perimeter terminals: every edge intersection gets a paired inbound source and
  outbound sink node, giving the simulation a full origin–destination graph.
- Routing via NetworkX Dijkstra with per-agent perturbed edge weights (±10%), so
  agents spread across plausible alternative routes instead of stacking on one path.
- Traffic-engineering metrics: Webster's optimal cycle length and HCM Level of
  Service (A–F) from average control delay.

## Project structure

| File | Responsibility |
|------|----------------|
| `main.py` | Pygame + pygame_gui application: rendering, world/screen transform, sidebar, click selection, and edit handling. |
| `network.py` | Network model. Owns intersections, internal links, terminals, terminal links, grid geometry, and the NetworkX routing graph. |
| `simulation.py` | Simulation engine (no Pygame). `Agent`, `Signal`, and `Simulation` classes with fixed-timestep stepping. |
| `metrics.py` | Traffic-engineering formulas: Webster's optimal cycle and HCM LOS thresholds. |
| `config.py` | Window, color, network, traffic, and simulation constants. |
| `requirements.txt` | Pinned dependencies. |

## Installation

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

Dependencies: `pygame-ce`, `pygame_gui`, `networkx`, `numpy`, `matplotlib`.

## Running

```bash
python main.py
```

## Usage

The window is split into a canvas (left) and a sidebar (right).

1. Click an intersection (light circle) to select it. The sidebar shows its
   **Cycle**, **Green NS**, and **Green EW** values. Edit them and press **Apply**.
2. Click a link (the line between two intersections) to select it. The sidebar shows
   its **Length** and **Lanes**. Edit them and press **Apply**.
3. Invalid edits are rejected with a status message and the previous values are kept.

Selected objects are highlighted. Perimeter terminals (inbound and outbound nodes)
are drawn at the network edges and are excluded from normal click editing to keep
the interface clean.

## Core concepts

**Network model.** Real grid intersections are stored separately from terminal
source/sink nodes, and internal links separately from terminal links. This keeps UI
editing limited to the real grid while still handing the simulation a complete graph
that includes entry and exit points.

**Naming.** Intersections are `I_<row>_<col>`. Inbound terminals are `T_IN_<side>_<i>`
and outbound terminals are `T_OUT_<side>_<i>`, where side is TOP, BOTTOM, LEFT, or
RIGHT. Links are named after their endpoints.

**Routing.** `Network.shortest_path(origin, dest, rng)` builds a temporary weighted
graph each call, perturbs every edge weight by ±10%, and runs Dijkstra. The
perturbation gives per-agent route variety while still favoring shorter paths.

**Signals.** Each intersection carries `cycle_length`, `green_ns`, `green_ew`, and
`offset`. The `Signal` state machine in `simulation.py` advances phase by elapsed
time on a fixed timestep.

**Metrics.** `websters_optimal_cycle(L_total, Y)` returns the Webster optimal cycle
and clamps the critical flow ratio `Y` at 0.95. `level_of_service(delay_s)` maps
average control delay to an HCM LOS grade from A to F.

## Configuration

Key constants live in `config.py`:

- Display: `WINDOW_WIDTH` 1400, `WINDOW_HEIGHT` 900, `SIDEBAR_WIDTH` 350, `FPS` 30.
- Network defaults: `DEFAULT_ROWS` 3, `DEFAULT_COLS` 3, default link length, default
  lanes.
- Traffic engineering: `SATURATION_FLOW` 1800 veh/hr/lane, `STARTUP_LOST_TIME` 2.0 s,
  free-flow speed.
- Simulation: `TIMESTEP` 1.0 s, `SIM_DURATION` 900 s, `WARMUP_DURATION` 180 s,
  `ROLLING_WINDOW` 300 s.

Note: a few constants (`DEFAULT_LINK_LENGTH_M`, `FREE_FLOW_SPEED`) are defined twice
in `config.py`; the later definition wins (link length 100 m, free-flow speed 15 m/s).
Worth collapsing to a single source of truth.

## Status and roadmap

The network model, UI, routing graph, and metric formulas are in place. The agent
and signal stepping logic in `simulation.py` is scaffolded and is the next piece to
flesh out: car/bus movement along routes, signal-gated discharge at stop lines, and
metric collection over the rolling window for live LOS readouts.

## Team

University of Texas at Austin Spring 2026 CAEE Hackathon, April 17–19, 2026. Built by Ifratul Hoque, Adeeba Naz, Jahin Labiba Chowdhury, and Shantanu Paul.

## License

[Add a license if you intend to share this publicly, e.g. MIT.]

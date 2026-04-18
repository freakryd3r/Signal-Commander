# Signal Commander — Step 1 (Scaffolding + Data Model)

**Course:** Traffic engineering hackathon  
**Goal of Step 1:** Bulletproof foundation — 3×3 signalized grid network with complete typed data model, NEMA 4-phase default signal plan, and a rendered Pygame window with panels. No simulation logic yet; that comes in Step 2.

## Files

| File | Purpose |
|---|---|
| `constants.py` | All magic numbers, HCM defaults, colors, direction conventions |
| `network.py` | `Link`, `Approach`, `Phase`, `PhasePlan`, `Intersection`, `Network` dataclasses |
| `signals.py` | `build_default_4phase_plan()` — NEMA 4-phase with equal splits |
| `scenarios.py` | `build_3x3_network()`, `load_am_peak_scenario()` |
| `rendering.py` | Background, panels, links (offset parallel), intersections, labels |
| `simulation.py` | Stub for Step 2 |
| `scoring.py` | Stub for Step 4 |
| `ui.py` | Stub for Step 3 |
| `main.py` | Pygame entry point with integrity checks |
| `test_step1.py` | Headless test runner (exhaustive correctness checks) |

## Install

```bash
pip install pygame
```

## Run

```bash
python main.py
```

**Expected console output:**

```
Intersections: 9
Links: 48
  Internal:          24
  Boundary inbound:  12
  Boundary outbound: 12
Demand entries: 12
All integrity checks passed.
```

**Expected visual:** Dark-themed 1600×900 window with a 3×3 grid of light-gray intersection nodes labeled `I_00` through `I_22`, two parallel gray lines connecting each adjacent pair (the opposing directed links), short stubs extending from perimeter intersections (boundary links), and left/right panel headers labeled "SCENARIO" and "CONTROLS".

Press **ESC** or close the window to quit.

## Run headless tests (no display required)

```bash
python test_step1.py
```

This runs exhaustive correctness checks (108 movement wirings, 36 inbound link resolutions, 24 boundary directions, 9 phase-plan arithmetic checks) without opening a window.

## Key conventions (fixed now, do not change)

- **Coordinate system:** `row ∈ {0,1,2}` top-to-bottom, `col ∈ {0,1,2}` left-to-right. 1 px = 1 m.
- **Direction-FROM:** An `Approach.direction = SOUTH` means the vehicle entered via the south leg and is heading NORTH.
- **Driver's left/right:** `LEFT_OF[heading]` is the compass direction to the driver's left (e.g., `LEFT_OF[NORTH] = WEST`).
- **Link ID:** `{from_node}_{dir}_{to_node}` for internal, `BND_{edge}{index}_{in|out}` for boundary.
- **Phase timing:** `total_time = effective_green + yellow + all_red`. Total lost time `L = n_phases × 4s = 16s` for 4-phase plans.
- **Default cycle:** `C = 60s`, `g = 11s` per phase, `Y = 3s`, `AR = 1s` per phase.

## References

- HCM 7th Ed. (TRB 2022), Chapter 19 (Signalized Intersections)
- Roess, Prassas, McShane (2019), *Traffic Engineering*, 5th ed.
- Webster (1958), RRL Technical Paper 39
- Akçelik (1981), ARRB Research Report 123

## Next: Step 2

Store-and-forward simulation engine, phase controller, HCM delay accumulation, conservation check, Webster validation test. See comments in `simulation.py` for the planned procedure.

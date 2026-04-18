# Signal Commander — Steps 1 + 2 + 3

**Hackathon project:** A traffic engineering game where the professor sets volumes and the student adjusts signal timing to minimize network delay.

## What's built

**Step 1:** Typed 3×3 network (9 intersections, 48 directed links, NEMA 4-phase signal plans, HCM-grounded defaults).

**Step 2:** Store-and-forward simulation engine (HCM / Webster / Akçelik compliant). Signals cycle, demand enters, queues grow, delay accumulates. Live V/C coloring, queue bars, green/yellow/red signal heads.

**Step 3:** Clickable intersection editor. Click any intersection → right panel opens with sliders for cycle (30–180s), four phase greens, offset (0–C), plus toggles for RTOR and LT-prohibition, plus Equal / Webster / Default preset buttons. Every change takes effect *immediately* in the live simulation.

## Files

| File | Purpose |
|---|---|
| `constants.py` | Magic numbers, HCM defaults, colors |
| `network.py` | Typed dataclasses (Link, Approach, Phase, PhasePlan, Intersection, Network) |
| `signals.py` | NEMA 4-phase plan builder |
| `scenarios.py` | Network construction + AM-peak demand |
| `simulation.py` | Store-and-forward engine, HCM-validated |
| `webster.py` | Webster optimum cycle + green allocation (iterative min-green enforcement) |
| `widgets.py` | Lightweight Pygame widgets: Slider, Button, Checkbox, Dropdown |
| `ui.py` | `IntersectionEditor` — the student's control panel |
| `rendering.py` | Pygame drawing (links, queues, signal heads, HUD, selection highlight) |
| `main.py` | Entry point with click routing + keyboard controls |
| `scoring.py` | Stub for Step 4 |
| `test_step1.py` | 8 structural tests |
| `test_step2.py` | 6 simulation validation tests |
| `test_step3.py` | 9 UI + Webster tests |

## Install and run

```bash
pip install pygame
python main.py
```

## Controls

| Key / Mouse | Action |
|---|---|
| **CLICK intersection** | Open editor for that intersection |
| **ESC** | Close editor (deselect) |
| **TAB** | Cycle through intersections |
| SPACE | Pause / resume |
| R | Reset simulation (keeps selected intersection) |
| UP / DOWN | Faster / slower (1×–20× sim steps per frame) |
| S | Single-step (while paused) |
| Q | Quit |

Inside the editor:

| Widget | Action |
|---|---|
| **Cycle slider** | 30–180 s; phase greens auto-rescale proportionally |
| **Phase 1–4 green sliders** | Adjust one phase; others redistribute to keep cycle constant |
| **Offset slider** | 0..C; wraps correctly; green wave coordination |
| **RTOR checkbox** | Toggle right-turn-on-red for all 4 approaches |
| **LT-prohibit EW/NS** | Ban left turns |
| **Equal button** | Reset to equal splits at current cycle |
| **Webster button** | Compute Webster-optimal cycle + splits from current demand |
| **Default button** | Reset to default 4-phase plan (60 s, equal splits, offset preserved) |

## Testing

```bash
python test_step1.py    # 8 tests — network structure
python test_step2.py    # 6 tests — simulation physics
python test_step3.py    # 9 tests — UI invariants + Webster math
```

All 23 tests must print PASS.

## Physics + UI validation

**Physics (Step 2):**
- Vehicle conservation: balance error ≈ 1.77e-11 veh after 15-min AM peak (float noise)
- HCM d₁ agreement: simulated 23.23 sec/veh vs analytical 23.23 sec/veh (ratio 1.000)
- Oversaturation: observed queue growth 28.18 veh matches theoretical (v−c)·t exactly
- Phase cycling: 15 cycles in 900s with C=60s (exact)
- Offset regression: mid-run offset changes picked up immediately

**UI (Step 3):**
- Cycle rescaling preserves green proportions
- Phase-split changes preserve cycle length (delta redistributed proportionally)
- Offset wraps modulo cycle
- Webster preset gives valid cycles with mins enforced iteratively
- Equal preset produces exact equal splits
- LT prohibition / RTOR toggles propagate correctly
- Approach volume estimation from boundary demand verified for middle intersection

## References

- HCM 7th Ed. (TRB 2022), Chapter 19
- Roess, Prassas, McShane (2019), *Traffic Engineering*, 5th ed.
- Webster (1958), RRL Technical Paper 39
- Akçelik (1981), ARRB Research Report 123
- Aboudolas, Papageorgiou, Kosmatopoulos (2009), *Transp. Res. C* 17(2)

## Coming next

**Step 4:** Scoreboard with three benchmarks (Baseline / Webster / Optimum) + "Best-so-far" tracker  
**Step 5:** Professor scenario controls (demand sliders, preset buttons, surge triggers)  
**Step 6:** Demo polish and presentation prep

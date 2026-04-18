# Signal Commander — Steps 1 + 2 + 3 (vigilance-audited)

**Hackathon project:** A traffic engineering game where the professor sets volumes and the student adjusts signal timing to minimize network delay.

## What's built

**Step 1:** Typed 3×3 network (9 intersections, 48 directed links, NEMA 4-phase signal plans, HCM-grounded defaults).

**Step 2:** Store-and-forward simulation engine (HCM / Webster / Akçelik compliant). Signals cycle, demand enters, queues grow, delay accumulates. Live V/C coloring, queue bars, green/yellow/red signal heads.

**Step 3:** Clickable intersection editor. Click any intersection → right panel opens with sliders for cycle (40–180s), four phase greens, offset (0–C), plus toggles for RTOR and LT-prohibition, plus Equal / Webster / Default preset buttons. Every change takes effect *immediately* in the live simulation.

## Files

| File | Purpose |
|---|---|
| `constants.py` | Magic numbers, HCM defaults, colors |
| `network.py` | Typed dataclasses (Link, Approach, Phase, PhasePlan, Intersection, Network) |
| `signals.py` | NEMA 4-phase plan builder |
| `scenarios.py` | Network construction + AM-peak demand |
| `simulation.py` | Store-and-forward engine, HCM-validated |
| `webster.py` | Webster optimum cycle + iterative green allocation |
| `widgets.py` | Lightweight Pygame widgets: Slider, Button, Checkbox, Dropdown |
| `ui.py` | `IntersectionEditor` — the student's control panel |
| `rendering.py` | Pygame drawing (links, queues, signal heads, HUD, selection highlight) |
| `main.py` | Entry point with click routing + keyboard controls |
| `scoring.py` | Stub for Step 4 |
| `test_step1.py` | 8 structural tests |
| `test_step2.py` | 6 simulation validation tests |
| `test_step3.py` | 9 UI + Webster tests |
| `stress_test.py` | 8 adversarial interaction scenarios |

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
| **Cycle slider** | 40–180 s; phase greens auto-rescale proportionally |
| **Phase 1–4 green sliders** | Adjust one phase; others redistribute iteratively to keep cycle constant |
| **Offset slider** | 0..C; wraps correctly; green wave coordination |
| **RTOR checkbox** | Toggle right-turn-on-red for all 4 approaches |
| **LT-prohibit EW / NS** | Ban left turns on either axis |
| **Equal button** | Reset to equal splits at current cycle |
| **Webster button** | Compute Webster-optimal cycle + splits from current demand |
| **Default button** | Reset to default 4-phase plan (60 s, equal splits, offset preserved) |

## Testing

```bash
python test_step1.py    # 8  — network structure
python test_step2.py    # 6  — simulation physics
python test_step3.py    # 9  — UI invariants + Webster math
python stress_test.py   # 8  — adversarial interaction scenarios
```

**31 total tests.** All must print PASS.

## Audit findings (all resolved)

Three real bugs caught and fixed during the vigilance audit:

**Bug 1 (Step 2):** `_advance_phase` and `movement_is_green` tracked phase state independently, causing desync when offset changes mid-run. Fixed: both now derive phase from `global_time + offset`, with `_advance_phase` called at the END of `step()` so renderers see current-time state.

**Bug 2 (Step 2):** Signal heads showed RED during yellow+all-red clearance interval. Fixed: heads now show YELLOW during clearance for the departing phase.

**Bug 3 (Step 3):** Webster's min-green enforcement used clamp-then-scale, which pushed values back below min after scaling. Fixed with iterative pin-and-redistribute allocation.

**Bug 4 (Step 3):** Cycle slider allowed values below 36s (physical floor given 5s min greens × 4 phases + 16s clearance), causing silent drift. Fixed: `MIN_CYCLE = 40.0` with 4s margin.

**Bug 5 (Step 3):** Phase-split redistribution used single-pass scale with min-green clamp, causing up to 1.3s cycle drift in edge cases. Fixed: same iterative pin-and-redistribute algorithm as Webster.

## Physics + UI validation

- **Vehicle conservation:** balance error ≈ 5e-12 veh even during 600s of concurrent UI changes
- **HCM d₁ agreement:** simulated 23.23 sec/veh vs analytical 23.23 sec/veh (ratio 1.000)
- **Oversaturation:** observed queue growth matches theoretical (v−c)·t exactly
- **Phase cycling:** 15 cycles in 900s with C=60s (exact)
- **Offset regression:** mid-run offset changes picked up immediately
- **Cycle rescaling:** greens preserved proportionally across any cycle change
- **Phase drag cycle preservation:** 0.0 drift across all edge cases
- **Webster preset:** valid cycles with mins iteratively enforced
- **Preset chaining:** 6-stage Webster→default→equal→Webster→Webster→default sequence stays consistent
- **All 9 intersections editable:** no state corruption across intersections

## Documented simplifications (not bugs, standard in literature)

- Approach-level aggregate queue re-randomizes turn types per step (Aboudolas 2009)
- Store-and-forward assumes no free-flow travel time (Gartner 1983)
- Permitted-LT uses `f_LT = 0.30` as first-order HCM approximation

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

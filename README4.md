# Signal Commander — Steps 1 + 2 + 3 + 4

**Hackathon project:** A traffic engineering game where the professor sets volumes and the student adjusts signal timing to minimize network delay.

## What's built

**Step 1:** Typed 3×3 network (9 intersections, 48 directed links, NEMA 4-phase signal plans, HCM-grounded defaults).

**Step 2:** Store-and-forward simulation engine (HCM / Webster / Akçelik compliant). Signals cycle, demand enters, queues grow, delay accumulates. Live V/C coloring, queue bars, green/yellow/red signal heads.

**Step 3:** Clickable intersection editor. Cycle / splits / offset sliders + RTOR and LT-prohibit toggles + Equal/Webster/Default preset buttons. All changes take effect immediately.

**Step 4:** Scoreboard with three benchmarks. Baseline / Webster-local / Optimum are each computed at load-time via full 15-min simulations; the student's current run is tracked live against these three. A "Best-so-far" tracker and improvement percentages make the game competitive.

## Files

| File | Purpose |
|---|---|
| `constants.py` | Magic numbers, HCM defaults |
| `network.py` | Typed dataclasses |
| `signals.py` | NEMA 4-phase builder |
| `scenarios.py` | 3x3 network construction + AM-peak |
| `simulation.py` | Store-and-forward HCM engine |
| `webster.py` | Webster cycle + iterative green allocation |
| `benchmarks.py` | Three benchmark computations (Baseline / Webster-Local / Optimum) |
| `scoring.py` | `ScoreBoard` — live tracker with extrapolation + best-so-far |
| `widgets.py` | Pygame widgets (Slider, Button, Checkbox, Dropdown) |
| `ui.py` | `IntersectionEditor` — student's control panel |
| `rendering.py` | Links, queues, signal heads, scoreboard |
| `main.py` | Entry point with loading splash |
| `test_step1.py` | 8 structural tests |
| `test_step2.py` | 6 simulation validation tests |
| `test_step3.py` | 9 UI + Webster tests |
| `test_step4.py` | 5 scoreboard + benchmark tests |
| `stress_test.py` | 8 adversarial interaction scenarios |

## Install and run

```bash
pip install pygame
python main.py
```

The first 2 seconds show a splash screen while the three benchmarks are computed. Then the main UI appears with the scoreboard visible in the right panel.

## Controls

| Key / Mouse | Action |
|---|---|
| **CLICK intersection** | Open editor |
| **ESC** | Close editor |
| **TAB** | Cycle through intersections |
| SPACE | Pause / resume |
| R | Reset simulation (benchmarks and best-so-far persist) |
| UP / DOWN | Speed 1×–20× |
| S | Single-step (while paused) |
| Q | Quit |

## Benchmarks explained

**Baseline** (red) — every intersection at default 60s cycle with equal splits, no coordination. The floor.

**Webster-local** (yellow) — every intersection runs Webster's optimum cycle and proportional splits computed from the AM-peak demand estimate for that intersection. Offsets stay zero. This is what "every engineer optimizes their intersection independently" looks like.

**Optimum** (green) — searches over common cycle lengths (local-Webster max, 60s, 90s, 120s), picks the cycle that minimizes 15-min network delay. All intersections share this common cycle with synchronized offsets and Webster-proportional splits.

**Current / Best** (blue / purple) — your live run, extrapolated to 15-minute equivalent delay. Best-so-far persists across the session (except on scenario change).

For the AM peak scenario, typical results:
- Baseline:  4.35 veh-hr (9.6 sec/veh average)
- Webster:   4.09 veh-hr (9.0 sec/veh) — 5.9% improvement
- Optimum:   3.43 veh-hr (7.5 sec/veh) — 21% improvement

## Testing

```bash
python test_step1.py    # 8  — network structure
python test_step2.py    # 6  — simulation physics
python test_step3.py    # 9  — UI invariants + Webster math
python test_step4.py    # 5  — scoreboard + benchmarks
python stress_test.py   # 8  — adversarial UI interactions
```

**36 total tests — all pass.**

## Physics validation

- Vehicle conservation: balance error ≈ 5e-12 veh after 600s with concurrent UI changes
- HCM d₁ agreement: simulated 23.23 sec/veh = HCM analytical 23.23 sec/veh (ratio 1.000)
- Oversaturation: queue growth matches theoretical (v−c)·t exactly
- Benchmark ordering: Optimum ≤ Webster ≤ Baseline always
- Scoreboard extrapolation: linear in sim time (verified)
- Best-so-far monotonicity: never increases once set

## Audit findings (all resolved)

Through vigilance audits across all steps, TEN bugs were caught and fixed:

1. **Phase state desync** (Step 2) — `_advance_phase` and `movement_is_green` used independent methods; fixed by deriving both from `global_time + offset`.
2. **Signal clearance color** (Step 2) — heads showed red during yellow+all-red; fixed to show yellow.
3. **Webster min-green enforcement** (Step 3) — clamp-then-scale violated minimums; replaced with iterative pin-and-redistribute.
4. **MIN_CYCLE too low** (Step 3) — slider allowed 30s but 36s is the physical floor; raised to 40s with margin.
5. **Phase drag residual drift** (Step 3) — same clamp-then-scale bug in UI; applied the same iterative fix.
6. **Optimum worse than Webster** (Step 4) — offset strategy assumed physical travel time but store-and-forward has none; replaced with cycle-length search for common-cycle optimum.
7. **sat_flow attribute error** (Step 4) — accessed on `Approach` instead of `Link`; replaced with `SAT_FLOW_BASE` constant.
8. **Scoreboard overlapped network** (Step 4) — moved from main canvas into right panel below editor.
9. **Offset not wrapped on preset** (Step 4) — `_preset_webster` didn't wrap `pp.offset` when cycle decreased; UI value and simulator state diverged. Fixed with explicit `pp.offset = pp.offset % pp.cycle_length`.
10. **Stale current score after R** (Step 4) — `R` reset created new sim but scoreboard kept old "current" values until new sim accumulated data. Added `ScoreBoard.reset_current()` called on R.

Plus one code-hygiene item: dead `draw_hud` function removed from `rendering.py` after being superseded by the scoreboard.

## Documented simplifications (not bugs, standard in literature)

- Approach-level aggregate queue re-randomizes turn types per step (Aboudolas 2009)
- Store-and-forward assumes no free-flow travel time (Gartner 1983)
- Permitted-LT uses `f_LT = 0.30` as HCM approximation
- Fixed turn ratios, not dynamic OD routing

## References

- HCM 7th Ed. (TRB 2022), Chapter 19
- Roess, Prassas, McShane (2019), *Traffic Engineering*, 5th ed.
- Webster (1958), RRL Technical Paper 39
- Akçelik (1981), ARRB Research Report 123
- Morgan & Little (1964), *Operations Research* 12(6)
- Aboudolas, Papageorgiou, Kosmatopoulos (2009), *Transp. Res. C* 17(2)

## Coming next

**Step 5:** Professor scenario controls (demand sliders, preset buttons, surge triggers)  
**Step 6:** Demo polish and 5-slide presentation prep

# Signal Commander — Steps 1 + 2 + 3 + 4 + 5

**Hackathon project:** A traffic engineering game where the professor sets demand patterns and triggers surprises, while the student adjusts signal timing at 9 intersections to minimize network delay — measured live against three benchmarks.

## What's built

**Step 1:** Typed 3×3 network (9 intersections, 48 directed links, NEMA 4-phase plans, HCM-grounded defaults).

**Step 2:** Store-and-forward simulation engine (HCM / Webster / Akçelik compliant). Signals cycle, demand enters, queues grow, delay accumulates. Live V/C coloring, queue bars, green/yellow/red signal heads.

**Step 3:** Clickable intersection editor. Cycle / splits / offset sliders + RTOR and LT-prohibit toggles + Equal/Webster/Default preset buttons. All changes take effect immediately in the live simulation.

**Step 4:** Scoreboard with three benchmarks. Baseline / Webster-local / Optimum precomputed at load; student's current run tracked live and extrapolated to 15-minute equivalent; best-so-far tracker.

**Step 5:** Professor's control panel (left side). Scenario preset buttons (AM peak / PM peak / Balanced / NS heavy) + per-edge demand sliders + theatrical triggers (surge, incident on I_11).

## Files

| File | Lines | Purpose |
|---|---|---|
| `constants.py` | 100 | Magic numbers, HCM defaults |
| `network.py` | 160 | Typed dataclasses (Link, Approach, Phase, PhasePlan, Intersection, Network) |
| `signals.py` | 45 | NEMA 4-phase builder |
| `scenarios.py` | 220 | 3×3 network construction + preset loaders + surge + incident |
| `simulation.py` | 370 | Store-and-forward HCM engine |
| `webster.py` | 170 | Webster cycle + iterative green allocation |
| `benchmarks.py` | 175 | Three benchmark computations |
| `scoring.py` | 120 | `ScoreBoard` — live tracker with extrapolation |
| `widgets.py` | 250 | Pygame widgets (Slider, Button, Checkbox, Dropdown) |
| `ui.py` | 400 | `IntersectionEditor` — student's control panel |
| `scenario_editor.py` | 200 | `ScenarioEditor` — professor's control panel |
| `rendering.py` | 400 | Links, queues, signal heads, scoreboard |
| `main.py` | 240 | Entry point + event routing |
| `test_step1.py` | 220 | 8 structural tests |
| `test_step2.py` | 370 | 6 simulation validation tests |
| `test_step3.py` | 380 | 9 UI + Webster tests |
| `test_step4.py` | 215 | 7 scoreboard + benchmark tests |
| `test_step5.py` | 225 | 8 scenario editor tests |
| `stress_test.py` | 255 | 8 adversarial interaction scenarios |

## Install and run

```bash
pip install pygame
python main.py
```

The first 2 seconds show a splash while benchmarks are computed. Then the full UI appears:

- **Left panel:** Professor's controls (presets, edge sliders, surge/incident)
- **Main canvas:** 3×3 network with live signals and queues
- **Right panel:** Student's intersection editor + scoreboard

## Controls

| Key / Mouse | Action |
|---|---|
| CLICK intersection | Open student's editor for that intersection |
| ESC | Close editor (deselect) |
| TAB | Cycle through intersections |
| SPACE | Pause / resume |
| R | Reset simulation (benchmarks preserved, best-so-far preserved) |
| UP / DOWN | Speed 1×–20× |
| S | Single-step (while paused) |
| Q | Quit |

### Left panel (professor)

| Widget | Action |
|---|---|
| **AM peak / PM peak / Balanced / NS heavy** buttons | Load a demand preset (benchmarks recompute, ~2s splash) |
| **N / S / E / W edge sliders** | Set uniform vph for all 3 boundary links on that edge |
| **+50% surge** | Multiply all current demand by 1.5× (capped at 2500 vph, benchmarks recompute) |
| **Reset dem** | Back to AM peak defaults |
| **Incident @I_11** | Block NS LT on I_11 + cut NS through phases to minimum |
| **Clear incident** | Restore I_11 to pre-incident state |

### Right panel (student)

| Widget | Action |
|---|---|
| **Cycle slider** | 40–180s; phase greens auto-rescale proportionally |
| **Phase 1–4 green sliders** | Redistribute across others to preserve cycle |
| **Offset slider** | 0..C; wraps correctly; green-wave coordination |
| **RTOR / LT-prohibit** | Per-movement rules |
| **Equal / Webster / Default** | Preset buttons |

## Testing

```bash
python test_step1.py    # 8  — network structure
python test_step2.py    # 6  — simulation physics
python test_step3.py    # 9  — UI invariants + Webster math
python test_step4.py    # 7  — scoreboard + benchmarks
python test_step5.py    # 8  — scenario editor + presets + incident
python stress_test.py   # 8  — adversarial UI interactions
```

**46 total tests — all pass.**

## Benchmarks (AM peak scenario)

- Baseline:  4.35 veh-hr (9.6 sec/veh avg)
- Webster-local: 4.09 veh-hr (+5.9% over baseline)
- Optimum:   3.43 veh-hr (+21.2% over baseline)

## Physics validation

- Vehicle conservation: balance error ≈ 5e-12 veh after 600s with concurrent UI changes
- HCM d₁ agreement: simulated 23.23 sec/veh = HCM analytical 23.23 sec/veh (ratio 1.000)
- Oversaturation: queue growth matches theoretical (v−c)·t exactly
- Benchmark ordering: Optimum ≤ Webster ≤ Baseline always
- Scoreboard extrapolation: linear in sim time
- Best-so-far monotonicity: never increases once set
- Incident round-trip: phase_plan exactly restored

## Audit findings (all resolved)

Through five vigilance-audit passes, **eleven bugs** were caught and fixed:

1. **Phase state desync** (Step 2) — `_advance_phase` and `movement_is_green` used independent methods; fixed by deriving both from `global_time + offset`.
2. **Signal clearance color** (Step 2) — heads showed red during yellow+all-red; fixed to show yellow.
3. **Webster min-green enforcement** (Step 3) — clamp-then-scale violated minimums; replaced with iterative pin-and-redistribute.
4. **MIN_CYCLE too low** (Step 3) — slider allowed 30s but 36s is the physical floor; raised to 40s.
5. **Phase drag residual drift** (Step 3) — same clamp-then-scale bug in UI; applied iterative fix.
6. **Optimum worse than Webster** (Step 4) — offset strategy assumed physical travel time but store-and-forward has none; replaced with cycle-length search.
7. **sat_flow attribute error** (Step 4) — accessed on `Approach` instead of `Link`; used `SAT_FLOW_BASE` constant.
8. **Scoreboard overlapped network** (Step 4) — moved into right panel below editor.
9. **Offset not wrapped on preset** (Step 4) — `_preset_webster` didn't wrap `pp.offset` when cycle decreased; UI and simulator diverged. Fixed.
10. **Stale current score after R** (Step 4) — reset created new sim but scoreboard kept old "current" values. Added `ScoreBoard.reset_current()`.
11. **Stale intersection sliders after incident** (Step 5) — `apply_incident` externally mutates phase_plan but sliders didn't refresh. Added public `IntersectionEditor.resync()` called from scenario callbacks.

Plus one code-hygiene item: dead `draw_hud` function removed.

## References

- HCM 7th Ed. (TRB 2022), Chapter 19
- Roess, Prassas, McShane (2019), *Traffic Engineering*, 5th ed.
- Webster (1958), RRL Technical Paper 39
- Akçelik (1981), ARRB Research Report 123
- Morgan & Little (1964), *Operations Research* 12(6)
- Aboudolas, Papageorgiou, Kosmatopoulos (2009), *Transp. Res. C* 17(2)

## Suggested demo script (for judging Sunday)

1. **Open**: "Signal Commander — a traffic engineering game that teaches signal coordination."
2. **Show default sim** (AM peak): "Baseline 4.35 veh-hr. Webster 4.09. Optimum 3.43."
3. **Click I_11, apply Webster**: "Watch — applied Webster to ONE intersection. Score went *worse*, -8.3%. Local optimization hurts the network."
4. **TAB + Webster all**: "Now all 9. Score matches yellow Webster bar. +6% over baseline."
5. **Common cycle**: "But the green Optimum bar is at 3.43. To reach it we need every intersection on a COMMON cycle — coordination, not just local optimization."
6. **Professor interruption**: "Now — surprise." Click "+50% surge". Network starts to fail. "Student has to adapt."
7. **Incident**: Click "Incident @I_11". "The main arterial just closed. Rethink."
8. **Close**: "The game scales from teaching Webster in a classroom to live arterial redesign in a workshop. Five steps of physics-honest simulation."

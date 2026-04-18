"""Stress test: simulate aggressive user interactions to catch edge-case bugs."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
pygame.init()

from constants import (
    DEFAULT_CYCLE, YELLOW_TIME, ALL_RED_TIME, MIN_CYCLE, MAX_CYCLE,
    NORTH, EAST, SOUTH, WEST,
)
from scenarios import build_3x3_network, load_am_peak_scenario
from simulation import Simulator
from ui import IntersectionEditor


def invariants_hold(intx, label=""):
    """Check that the intersection's state is internally consistent."""
    pp = intx.phase_plan
    # cycle_length = sum of phase total_times
    computed_cycle = sum(p.total_time for p in pp.phases)
    pp_cycle = pp.cycle_length
    assert abs(computed_cycle - pp_cycle) < 1e-6, \
        f"{label}: cycle_length property inconsistent ({computed_cycle} vs {pp_cycle})"

    # All greens >= 0
    for i, p in enumerate(pp.phases):
        assert p.effective_green >= 0, \
            f"{label}: phase {i} has negative green {p.effective_green}"
        # total_time consistent
        assert abs(p.total_time - (p.effective_green + p.yellow_time + p.all_red_time)) < 1e-9

    # Offset in [0, cycle)
    assert 0 <= pp.offset < pp.cycle_length + 1e-6, \
        f"{label}: offset {pp.offset} out of range [0, {pp.cycle_length})"


def stress_cycle_extreme():
    """Drag cycle slider to min and max rapidly. Each step should leave
    the phase plan in a valid state.
    """
    print("\n--- Stress 1: rapid cycle slider drag ---")
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    editor = IntersectionEditor(net, lambda: demand)
    editor.select(net.intersections["I_11"])

    for cycle in [MIN_CYCLE, MAX_CYCLE, MIN_CYCLE, 60, 45, 120, 37, MIN_CYCLE]:
        editor._on_cycle_change(cycle)
        invariants_hold(editor.selected, f"cycle={cycle}")
        pp = editor.selected.phase_plan
        # Report
        actual_cycle = pp.cycle_length
        greens = [p.effective_green for p in pp.phases]
        drift = actual_cycle - cycle
        status = "OK" if abs(drift) < 1 else f"DRIFT={drift:+.2f}"
        print(f"  Set cycle={cycle:.0f}, actual={actual_cycle:.2f}, "
              f"greens={['%.1f'%g for g in greens]} [{status}]")
    print("  PASS (no assertion failures)")


def stress_phase_extreme():
    """Drag each phase slider to its min/max rapidly."""
    print("\n--- Stress 2: rapid phase slider drag ---")
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    editor = IntersectionEditor(net, lambda: demand)
    editor.select(net.intersections["I_11"])

    pp = editor.selected.phase_plan
    original_cycle = pp.cycle_length

    for idx in range(4):
        min_g, max_g = editor._green_bounds(pp.cycle_length)
        for target in [min_g, max_g, (min_g + max_g) / 2]:
            editor._on_phase_green_change(idx, target)
            invariants_hold(editor.selected, f"phase{idx}={target}")
            # Cycle should stay close to what it was (phase-change preserves cycle)
            drift = editor.selected.phase_plan.cycle_length - original_cycle
            assert abs(drift) < 1.0, f"cycle drifted {drift} on phase {idx}"

    print("  PASS: cycle preserved across phase drags")


def stress_offset_extreme():
    """Push offset to various values including > cycle."""
    print("\n--- Stress 3: offset extremes ---")
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    editor = IntersectionEditor(net, lambda: demand)
    editor.select(net.intersections["I_11"])

    pp = editor.selected.phase_plan
    for off in [0, pp.cycle_length - 0.5, pp.cycle_length,
                pp.cycle_length + 10, 500]:
        editor._on_offset_change(off)
        invariants_hold(editor.selected, f"offset={off}")
        print(f"  Set offset={off}, actual={pp.offset:.2f}")
    print("  PASS")


def stress_preset_cycles():
    """Apply presets in various orders. Each must leave valid state."""
    print("\n--- Stress 4: preset chaining ---")
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    editor = IntersectionEditor(net, lambda: demand)
    editor.select(net.intersections["I_11"])

    sequence = [
        ("webster", editor._preset_webster),
        ("default", editor._preset_default),
        ("equal", editor._preset_equal),
        ("webster", editor._preset_webster),
        ("webster", editor._preset_webster),  # apply twice
        ("default", editor._preset_default),
    ]
    for label, fn in sequence:
        fn()
        invariants_hold(editor.selected, f"after {label}")
        pp = editor.selected.phase_plan
        print(f"  After {label}: C={pp.cycle_length:.1f}, "
              f"greens={['%.1f'%p.effective_green for p in pp.phases]}")
    print("  PASS")


def stress_sim_with_changes():
    """Run sim while applying UI changes mid-run. Conservation must hold."""
    print("\n--- Stress 5: sim runs while UI changes ---")
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    sim = Simulator(net, demand)
    editor = IntersectionEditor(net, lambda: demand)
    editor.select(net.intersections["I_11"])

    for block in range(10):
        for _ in range(60):
            sim.step()
        # Apply a random UI change
        if block % 3 == 0:
            editor._on_cycle_change(45.0 + block * 5)
        elif block % 3 == 1:
            editor._on_phase_green_change(0, 10 + block)
        else:
            editor._on_offset_change(block * 5)

    result = sim.conservation_check()
    print(f"  After 600s with UI changes: balance={result['balance_error']:.6e}")
    print(f"  Delay={result['total_delay_vehhr']:.3f} veh-hr")
    assert abs(result["balance_error"]) < 1e-3, "Conservation broken by UI changes"
    print("  PASS: conservation holds across UI changes")


def stress_all_intersections():
    """Cycle through all 9 intersections, apply changes to each."""
    print("\n--- Stress 6: all intersections editable ---")
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    editor = IntersectionEditor(net, lambda: demand)

    for iid in sorted(net.intersections.keys()):
        editor.select(net.intersections[iid])
        editor._preset_webster()
        invariants_hold(editor.selected, f"after webster at {iid}")

    # Reset all to default before checking global state
    for iid in sorted(net.intersections.keys()):
        editor.select(net.intersections[iid])
        editor._preset_default()
        invariants_hold(editor.selected, f"after default at {iid}")

    print("  PASS: all 9 intersections edit cleanly")


def stress_extreme_demand():
    """Zero demand and huge demand — Webster should not crash."""
    print("\n--- Stress 7: zero and huge demand ---")
    net = build_3x3_network()

    # Zero demand
    demand = {lid: 0.0 for lid in net.boundary_inbound}
    editor = IntersectionEditor(net, lambda: demand)
    editor.select(net.intersections["I_11"])
    editor._preset_webster()
    invariants_hold(editor.selected, "zero demand webster")
    pp = editor.selected.phase_plan
    print(f"  Zero demand: C={pp.cycle_length:.1f}, "
          f"greens={[f'{p.effective_green:.1f}' for p in pp.phases]}")

    # Huge demand
    demand2 = {lid: 2500.0 for lid in net.boundary_inbound}
    editor2 = IntersectionEditor(net, lambda: demand2)
    editor2.select(net.intersections["I_11"])
    editor2._preset_webster()
    invariants_hold(editor2.selected, "huge demand webster")
    pp2 = editor2.selected.phase_plan
    print(f"  Huge demand: C={pp2.cycle_length:.1f}, "
          f"greens={[f'{p.effective_green:.1f}' for p in pp2.phases]}")

    print("  PASS")


def stress_preset_then_drag():
    """After Webster preset, drag sliders. Should stay consistent."""
    print("\n--- Stress 8: preset then drag ---")
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    editor = IntersectionEditor(net, lambda: demand)
    editor.select(net.intersections["I_11"])

    def snapshot(label):
        # Always read fresh; _preset_default replaces the phase_plan object
        pp = editor.selected.phase_plan
        greens = [f"{p.effective_green:.1f}" for p in pp.phases]
        print(f"  {label}: C={pp.cycle_length:.1f}, greens={greens}")
        invariants_hold(editor.selected, label)

    editor._preset_webster()
    snapshot("Webster")

    editor._on_cycle_change(80.0)
    snapshot("cycle=80")

    editor._on_phase_green_change(0, 30)
    snapshot("phase0=30")

    editor._preset_default()
    snapshot("default")

    editor._on_cycle_change(100)
    snapshot("cycle=100")

    editor._on_phase_green_change(2, 40)
    snapshot("phase2=40")

    print("  PASS")


if __name__ == "__main__":
    stress_cycle_extreme()
    stress_phase_extreme()
    stress_offset_extreme()
    stress_preset_cycles()
    stress_sim_with_changes()
    stress_all_intersections()
    stress_extreme_demand()
    stress_preset_then_drag()
    print("\n========== STRESS TESTS DONE ==========")

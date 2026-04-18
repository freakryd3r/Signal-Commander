"""Step 5 adversarial stress testing.

Scenarios that are hard to detect in unit tests:
  1. Rapid scenario-preset toggling — does state stay consistent?
  2. Incident applied while student is editing I_11 — do both stay sync'd?
  3. Preset change while incident is active — does clear + reapply work?
  4. Edge slider changes don't corrupt benchmarks (they shouldn't fire recompute)
  5. Scenario preset → student edit → different preset — student settings preserved?
  6. R reset while incident active — incident persists
  7. Student editing I_11, professor triggers incident → clears → slider values?
  8. Memory: no object leaks across many scenario changes
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
pygame.init()

import gc
from scenarios import (
    build_3x3_network, load_am_peak_scenario, SCENARIO_PRESETS,
)
from scenario_editor import ScenarioEditor
from ui import IntersectionEditor
from simulation import Simulator
from constants import NORTH, SOUTH


def make_setup():
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    calls = {"scen": 0, "nudge": 0}
    scen_editor = ScenarioEditor(
        net, demand,
        on_scenario_change=lambda: calls.__setitem__("scen", calls["scen"] + 1),
        on_demand_nudge=lambda: calls.__setitem__("nudge", calls["nudge"] + 1),
    )
    intx_editor = IntersectionEditor(net, lambda: demand)
    return net, demand, scen_editor, intx_editor, calls


def invariants(net, scen_editor, label):
    """Check no silent state corruption."""
    # All intersections have valid phase plans
    for intx in net.intersections.values():
        pp = intx.phase_plan
        assert pp is not None
        assert len(pp.phases) == 4
        # Cycle is sum of total_times
        computed_cycle = sum(p.total_time for p in pp.phases)
        assert abs(computed_cycle - pp.cycle_length) < 1e-6, \
            f"{label}: {intx.node_id} cycle inconsistent"
        # Offset wrapped
        assert 0 <= pp.offset <= pp.cycle_length + 1e-6, \
            f"{label}: {intx.node_id} offset out of range"

    # Demand is finite and non-negative
    for lid in scen_editor.demand:
        v = scen_editor.demand[lid]
        assert v >= 0 and v < 1e6, f"{label}: demand[{lid}]={v}"


def test_rapid_preset_toggling():
    """Click through all 4 presets rapidly. State stays consistent."""
    print("\n--- Adversarial 1: rapid preset toggling ---")
    net, demand, scen, intx, calls = make_setup()

    sequence = ["PM peak", "NS heavy", "Balanced", "AM peak",
                "NS heavy", "PM peak", "AM peak"]
    for name in sequence:
        scen._apply_preset(name)
        invariants(net, scen, f"after {name}")

    assert calls["scen"] == len(sequence), \
        f"expected {len(sequence)} scen calls, got {calls['scen']}"
    print(f"  7 preset changes: all invariants hold, callbacks={calls}")
    print("  PASS")


def test_incident_during_edit():
    """Student is editing I_11. Professor triggers incident. Clear.
    Verify editor sliders stay consistent with phase_plan."""
    print("\n--- Adversarial 2: incident during edit ---")
    net, demand, scen, intx, calls = make_setup()

    intx.select(net.intersections["I_11"])
    # Student applies Webster
    intx._preset_webster()
    pp_webster_greens = [p.effective_green for p in intx.selected.phase_plan.phases]
    cycle_webster = intx.selected.phase_plan.cycle_length
    print(f"  Student's Webster on I_11: cycle={cycle_webster:.1f}, "
          f"greens={[f'{g:.1f}' for g in pp_webster_greens]}")

    # Professor triggers incident
    scen._trigger_incident()
    intx.resync()  # simulate main.py's callback-triggered resync

    # Sliders should match post-incident state
    for i in range(4):
        slider_val = intx._phase_sliders[i].value
        pp_val = intx.selected.phase_plan.phases[i].effective_green
        assert abs(slider_val - pp_val) < 0.01, (
            f"phase {i}: slider={slider_val}, pp={pp_val}"
        )
    # NS through + LT should be at 5
    assert intx.selected.phase_plan.phases[2].effective_green == 5.0
    assert intx.selected.phase_plan.phases[3].effective_green == 5.0
    print(f"  During incident: greens="
          f"{[f'{p.effective_green:.1f}' for p in intx.selected.phase_plan.phases]}")

    # Professor clears
    scen._clear_incident()
    intx.resync()

    # Back to student's Webster exactly
    for i, expected in enumerate(pp_webster_greens):
        actual = intx.selected.phase_plan.phases[i].effective_green
        assert abs(actual - expected) < 0.01, (
            f"phase {i} not restored: {actual} != {expected}"
        )
        slider_val = intx._phase_sliders[i].value
        assert abs(slider_val - actual) < 0.01

    print(f"  After clear: greens restored to Webster, sliders match")
    print("  PASS")


def test_preset_while_incident_active():
    """Preset button with incident active: clear_incident fires first,
    then new demand loaded. Verify I_11 is reset to default (not stuck in incident)."""
    print("\n--- Adversarial 3: preset while incident active ---")
    net, demand, scen, intx, calls = make_setup()

    # Trigger incident
    scen._trigger_incident()
    i11 = net.intersections["I_11"]
    assert i11.approaches[NORTH].lt_prohibited == True
    assert scen._incident_state is not None

    # Apply new preset while incident active
    scen._apply_preset("PM peak")

    # Incident should be cleared
    assert scen._incident_state is None, "incident state not cleared by preset"
    assert i11.approaches[NORTH].lt_prohibited == False, (
        "NS LT still prohibited after preset clears incident"
    )
    # NS phases restored (not stuck at 5.0)
    assert i11.phase_plan.phases[2].effective_green != 5.0 or \
           i11.phase_plan.phases[3].effective_green != 5.0, (
        "NS phases still at 5.0 — incident not fully cleared"
    )
    print(f"  After preset while incident active:")
    print(f"    incident_state={scen._incident_state}")
    print(f"    NS LT prohibited: {i11.approaches[NORTH].lt_prohibited}")
    print(f"    I_11 greens: {[p.effective_green for p in i11.phase_plan.phases]}")
    print("  PASS")


def test_edge_slider_doesnt_recompute():
    """Edge slider drags fire nudge (not scenario_change), so benchmarks stay stable.
    Only presets/surge/incident recompute."""
    print("\n--- Adversarial 4: edge sliders don't trigger scenario_change ---")
    net, demand, scen, intx, calls = make_setup()

    for edge in "NSEW":
        scen._on_edge_slider(edge, 700)
        scen._on_edge_slider(edge, 1000)

    assert calls["scen"] == 0, f"slider fired scen callback {calls['scen']} times"
    assert calls["nudge"] == 8, f"expected 8 nudge calls, got {calls['nudge']}"
    print(f"  8 slider changes: scen={calls['scen']}, nudge={calls['nudge']}")
    print("  PASS")


def test_student_settings_persist_across_preset():
    """Student's per-intersection settings should persist when professor
    changes demand preset (only demand changes, not signal plans)."""
    print("\n--- Adversarial 5: student settings persist across preset ---")
    net, demand, scen, intx, calls = make_setup()

    # Student applies Webster to I_11
    intx.select(net.intersections["I_11"])
    intx._preset_webster()
    cycle_before = intx.selected.phase_plan.cycle_length
    greens_before = [p.effective_green for p in intx.selected.phase_plan.phases]

    # Professor changes preset
    scen._apply_preset("NS heavy")

    # I_11's phase plan should be unchanged (only demand changed)
    cycle_after = net.intersections["I_11"].phase_plan.cycle_length
    greens_after = [p.effective_green for p in net.intersections["I_11"].phase_plan.phases]

    assert abs(cycle_before - cycle_after) < 0.01, (
        f"cycle changed from {cycle_before} to {cycle_after} across preset"
    )
    for i, (b, a) in enumerate(zip(greens_before, greens_after)):
        assert abs(b - a) < 0.01, f"phase {i}: {b} != {a}"
    print(f"  I_11 settings preserved across preset change")
    print(f"    cycle={cycle_after:.1f}, greens={[f'{g:.1f}' for g in greens_after]}")
    print("  PASS")


def test_surge_multiple_applications():
    """Multiple surges compound but cap at 2500."""
    print("\n--- Adversarial 6: multiple surges respect cap ---")
    net, demand, scen, intx, calls = make_setup()

    # AM peak east = 800, 800 * 1.5 = 1200, * 1.5 = 1800, * 1.5 = 2500 (capped)
    scen._trigger_surge()  # 800 -> 1200
    assert demand["BND_E0_in"] == 1200
    scen._trigger_surge()  # 1200 -> 1800
    assert demand["BND_E0_in"] == 1800
    scen._trigger_surge()  # 1800 -> 2500 (capped, not 2700)
    assert demand["BND_E0_in"] == 2500, f"expected cap at 2500, got {demand['BND_E0_in']}"
    scen._trigger_surge()  # still 2500
    assert demand["BND_E0_in"] == 2500
    print(f"  4 surges compound correctly, cap at 2500")
    print("  PASS")


def test_no_memory_leak_across_presets():
    """After many preset changes + incident cycles, Network objects should be GC'd
    (checked via gc.collect())."""
    print("\n--- Adversarial 7: no lingering networks after many changes ---")
    import gc

    net, demand, scen, intx, calls = make_setup()

    # Before test: count live Network objects
    import network as network_mod
    gc.collect()
    before_count = sum(1 for obj in gc.get_objects() if isinstance(obj, network_mod.Network))

    # 20 preset changes + incidents
    for i in range(20):
        scen._apply_preset("PM peak")
        scen._trigger_incident()
        scen._clear_incident()
        scen._apply_preset("NS heavy")
        scen._trigger_surge()
        scen._apply_preset("AM peak")

    gc.collect()
    after_count = sum(1 for obj in gc.get_objects() if isinstance(obj, network_mod.Network))

    print(f"  Networks alive before: {before_count}, after 120 operations: {after_count}")
    # Should be same count (we didn't create new networks, just modified)
    assert after_count == before_count, (
        f"Leaked {after_count - before_count} Network objects"
    )
    print("  PASS: no network object leakage")


def test_reset_preserves_incident():
    """R reset should not clear an active incident (incident is network-level state)."""
    print("\n--- Adversarial 8: R reset preserves incident ---")
    net, demand, scen, intx, calls = make_setup()

    scen._trigger_incident()
    i11 = net.intersections["I_11"]
    assert i11.approaches[NORTH].lt_prohibited == True

    # Simulate R: new simulator but same network
    sim = Simulator(net, demand)

    # Incident still active on network
    assert i11.approaches[NORTH].lt_prohibited == True, (
        "R reset cleared the incident — should have persisted"
    )
    assert scen._incident_state is not None, (
        "scen_editor's incident tracking state cleared by R"
    )
    print("  Incident persists through R reset")
    print("  PASS")


if __name__ == "__main__":
    test_rapid_preset_toggling()
    test_incident_during_edit()
    test_preset_while_incident_active()
    test_edge_slider_doesnt_recompute()
    test_student_settings_persist_across_preset()
    test_surge_multiple_applications()
    test_no_memory_leak_across_presets()
    test_reset_preserves_incident()
    print("\n========== STEP 5 ADVERSARIAL STRESS TESTS PASSED ==========")

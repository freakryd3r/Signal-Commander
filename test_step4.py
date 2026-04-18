"""Step 4 validation: benchmarks + scoreboard correctness.

Tests:
  Test P: Baseline benchmark matches Step 2 Test A result
  Test Q: Optimum <= Webster <= Baseline ordering holds for AM peak
  Test R: ScoreBoard extrapolation is linear in sim time
  Test S: Best-so-far only updates after min_time and only when improved
  Test T: ScoreBoard ratios and percentages are sensible
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
pygame.init()

from scenarios import build_3x3_network, load_am_peak_scenario
from simulation import Simulator
from benchmarks import compute_baseline, compute_webster_local, compute_optimum, compute_all
from scoring import ScoreBoard, BenchmarkValues
from constants import SIM_DURATION


def test_baseline_matches_step2():
    """The baseline benchmark is just 'run default network for 15 min'.
    The same result should have been produced by Step 2 Test A (AM peak).
    """
    print("\n--- Test P: Baseline matches Step 2 AM peak ---")
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    d_hr, avg, thru = compute_baseline(demand)
    print(f"  Baseline: {d_hr:.3f} veh-hr, {avg:.2f} sec/veh, {thru:.1f} throughput")
    # Step 2 Test A reported: total delay 4.346 veh-hr, avg 9.61 sec/veh
    assert abs(d_hr - 4.346) < 0.01, f"baseline delay {d_hr}, expected ~4.346"
    assert abs(avg - 9.61) < 0.1, f"avg delay {avg}, expected ~9.61"
    print("  PASS")


def test_benchmark_ordering():
    """Optimum <= Webster <= Baseline for AM peak."""
    print("\n--- Test Q: Benchmark ordering (Optimum <= Webster <= Baseline) ---")
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    bench = compute_all(demand)
    b = bench["baseline"]["delay_vehhr"]
    w = bench["webster"]["delay_vehhr"]
    o = bench["optimum"]["delay_vehhr"]
    print(f"  Baseline: {b:.3f}, Webster: {w:.3f}, Optimum: {o:.3f}")
    assert o <= w + 0.01, f"Optimum {o} > Webster {w}"
    assert w <= b + 0.01, f"Webster {w} > Baseline {b}"
    print("  PASS")


def test_scoreboard_extrapolation():
    """Scoreboard extrapolates linearly from partial run to full duration."""
    print("\n--- Test R: Scoreboard extrapolation ---")
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)

    # Fake benchmarks
    bench = {
        "baseline": {"delay_vehhr": 10.0, "avg_sec": 20.0, "throughput": 1000},
        "webster":  {"delay_vehhr": 7.0,  "avg_sec": 14.0, "throughput": 1000},
        "optimum":  {"delay_vehhr": 5.0,  "avg_sec": 10.0, "throughput": 1000},
    }
    score = ScoreBoard.from_benchmarks(bench)

    sim = Simulator(net, demand)
    # Run 450 sec (half the 900-sec duration)
    for _ in range(450):
        sim.step()
    raw_delay_hr = sim.total_delay / 3600.0
    score.update(sim)

    # Extrapolation: (raw_delay / 450) * 900 = raw_delay * 2
    expected_extrapolated = raw_delay_hr * (SIM_DURATION / 450.0)
    assert abs(score.current_delay_vehhr - expected_extrapolated) < 1e-6, (
        f"Got {score.current_delay_vehhr}, expected {expected_extrapolated}"
    )
    print(f"  At t=450, raw={raw_delay_hr:.3f}, extrapolated={score.current_delay_vehhr:.3f}, "
          f"expected={expected_extrapolated:.3f}")
    print("  PASS")


def test_best_so_far_gating():
    """Best-so-far should update only after min_time and only on improvement."""
    print("\n--- Test S: Best-so-far gating ---")
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    bench = {
        "baseline": {"delay_vehhr": 10.0, "avg_sec": 20.0, "throughput": 1000},
        "webster":  {"delay_vehhr": 7.0,  "avg_sec": 14.0, "throughput": 1000},
        "optimum":  {"delay_vehhr": 5.0,  "avg_sec": 10.0, "throughput": 1000},
    }
    score = ScoreBoard.from_benchmarks(bench)
    sim = Simulator(net, demand)

    # Run only 100 sec - below min_time_for_best (300)
    for _ in range(100):
        sim.step()
    score.update(sim)
    assert score.best_delay_vehhr == float("inf"), \
        "best should not update before min_time"

    # Run to 400 sec - above min_time
    for _ in range(300):
        sim.step()
    score.update(sim)
    first_best = score.best_delay_vehhr
    assert first_best < float("inf"), "best should have updated"
    print(f"  After 400s: best = {first_best:.3f}")

    # Run to 800 sec — should NOT degrade best even if current gets worse
    for _ in range(400):
        sim.step()
    score.update(sim)
    assert score.best_delay_vehhr <= first_best + 1e-6, (
        f"best went UP from {first_best} to {score.best_delay_vehhr}"
    )
    print(f"  After 800s: best = {score.best_delay_vehhr:.3f} (never went up)")
    print("  PASS")


def test_ratio_computations():
    """Scoreboard ratio math."""
    print("\n--- Test T: ratio and percentage math ---")
    bench = {
        "baseline": {"delay_vehhr": 10.0, "avg_sec": 20.0, "throughput": 1000},
        "webster":  {"delay_vehhr": 7.0,  "avg_sec": 14.0, "throughput": 1000},
        "optimum":  {"delay_vehhr": 5.0,  "avg_sec": 10.0, "throughput": 1000},
    }
    score = ScoreBoard.from_benchmarks(bench)

    score.current_delay_vehhr = 8.0
    # vs baseline: 8/10 = 0.8, so 20% improvement
    pct = score.percent_improvement_over_baseline()
    assert abs(pct - 20.0) < 1e-6, f"pct={pct}"
    # gap to optimum: (8-5)/(10-5) = 0.6 = 60%
    gap = score.gap_to_optimum()
    assert abs(gap - 0.6) < 1e-6, f"gap={gap}"

    # Matching baseline
    score.current_delay_vehhr = 10.0
    assert abs(score.percent_improvement_over_baseline()) < 1e-6
    assert abs(score.gap_to_optimum() - 1.0) < 1e-6

    # Matching optimum
    score.current_delay_vehhr = 5.0
    assert abs(score.percent_improvement_over_baseline() - 50.0) < 1e-6
    assert abs(score.gap_to_optimum() - 0.0) < 1e-6

    # Better than optimum (unusual)
    score.current_delay_vehhr = 4.0
    assert score.gap_to_optimum() < 0.0
    print(f"  Ratios all match expected values.")
    print("  PASS")


def test_offset_wrap_after_webster():
    """Regression: offset must stay in [0, cycle) after Webster preset
    changes cycle length. Previously pp.offset could exceed new cycle."""
    print("\n--- Test U: offset wraps correctly after Webster preset ---")
    from ui import IntersectionEditor
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    editor = IntersectionEditor(net, lambda: demand)
    editor.select(net.intersections["I_11"])

    # Set offset to 50 on default cycle=60
    editor._on_offset_change(50.0)
    editor._offset_slider.value = 50.0
    assert editor.selected.phase_plan.offset == 50.0

    # Apply Webster (cycle drops to ~45)
    editor._preset_webster()
    pp = editor.selected.phase_plan
    print(f"  After Webster: cycle={pp.cycle_length:.2f}, offset={pp.offset:.2f}, "
          f"slider={editor._offset_slider.value:.2f}")

    assert 0 <= pp.offset < pp.cycle_length, (
        f"pp.offset={pp.offset} not in [0, {pp.cycle_length})"
    )
    assert abs(editor._offset_slider.value - pp.offset) < 0.01, (
        f"slider.value={editor._offset_slider.value} != pp.offset={pp.offset}"
    )
    print("  PASS: offset wraps, UI and data stay in sync")


def test_reset_current():
    """ScoreBoard.reset_current() clears current but preserves benchmarks/best."""
    print("\n--- Test V: ScoreBoard.reset_current ---")
    bench = {
        "baseline": {"delay_vehhr": 10.0, "avg_sec": 20.0, "throughput": 1000},
        "webster":  {"delay_vehhr": 7.0,  "avg_sec": 14.0, "throughput": 1000},
        "optimum":  {"delay_vehhr": 5.0,  "avg_sec": 10.0, "throughput": 1000},
    }
    score = ScoreBoard.from_benchmarks(bench)
    score.current_delay_vehhr = 8.5
    score.current_avg_sec = 17.0
    score.best_delay_vehhr = 8.5

    score.reset_current()

    assert score.current_delay_vehhr == 0.0
    assert score.current_avg_sec == 0.0
    assert score.best_delay_vehhr == 8.5, "best should be preserved"
    assert score.baseline.delay_vehhr == 10.0, "benchmarks should be preserved"
    print("  PASS: current cleared, benchmarks and best preserved")


if __name__ == "__main__":
    test_baseline_matches_step2()
    test_benchmark_ordering()
    test_scoreboard_extrapolation()
    test_best_so_far_gating()
    test_ratio_computations()
    test_offset_wrap_after_webster()
    test_reset_current()
    print("\n========== ALL STEP 4 TESTS PASSED ==========")

"""Headless integrity test runner (no pygame display required)."""

import sys
import os

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set dummy SDL video driver so pygame can init without a display
os.environ["SDL_VIDEODRIVER"] = "dummy"

from scenarios import build_3x3_network, load_am_peak_scenario
from main import run_integrity_checks
from constants import (
    NORTH, SOUTH, EAST, WEST, DIRECTION_NAMES, OPPOSITE,
    LEFT_OF, RIGHT_OF, GRID_SPACING, GRID_X0, GRID_Y0,
)


def test_basic():
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)

    n_internal = sum(
        1 for l in net.links.values()
        if not (l.is_boundary_inbound or l.is_boundary_outbound)
    )
    print(f"Intersections: {len(net.intersections)}")
    print(f"Links: {len(net.links)}")
    print(f"  Internal:          {n_internal}")
    print(f"  Boundary inbound:  {len(net.boundary_inbound)}")
    print(f"  Boundary outbound: {len(net.boundary_outbound)}")
    print(f"Demand entries: {len(demand)}")

    run_integrity_checks(net)
    return net


def test_movement_wiring_all_corners(net):
    """Exhaustively verify wiring at every corner + the center intersection."""
    print("\n--- Exhaustive movement wiring check ---")

    # For each intersection, for each approach direction,
    # verify the wired outbound links point to the correct neighbor.
    def expected_exit_neighbor(r, c, exit_dir):
        if exit_dir == NORTH: return (r - 1, c)
        if exit_dir == SOUTH: return (r + 1, c)
        if exit_dir == EAST:  return (r, c + 1)
        if exit_dir == WEST:  return (r, c - 1)
        return None

    def expected_link_id(intx, exit_dir):
        nr, nc = expected_exit_neighbor(intx.row, intx.col, exit_dir)
        if 0 <= nr <= 2 and 0 <= nc <= 2:
            return f"{intx.node_id}_{DIRECTION_NAMES[exit_dir]}_I_{nr}{nc}"
        # Boundary
        if exit_dir == NORTH: return f"BND_N{intx.col}_out"
        if exit_dir == SOUTH: return f"BND_S{intx.col}_out"
        if exit_dir == EAST:  return f"BND_E{intx.row}_out"
        if exit_dir == WEST:  return f"BND_W{intx.row}_out"
        return None

    errors = 0
    for intx in net.intersections.values():
        for appr_dir, appr in intx.approaches.items():
            heading = OPPOSITE[appr_dir]
            exp_through = expected_link_id(intx, heading)
            exp_left = expected_link_id(intx, LEFT_OF[heading])
            exp_right = expected_link_id(intx, RIGHT_OF[heading])

            if appr.out_through != exp_through:
                print(f"  [FAIL] {intx.node_id} appr-from-{DIRECTION_NAMES[appr_dir]} "
                      f"THROUGH: got {appr.out_through}, expected {exp_through}")
                errors += 1
            if appr.out_left != exp_left:
                print(f"  [FAIL] {intx.node_id} appr-from-{DIRECTION_NAMES[appr_dir]} "
                      f"LEFT: got {appr.out_left}, expected {exp_left}")
                errors += 1
            if appr.out_right != exp_right:
                print(f"  [FAIL] {intx.node_id} appr-from-{DIRECTION_NAMES[appr_dir]} "
                      f"RIGHT: got {appr.out_right}, expected {exp_right}")
                errors += 1

    assert errors == 0, f"{errors} wiring errors found"
    print(f"  All {9 * 4 * 3} movement wirings correct (9 intx x 4 appr x 3 mvmts).")


def test_every_wired_link_exists(net):
    """Every link referenced by out_L/out_T/out_R must exist in net.links."""
    print("\n--- Link existence check ---")
    missing = 0
    for intx in net.intersections.values():
        for appr_dir, appr in intx.approaches.items():
            for lbl, link_id in [("L", appr.out_left),
                                 ("T", appr.out_through),
                                 ("R", appr.out_right)]:
                if link_id not in net.links:
                    print(f"  [FAIL] {intx.node_id}/{DIRECTION_NAMES[appr_dir]}/{lbl} "
                          f"references nonexistent link {link_id}")
                    missing += 1
    assert missing == 0
    print(f"  All wired links exist in net.links.")


def test_every_inbound_link_resolves(net):
    """Every approach's inbound_link_id must resolve to a link that
    terminates at that intersection with the right downstream_approach_dir."""
    print("\n--- Inbound link resolution check ---")
    errors = 0
    for intx in net.intersections.values():
        for d, appr in intx.approaches.items():
            link = net.links.get(appr.inbound_link_id)
            if link is None:
                print(f"  [FAIL] {intx.node_id}/{DIRECTION_NAMES[d]} inbound missing")
                errors += 1
                continue
            if link.to_node != intx.node_id:
                print(f"  [FAIL] {intx.node_id}/{DIRECTION_NAMES[d]} inbound "
                      f"{link.link_id} terminates at {link.to_node}")
                errors += 1
            if link.downstream_approach_dir != d:
                print(f"  [FAIL] {intx.node_id}/{DIRECTION_NAMES[d]} inbound "
                      f"{link.link_id} has approach_dir={link.downstream_approach_dir}")
                errors += 1
    assert errors == 0
    print(f"  All 36 approach-inbound links resolve correctly.")


def test_intersection_positions(net):
    """Positions should form a clean 3x3 grid."""
    print("\n--- Intersection positions ---")
    for r in range(3):
        for c in range(3):
            intx = net.intersections[f"I_{r}{c}"]
            ex = GRID_X0 + c * GRID_SPACING
            ey = GRID_Y0 + r * GRID_SPACING
            assert intx.x == ex, f"I_{r}{c} x={intx.x}, expected {ex}"
            assert intx.y == ey, f"I_{r}{c} y={intx.y}, expected {ey}"
    print("  All 9 intersection positions correct.")


def test_boundary_directions(net):
    """Boundary links should have boundary_direction set correctly."""
    print("\n--- Boundary direction check ---")
    for link_id in net.boundary_inbound + net.boundary_outbound:
        link = net.links[link_id]
        assert link.boundary_direction is not None, \
            f"{link_id} missing boundary_direction"
        # Derive expected from name
        if "_N" in link_id: expected = NORTH
        elif "_S" in link_id: expected = SOUTH
        elif "_E" in link_id: expected = EAST
        elif "_W" in link_id: expected = WEST
        else: raise AssertionError(f"Unknown boundary naming: {link_id}")
        assert link.boundary_direction == expected, \
            f"{link_id} has boundary_direction={link.boundary_direction}, expected {expected}"
    print(f"  All 24 boundary links have correct boundary_direction.")


def test_demand_validity(net, demand):
    """Every demand entry must reference a real inbound boundary link."""
    print("\n--- Demand validity check ---")
    for link_id in demand:
        assert link_id in net.boundary_inbound, \
            f"Demand entry {link_id} is not an inbound boundary link"
    print(f"  All {len(demand)} demand entries reference valid inbound boundary links.")


def test_phase_plan_math(net):
    """Check cycle length arithmetic for every intersection."""
    print("\n--- Phase plan arithmetic ---")
    from constants import DEFAULT_CYCLE, YELLOW_TIME, ALL_RED_TIME
    expected_g = (DEFAULT_CYCLE - 4 * (YELLOW_TIME + ALL_RED_TIME)) / 4
    for intx in net.intersections.values():
        pp = intx.phase_plan
        for phase in pp.phases:
            assert abs(phase.effective_green - expected_g) < 1e-6, \
                f"{intx.node_id} phase {phase.phase_id} g={phase.effective_green}, expected {expected_g}"
            assert abs(phase.total_time - (expected_g + YELLOW_TIME + ALL_RED_TIME)) < 1e-6
        assert abs(pp.cycle_length - DEFAULT_CYCLE) < 1e-6
        assert abs(pp.total_lost_time - 16.0) < 1e-6
    print(f"  All 9 phase plans: g={expected_g}s, cycle={DEFAULT_CYCLE}s, L=16s.")


if __name__ == "__main__":
    net = test_basic()
    test_movement_wiring_all_corners(net)
    test_every_wired_link_exists(net)
    test_every_inbound_link_resolves(net)
    test_intersection_positions(net)
    test_boundary_directions(net)
    demand = load_am_peak_scenario(net)
    test_demand_validity(net, demand)
    test_phase_plan_math(net)

    print("\n========== ALL TESTS PASSED ==========")

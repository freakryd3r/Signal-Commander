"""Pygame entry point. Builds network, runs loop, renders."""

import sys
import pygame

from constants import (
    SCREEN_W, SCREEN_H, FPS, DEFAULT_CYCLE,
    DIRECTION_NAMES, SOUTH, JAM_SPACING, LANES_PER_APPROACH, GRID_SPACING,
)
from scenarios import build_3x3_network, load_am_peak_scenario
import rendering


def run_integrity_checks(net) -> None:
    """Verify the network is well-formed before entering the main loop."""
    # ---- Counts ----
    assert len(net.intersections) == 9, (
        f"Expected 9 intersections, got {len(net.intersections)}"
    )
    assert len(net.links) == 48, (
        f"Expected 48 links (24 internal + 24 boundary), got {len(net.links)}"
    )
    assert len(net.boundary_inbound) == 12, (
        f"Expected 12 inbound boundary links, got {len(net.boundary_inbound)}"
    )
    assert len(net.boundary_outbound) == 12, (
        f"Expected 12 outbound boundary links, got {len(net.boundary_outbound)}"
    )
    n_internal = sum(
        1 for l in net.links.values()
        if not (l.is_boundary_inbound or l.is_boundary_outbound)
    )
    assert n_internal == 24, (
        f"Expected 24 internal links, got {n_internal}"
    )

    # ---- Per-intersection structure ----
    for intx in net.intersections.values():
        for d, appr in intx.approaches.items():
            assert appr.inbound_link_id is not None, (
                f"{intx.node_id} approach {DIRECTION_NAMES[d]} "
                "missing inbound link"
            )
            assert appr.out_through is not None, (
                f"{intx.node_id} approach {DIRECTION_NAMES[d]} "
                "missing through exit"
            )
            assert appr.out_left is not None, (
                f"{intx.node_id} approach {DIRECTION_NAMES[d]} "
                "missing left exit"
            )
            assert appr.out_right is not None, (
                f"{intx.node_id} approach {DIRECTION_NAMES[d]} "
                "missing right exit"
            )
            assert abs(appr.p_left + appr.p_through + appr.p_right - 1.0) < 1e-6, (
                f"{intx.node_id} approach {DIRECTION_NAMES[d]} turn "
                "ratios do not sum to 1"
            )

        assert intx.phase_plan is not None, f"{intx.node_id} missing phase plan"
        assert len(intx.phase_plan.phases) == 4, (
            f"{intx.node_id} phase plan has {len(intx.phase_plan.phases)} "
            "phases, expected 4"
        )
        assert abs(intx.phase_plan.cycle_length - DEFAULT_CYCLE) < 0.1, (
            f"{intx.node_id} cycle = {intx.phase_plan.cycle_length}, "
            f"expected {DEFAULT_CYCLE}"
        )

    # ---- Storage sanity: internal link should store ~300/6.7*2 = ~89 veh ----
    expected_storage = (GRID_SPACING / JAM_SPACING) * LANES_PER_APPROACH
    sample = next(
        l for l in net.links.values()
        if not (l.is_boundary_inbound or l.is_boundary_outbound)
    )
    assert abs(sample.storage_veh - expected_storage) < 0.5, (
        f"Internal link storage = {sample.storage_veh}, "
        f"expected ~{expected_storage:.2f}"
    )

    # ---- Spot-check movement wiring at I_11 ----
    # Driver entering via I_11's SOUTH approach is heading NORTH, so:
    #   THROUGH -> I_01 (via NORTH), LEFT -> I_10 (via WEST), RIGHT -> I_12 (via EAST)
    i11 = net.intersections["I_11"]
    appr = i11.approaches[SOUTH]
    assert appr.out_through == "I_11_N_I_01", (
        f"I_11 SOUTH-approach THROUGH should be 'I_11_N_I_01', got {appr.out_through}"
    )
    assert appr.out_left == "I_11_W_I_10", (
        f"I_11 SOUTH-approach LEFT should be 'I_11_W_I_10', got {appr.out_left}"
    )
    assert appr.out_right == "I_11_E_I_12", (
        f"I_11 SOUTH-approach RIGHT should be 'I_11_E_I_12', got {appr.out_right}"
    )

    # ---- Boundary wiring spot-check at I_00 (top-left corner) ----
    # NORTH approach is boundary inbound.
    i00 = net.intersections["I_00"]
    from constants import NORTH as NORTH_DIR, WEST as WEST_DIR
    assert i00.approaches[NORTH_DIR].inbound_link_id == "BND_N0_in", (
        f"I_00 NORTH approach should be fed by BND_N0_in, got "
        f"{i00.approaches[NORTH_DIR].inbound_link_id}"
    )
    assert i00.approaches[WEST_DIR].inbound_link_id == "BND_W0_in", (
        f"I_00 WEST approach should be fed by BND_W0_in, got "
        f"{i00.approaches[WEST_DIR].inbound_link_id}"
    )

    print("All integrity checks passed.")


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("Signal Commander - Step 1")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Arial", 14)

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

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        rendering.draw_background(screen)
        rendering.draw_panels(screen)
        rendering.draw_panel_headers(screen, font)
        for link in net.links.values():
            rendering.draw_link(screen, net, link)
        for intx in net.intersections.values():
            rendering.draw_intersection(screen, intx)
        rendering.draw_labels(screen, net, font)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()

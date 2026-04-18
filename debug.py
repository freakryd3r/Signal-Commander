"""
debug.py — Debug scenarios for Signal Lord.

Each scenario function builds a specific (network, simulation) pair
for testing one feature in isolation.

Two usage patterns:

(A) Standalone headless validation (no pygame, runs in terminal):
        python debug.py
    Prints agent movement step-by-step so you can confirm the
    physics without waiting for main.py integration.

(B) Integration with main.py (Phase 2+):
        from debug import setup_debug_one_car
        network, sim = setup_debug_one_car()
    main.py uses the returned network for rendering and sim
    for stepping inside its game loop.
"""

from network import Network
from simulation import Simulation


# ============================================================
# Scenario: one car, then a second car 3 seconds later
# ============================================================

def setup_debug_one_car():
    """
    Build the standard Phase 2 debug scenario.

    Two cars, same route: west entry on row 1 → east exit on row 1.
    Car A spawns at t=0. Car B spawns at t=3.

    Returns (network, sim). Simulation is left PAUSED; caller must
    call sim.resume() to start.
    """
    network = Network(rows=3, cols=3, link_length=200)
    sim = Simulation(network, seed=42)

    # Pass terminal IDs directly to get the full route including
    # the inbound and outbound terminal links.
    route_a = network.shortest_path("T_IN_LEFT_1", "T_OUT_RIGHT_1", sim.rng)
    route_b = network.shortest_path("T_IN_LEFT_1", "T_OUT_RIGHT_1", sim.rng)

    if not route_a or not route_b:
        raise RuntimeError(
            "Debug scenario could not build a route. Terminal IDs may be wrong."
        )

    sim.schedule_spawn(spawn_time_s=0.0, route=route_a, agent_type="car")
    sim.schedule_spawn(spawn_time_s=3.0, route=route_b, agent_type="car")

    return network, sim


# ============================================================
# Headless runner — prints movement to terminal for validation
# ============================================================

def run_debug_one_car_headless(total_sim_seconds=45, print_interval_s=1.0):
    """
    Run the one-car scenario without pygame; print positions.
    Useful for confirming simulation.py works in isolation.
    """
    network, sim = setup_debug_one_car()
    sim.resume()

    # Physics step size used for headless test (1 Hz is fine for validation).
    dt = 1.0
    last_print_t = -1.0

    print("=" * 60)
    print("Debug scenario: one car t=0, one car t=3")
    print("=" * 60)

    # Show route once at the top
    route = network.shortest_path("T_IN_LEFT_1", "T_OUT_RIGHT_1", sim.rng)
    print(f"Route length: {len(route)} links, "
          f"total {sum(l.length_m for l in route):.0f} m")
    for i, link in enumerate(route):
        print(f"  [{i}] {link.from_int.id} -> {link.to_int.id}  "
              f"({link.length_m:.0f} m)")
    print()

    steps = int(total_sim_seconds / dt)
    for _ in range(steps):
        sim.step(dt)

        if sim.state.time_s - last_print_t >= print_interval_s - 1e-6:
            last_print_t = sim.state.time_s
            active = sim.get_agents()
            print(f"t={sim.state.time_s:6.1f}s  "
                  f"active={len(active):2d}  "
                  f"completed={len(sim.state.completed_trips):2d}")
            for a in active:
                link = a.current_link()
                link_label = f"{link.from_int.id}->{link.to_int.id}" if link else "N/A"
                print(f"    agent_{a.id} ({a.agent_type}): "
                      f"on {link_label}, "
                      f"pos={a.position_on_link_m:6.1f}m, "
                      f"world=({a.x_m:6.1f}, {a.y_m:6.1f})")

        # Early exit once everything has completed
        if not sim.get_agents() and sim.state.completed_trips:
            print(f"\nAll agents finished by t={sim.state.time_s:.1f}s")
            break

    print()
    print("Completed trips:")
    for trip in sim.state.completed_trips:
        print(f"  agent_{trip['agent_id']}: "
              f"{trip['origin_id']} -> {trip['dest_id']}, "
              f"travel time {trip['travel_time_s']:.1f}s")


# ============================================================
# Scenario registry (main.py will consume this via argparse later)
# ============================================================

SCENARIOS = {
    "debug_one_car": setup_debug_one_car,
}


def get_scenario(name):
    """Look up a scenario by name; returns the setup function or None."""
    return SCENARIOS.get(name)


if __name__ == "__main__":
    run_debug_one_car_headless()
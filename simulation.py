# =============================================================
# SIGNAL LORD — UNIT CONVENTIONS
# =============================================================
# Distance:  meters (m)
# Time:      seconds (s)
# Speed:     meters per second (m/s)
# Flow:      vehicles per hour (veh/hr)
# Density:   vehicles per kilometer (veh/km)
# Angles:    radians internally, degrees only at display
#
# World space: meters, used for all simulation logic.
# Screen space: pixels, used only for rendering.
# Convert with world_to_screen() and screen_to_world() helpers.
#
# DO NOT mix units. Convert at display time only.
# =============================================================

# (units header)

class Agent:
    """Base class for cars and buses."""
    def __init__(self, agent_id, route):
        self.id = agent_id
        self.route = route          # list of links
        self.position_on_link = 0.0 # meters from upstream
        self.current_link_idx = 0
        self.speed = 0.0
        self.active = True

    def step(self, dt):
        pass  # filled in later


class Signal:
    """Signal state machine for an intersection."""
    def __init__(self, intersection):
        self.intersection = intersection
        self.phase = "NS_GREEN"
        self.time_in_phase = 0.0

    def step(self, dt):
        pass  # filled in later


class Simulation:
    """Owns all agents and signals; no Pygame calls."""
    def __init__(self, network, seed=42):
        self.network = network
        self.seed = seed
        self.time = 0.0
        self.agents = []
        self.signals = {iid: Signal(i) for iid, i in network.intersections.items()}
        self.completed_trips = []
        self.denied_entry = 0

    def step(self, dt):
        self.time += dt
        for sig in self.signals.values():
            sig.step(dt)
        for agent in self.agents:
            if agent.active:
                agent.step(dt)

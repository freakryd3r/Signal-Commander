"""
simulation.py
==============================================================
SIGNAL LORD — UNIT CONVENTIONS
==============================================================
Distance:  meters (m)
Time:      seconds (s)
Speed:     meters per second (m/s)
Flow:      vehicles per hour (veh/hr)
Density:   vehicles per kilometer (veh/km)

World space: meters, used for all simulation logic.
Screen space: pixels, used only for rendering (main.py).

DO NOT mix units. Convert at display time only.
==============================================================

==============================================================
CONTRACT WITH main.py AND metrics.py — DO NOT BREAK
==============================================================
main.py calls:
  sim.step(dt)            — advance one timestep
  sim.pause()             — freeze stepping
  sim.resume()            — unfreeze stepping
  sim.reset_simulation()  — clear agents + sim state, keep network
  sim.set_speed(mult)     — fast-forward integer multiplier
  sim.get_agents()        — live list of active Agent objects
  sim.get_state()         — SimulationState (schema below)
  sim.spawn_agent(route, agent_type) — add an agent
  sim.schedule_spawn(time_s, route, agent_type) — queue a spawn

Per-agent fields exposed for rendering:
  agent.id                 — int
  agent.agent_type         — "car" or "bus"
  agent.x_m, agent.y_m     — world coordinates
  agent.heading_rad        — direction of travel
  agent.active             — bool

Per-signal fields exposed for rendering (Phase 4+):
  signal.current_phase     — one of: "NS_GREEN", "NS_YELLOW",
                             "ALL_RED", "EW_GREEN", "EW_YELLOW"
  signal.time_in_phase_s   — float seconds since phase started

SimulationState schema (metrics.py contract) — see dataclasses below.
==============================================================
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict
import math
import numpy as np

from config import (
    FREE_FLOW_SPEED,
    WARMUP_DURATION,
)

# -----------------------------------------------------------------
# Vehicle constants (simulation-internal; not user-tunable)
# -----------------------------------------------------------------
CAR_LENGTH_M = 5.0
BUS_LENGTH_M = 12.0
MIN_GAP_AT_REST_M = 2.0        # used in Phase 3 car-following
HEADWAY_TIME_S = 1.5           # used in Phase 3 car-following


# =================================================================
# STATE DATACLASSES — FROZEN SCHEMA (consumed by metrics.py)
# =================================================================
# Person C reads these. Do not rename or remove fields without a
# 3-person discussion. New fields can be ADDED at any time.
# =================================================================

@dataclass
class LinkState:
    """Per-link dynamic state. Updated each sim step."""
    link_id: str
    num_vehicles: int = 0
    density_veh_per_km: float = 0.0
    mean_speed_ms: float = 0.0


@dataclass
class IntersectionState:
    """Per-intersection dynamic state. Updated each sim step."""
    intersection_id: str

    # Signal timing snapshot (read from Signal every step)
    current_phase: str = "NS_GREEN"
    time_in_phase_s: float = 0.0
    cycle_start_time_s: float = 0.0
    cycle_length_s: float = 60.0
    green_ns_s: float = 30.0
    green_ew_s: float = 30.0
    yellow_s: float = 3.0
    all_red_s: float = 2.0

    # Full history logs — (time_s, count) tuples per approach.
    # metrics.py uses these for cumulative input-output diagrams.
    arrivals_by_approach: Dict[str, list] = field(
        default_factory=lambda: {"N": [], "S": [], "E": [], "W": []}
    )
    departures_by_approach: Dict[str, list] = field(
        default_factory=lambda: {"N": [], "S": [], "E": [], "W": []}
    )

    # Per-step deltas (reset every step)
    arrivals_this_step: Dict[str, int] = field(
        default_factory=lambda: {"N": 0, "S": 0, "E": 0, "W": 0}
    )
    departures_this_step: Dict[str, int] = field(
        default_factory=lambda: {"N": 0, "S": 0, "E": 0, "W": 0}
    )

    # Measured flows per approach, updated once per completed cycle.
    # Used by metrics.py for Webster's optimal cycle and delay.
    last_cycle_flows: Dict[str, float] = field(
        default_factory=lambda: {"N": 0.0, "S": 0.0, "E": 0.0, "W": 0.0}
    )

    # Current queue length per approach
    queue_lengths: Dict[str, int] = field(
        default_factory=lambda: {"N": 0, "S": 0, "E": 0, "W": 0}
    )
    # Pending timing changes (applied at next NS_GREEN boundary in Phase 4+).
    # metrics.py sets these when user clicks "Apply Webster". simulation.py
    # swaps them in when the signal cycles back to phase 0.
    pending_cycle_length_s: Optional[float] = None
    pending_green_ns_s: Optional[float] = None
    pending_green_ew_s: Optional[float] = None

@dataclass
class SimulationState:
    """Top-level simulation state. Returned by sim.get_state()."""
    time_s: float = 0.0
    dt_s: float = 1.0
    sim_running: bool = False
    warmup_complete: bool = False

    # Live mutable lists — read-only by convention (contract w/ metrics.py)
    agents: list = field(default_factory=list)
    completed_trips: list = field(default_factory=list)
    completed_trips_this_step: list = field(default_factory=list)

    denied_entries_total: int = 0
    denied_entries_this_step: int = 0

    intersections: Dict[str, IntersectionState] = field(default_factory=dict)
    links: Dict[str, LinkState] = field(default_factory=dict)


# =================================================================
# AGENT
# =================================================================

class Agent:
    """
    A vehicle (car or bus) traversing the network.

    Phase 2: moves at free flow speed; ignores signals and other agents.
    Phase 3: car-following gap logic added.
    Phase 5: signal compliance (red → stop).
    """

    def __init__(self, agent_id, agent_type, route, spawn_time_s):
        # Identity
        self.id = agent_id
        self.agent_type = agent_type  # "car" or "bus"

        # Route: list of Link objects traversed in order.
        # For origin→destination traversal:
        #   route[0]       = inbound terminal link
        #   route[1..n-2]  = interior links
        #   route[n-1]     = outbound terminal link
        self.route = route

        # Position along the route
        self.current_link_idx = 0
        self.position_on_link_m = 0.0
        self.speed_ms = FREE_FLOW_SPEED

        # World coordinates (derived; refreshed each step)
        self.x_m = 0.0
        self.y_m = 0.0
        self.heading_rad = 0.0

        # Lifecycle
        self.active = True
        self.spawn_time_s = spawn_time_s
        self.completion_time_s: Optional[float] = None

        # Origin/destination node IDs for trip records
        self.origin_id = route[0].from_int.id if route else None
        self.dest_id = route[-1].to_int.id if route else None

        # Initialize world position from route[0] start
        self._update_world_position()

    @property
    def length_m(self):
        """Physical vehicle length for car-following (Phase 3)."""
        return BUS_LENGTH_M if self.agent_type == "bus" else CAR_LENGTH_M

    def current_link(self):
        """The link the agent is currently traversing, or None if done."""
        if 0 <= self.current_link_idx < len(self.route):
            return self.route[self.current_link_idx]
        return None

    def _update_world_position(self):
        """Interpolate x_m, y_m, heading from current link + position."""
        link = self.current_link()
        if link is None or link.length_m <= 0:
            return

        frac = self.position_on_link_m / link.length_m
        frac = max(0.0, min(1.0, frac))

        self.x_m = link.from_int.x_m + frac * (link.to_int.x_m - link.from_int.x_m)
        self.y_m = link.from_int.y_m + frac * (link.to_int.y_m - link.from_int.y_m)

        dx = link.to_int.x_m - link.from_int.x_m
        dy = link.to_int.y_m - link.from_int.y_m
        self.heading_rad = math.atan2(dy, dx)

    def step(self, dt):
        """
        Advance one physics timestep.

        Phase 2: pure free-flow motion. No gap checking, no signals.
        """
        if not self.active:
            return

        # Advance along current link
        distance = self.speed_ms * dt
        self.position_on_link_m += distance

        # Jump to next link(s) if we overran. The `while` handles
        # edge cases where dt is large enough to cross multiple links
        # in a single tick (shouldn't happen at realistic dt, but safe).
        while (
            self.current_link() is not None
            and self.position_on_link_m >= self.current_link().length_m
            and self.current_link_idx < len(self.route) - 1
        ):
            excess = self.position_on_link_m - self.current_link().length_m
            self.current_link_idx += 1
            self.position_on_link_m = excess

        # If we've reached the end of the final link, deactivate.
        if self.current_link_idx == len(self.route) - 1:
            last = self.current_link()
            if last is not None and self.position_on_link_m >= last.length_m:
                self.active = False
                return

        self._update_world_position()

    def __repr__(self):
        return (
            f"Agent(id={self.id}, type={self.agent_type}, "
            f"link={self.current_link_idx}/{len(self.route)}, "
            f"pos={self.position_on_link_m:.1f}m, active={self.active})"
        )


# =================================================================
# SIGNAL (Phase 2 stub; Phase 4 implements state machine)
# =================================================================

class Signal:
    """
    Signal state machine for one intersection.

    Phase 2: stub. Always NS_GREEN, never transitions.
    Phase 4: implements full cycle: NS_GREEN → NS_YELLOW → ALL_RED
                                    → EW_GREEN → EW_YELLOW → ALL_RED → loop.
    """

    def __init__(self, intersection):
        self.intersection = intersection
        self.current_phase = "NS_GREEN"
        self.time_in_phase_s = 0.0
        self.cycle_start_time_s = 0.0

    def step(self, dt):
        # Phase 2: accumulate time only; no transitions.
        self.time_in_phase_s += dt


# =================================================================
# SIMULATION — owner of time, agents, signals, and state
# =================================================================

class Simulation:
    """
    Owns all simulation state. Pygame-free. Called by main.py.

    Lifecycle:
      sim = Simulation(network, seed=42)
      sim.schedule_spawn(0.0, route, "car")
      sim.resume()
      while running:
          sim.step(dt)
    """

    def __init__(self, network, seed=42):
        self.network = network
        self.seed = seed
        self.rng = np.random.default_rng(seed)

        # Create the state bag and keep it alive for the whole run.
        self.state = SimulationState()

        # Alias for readability — same list object, two names.
        self.agents = self.state.agents

        # Agent ID generator
        self._next_agent_id = 0

        # Scheduled-spawn queue: list of (spawn_time_s, route, agent_type).
        # Kept sorted by spawn_time_s.
        self._scheduled_spawns: List[tuple] = []

        # Create signal + intersection state for every real intersection.
        self.signals: Dict[str, Signal] = {}
        for inter in network.intersections:
            self.signals[inter.id] = Signal(inter)
            self.state.intersections[inter.id] = IntersectionState(
                intersection_id=inter.id,
                cycle_length_s=float(inter.cycle_length),
                green_ns_s=float(inter.green_ns),
                green_ew_s=float(inter.green_ew),
            )

        # Create link state for every link (interior + terminal).
        for link in network.get_all_links():
            self.state.links[link.id] = LinkState(link_id=link.id)

        # Fast-forward integer multiplier. main.py decides how many
        # step() calls happen per rendered frame based on this.
        self.speed_multiplier = 1

    # ----------------- Control API (called by main.py) -----------------

    def pause(self):
        self.state.sim_running = False

    def resume(self):
        self.state.sim_running = True

    def set_speed(self, multiplier):
        self.speed_multiplier = max(1, int(multiplier))

    def reset_simulation(self):
        """Clear all dynamic state; keep network config intact."""
        self.agents.clear()
        self._next_agent_id = 0
        self._scheduled_spawns.clear()

        self.state.time_s = 0.0
        self.state.sim_running = False
        self.state.warmup_complete = False
        self.state.completed_trips.clear()
        self.state.completed_trips_this_step.clear()
        self.state.denied_entries_total = 0
        self.state.denied_entries_this_step = 0

        self.rng = np.random.default_rng(self.seed)

        # Reset signals
        for sig in self.signals.values():
            sig.current_phase = "NS_GREEN"
            sig.time_in_phase_s = 0.0
            sig.cycle_start_time_s = 0.0

        # Reset intersection state
        for istate in self.state.intersections.values():
            istate.current_phase = "NS_GREEN"
            istate.time_in_phase_s = 0.0
            istate.cycle_start_time_s = 0.0
            for d in ("N", "S", "E", "W"):
                istate.arrivals_by_approach[d].clear()
                istate.departures_by_approach[d].clear()
                istate.arrivals_this_step[d] = 0
                istate.departures_this_step[d] = 0
                istate.last_cycle_flows[d] = 0.0
                istate.queue_lengths[d] = 0

        # Reset link state
        for lstate in self.state.links.values():
            lstate.num_vehicles = 0
            lstate.density_veh_per_km = 0.0
            lstate.mean_speed_ms = 0.0

    # ----------------- Read API -----------------

    def get_agents(self):
        """Return only active agents."""
        return [a for a in self.agents if a.active]

    def get_state(self):
        """Return the live SimulationState (mutable — read-only by convention)."""
        return self.state

    # ----------------- Spawn API -----------------

    def spawn_agent(self, route, agent_type="car"):
        """Create and activate an agent immediately. Returns the Agent."""
        if not route:
            return None
        agent = Agent(
            agent_id=self._next_agent_id,
            agent_type=agent_type,
            route=route,
            spawn_time_s=self.state.time_s,
        )
        self._next_agent_id += 1
        self.agents.append(agent)
        return agent

    def schedule_spawn(self, spawn_time_s, route, agent_type="car"):
        """Queue a spawn to happen when sim.time_s reaches spawn_time_s."""
        self._scheduled_spawns.append((spawn_time_s, route, agent_type))
        self._scheduled_spawns.sort(key=lambda t: t[0])

    # ----------------- Main step -----------------

    def step(self, dt):
        """
        Advance simulation by dt seconds.

        Order:
          1. Clear per-step counters.
          2. Process any scheduled spawns whose time has come.
          3. Step signals.
          4. Step agents. Track completions.
          5. Refresh derived link state (densities, speeds).
        """
        if not self.state.sim_running:
            return

        self.state.dt_s = dt
        self.state.time_s += dt
        self.state.warmup_complete = self.state.time_s >= WARMUP_DURATION

        # 1. Reset per-step counters
        self.state.completed_trips_this_step.clear()
        self.state.denied_entries_this_step = 0
        for istate in self.state.intersections.values():
            for d in ("N", "S", "E", "W"):
                istate.arrivals_this_step[d] = 0
                istate.departures_this_step[d] = 0

        # 2. Process scheduled spawns
        while self._scheduled_spawns and self._scheduled_spawns[0][0] <= self.state.time_s:
            _, route, agent_type = self._scheduled_spawns.pop(0)
            self.spawn_agent(route, agent_type)

        # 3. Step signals; mirror their state into IntersectionState for metrics.py
        for sig in self.signals.values():
            sig.step(dt)
            istate = self.state.intersections[sig.intersection.id]
            istate.current_phase = sig.current_phase
            istate.time_in_phase_s = sig.time_in_phase_s
            istate.cycle_start_time_s = sig.cycle_start_time_s

        # 4. Step agents; record completions
        for agent in self.agents:
            was_active = agent.active
            agent.step(dt)
            if was_active and not agent.active:
                agent.completion_time_s = self.state.time_s
                trip = {
                    "agent_id": agent.id,
                    "agent_type": agent.agent_type,
                    "travel_time_s": self.state.time_s - agent.spawn_time_s,
                    "spawn_time_s": agent.spawn_time_s,
                    "origin_id": agent.origin_id,
                    "dest_id": agent.dest_id,
                }
                self.state.completed_trips.append(trip)
                self.state.completed_trips_this_step.append(trip)

        # 5. Refresh per-link dynamic state
        self._update_link_states()

    def _update_link_states(self):
        """Count vehicles per link and compute density + mean speed."""
        # Zero out
        for lstate in self.state.links.values():
            lstate.num_vehicles = 0
            lstate.mean_speed_ms = 0.0

        # Accumulate
        speed_sum: Dict[str, float] = {}
        for agent in self.agents:
            if not agent.active:
                continue
            link = agent.current_link()
            if link is None:
                continue
            lstate = self.state.links.get(link.id)
            if lstate is None:
                continue
            lstate.num_vehicles += 1
            speed_sum[link.id] = speed_sum.get(link.id, 0.0) + agent.speed_ms

        # Finalize density + mean speed
        for link_id, lstate in self.state.links.items():
            link = self.network.get_link_by_id(link_id)
            if link is None or link.length_m <= 0:
                continue
            length_km = link.length_m / 1000.0
            lstate.density_veh_per_km = lstate.num_vehicles / length_km
            if lstate.num_vehicles > 0:
                lstate.mean_speed_ms = speed_sum.get(link_id, 0.0) / lstate.num_vehicles
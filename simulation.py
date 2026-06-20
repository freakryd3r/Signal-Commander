"""
simulation.py
==============================================================
SIGNAL Commander — UNIT CONVENTIONS
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
# Signal phase order + default durations (per-intersection overrides live on
# the Intersection object: cycle_length, green_ns, green_ew).
YELLOW_DURATION_S = 3.0
ALL_RED_DURATION_S = 2.0
# Position of the stop line on each approach link, measured upstream of
# the intersection center. Agents decelerate to stop here on red.
STOP_LINE_OFFSET_M = 5.0

# Minimum speed below which we consider an agent "stopped" (for queue
# detection in metrics.py and for startup-lost-time logic in Phase 6).
STOPPED_SPEED_THRESHOLD_MS = 0.5
DRIVER_REACTION_TIME_S = 1.0
QUEUE_DETECTION_ZONE_M = 50.0
SIM_DURATION_S = 3600.0 
VIRTUAL_QUEUE_CAP = 50
SOURCE_ENTRY_MIN_GAP_M = 15.0

# Phase sequence — signals cycle in this exact order.
PHASE_SEQUENCE = [
    "NS_GREEN",
    "NS_YELLOW",
    "ALL_RED_1",
    "EW_GREEN",
    "EW_YELLOW",
    "ALL_RED_2",
]

# =================================================================
# STATE DATACLASSES — FROZEN SCHEMA (consumed by metrics.py)
# =================================================================
# Person C reads these. Do not rename or remove fields without a
# 3-person discussion. New fields can be ADDED at any time.
# =================================================================

def _approach_direction_for_link(link):
    """
    Given a link traveling into an intersection, return the approach direction
    as seen from that intersection.

    A link going east→west (from_x > to_x) approaches from the east,
    so the downstream intersection sees traffic from its "E" approach.

    Returns one of "N", "S", "E", "W", or None if the link is neither
    horizontal nor vertical (shouldn't happen on a grid).
    """
    dx = link.to_int.x_m - link.from_int.x_m
    dy = link.to_int.y_m - link.from_int.y_m

    # Horizontal movement (dominant east-west component)
    if abs(dx) > abs(dy):
        # Traffic traveling +x (east) arrives from the west side
        return "W" if dx > 0 else "E"
    else:
        # Traffic traveling +y (south in screen coords) arrives from the north
        return "N" if dy > 0 else "S"

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

    # Per-cycle flow accumulation (Phase 7).
    # Cleared on entering NS_GREEN. At the start of NS_GREEN we convert
    # the previous cycle's accumulated counts to veh/hr and snapshot them.
    cycle_departures_accum: Dict[str, int] = field(
        default_factory=lambda: {"N": 0, "S": 0, "E": 0, "W": 0}
    )

@dataclass
class SimulationState:
    """Top-level simulation state. Returned by sim.get_state()."""
    time_s: float = 0.0
    dt_s: float = 1.0
    sim_running: bool = False
    warmup_complete: bool = False
    sim_completed: bool = False

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

        self.was_stopped = False
        self.free_to_move_at_s = None

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
        Advance position by (speed_ms * dt). Speed is set by the
        simulation's car-following rule before this is called.

        Phase 3: pure kinematic update; speed already reflects gap to leader.
        """
        if not self.active:
            return

        distance = self.speed_ms * dt
        self.position_on_link_m += distance

        # Advance across link boundaries if we overran.
        while (
            self.current_link() is not None
            and self.position_on_link_m >= self.current_link().length_m
            and self.current_link_idx < len(self.route) - 1
        ):
            excess = self.position_on_link_m - self.current_link().length_m
            self.current_link_idx += 1
            self.position_on_link_m = excess

        # If past the end of the last link, deactivate.
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
    Traffic signal state machine for one intersection.

    Phase 4: cycles NS_GREEN → NS_YELLOW → ALL_RED_1 → EW_GREEN
                    → EW_YELLOW → ALL_RED_2 → repeat.

    Durations come from the Intersection's cycle_length, green_ns, green_ew,
    plus module-level YELLOW_DURATION_S / ALL_RED_DURATION_S.

    Pending timing changes (set by main.py or metrics.py via
    intersection_state.pending_*) are applied at the start of NS_GREEN
    so a cycle is never interrupted mid-phase.
    """

    def __init__(self, intersection):
        self.intersection = intersection
        # Offset delays this signal's first phase by `intersection.offset` seconds
        # relative to sim start. Before offset elapses, signal is in "pre-start"
        # (effectively all-red with time accumulating toward the offset).
        self.phase_idx = 0
        self.current_phase = PHASE_SEQUENCE[0]
        self.time_in_phase_s = 0.0
        self.cycle_start_time_s = 0.0
        # Pre-start state: before first phase begins at t = intersection.offset.
        self.waiting_for_offset = True

    def _phase_duration(self):
        """Duration of the current phase in seconds, based on intersection timing."""
        phase = self.current_phase
        inter = self.intersection
        if phase == "NS_GREEN":
            return float(inter.green_ns)
        if phase == "EW_GREEN":
            return float(inter.green_ew)
        if phase in ("NS_YELLOW", "EW_YELLOW"):
            return YELLOW_DURATION_S
        if phase in ("ALL_RED_1", "ALL_RED_2"):
            return ALL_RED_DURATION_S
        return 0.0

    def _snapshot_cycle_flows(self, istate, sim_time_s):
        """
        At the NS_GREEN boundary, convert the just-completed cycle's
        accumulated departures to veh/hr and store them as last_cycle_flows.
        Then reset the accumulator for the upcoming cycle.

        Uses the actual cycle duration (sim_time_s - cycle_start_time_s)
        so the conversion is accurate even if cycle length was changed.
        """
        cycle_duration = sim_time_s - istate.cycle_start_time_s
        if cycle_duration <= 0:
            # First cycle; nothing to snapshot
            for d in ("N", "S", "E", "W"):
                istate.cycle_departures_accum[d] = 0
            return

        for d in ("N", "S", "E", "W"):
            count = istate.cycle_departures_accum[d]
            flow_vph = (count / cycle_duration) * 3600.0
            istate.last_cycle_flows[d] = flow_vph
            istate.cycle_departures_accum[d] = 0

    def _apply_pending_timing(self, istate, sim_time_s):
        """
        Swap in any queued cycle_length / green_ns / green_ew from the
        IntersectionState. Called only at the NS_GREEN boundary so the
        signal never stutters mid-cycle.
        """
        if istate.pending_cycle_length_s is not None:
            self.intersection.cycle_length = istate.pending_cycle_length_s
            istate.cycle_length_s = istate.pending_cycle_length_s
            istate.pending_cycle_length_s = None

        if istate.pending_green_ns_s is not None:
            self.intersection.green_ns = istate.pending_green_ns_s
            istate.green_ns_s = istate.pending_green_ns_s
            istate.pending_green_ns_s = None

        if istate.pending_green_ew_s is not None:
            self.intersection.green_ew = istate.pending_green_ew_s
            istate.green_ew_s = istate.pending_green_ew_s
            istate.pending_green_ew_s = None

    def step(self, dt, sim_time_s, istate):
        """
        Advance the signal state machine by dt seconds.

        If still within the pre-start offset period, accumulate time and
        show all-red until offset elapses. Then start the normal cycle.
        """
        # Pre-start gate: hold at all-red until offset is reached
        if self.waiting_for_offset:
            self.time_in_phase_s += dt
            if self.time_in_phase_s >= self.intersection.offset:
                # Offset elapsed — enter first phase (NS_GREEN) and reset
                self.waiting_for_offset = False
                self.phase_idx = 0
                self.current_phase = PHASE_SEQUENCE[0]
                self.time_in_phase_s = 0.0
                self.cycle_start_time_s = sim_time_s
                # Mirror to state
                istate.current_phase = self.current_phase
                istate.time_in_phase_s = 0.0
                istate.cycle_start_time_s = self.cycle_start_time_s
            else:
                # Display as all-red during pre-start (so metrics.py sees a
                # red-like state; agents don't discharge through it)
                istate.current_phase = "ALL_RED_1"
                istate.time_in_phase_s = self.time_in_phase_s
            return

        self.time_in_phase_s += dt

        duration = self._phase_duration()
        if self.time_in_phase_s < duration:
            return

        # Time to transition
        self.phase_idx = (self.phase_idx + 1) % len(PHASE_SEQUENCE)
        self.current_phase = PHASE_SEQUENCE[self.phase_idx]
        self.time_in_phase_s = 0.0

        if self.current_phase == "NS_GREEN":
            self._snapshot_cycle_flows(istate, sim_time_s)
            self.cycle_start_time_s = sim_time_s
            self._apply_pending_timing(istate, sim_time_s)

    def is_green_for(self, approach):
        if self.waiting_for_offset:
            return False
        phase = self.current_phase
        if phase == "NS_GREEN":
            return approach in ("N", "S")
        if phase == "EW_GREEN":
            return approach in ("E", "W")
        return False

    def is_yellow_for(self, approach):
        if self.waiting_for_offset:
            return False
        phase = self.current_phase
        if phase == "NS_YELLOW":
            return approach in ("N", "S")
        if phase == "EW_YELLOW":
            return approach in ("E", "W")
        return False

    def is_red_for(self, approach):
        # Everything that's not green or yellow is red (including all-red phases).
        return not (self.is_green_for(approach) or self.is_yellow_for(approach))


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

        # OD demand: od_matrix[origin_int_id][dest_int_id] = veh/hr
        # Empty by default. Use set_od_matrix() or set_demand_preset() to populate.
        self.od_matrix: Dict[str, Dict[str, float]] = {}
        self.demand_scale = 1.0

        # Virtual queues per origin intersection (agents waiting to spawn)
        # Keyed by intersection id; value is count of agents pending.
        self._virtual_queue: Dict[str, int] = {}
        for inter in network.intersections:
            if network.is_perimeter(inter.id):
                self._virtual_queue[inter.id] = 0

        # Cache reachable origin→destination pairs so we don't compute
        # shortest paths for impossible pairs every tick.
        self._valid_od_pairs = None  # populated on first use

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
        self.state.sim_completed = False
        self.state.completed_trips.clear()
        self.state.completed_trips_this_step.clear()
        self.state.denied_entries_total = 0
        self.state.denied_entries_this_step = 0

        self.rng = np.random.default_rng(self.seed)

        # Reset signals — each goes back to pre-start, honoring its offset
        for sig in self.signals.values():
            sig.current_phase = "NS_GREEN"
            sig.time_in_phase_s = 0.0
            sig.cycle_start_time_s = 0.0
            sig.waiting_for_offset = True
            sig.phase_idx = 0

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

    # ----------------- OD demand management (Phase 7) -----------------

    def set_od_matrix(self, od_matrix):
        """
        Replace the OD matrix.
          od_matrix: dict of dicts, od_matrix[origin_id][dest_id] = veh/hr
        Only perimeter intersections should appear as keys. Values
        with demand <= 0 are treated as no demand.
        """
        self.od_matrix = {}
        for origin_id, dests in od_matrix.items():
            if not self.network.is_perimeter(origin_id):
                continue
            self.od_matrix[origin_id] = {}
            for dest_id, rate in dests.items():
                if not self.network.is_perimeter(dest_id):
                    continue
                if origin_id == dest_id:
                    continue
                if rate > 0:
                    self.od_matrix[origin_id][dest_id] = float(rate)
        self._valid_od_pairs = None  # invalidate cache

    def set_demand_scale(self, scale):
        """Set the master demand multiplier. Typical range: 0.0 to 2.0."""
        self.demand_scale = max(0.0, float(scale))

    def _source_has_room(self, origin_id):
        """
        Check whether the source terminal for this origin has physical
        room for a new agent. Inspect the inbound terminal link — if any
        existing agent is within SOURCE_ENTRY_MIN_GAP_M of the terminal
        start, return False.
        """
        # Find any inbound terminal link attached to this intersection.
        # Any one is fine — if the spawner picks a different terminal
        # link, we'll re-check per spawn.
        inbound_links = [
            lnk for lnk in self.network.terminal_links
            if lnk.in_or_out == "in" and lnk.to_int.id == origin_id
        ]
        if not inbound_links:
            return False

        # Check every agent on any inbound terminal link for this intersection
        for lnk in inbound_links:
            for agent in self.agents:
                if not agent.active:
                    continue
                if agent.current_link() is None:
                    continue
                if agent.current_link().id == lnk.id:
                    if agent.position_on_link_m < SOURCE_ENTRY_MIN_GAP_M:
                        return False
        return True

    def _try_spawn_od(self, origin_id, dest_id):
        """
        Attempt to spawn an agent from origin to destination.
        Returns True if spawned, False if queued virtually or denied.

        Route construction:
          [inbound_terminal_link, interior_links..., outbound_terminal_link]
        Agent appears at position 0 on the inbound terminal link, outside
        the grid perimeter. Exits at the end of the outbound terminal link.
        """
        if not self._source_has_room(origin_id):
            self._virtual_queue[origin_id] = self._virtual_queue.get(origin_id, 0) + 1
            if self._virtual_queue[origin_id] > VIRTUAL_QUEUE_CAP:
                self._virtual_queue[origin_id] = VIRTUAL_QUEUE_CAP
                self.state.denied_entries_total += 1
                self.state.denied_entries_this_step += 1
            return False

        # Build the full route with terminal links at both ends.
        interior = self.network.shortest_path(origin_id, dest_id, self.rng)
        if not interior:
            return False

        # Look up the terminal links using the default-side logic
        # already built into network.shortest_path.
        # Pick terminal sides. Corner intersections have 2 valid sides;
        # pick randomly for spatial balance. Middle-edge intersections
        # have only 1 side, which is picked deterministically.
        origin_side = self._pick_random_terminal_side(origin_id, "in")
        dest_side = self._pick_random_terminal_side(dest_id, "out")
        if origin_side is None or dest_side is None:
            return False

        inbound = self.network.get_terminal_link(origin_id, origin_side, "in")
        outbound = self.network.get_terminal_link(dest_id, dest_side, "out")
        if inbound is None or outbound is None:
            return False

        route = [inbound] + interior + [outbound]
        self.spawn_agent(route, agent_type="car")
        return True

    def _available_terminal_sides(self, intersection_id, in_or_out):
        """
        Return list of valid terminal sides ("N", "S", "E", "W") for this
        perimeter intersection. Corner intersections return 2 sides;
        middle-edge intersections return 1.
        """
        sides = []
        for side in ("N", "S", "E", "W"):
            link = self.network.get_terminal_link(intersection_id, side, in_or_out)
            if link is not None:
                sides.append(side)
        return sides

    def _pick_random_terminal_side(self, intersection_id, in_or_out):
        """
        Pick a terminal side (randomly for corners, deterministically for
        middle-edge) using this simulation's RNG so results are reproducible.
        """
        sides = self._available_terminal_sides(intersection_id, in_or_out)
        if not sides:
            return None
        if len(sides) == 1:
            return sides[0]
        # Multiple sides: pick with RNG
        idx = int(self.rng.integers(0, len(sides)))
        return sides[idx]

    def _drain_virtual_queues(self):
        """
        Each tick, try to physically spawn one pending agent per source
        with a non-empty virtual queue. We pick the destination randomly
        weighted by OD demand for this origin.
        """
        for origin_id, pending in list(self._virtual_queue.items()):
            if pending <= 0:
                continue
            if not self._source_has_room(origin_id):
                continue

            # Pick a destination weighted by OD demand from this origin
            dests = self.od_matrix.get(origin_id, {})
            if not dests:
                # No demand from this origin; leave virtual queue alone
                # (would be odd — it shouldn't have queued without demand — but safe)
                continue

            dest_ids = list(dests.keys())
            weights = np.array([dests[d] for d in dest_ids], dtype=float)
            if weights.sum() <= 0:
                continue
            weights /= weights.sum()
            dest_id = self.rng.choice(dest_ids, p=weights)

            interior = self.network.shortest_path(origin_id, dest_id, self.rng)
            if not interior:
                continue

            origin_side = self._pick_random_terminal_side(origin_id, "in")
            dest_side = self._pick_random_terminal_side(dest_id, "out")
            if origin_side is None or dest_side is None:
                continue

            inbound = self.network.get_terminal_link(origin_id, origin_side, "in")
            outbound = self.network.get_terminal_link(dest_id, dest_side, "out")
            if inbound is None or outbound is None:
                continue

            route = [inbound] + interior + [outbound]
            self.spawn_agent(route, agent_type="car")
            self._virtual_queue[origin_id] = pending - 1

    def _generate_poisson_arrivals(self, dt):
        """
        For every (origin, destination) in the OD matrix, draw a Bernoulli
        per tick with probability = rate_per_s × dt × demand_scale. If it
        fires, try to spawn.
        """
        if self.demand_scale == 0.0:
            return

        # Collect inbound terminal links with positive inflow
        active_terminals = [
            lnk for lnk in self.network.terminal_links
            if lnk.in_or_out == "in" and lnk.inflow_vph > 0
        ]

        # If user hasn't set any inflows, fall back to OD matrix
        if not active_terminals:
            if not self.od_matrix:
                return
            for origin_id, dests in self.od_matrix.items():
                for dest_id, rate_vph in dests.items():
                    rate_per_s = rate_vph / 3600.0
                    p = rate_per_s * dt * self.demand_scale
                    p = min(p, 1.0)
                    if self.rng.random() < p:
                        self._try_spawn_od(origin_id, dest_id)
            return

        # Per-terminal Poisson spawning with uniform destination selection
        perimeter_ids = [
            inter.id for inter in self.network.intersections
            if self.network.is_perimeter(inter.id)
        ]

        for inbound_link in active_terminals:
            origin_id = inbound_link.to_int.id  # perimeter intersection
            rate_per_s = inbound_link.inflow_vph / 3600.0
            p = rate_per_s * dt * self.demand_scale
            p = min(p, 1.0)
            if self.rng.random() < p:
                # Pick a destination uniformly from other perimeter intersections
                candidates = [iid for iid in perimeter_ids if iid != origin_id]
                if not candidates:
                    continue
                dest_id = candidates[int(self.rng.integers(0, len(candidates)))]
                self._try_spawn_od(origin_id, dest_id)

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
        if self.state.sim_completed:
            return

        self.state.dt_s = dt
        self.state.time_s += dt
        self.state.warmup_complete = self.state.time_s >= WARMUP_DURATION

        # Check completion AFTER advancing time so the final step runs
        if self.state.time_s >= SIM_DURATION_S:
            self.state.sim_completed = True
            self.state.sim_running = False
            return

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
        # 2b. Generate Poisson OD arrivals (Phase 7)
        self._generate_poisson_arrivals(dt)

        # 2c. Attempt to drain any virtual queues that are pending
        self._drain_virtual_queues()

        # 3. Step signals; mirror their state into IntersectionState for metrics.py
        for sig in self.signals.values():
            istate = self.state.intersections[sig.intersection.id]
            sig.step(dt, self.state.time_s, istate)
            istate.current_phase = sig.current_phase
            istate.time_in_phase_s = sig.time_in_phase_s
            istate.cycle_start_time_s = sig.cycle_start_time_s

        # 4. Determine each agent's speed, applying:
        #    (a) car-following (Phase 3)
        #    (b) signal compliance (Phase 5)
        #    (c) startup lost time on release from stop (Phase 6)
        for agent in self.agents:
            if not agent.active:
                continue

            # (a) car-following constraint
            _leader, gap_m = self._find_leader(agent)

            if gap_m == float("inf"):
                cf_speed = FREE_FLOW_SPEED
            else:
                cf_speed = max(0.0, (gap_m - MIN_GAP_AT_REST_M) / HEADWAY_TIME_S)
                cf_speed = min(FREE_FLOW_SPEED, cf_speed)

            # (b) signal constraint
            sig_speed = self._signal_constrained_speed(agent)

            # Raw speed before reaction-time check
            raw_speed = min(cf_speed, sig_speed)

            # (c) startup lost time: if we're currently stopped AND the raw
            # speed says "you can move now," hold still for DRIVER_REACTION_TIME_S
            # to simulate driver reaction.
            if agent.was_stopped:
                if raw_speed > STOPPED_SPEED_THRESHOLD_MS:
                    # This is the moment we became free to move
                    if agent.free_to_move_at_s is None:
                        agent.free_to_move_at_s = self.state.time_s
                    # Check if reaction time has elapsed
                    elapsed = self.state.time_s - agent.free_to_move_at_s
                    if elapsed < DRIVER_REACTION_TIME_S:
                        raw_speed = 0.0  # still reacting
                    else:
                        # Reaction done; release and clear the flags
                        agent.was_stopped = False
                        agent.free_to_move_at_s = None
                else:
                    # Still stopped; clear pending release timer if there was one
                    agent.free_to_move_at_s = None

            # Update stop tracking for next tick
            if raw_speed <= STOPPED_SPEED_THRESHOLD_MS:
                agent.was_stopped = True
            # (if raw_speed > threshold and was_stopped was True, the
            # reaction-time machinery above handled it)

            agent.speed_ms = raw_speed

        # 5. Advance each agent by its computed speed; record completions
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

        # 6. Refresh per-link dynamic state
        self._update_link_states()

        # 7. Per-intersection measurements (queue lengths, stop-line crossings)
        self._update_intersection_measurements()

    # ----------------- Car-following helpers (Phase 3) -----------------

    def _find_leader(self, agent):
        """
        Return (leader_agent, gap_m) for the agent directly ahead of `agent`
        on its route, or (None, inf) if no leader is visible.

        Search strategy:
          1. Check same link — closest active agent ahead on the same link.
          2. If none, check the next link in the route — closest active agent
             on route[current_link_idx + 1], distance measured as
             (remaining distance on current link) + (leader's position on next link).

        Only looks one link ahead. Good enough: agents travel at most
        ~15 m/s and our links are ≥100 m, so a leader is almost always
        on the current or next link within one tick's notice.
        """
        my_link = agent.current_link()
        if my_link is None:
            return None, float("inf")

        best_leader = None
        best_gap = float("inf")

        # 1. Leaders on the same link, ahead of me
        for other in self.agents:
            if other is agent or not other.active:
                continue
            other_link = other.current_link()
            if other_link is None or other_link.id != my_link.id:
                continue
            if other.position_on_link_m <= agent.position_on_link_m:
                continue  # behind me, ignore
            # Bumper-to-bumper gap: leader's tail minus my nose
            gap = (other.position_on_link_m - other.length_m) - agent.position_on_link_m
            if gap < best_gap:
                best_gap = gap
                best_leader = other

        if best_leader is not None:
            return best_leader, max(best_gap, 0.0)

        # 2. No same-link leader; check the next link in my route
        if agent.current_link_idx + 1 >= len(agent.route):
            return None, float("inf")

        next_link = agent.route[agent.current_link_idx + 1]
        remaining_on_current = my_link.length_m - agent.position_on_link_m

        for other in self.agents:
            if other is agent or not other.active:
                continue
            other_link = other.current_link()
            if other_link is None or other_link.id != next_link.id:
                continue
            # Gap spans two links: remaining on current + leader's pos on next
            gap = remaining_on_current + (other.position_on_link_m - other.length_m)
            if gap < best_gap:
                best_gap = gap
                best_leader = other

        return best_leader, max(best_gap, 0.0) if best_leader is not None else float("inf")

    def _signal_constrained_speed(self, agent):
        """
        Return the maximum speed this agent is allowed by the next
        downstream signal, or FREE_FLOW_SPEED if no signal applies.

        Stop line is STOP_LINE_OFFSET_M upstream of the intersection center.
        The signal this agent obeys is the one at link.to_int — only applies
        if to_int is a real intersection (not a terminal).
        """
        link = agent.current_link()
        if link is None:
            return FREE_FLOW_SPEED

        # No signal compliance on outbound terminal links (agent is leaving)
        # or if downstream is not a real intersection.
        downstream = link.to_int
        if downstream.is_terminal:
            return FREE_FLOW_SPEED

        signal = self.signals.get(downstream.id)
        if signal is None:
            return FREE_FLOW_SPEED

        approach = _approach_direction_for_link(link)
        if approach is None:
            return FREE_FLOW_SPEED

        # Distance from agent's nose to the stop line
        stop_line_pos = link.length_m - STOP_LINE_OFFSET_M
        dist_to_stop = stop_line_pos - agent.position_on_link_m

        # If we're already past the stop line, the signal doesn't restrict us
        # (we're in the middle of clearing the intersection).
        if dist_to_stop <= 0:
            return FREE_FLOW_SPEED

        # Decide based on signal state
        if signal.is_green_for(approach):
            return FREE_FLOW_SPEED

        if signal.is_yellow_for(approach):
            # Dilemma zone: can we clear at current speed?
            # Time remaining in yellow = YELLOW_DURATION_S - time_in_phase
            remaining = YELLOW_DURATION_S - signal.time_in_phase_s
            if remaining > 0 and agent.speed_ms * remaining >= dist_to_stop:
                return FREE_FLOW_SPEED
            # Otherwise fall through to red-equivalent stop behavior

        # Red (or yellow-can't-clear): decelerate to stop at the stop line.
        # Treat the stop line as a virtual stationary leader.
        allowed = max(0.0, (dist_to_stop - MIN_GAP_AT_REST_M) / HEADWAY_TIME_S)
        return min(FREE_FLOW_SPEED, allowed)

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
    
    def _update_intersection_measurements(self):
        """
        Per-tick updates to each IntersectionState:
          - queue_lengths: count stopped agents in the detection zone
          - arrivals_this_step / departures_this_step: detect stop-line
            crossings this tick
          - arrivals_by_approach / departures_by_approach: append
            (time, count) tuples to the cumulative logs

        Arrival = agent entered the queue detection zone this tick.
        Departure = agent crossed the stop line this tick (moving downstream).
        """
        # Zero per-step counters
        for istate in self.state.intersections.values():
            for d in ("N", "S", "E", "W"):
                istate.queue_lengths[d] = 0
                istate.arrivals_this_step[d] = 0
                istate.departures_this_step[d] = 0

        # Iterate active agents and attribute to downstream intersection
        for agent in self.agents:
            if not agent.active:
                continue

            link = agent.current_link()
            if link is None:
                continue

            downstream = link.to_int
            if downstream.is_terminal:
                # Agent is leaving the network; no intersection measurement
                continue

            istate = self.state.intersections.get(downstream.id)
            if istate is None:
                continue

            approach = _approach_direction_for_link(link)
            if approach is None:
                continue

            stop_line_pos = link.length_m - STOP_LINE_OFFSET_M
            dist_to_stop = stop_line_pos - agent.position_on_link_m

            # Queue length: stopped agent within the detection zone upstream
            # of the stop line
            in_detection_zone = (
                dist_to_stop >= 0 and dist_to_stop <= QUEUE_DETECTION_ZONE_M
            )
            if in_detection_zone and agent.speed_ms < STOPPED_SPEED_THRESHOLD_MS:
                istate.queue_lengths[approach] += 1

            # Arrival event: crossed into the detection zone this tick.
            # We detect this via the "previous step" position. Store that
            # on the agent for state continuity.
            prev_pos = getattr(agent, "_prev_position_on_link_m", None)
            prev_link_id = getattr(agent, "_prev_link_id", None)

            same_link = prev_link_id == link.id
            if same_link and prev_pos is not None:
                prev_dist = stop_line_pos - prev_pos
                # Arrived at detection zone (crossed inward this tick)
                if prev_dist > QUEUE_DETECTION_ZONE_M and dist_to_stop <= QUEUE_DETECTION_ZONE_M:
                    istate.arrivals_this_step[approach] += 1
                # Departed across stop line this tick (was upstream of stop,
                # is now past it)
                if prev_dist > 0 and dist_to_stop <= 0:
                    istate.departures_this_step[approach] += 1
            elif not same_link:
                # Agent just transitioned to this link from upstream.
                # If it spawned right on or past the detection zone it counts
                # as an arrival. Most common case: agents coming from another
                # link in the route, so they appear at position 0, which means
                # dist_to_stop = link.length_m - STOP_LINE_OFFSET_M. That's
                # almost certainly outside the 50m zone on any real link, so
                # no arrival counted here. Correct behavior.
                pass

            # Track for next tick
            agent._prev_position_on_link_m = agent.position_on_link_m
            agent._prev_link_id = link.id

        # Append non-zero this-step counts to the cumulative logs,
        # and accumulate departures for the current signal cycle.
        for istate in self.state.intersections.values():
            for d in ("N", "S", "E", "W"):
                a = istate.arrivals_this_step[d]
                if a > 0:
                    istate.arrivals_by_approach[d].append((self.state.time_s, a))
                dep = istate.departures_this_step[d]
                if dep > 0:
                    istate.departures_by_approach[d].append((self.state.time_s, dep))
                # Per-cycle flow accumulator (reset at NS_GREEN entry by Signal)
                istate.cycle_departures_accum[d] += dep
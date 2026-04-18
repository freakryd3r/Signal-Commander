"""Network data model. Pure data — no simulation logic.

Every field here is used in a later step; nothing is speculative.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from constants import (
    GRID_SPACING, LANES_PER_APPROACH, FREE_FLOW_SPEED, SAT_FLOW_BASE,
    JAM_SPACING, DEFAULT_P_LEFT, DEFAULT_P_THROUGH, DEFAULT_P_RIGHT,
    YELLOW_TIME, ALL_RED_TIME, LOST_TIME_PER_PHASE, DIRECTIONS,
    GRID_ROWS, GRID_COLS, NORTH, SOUTH, EAST, WEST,
)


# =============================================================================
# Link
# =============================================================================
@dataclass
class Link:
    """A directed link. Internal (between intersections) or boundary (to/from
    the outside world).

    Step 1 uses: link_id, from_node, to_node, geometry, storage.
    Step 2 uses: queue, in_transit, cum_in, cum_out.
    Step 4 uses: metrics derived from cum counts and queue time-series.
    """
    link_id: str
    from_node: str                      # intersection id or boundary tag
    to_node: str                        # intersection id or boundary tag

    # Geometry
    length: float = GRID_SPACING        # meters
    lanes: int = LANES_PER_APPROACH
    free_flow_speed: float = FREE_FLOW_SPEED

    # Capacity parameters (HCM)
    sat_flow: float = SAT_FLOW_BASE     # pc/hr/ln base

    # Storage (computed in __post_init__)
    storage_veh: float = field(init=False)

    # --- Dynamic state (Step 2) ---
    queue: float = 0.0                  # veh queued at downstream stop bar
    in_transit: float = 0.0             # veh on link, not yet queued

    # Cumulative counts for Little's Law and conservation checks
    cum_in: float = 0.0
    cum_out: float = 0.0

    # --- Topology flags ---
    # For internal inbound links and boundary inbound links: which approach
    # direction at to_node they feed. For boundary outbound links: None.
    downstream_approach_dir: Optional[int] = None

    # For boundary links only: which compass direction from the intersection
    # the link points (NORTH for a link on the north edge, etc.). Used by the
    # renderer to locate the off-grid endpoint.
    boundary_direction: Optional[int] = None

    is_boundary_inbound: bool = False
    is_boundary_outbound: bool = False

    def __post_init__(self) -> None:
        # HCM storage convention: length / jam-spacing, times number of lanes
        self.storage_veh = (self.length / JAM_SPACING) * self.lanes


# =============================================================================
# Approach
# =============================================================================
@dataclass
class Approach:
    """One of 4 approaches at an intersection.

    Holds turning proportions, outbound-movement link pointers, and
    per-step bookkeeping for simulation and scoring.
    """
    direction: int                      # NORTH/EAST/SOUTH/WEST: comes FROM
    inbound_link_id: Optional[str] = None

    # Turning proportions (must sum to 1.0)
    p_left: float = DEFAULT_P_LEFT
    p_through: float = DEFAULT_P_THROUGH
    p_right: float = DEFAULT_P_RIGHT

    # Outbound movement links (wired during network construction)
    out_left: Optional[str] = None
    out_through: Optional[str] = None
    out_right: Optional[str] = None

    # Lane configuration
    lanes: int = LANES_PER_APPROACH
    has_exclusive_left_lane: bool = False
    has_exclusive_right_lane: bool = False
    rtor_allowed: bool = True
    lt_prohibited: bool = False

    # Saturation flow adjustment factors (HCM Eq. 19-8 simplified subset).
    # Effective approach saturation flow: sat_flow * lanes * f_lt * f_rt.
    f_lt: float = 1.0
    f_rt: float = 0.95

    # Per-step counters (Step 2)
    arrivals_this_step: float = 0.0
    served_this_step: float = 0.0

    # Aggregates for scoring (Step 4)
    total_delay: float = 0.0            # veh-seconds
    total_throughput: float = 0.0       # veh
    max_queue: float = 0.0              # veh


# =============================================================================
# Phase
# =============================================================================
@dataclass
class Phase:
    """A single signal phase.

    `effective_green` is the HCM effective green g (used in delay formulas).
    Phase total wall-clock time in the cycle:
        total_time = effective_green + yellow_time + all_red_time

    This absorbs the start-up lost time into the effective-green figure, which
    is the standard HCM convention for signal-timing analysis.
    """
    phase_id: int
    protected_movements: List[Tuple[int, str]] = field(default_factory=list)
    permitted_movements: List[Tuple[int, str]] = field(default_factory=list)
    effective_green: float = 15.0       # sec (HCM g)
    yellow_time: float = YELLOW_TIME
    all_red_time: float = ALL_RED_TIME

    @property
    def total_time(self) -> float:
        """Wall-clock duration this phase occupies in the cycle."""
        return self.effective_green + self.yellow_time + self.all_red_time


# =============================================================================
# PhasePlan
# =============================================================================
@dataclass
class PhasePlan:
    """Ordered list of phases defining one complete cycle."""
    phases: List[Phase] = field(default_factory=list)
    offset: float = 0.0                 # sec relative to network reference time

    @property
    def cycle_length(self) -> float:
        return sum(p.total_time for p in self.phases)

    @property
    def total_lost_time(self) -> float:
        # L = n_phases * LOST_TIME_PER_PHASE (HCM convention)
        return len(self.phases) * LOST_TIME_PER_PHASE


# =============================================================================
# Intersection
# =============================================================================
@dataclass
class Intersection:
    """A signalized intersection. Approaches keyed by direction-FROM."""
    node_id: str
    row: int
    col: int
    x: float = 0.0
    y: float = 0.0

    approaches: Dict[int, Approach] = field(default_factory=dict)

    phase_plan: Optional[PhasePlan] = None
    current_phase_idx: int = 0
    time_in_phase: float = 0.0          # sec since current phase started

    cycles_completed: int = 0


# =============================================================================
# Network container
# =============================================================================
@dataclass
class Network:
    intersections: Dict[str, Intersection] = field(default_factory=dict)
    links: Dict[str, Link] = field(default_factory=dict)
    boundary_inbound: List[str] = field(default_factory=list)
    boundary_outbound: List[str] = field(default_factory=list)

    def get_intersection(self, row: int, col: int) -> Intersection:
        return self.intersections[f"I_{row}{col}"]

    def adjacent_intersection(self, row: int, col: int,
                              direction: int) -> Optional[Intersection]:
        """Intersection adjacent to (row, col) in `direction`, or None if off-grid."""
        delta = {NORTH: (-1, 0), SOUTH: (1, 0),
                 EAST: (0, 1), WEST: (0, -1)}[direction]
        nr = row + delta[0]
        nc = col + delta[1]
        if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS:
            return self.get_intersection(nr, nc)
        return None

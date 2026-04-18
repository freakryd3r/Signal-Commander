"""
metrics.py

Traffic metrics engine for Signal Lord.

This module owns:
- Webster optimal cycle logic
- Webster delay
- LOS classification
- CID computation
- Link density heatmap color mapping
- CSV export

This module does NOT own:
- simulation physics
- agents
- signals
- routing
- sidebar UI
- the Pygame main loop

IMPORTANT:
- Do not mutate SimulationState or anything nested inside it.
- Do not import pygame globally in this file.
- Keep units internal:
    * time: seconds
    * flow: vehicles/hour
    * density: vehicles/km

Notes on Webster cycle logic implemented here
---------------------------------------------
This version follows the updated modeling logic discussed in the team:

1. Candidate lane groups are evaluated using equivalent flow:
       q_eq = q_through + 1.4*q_right + eL*q_left

2. For each bound (N, S, E, W), choose the lane group with the maximum q_eq.
   That maximum is the critical lane flow for that bound.

3. For each phase:
       qc_NS = max(qc_N, qc_S)
       qc_EW = max(qc_E, qc_W)

4. Compute Y using those critical lane flows directly:
       y_NS = qc_NS / 1900
       y_EW = qc_EW / 1900
       Y = y_NS + y_EW

   Per the latest team decision, do NOT divide by lane count n.

5. If a left turn is protected:
       eL = 1.6 and no iteration is needed.

   If a left turn is unprotected:
       iterate on eL using the Q0*(C/G) criterion until the eL assumption is
       consistent with the resulting timing.

Because SimulationState does NOT currently contain movement-level flows or
lane-group definitions, this module accepts an external timing/movement config
for cycle optimization rather than inventing new state fields.
"""

from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Tuple, Optional, Any

import numpy as np


# =============================================================================
# CONSTANTS
# =============================================================================

SAT_FLOW = 1900.0  # veh/hr per critical lane
WARMUP_TIME_S = 180.0
ROLLING_WINDOW_S = 300.0

RIGHT_TURN_EQUIV = 1.4
PROTECTED_LEFT_EQUIV = 1.6

DEFAULT_STARTUP_LOST_S = 2.0
EL_TOL = 1e-9
MAX_ITER = 25


# =============================================================================
# DATA CLASSES FOR EXTERNAL CONFIGURATION
# =============================================================================

@dataclass(frozen=True)
class LaneGroupConfig:
    """
    Configuration for one candidate lane group.

    Parameters
    ----------
    name : str
        Human-readable label, e.g. 'NB_left_shared' or 'EB_thru_right'.
    total_flow_vph : float
        Total lane-group flow in veh/hr.
    through_pct : float
        Fraction of total flow that is through movement.
    right_pct : float
        Fraction of total flow that is right-turn movement.
    left_pct : float
        Fraction of total flow that is left-turn movement.
    protected_left : bool
        True if left turn is protected. Then eL = 1.6 with no iteration.
    opposing_flow_q0_vph : float
        Opposing flow Q0 used in the Q0*(C/G) logic for unprotected lefts.
    opposing_lanes : int
        Number of opposing lanes for the Q0*(C/G) eL lookup.
        Supported here: 1, 2, 3.
    """
    name: str
    total_flow_vph: float
    through_pct: float
    right_pct: float
    left_pct: float
    protected_left: bool
    opposing_flow_q0_vph: float = 0.0
    opposing_lanes: int = 1


@dataclass(frozen=True)
class PhaseTimingConfig:
    """
    Fixed timing design inputs used inside the iterative cycle calculation.

    Parameters
    ----------
    yellow_ns_s : float
        Yellow time for the NS phase in seconds.
    all_red_ns_s : float
        All-red time for the NS phase in seconds.
    yellow_ew_s : float
        Yellow time for the EW phase in seconds.
    all_red_ew_s : float
        All-red time for the EW phase in seconds.
    startup_lost_per_phase_s : float
        Startup lost time per phase in seconds.
    """
    yellow_ns_s: float
    all_red_ns_s: float
    yellow_ew_s: float
    all_red_ew_s: float
    startup_lost_per_phase_s: float = DEFAULT_STARTUP_LOST_S


@dataclass(frozen=True)
class IntersectionMovementConfig:
    """
    External movement/lane-group configuration for one intersection.

    Parameters
    ----------
    lane_groups_by_bound : dict[str, list[LaneGroupConfig]]
        Keys must be 'N', 'S', 'E', 'W'. Each value is a list of candidate lane groups.
    timing : PhaseTimingConfig
        Fixed yellow/all-red/startup timing inputs for the cycle calculation.
    initial_unprotected_el_by_bound : dict[str, float] | None
        Optional initial eL assumptions for unprotected lefts by bound.
        If omitted, defaults are chosen from the lookup table mid-range values:
            opposing_lanes=1 -> 2.9
            opposing_lanes=2 -> 2.8
            opposing_lanes=3 -> 3.4
    """
    lane_groups_by_bound: Dict[str, List[LaneGroupConfig]]
    timing: PhaseTimingConfig
    initial_unprotected_el_by_bound: Optional[Dict[str, float]] = None


# =============================================================================
# BASIC METRIC HELPERS
# =============================================================================

def level_of_service(delay_s: float) -> Tuple[str, Tuple[int, int, int]]:
    """
    Return HCM-style LOS label and badge color using control delay thresholds.
    """
    if delay_s < 0:
        raise ValueError("delay_s must be nonnegative.")

    if delay_s <= 10:
        return "A", (0, 200, 0)
    if delay_s <= 20:
        return "B", (100, 220, 0)
    if delay_s <= 35:
        return "C", (200, 200, 0)
    if delay_s <= 55:
        return "D", (255, 150, 0)
    if delay_s <= 80:
        return "E", (255, 80, 0)
    return "F", (255, 0, 0)


def link_density_color(density_veh_per_km: float, jam_density: float = 150.0) -> Tuple[int, int, int]:
    """
    Map link density to a simple green-yellow-red heatmap color.
    """
    if density_veh_per_km < 0:
        raise ValueError("density_veh_per_km must be nonnegative.")
    if jam_density <= 0:
        raise ValueError("jam_density must be positive.")

    ratio = min(density_veh_per_km / jam_density, 1.0)

    if ratio < 0.5:
        return (int(255 * ratio * 2), 255, 0)
    return (255, int(255 * (1 - (ratio - 0.5) * 2)), 0)


def mean_travel_time(completed_trips: List[Dict[str, Any]]) -> float:
    """
    Mean travel time in seconds from completed trips.
    """
    if not completed_trips:
        return 0.0

    times = [trip["travel_time_s"] for trip in completed_trips]
    return float(np.mean(times))


def percentile_travel_time(completed_trips: List[Dict[str, Any]], p: float = 85.0) -> float:
    """
    Compute percentile travel time in seconds.
    """
    if not completed_trips:
        return 0.0
    if not (0 <= p <= 100):
        raise ValueError("p must be between 0 and 100.")

    times = [trip["travel_time_s"] for trip in completed_trips]
    return float(np.percentile(times, p))


def has_valid_last_cycle_flows(intersection_state: Any) -> bool:
    """
    Return True if at least one last-cycle flow is available.

    Webster-based calculations should not run before the first full
    signal cycle completes.
    """
    return any(flow > 0 for flow in intersection_state.last_cycle_flows.values())


# =============================================================================
# CID
# =============================================================================

def compute_cid(intersection_state: Any, approach: str, current_time_s: float) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute cumulative arrivals and departures for one approach.
    """
    if approach not in ("N", "S", "E", "W"):
        raise ValueError(f"Invalid approach '{approach}'.")
    if current_time_s < 0:
        raise ValueError("current_time_s must be nonnegative.")

    arrivals = intersection_state.arrivals_by_approach[approach]
    departures = intersection_state.departures_by_approach[approach]

    time_axis = np.arange(0, int(current_time_s) + 1)
    arr_counts = np.zeros_like(time_axis, dtype=float)
    dep_counts = np.zeros_like(time_axis, dtype=float)

    for t, count in arrivals:
        t_int = int(t)
        if 0 <= t_int < len(arr_counts):
            arr_counts[t_int] += count

    for t, count in departures:
        t_int = int(t)
        if 0 <= t_int < len(dep_counts):
            dep_counts[t_int] += count

    cum_arr = np.cumsum(arr_counts)
    cum_dep = np.cumsum(dep_counts)

    return cum_arr, cum_dep


# =============================================================================
# WEBSTER DELAY
# =============================================================================

def websters_delay(
    intersection_state: Any,
    approach: str,
    cycle_length_s: float,
    green_s: float,
) -> float:
    """
    Compute Webster average control delay estimate for one approach.
    """
    if approach not in ("N", "S", "E", "W"):
        raise ValueError(f"Invalid approach '{approach}'.")
    if cycle_length_s <= 0:
        raise ValueError("cycle_length_s must be positive.")
    if green_s <= 0:
        raise ValueError("green_s must be positive.")
    if green_s > cycle_length_s:
        raise ValueError("green_s cannot exceed cycle_length_s.")
    if not has_valid_last_cycle_flows(intersection_state):
        raise ValueError(
            "Webster metrics are unavailable until the first signal cycle completes."
        )

    flow_vph = float(intersection_state.last_cycle_flows[approach])

    capacity_vph = (green_s / cycle_length_s) * SAT_FLOW
    if capacity_vph <= 0:
        raise ValueError("Computed capacity_vph must be positive.")

    x = flow_vph / capacity_vph
    g_over_c = green_s / cycle_length_s

    denominator = 1.0 - min(1.0, x) * g_over_c
    if denominator <= 0:
        raise ValueError("Webster uniform delay denominator is nonpositive.")

    d1 = 0.5 * cycle_length_s * ((1.0 - g_over_c) ** 2) / denominator

    T_hr = 0.25
    k = 0.5
    I = 1.0

    sqrt_term = (x - 1.0) ** 2 + (8.0 * k * I * x) / (capacity_vph * T_hr)
    d2 = 900.0 * T_hr * ((x - 1.0) + np.sqrt(max(0.0, sqrt_term)))

    return float(d1 + d2)


# =============================================================================
# EQUIVALENCE FACTOR HELPERS
# =============================================================================

def split_total_flow_by_percentages(
    total_flow_vph: float,
    through_pct: float,
    right_pct: float,
    left_pct: float,
) -> Dict[str, float]:
    """
    Split a total lane-group flow into through/right/left components.
    """
    if total_flow_vph < 0:
        raise ValueError("total_flow_vph must be nonnegative.")

    for name, val in {
        "through_pct": through_pct,
        "right_pct": right_pct,
        "left_pct": left_pct,
    }.items():
        if val < 0:
            raise ValueError(f"{name} must be nonnegative.")

    total_pct = through_pct + right_pct + left_pct
    if abs(total_pct - 1.0) > 1e-6:
        raise ValueError(f"Movement percentages must sum to 1.0, got {total_pct:.6f}.")

    return {
        "through_vph": total_flow_vph * through_pct,
        "right_vph": total_flow_vph * right_pct,
        "left_vph": total_flow_vph * left_pct,
    }


def lookup_unprotected_left_equivalence_factor(opposing_lanes: int, q0_c_over_g: float) -> float:
    """
    Lookup eL for an unprotected left turn using the table logic discussed.
    """
    if q0_c_over_g <= 0:
        raise ValueError("q0_c_over_g must be positive for unprotected left lookup.")

    if opposing_lanes == 1:
        if 0 < q0_c_over_g < 1000:
            return 1.6
        if 1000 <= q0_c_over_g < 1350:
            return 2.9

    elif opposing_lanes == 2:
        if 0 < q0_c_over_g < 1000:
            return 2.0
        if 1000 <= q0_c_over_g < 1350:
            return 2.8
        if 1350 <= q0_c_over_g < 2000:
            return 6.0

    elif opposing_lanes == 3:
        if 0 < q0_c_over_g < 1000:
            return 2.2
        if 1000 <= q0_c_over_g < 1350:
            return 3.4
        if 1350 <= q0_c_over_g < 2400:
            return 8.9

    raise ValueError(
        f"No valid unprotected-left eL found for opposing_lanes={opposing_lanes}, "
        f"q0_c_over_g={q0_c_over_g:.3f}"
    )


def default_initial_unprotected_el(opposing_lanes: int) -> float:
    """
    Default initial eL guess for unprotected left turns.
    """
    if opposing_lanes == 1:
        return 2.9
    if opposing_lanes == 2:
        return 2.8
    if opposing_lanes == 3:
        return 3.4
    raise ValueError(f"Unsupported opposing_lanes={opposing_lanes}.")


def compute_lane_group_equivalent_flow(
    lane_group: LaneGroupConfig,
    left_equiv_factor: float,
) -> Dict[str, float]:
    """
    Compute equivalent flow for one candidate lane group.
    """
    split = split_total_flow_by_percentages(
        total_flow_vph=lane_group.total_flow_vph,
        through_pct=lane_group.through_pct,
        right_pct=lane_group.right_pct,
        left_pct=lane_group.left_pct,
    )

    q_eq = (
        split["through_vph"]
        + RIGHT_TURN_EQUIV * split["right_vph"]
        + left_equiv_factor * split["left_vph"]
    )

    return {
        "through_vph": split["through_vph"],
        "right_vph": split["right_vph"],
        "left_vph": split["left_vph"],
        "equivalent_flow_vph": q_eq,
    }


# =============================================================================
# WEBSTER CYCLE WITH PROTECTED / UNPROTECTED LEFT LOGIC
# =============================================================================

def _choose_critical_lane_group_for_bound(
    bound_lane_groups: List[LaneGroupConfig],
    left_equiv_factors_by_name: Dict[str, float],
) -> Dict[str, Any]:
    """
    Choose the critical lane group for one bound by maximum equivalent flow.
    """
    if not bound_lane_groups:
        raise ValueError("Each bound must have at least one candidate lane group.")

    candidates = []
    for lg in bound_lane_groups:
        if lg.name not in left_equiv_factors_by_name:
            raise ValueError(f"Missing left equivalence factor for lane group '{lg.name}'.")

        lane_data = compute_lane_group_equivalent_flow(
            lane_group=lg,
            left_equiv_factor=left_equiv_factors_by_name[lg.name],
        )

        candidates.append({
            "lane_group_name": lg.name,
            "protected_left": lg.protected_left,
            "opposing_lanes": lg.opposing_lanes,
            "opposing_flow_q0_vph": lg.opposing_flow_q0_vph,
            "left_equiv_factor": left_equiv_factors_by_name[lg.name],
            "through_vph": lane_data["through_vph"],
            "right_vph": lane_data["right_vph"],
            "left_vph": lane_data["left_vph"],
            "critical_lane_flow_vph": lane_data["equivalent_flow_vph"],
        })

    chosen = max(candidates, key=lambda x: x["critical_lane_flow_vph"])
    chosen["all_candidates"] = candidates
    return chosen


def websters_optimal_cycle_from_lane_groups(
    config: IntersectionMovementConfig,
    clamp_y_at: float = 0.95,
) -> Dict[str, Any]:
    """
    Compute Webster optimal cycle length using the team's updated logic.
    """
    required_bounds = ("N", "S", "E", "W")
    for b in required_bounds:
        if b not in config.lane_groups_by_bound:
            raise ValueError(f"Missing lane_groups_by_bound entry for bound '{b}'.")

    left_equiv_factors_by_name: Dict[str, float] = {}
    init_by_bound = config.initial_unprotected_el_by_bound or {}

    for bound, lane_groups in config.lane_groups_by_bound.items():
        for lg in lane_groups:
            if lg.protected_left:
                left_equiv_factors_by_name[lg.name] = PROTECTED_LEFT_EQUIV
            else:
                left_equiv_factors_by_name[lg.name] = init_by_bound.get(
                    bound,
                    default_initial_unprotected_el(lg.opposing_lanes),
                )

    iteration_count = 0
    converged = False

    while not converged:
        iteration_count += 1
        if iteration_count > MAX_ITER:
            raise ValueError("Unprotected-left eL iteration did not converge within MAX_ITER.")

        critical_bound_results: Dict[str, Dict[str, Any]] = {}
        for bound in required_bounds:
            critical_bound_results[bound] = _choose_critical_lane_group_for_bound(
                bound_lane_groups=config.lane_groups_by_bound[bound],
                left_equiv_factors_by_name=left_equiv_factors_by_name,
            )

        qc_n = critical_bound_results["N"]["critical_lane_flow_vph"]
        qc_s = critical_bound_results["S"]["critical_lane_flow_vph"]
        qc_e = critical_bound_results["E"]["critical_lane_flow_vph"]
        qc_w = critical_bound_results["W"]["critical_lane_flow_vph"]

        qc_ns = max(qc_n, qc_s)
        qc_ew = max(qc_e, qc_w)

        y_ns = qc_ns / SAT_FLOW
        y_ew = qc_ew / SAT_FLOW
        y_total_raw = y_ns + y_ew

        was_y_clamped = False
        y_total = y_total_raw
        if y_total > clamp_y_at:
            y_total = clamp_y_at
            was_y_clamped = True
            if y_total_raw > 0:
                scale = y_total / y_total_raw
                y_ns *= scale
                y_ew *= scale

        if y_total <= 0:
            raise ValueError("Computed Y must be positive.")

        timing = config.timing
        lost_ns_s = timing.startup_lost_per_phase_s + timing.yellow_ns_s + timing.all_red_ns_s
        lost_ew_s = timing.startup_lost_per_phase_s + timing.yellow_ew_s + timing.all_red_ew_s
        lost_time_s = lost_ns_s + lost_ew_s

        denominator = 1.0 - y_total
        if denominator <= 0:
            raise ValueError("Webster cycle denominator is nonpositive after Y calculation.")

        optimal_cycle_s = (1.5 * lost_time_s + 5.0) / denominator
        if optimal_cycle_s <= lost_time_s:
            raise ValueError("Computed cycle length must exceed lost time.")

        effective_green_total_s = optimal_cycle_s - lost_time_s
        green_ns_s = (y_ns / y_total) * effective_green_total_s
        green_ew_s = (y_ew / y_total) * effective_green_total_s

        red_ns_s = optimal_cycle_s - green_ns_s
        red_ew_s = optimal_cycle_s - green_ew_s

        updated_left_equiv_factors_by_name = dict(left_equiv_factors_by_name)

        for bound in required_bounds:
            serving_green_s = green_ns_s if bound in ("N", "S") else green_ew_s

            for lg in config.lane_groups_by_bound[bound]:
                if lg.protected_left:
                    updated_left_equiv_factors_by_name[lg.name] = PROTECTED_LEFT_EQUIV
                    continue

                q0_c_over_g = lg.opposing_flow_q0_vph * optimal_cycle_s / serving_green_s
                updated_left_equiv_factors_by_name[lg.name] = lookup_unprotected_left_equivalence_factor(
                    opposing_lanes=lg.opposing_lanes,
                    q0_c_over_g=q0_c_over_g,
                )

        converged = True
        for lg_name, old_val in left_equiv_factors_by_name.items():
            new_val = updated_left_equiv_factors_by_name[lg_name]
            if abs(new_val - old_val) > EL_TOL:
                converged = False
                break

        left_equiv_factors_by_name = updated_left_equiv_factors_by_name

    final_critical_bound_results: Dict[str, Dict[str, Any]] = {}
    for bound in required_bounds:
        final_critical_bound_results[bound] = _choose_critical_lane_group_for_bound(
            bound_lane_groups=config.lane_groups_by_bound[bound],
            left_equiv_factors_by_name=left_equiv_factors_by_name,
        )

    return {
        "optimal_cycle_s": float(optimal_cycle_s),
        "was_y_clamped": was_y_clamped,
        "y_total": float(y_total),
        "y_total_raw_before_clamp": float(y_total_raw),
        "y_ns": float(y_ns),
        "y_ew": float(y_ew),
        "lost_time_s": float(lost_time_s),
        "lost_ns_s": float(lost_ns_s),
        "lost_ew_s": float(lost_ew_s),
        "green_ns_s": float(green_ns_s),
        "green_ew_s": float(green_ew_s),
        "red_ns_s": float(red_ns_s),
        "red_ew_s": float(red_ew_s),
        "critical_bound_results": final_critical_bound_results,
        "phase_critical_flows_vph": {
            "NS": float(max(
                final_critical_bound_results["N"]["critical_lane_flow_vph"],
                final_critical_bound_results["S"]["critical_lane_flow_vph"],
            )),
            "EW": float(max(
                final_critical_bound_results["E"]["critical_lane_flow_vph"],
                final_critical_bound_results["W"]["critical_lane_flow_vph"],
            )),
        },
        "timing_inputs": {
            "yellow_ns_s": timing.yellow_ns_s,
            "all_red_ns_s": timing.all_red_ns_s,
            "yellow_ew_s": timing.yellow_ew_s,
            "all_red_ew_s": timing.all_red_ew_s,
            "startup_lost_per_phase_s": timing.startup_lost_per_phase_s,
        },
        "final_left_equiv_factors_by_lane_group": dict(left_equiv_factors_by_name),
        "iteration_count": iteration_count,
    }

def websters_optimal_cycle_simple(
    intersection_state: Any,
    yellow_s: float = 3.0,
    all_red_s: float = 2.0,
    startup_lost_per_phase_s: float = 2.0,
    clamp_y_at: float = 0.95,
) -> Dict[str, Any]:
    """
    Simplified Webster optimal cycle based on aggregate per-approach
    flows in last_cycle_flows. Assumes all flow is through-movement
    (no turning equivalencies). Good enough for demo; full lane-group
    Webster is available via websters_optimal_cycle_from_lane_groups().

    Returns dict with:
      optimal_cycle_s, was_y_clamped, y_total, y_ns, y_ew,
      green_ns_s, green_ew_s, lost_time_s, flow_inputs (for UI display).
    """
    if not has_valid_last_cycle_flows(intersection_state):
        raise ValueError("No measured flows yet. Wait for first cycle to complete.")

    flows = intersection_state.last_cycle_flows
    # Critical lane flow per phase: max of the two approaches
    qc_ns = max(flows["N"], flows["S"])
    qc_ew = max(flows["E"], flows["W"])

    y_ns = qc_ns / SAT_FLOW
    y_ew = qc_ew / SAT_FLOW
    y_total_raw = y_ns + y_ew

    was_y_clamped = False
    y_total = y_total_raw
    if y_total > clamp_y_at:
        y_total = clamp_y_at
        was_y_clamped = True
        if y_total_raw > 0:
            scale = y_total / y_total_raw
            y_ns *= scale
            y_ew *= scale

    if y_total <= 0:
        raise ValueError("Computed Y is nonpositive. Demand is too low to run Webster.")

    # Lost time: 2 phases, each with startup + yellow + all_red
    lost_time_s = 2.0 * (startup_lost_per_phase_s + yellow_s + all_red_s)

    denominator = 1.0 - y_total
    if denominator <= 0:
        raise ValueError("Webster cycle denominator is nonpositive.")

    optimal_cycle_s = (1.5 * lost_time_s + 5.0) / denominator
    if optimal_cycle_s <= lost_time_s:
        raise ValueError("Computed cycle length must exceed lost time.")

    effective_green_total_s = optimal_cycle_s - lost_time_s
    green_ns_s = (y_ns / y_total) * effective_green_total_s
    green_ew_s = (y_ew / y_total) * effective_green_total_s

    return {
        "optimal_cycle_s": float(optimal_cycle_s),
        "green_ns_s": float(green_ns_s),
        "green_ew_s": float(green_ew_s),
        "y_total": float(y_total),
        "y_total_raw_before_clamp": float(y_total_raw),
        "y_ns": float(y_ns),
        "y_ew": float(y_ew),
        "lost_time_s": float(lost_time_s),
        "was_y_clamped": was_y_clamped,
        "flow_inputs": dict(flows),
    }

# =============================================================================
# MAIN ENGINE
# =============================================================================

class MetricsEngine:
    """
    Main metrics interface for simulation and UI.
    """

    def __init__(self) -> None:
        """Initialize all internal storage."""
        self.reset_all()

    def update(self, sim_state: Any) -> None:
        """
        Update engine state from the latest SimulationState snapshot.

        Uses per-step fields to avoid double-counting:
        - completed_trips_this_step
        - denied_entries_this_step

        Keeps the latest full state for cumulative display fields.
        """
        
        self.current_time_s = float(sim_state.time_s)
        self.latest_state = sim_state

        self.completed_trips.extend(sim_state.completed_trips_this_step)
        self.denied_entries += int(sim_state.denied_entries_this_step)
        if sim_state.warmup_complete:
            self.post_warmup_completed_trips.extend(sim_state.completed_trips_this_step)
            for trip in sim_state.completed_trips_this_step:
                self.rolling_completed_trips.append((self.current_time_s, trip))
            per_intersection = self.get_intersection_metrics(sim_state)
            mean_delays = [vals["mean_delay_sec_per_veh"] for vals in per_intersection.values()]
            sampled_delay = float(np.mean(mean_delays)) if mean_delays else 0.0
            self.rolling_network_delay_samples.append((self.current_time_s, sampled_delay))

        self._prune_rolling_window()

    def _prune_rolling_window(self) -> None:
        """
        Drop rolling records that are outside the rolling window.
        """
        cutoff_time_s = self.current_time_s - ROLLING_WINDOW_S
        while self.rolling_completed_trips and self.rolling_completed_trips[0][0] < cutoff_time_s:
            self.rolling_completed_trips.popleft()
        while self.rolling_network_delay_samples and self.rolling_network_delay_samples[0][0] < cutoff_time_s:
            self.rolling_network_delay_samples.popleft()

    def _rolling_trip_payloads(self) -> List[Dict[str, Any]]:
        """
        Return just the trip payloads from the rolling-window store.
        """
        return [trip for _, trip in self.rolling_completed_trips]

    def _rolling_network_mean_delay(self) -> float:
        """
        Return the mean sampled network delay over the rolling window.
        """
        if not self.rolling_network_delay_samples:
            return 0.0
        return float(np.mean([delay for _, delay in self.rolling_network_delay_samples]))


    def get_network_metrics(self) -> Dict[str, float]:
        """
        Return network-level metrics excluding warm-up.

        Uses cumulative display fields from latest_state:
        - completed_trips
        - denied_entries_total
        """
        if self.latest_state is None:
            return {
                "total_completed_trips": 0.0,
                "denied_entries": 0.0,
                "total_vehicles_in_network": 0.0,
                "network_mean_delay_s": 0.0,
                "mean_travel_time_s": 0.0,
                "p85_travel_time_s": 0.0,
                "rolling_completed_trips": 0.0,
                "rolling_mean_travel_time_s": 0.0,
                "rolling_p85_travel_time_s": 0.0,
                "rolling_network_mean_delay_s": 0.0,
                "warmup_excluded": 0.0,
            }

        total_completed_trips = float(len(self.latest_state.completed_trips))
        denied_entries_total = float(self.latest_state.denied_entries_total)
        total_vehicles_in_network = float(sum(link.num_vehicles for link in self.latest_state.links.values()))
        per_intersection = self.get_intersection_metrics(self.latest_state)
        mean_delays = [vals["mean_delay_sec_per_veh"] for vals in per_intersection.values()]
        network_mean_delay_s = float(np.mean(mean_delays)) if mean_delays else 0.0

        if not self.latest_state.warmup_complete:
            return {
                "total_completed_trips": total_completed_trips,
                "denied_entries": denied_entries_total,
                "total_vehicles_in_network": total_vehicles_in_network,
                "network_mean_delay_s": 0.0,
                "mean_travel_time_s": 0.0,
                "p85_travel_time_s": 0.0,
                "rolling_completed_trips": 0.0,
                "rolling_mean_travel_time_s": 0.0,
                "rolling_p85_travel_time_s": 0.0,
                "rolling_network_mean_delay_s": 0.0,
                "warmup_excluded": 0.0,
            }

        rolling_trips = self._rolling_trip_payloads()

        return {
            "total_completed_trips": total_completed_trips,
            "denied_entries": denied_entries_total,
            "total_vehicles_in_network": total_vehicles_in_network,
            "network_mean_delay_s": network_mean_delay_s,
            "mean_travel_time_s": mean_travel_time(self.post_warmup_completed_trips),
            "p85_travel_time_s": percentile_travel_time(self.post_warmup_completed_trips, p=85.0),
            "rolling_completed_trips": float(len(rolling_trips)),
            "rolling_mean_travel_time_s": mean_travel_time(rolling_trips),
            "rolling_p85_travel_time_s": percentile_travel_time(rolling_trips, p=85.0),
            "rolling_network_mean_delay_s": self._rolling_network_mean_delay(),
            "warmup_excluded": 1.0,
        }

    def get_intersection_metrics(
        self,
        sim_state: Any,
        cycle_green_by_intersection: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Compute per-intersection delay and LOS.
        """
        results: Dict[str, Dict[str, Any]] = {}

        for intersection_id, inter in sim_state.intersections.items():
            if cycle_green_by_intersection and intersection_id in cycle_green_by_intersection:
                timing = cycle_green_by_intersection[intersection_id]
                cycle_length_s = float(timing["cycle_length_s"])
                green_ns_s = float(timing["green_ns_s"])
                green_ew_s = float(timing["green_ew_s"])
                used_placeholder_timing = False
            else:
                cycle_length_s = float(inter.cycle_length_s)
                green_ns_s = float(inter.green_ns_s)
                green_ew_s = float(inter.green_ew_s)
                used_placeholder_timing = False

            delays: List[float] = []
            approach_delays: Dict[str, Any] = {}

            for approach in ("N", "S", "E", "W"):
                green_s = green_ns_s if approach in ("N", "S") else green_ew_s
                try:
                    delay_s = websters_delay(
                        intersection_state=inter,
                        approach=approach,
                        cycle_length_s=cycle_length_s,
                        green_s=green_s,
                    )
                    delays.append(delay_s)
                    approach_delays[approach] = delay_s
                except Exception:
                    approach_delays[approach] = None

            mean_delay_s = float(np.mean(delays)) if delays else 0.0
            los, los_color = level_of_service(mean_delay_s)

            throughput_vph = float(sum(inter.last_cycle_flows.values()))
            capacity_vph = SAT_FLOW * ((green_ns_s / cycle_length_s) * 2 + (green_ew_s / cycle_length_s) * 2)
            vc_ratio = throughput_vph / capacity_vph if capacity_vph > 0 else 0.0

            results[intersection_id] = {
                "mean_delay_sec_per_veh": mean_delay_s,
                "los": los,
                "los_color": los_color,
                "throughput_veh_hr": throughput_vph,
                "vc_ratio": vc_ratio,
                "approach_delay_sec_per_veh": approach_delays,
                "used_placeholder_timing": used_placeholder_timing,
                "cycle_length_s": cycle_length_s,
                "green_ns_s": green_ns_s,
                "green_ew_s": green_ew_s,
            }

        return results

    def get_webster_recommendation(
        self,
        intersection_movement_config: IntersectionMovementConfig,
    ) -> Dict[str, Any]:
        """
        Return Webster cycle recommendation using the external movement config.
        """
        return websters_optimal_cycle_from_lane_groups(intersection_movement_config)

    def get_cid_data(self, intersection_state: Any, approach: str, current_time_s: float) -> Dict[str, np.ndarray]:
        """
        Return CID data in a UI-friendly dictionary.
        """
        arrivals, departures = compute_cid(intersection_state, approach, current_time_s)
        return {
            "cumulative_arrivals": arrivals,
            "cumulative_departures": departures,
        }

    def get_link_heatmap_color(self, density_veh_per_km: float) -> Tuple[int, int, int]:
        """
        Return heatmap color for a link density value.
        """
        return link_density_color(density_veh_per_km)

    def reset_simulation_metrics(self) -> None:
        """
        Clear dynamic simulation metrics while keeping engine object alive.
        """
        self.completed_trips: List[Dict[str, Any]] = []
        self.denied_entries: int = 0
        self.current_time_s: float = 0.0
        self.latest_state: Optional[Any] = None
        self.post_warmup_completed_trips: List[Dict[str, Any]] = []
        self.rolling_completed_trips: Deque[Tuple[float, Dict[str, Any]]] = deque()
        self.rolling_network_delay_samples: Deque[Tuple[float, float]] = deque()

    def reset_all(self) -> None:
        """
        Full reset of all internal state.
        """
        self.reset_simulation_metrics()
        

    def export_csv(
        self,
        sim_state: Any,
        per_intersection_path: str,
        network_path: str,
        cycle_green_by_intersection: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> None:
        """
        Export per-intersection and network-level CSVs.
        """
        export_csv(
            sim_state=sim_state,
            per_intersection_path=per_intersection_path,
            network_path=network_path,
            cycle_green_by_intersection=cycle_green_by_intersection,
        )

    def get_webster_recommendation_simple(
    self,
    intersection_state: Any,
    yellow_s: float = 3.0,
    all_red_s: float = 2.0,
    ) -> Dict[str, Any]:
        return websters_optimal_cycle_simple(
        intersection_state=intersection_state,
        yellow_s=yellow_s,
        all_red_s=all_red_s,
    )

# =============================================================================
# CSV EXPORT
# =============================================================================

def export_csv(
    sim_state: Any,
    per_intersection_path: str,
    network_path: str,
    cycle_green_by_intersection: Optional[Dict[str, Dict[str, float]]] = None,
) -> None:
    """
    Write per-intersection and network-level CSV files.
    """
    engine = MetricsEngine()
    engine.update(sim_state)

    per_intersection = engine.get_intersection_metrics(
        sim_state=sim_state,
        cycle_green_by_intersection=cycle_green_by_intersection,
    )
    network_metrics = engine.get_network_metrics()

    with open(per_intersection_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "intersection_id",
            "cycle_length_s",
            "green_ns_s",
            "green_ew_s",
            "mean_delay_s",
            "los",
            "throughput_veh_hr",
            "vc_ratio",
        ])

        for intersection_id, vals in per_intersection.items():
            writer.writerow([
                intersection_id,
                vals["cycle_length_s"],
                vals["green_ns_s"],
                vals["green_ew_s"],
                vals["mean_delay_sec_per_veh"],
                vals["los"],
                vals["throughput_veh_hr"],
                vals["vc_ratio"],
            ])

    with open(network_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "total_completed_trips",
            "denied_entries",
            "total_vehicles_in_network",
            "mean_travel_time_s",
            "p85_travel_time_s",
            "network_mean_delay_s",
            "rolling_completed_trips",
            "rolling_mean_travel_time_s",
            "rolling_p85_travel_time_s",
            "rolling_network_mean_delay_s",
            "warmup_excluded",
        ])

        writer.writerow([
            network_metrics["total_completed_trips"],
            network_metrics["denied_entries"],
            network_metrics["total_vehicles_in_network"],
            network_metrics["mean_travel_time_s"],
            network_metrics["p85_travel_time_s"],
            network_metrics["network_mean_delay_s"],
            network_metrics["rolling_completed_trips"],
            network_metrics["rolling_mean_travel_time_s"],
            network_metrics["rolling_p85_travel_time_s"],
            network_metrics["rolling_network_mean_delay_s"],
            network_metrics["warmup_excluded"],
        ])
        

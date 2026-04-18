"""Simulation core: store-and-forward queue dynamics with NEMA phase control.

References:
  - HCM 7th Ed. (TRB 2022), Ch. 19
  - Webster (1958), RRL Tech Paper 39
  - Akcelik (1981), ARRB Report 123
  - Gartner (1983); Aboudolas et al. (2009) Transp. Res. C 17(2)

Time-stepping algorithm (every Delta-t seconds):
  1. Advance each intersection's phase clock; wrap at cycle_length.
  2. Inject external demand at boundary inbound links (deterministic arrivals).
  3. For each inbound link at each intersection, compute per-movement outflow
     at the stop bar, capped by queue / sat-flow-during-green / downstream storage.
  4. Route outflows into downstream link queues using approach turn ratios.
  5. Update queue state q(t+dt) = q(t) + dt*(u + d - s).
  6. Accumulate delay = sum over links of queue(t) * dt [veh-seconds].
  7. Log throughput, max queues, spillback events.

Assumptions / simplifications (all defensible):
  - Queues accumulate at the downstream stop bar instantly (no free-flow
    travel time modelled). Standard store-and-forward assumption.
  - Arrivals are deterministic. HCM d2 accounts for randomness analytically.
  - One lane-group per approach, weighted by turn shares.
  - Permitted LTs use f_lt = 0.30 during permitted-only phases as a
    first-order approximation of HCM's opposing-volume capacity model.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple
from constants import (
    DT, SAT_FLOW_BASE,
    MOVEMENT_LEFT, MOVEMENT_THROUGH, MOVEMENT_RIGHT,
)
from network import Network, Intersection


# Permitted-LT capacity reduction factor (simplified HCM permitted-LT model)
F_LT_PERMITTED = 0.30

# Right-turn-on-red capacity as fraction of saturated through flow
F_RT_ON_RED = 0.25


# =============================================================================
# Signal state helper
# =============================================================================
def movement_is_green(intx: Intersection, approach_dir: int,
                      movement: str, global_time: float) -> Tuple[bool, bool]:
    """Return (is_protected_green, is_permitted_green) for a movement at `global_time`.

    Uses the intersection's offset and current phase plan. Clearance interval
    (yellow + all-red) at the end of each phase counts as red.
    """
    pp = intx.phase_plan
    if pp is None or not pp.phases:
        return (False, False)

    local_t = (global_time + pp.offset) % pp.cycle_length

    # Find active phase
    elapsed = 0.0
    active = pp.phases[0]
    for phase in pp.phases:
        if elapsed + phase.total_time > local_t:
            active = phase
            break
        elapsed += phase.total_time

    # Within the phase, green is effective_green; yellow+all_red is clearance.
    time_in_phase = local_t - elapsed
    in_green_interval = time_in_phase < active.effective_green

    key = (approach_dir, movement)
    is_protected = in_green_interval and key in active.protected_movements
    is_permitted = in_green_interval and key in active.permitted_movements
    return (is_protected, is_permitted)


# =============================================================================
# Simulator
# =============================================================================
@dataclass
class StepMetrics:
    """Metrics collected each time step for diagnostics / scoring."""
    time: float = 0.0
    total_queue: float = 0.0
    total_delay_increment: float = 0.0
    external_inflow: float = 0.0
    external_outflow: float = 0.0
    spillback_count: int = 0


class Simulator:
    """Orchestrates the network simulation."""

    def __init__(self, net: Network, demand: Dict[str, float], dt: float = DT):
        self.net = net
        self.demand = demand            # veh/hr per inbound boundary link
        self.dt = dt
        self.global_time = 0.0

        self.total_delay = 0.0          # veh-seconds network-wide
        self.total_throughput = 0.0     # veh that exited the network
        self.total_external_in = 0.0    # veh injected at boundaries
        self.spillback_events = 0

        self.history: List[StepMetrics] = []

        # Saturation flow in veh per second per lane (constant)
        self.sat_per_sec_per_lane = SAT_FLOW_BASE / 3600.0  # ~0.528

        # Initialize each intersection's phase display state so renderers
        # called before the first step() see the correct initial phase.
        for intx in self.net.intersections.values():
            self._advance_phase(intx)

    # -------------------------------------------------------------------------
    # Main step
    # -------------------------------------------------------------------------
    def step(self) -> StepMetrics:
        """Advance the simulation by one dt.

        The phase state used for SERVING is evaluated at `global_time` (start
        of this step's interval). After serving and queue updates, we advance
        global_time and then recompute the DISPLAY phase state so that any
        render call between step() invocations sees the correct 'current' state.
        """
        metrics = StepMetrics(time=self.global_time)

        # 1. External demand at boundary inbound links.
        ext_in = self._inject_boundary_demand()
        metrics.external_inflow = ext_in
        self.total_external_in += ext_in

        # 2. Compute outflows at every intersection based on q(t) BEFORE any
        #    updates. Collect them in staging dicts, then apply simultaneously.
        outflow_to_downstream: Dict[str, float] = {}
        outflow_served: Dict[str, float] = {}

        for intx in self.net.intersections.values():
            self._serve_intersection(intx, outflow_to_downstream, outflow_served)

        # 3. Vehicles sent to boundary outbound links are 'exited'.
        ext_out = self._drain_boundary_outbound(outflow_to_downstream)
        metrics.external_outflow = ext_out
        self.total_throughput += ext_out

        # 4. Apply all queue updates simultaneously.
        spillback_this_step = 0
        for link_id, link in self.net.links.items():
            if link.is_boundary_outbound:
                continue

            served = outflow_served.get(link_id, 0.0)
            added = outflow_to_downstream.get(link_id, 0.0)

            link.queue = max(0.0, link.queue - served) + added
            link.cum_out += served
            link.cum_in += added

            if link.queue >= link.storage_veh - 1e-6:
                link.queue = link.storage_veh
                spillback_this_step += 1

        metrics.spillback_count = spillback_this_step
        self.spillback_events += spillback_this_step

        # 5. Accumulate delay: integral of queue over time.
        total_q = sum(
            l.queue for l in self.net.links.values()
            if not l.is_boundary_outbound
        )
        delay_inc = total_q * self.dt
        metrics.total_queue = total_q
        metrics.total_delay_increment = delay_inc
        self.total_delay += delay_inc

        # 6. Advance clock.
        self.global_time += self.dt
        self.history.append(metrics)

        # 7. Update phase display state to reflect the NEW global_time, so
        #    renderers called after step() see the current-time signal state.
        for intx in self.net.intersections.values():
            self._advance_phase(intx)

        # 8. Per-approach aggregates (max queue, delay, throughput).
        self._update_approach_aggregates()

        return metrics

    # -------------------------------------------------------------------------
    # Phase clock
    # -------------------------------------------------------------------------
    def _advance_phase(self, intx: Intersection) -> None:
        """Derive phase index and time-in-phase from global_time + offset.

        This keeps the displayed phase state in perfect sync with the green
        state computed by `movement_is_green`. If the user changes the offset
        at runtime (Step 3), this will pick up the change immediately.
        """
        pp = intx.phase_plan
        if pp is None:
            return

        C = pp.cycle_length
        if C <= 0:
            return

        local_t = (self.global_time + pp.offset) % C
        elapsed = 0.0
        for i, phase in enumerate(pp.phases):
            if elapsed + phase.total_time > local_t + 1e-9:
                intx.current_phase_idx = i
                intx.time_in_phase = local_t - elapsed
                break
            elapsed += phase.total_time
        else:
            # Fallback (should be unreachable)
            intx.current_phase_idx = len(pp.phases) - 1
            intx.time_in_phase = 0.0

        # Cycles completed since simulation start (integer count)
        intx.cycles_completed = int((self.global_time + pp.offset) / C)

    # -------------------------------------------------------------------------
    # Boundary demand
    # -------------------------------------------------------------------------
    def _inject_boundary_demand(self) -> float:
        """Deterministic arrivals at boundary inbound links (veh/hr -> veh this dt)."""
        total = 0.0
        for link_id, veh_per_hour in self.demand.items():
            link = self.net.links[link_id]
            arrivals = (veh_per_hour / 3600.0) * self.dt

            available = link.storage_veh - link.queue
            if arrivals > available:
                arrivals = max(0.0, available)

            link.queue += arrivals
            link.cum_in += arrivals
            total += arrivals
        return total

    # -------------------------------------------------------------------------
    # Intersection service
    # -------------------------------------------------------------------------
    def _serve_intersection(self, intx: Intersection,
                            outflow_to_downstream: Dict[str, float],
                            outflow_served: Dict[str, float]) -> None:
        """Serve each approach: move queued vehicles onto downstream links."""
        for appr_dir, appr in intx.approaches.items():
            if appr.inbound_link_id is None:
                continue
            inbound = self.net.links[appr.inbound_link_id]

            if inbound.queue <= 1e-9:
                continue

            served_total = 0.0

            for mvmt, p_share, out_link_id in [
                (MOVEMENT_LEFT, appr.p_left, appr.out_left),
                (MOVEMENT_THROUGH, appr.p_through, appr.out_through),
                (MOVEMENT_RIGHT, appr.p_right, appr.out_right),
            ]:
                if mvmt == MOVEMENT_LEFT and appr.lt_prohibited:
                    continue

                queued_for_movement = inbound.queue * p_share
                if queued_for_movement <= 1e-9:
                    continue

                is_protected, is_permitted = movement_is_green(
                    intx, appr_dir, mvmt, self.global_time
                )

                if is_protected:
                    sat_rate = (self.sat_per_sec_per_lane * appr.lanes
                                * appr.f_lt * appr.f_rt)
                elif is_permitted and mvmt == MOVEMENT_LEFT:
                    sat_rate = (self.sat_per_sec_per_lane * appr.lanes
                                * F_LT_PERMITTED)
                elif mvmt == MOVEMENT_RIGHT and appr.rtor_allowed:
                    sat_rate = (self.sat_per_sec_per_lane * appr.lanes
                                * F_RT_ON_RED * appr.f_rt)
                else:
                    sat_rate = 0.0

                capacity_this_step = sat_rate * self.dt

                if out_link_id is None:
                    downstream_available = float("inf")
                else:
                    out_link = self.net.links[out_link_id]
                    if out_link.is_boundary_outbound:
                        downstream_available = float("inf")
                    else:
                        downstream_available = max(
                            0.0, out_link.storage_veh - out_link.queue
                        )

                served = min(queued_for_movement,
                             capacity_this_step,
                             downstream_available)

                if served > 0:
                    served_total += served
                    if out_link_id is not None:
                        outflow_to_downstream[out_link_id] = (
                            outflow_to_downstream.get(out_link_id, 0.0) + served
                        )
                    appr.served_this_step += served

            outflow_served[appr.inbound_link_id] = (
                outflow_served.get(appr.inbound_link_id, 0.0) + served_total
            )

    # -------------------------------------------------------------------------
    # Boundary outflow
    # -------------------------------------------------------------------------
    def _drain_boundary_outbound(
        self, outflow_to_downstream: Dict[str, float]
    ) -> float:
        total = 0.0
        for link_id in list(outflow_to_downstream.keys()):
            link = self.net.links[link_id]
            if link.is_boundary_outbound:
                veh = outflow_to_downstream.pop(link_id)
                link.cum_in += veh
                link.cum_out += veh
                total += veh
        return total

    # -------------------------------------------------------------------------
    # Aggregates
    # -------------------------------------------------------------------------
    def _update_approach_aggregates(self) -> None:
        for intx in self.net.intersections.values():
            for appr in intx.approaches.values():
                if appr.inbound_link_id is None:
                    continue
                link = self.net.links[appr.inbound_link_id]
                if link.queue > appr.max_queue:
                    appr.max_queue = link.queue
                appr.total_throughput += appr.served_this_step
                appr.total_delay += link.queue * self.dt
                appr.served_this_step = 0.0
                appr.arrivals_this_step = 0.0

    # -------------------------------------------------------------------------
    # Diagnostics
    # -------------------------------------------------------------------------
    def conservation_check(self) -> Dict[str, float]:
        """Vehicle-count conservation: injected = exited + still_queued."""
        queued_now = sum(
            l.queue for l in self.net.links.values()
            if not l.is_boundary_outbound
        )
        balance = self.total_external_in - self.total_throughput - queued_now

        return {
            "injected": self.total_external_in,
            "exited": self.total_throughput,
            "still_queued": queued_now,
            "balance_error": balance,
            "total_delay_vehsec": self.total_delay,
            "total_delay_vehhr": self.total_delay / 3600.0,
            "avg_delay_per_veh_sec": (
                self.total_delay / max(self.total_throughput, 1e-9)
            ),
            "spillback_events": self.spillback_events,
        }

    def run(self, duration_sec: float) -> Dict[str, float]:
        n_steps = int(round(duration_sec / self.dt))
        for _ in range(n_steps):
            self.step()
        return self.conservation_check()

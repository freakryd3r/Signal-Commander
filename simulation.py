"""Simulation core. Filled in Step 2.

Planned implementation:
  - Phase controller: advance each intersection's current phase based on
    time_in_phase vs. current phase total_time; wrap around and bump
    cycles_completed.
  - Outflow at stop bars:
      s_ij = min( queue/dt,
                  sat_flow * lanes * f_lt * f_rt * green_indicator(t),
                  (downstream_storage - downstream_queue) / dt )
  - Inflow from upstream turning movements (using approach turn ratios).
  - External demand injected at boundary inbound links.
  - Queue update: q(t+dt) = q(t) + dt * (u + d - s).
  - Delay accumulation: sum of (queue * dt) across all links and steps.
  - Conservation check: cum_in_boundary - cum_out_boundary == sum(queues).
"""


def step(net, demand, dt):
    """Advance the network one time step of `dt` seconds. TODO(Step 2)."""
    pass

"""Delay / LOS / benchmark scoring. Filled in Step 4.

Planned outputs:
  - total_delay (veh-sec and veh-hr)
  - avg_delay_per_vehicle (sec)
  - worst_approach_los (A..F per HCM Exhibit 19-8)
  - throughput (veh)
  - max_queue (veh and m)
  - spillback_events (count)
  - benchmarks: J_baseline (60s equal splits), J_webster (isolated optimum),
    J_optimum (pre-tuned for demo).
"""


def compute_score(net):
    """Return dict of scoring metrics. TODO(Step 4)."""
    return {}

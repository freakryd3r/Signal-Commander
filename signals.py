"""Signal phase plan construction. Controller logic (time-stepping) comes in Step 2."""

from constants import (
    DEFAULT_CYCLE, LOST_TIME_PER_PHASE, YELLOW_TIME, ALL_RED_TIME,
    NORTH, EAST, SOUTH, WEST,
)
from network import Phase, PhasePlan


def build_default_4phase_plan(cycle: float = DEFAULT_CYCLE) -> PhasePlan:
    """NEMA-style 4-phase plan with equal splits.

    Phases:
      1. EB + WB through/right (with permitted LT)
      2. EB + WB left (protected)
      3. NB + SB through/right (with permitted LT)
      4. NB + SB left (protected)

    Timing arithmetic (Y=yellow, AR=all-red, n=#phases):
        cycle = n * (g + Y + AR)
        g     = (cycle - n*(Y + AR)) / n
    With cycle=60, Y=3, AR=1, n=4 -> g = 11 per phase.
    Cycle check: 4 * (11 + 3 + 1) = 60. OK.
    """
    n_phases = 4
    clearance_per_phase = YELLOW_TIME + ALL_RED_TIME
    g = (cycle - n_phases * clearance_per_phase) / n_phases

    if g < 5.0:
        # Safeguard if cycle is too short; in practice the UI will enforce
        # MIN_CYCLE such that this branch is not taken.
        g = 5.0

    phases = [
        Phase(phase_id=1, effective_green=g,
              protected_movements=[(EAST, "T"), (EAST, "R"),
                                   (WEST, "T"), (WEST, "R")],
              permitted_movements=[(EAST, "L"), (WEST, "L")]),
        Phase(phase_id=2, effective_green=g,
              protected_movements=[(EAST, "L"), (WEST, "L")]),
        Phase(phase_id=3, effective_green=g,
              protected_movements=[(NORTH, "T"), (NORTH, "R"),
                                   (SOUTH, "T"), (SOUTH, "R")],
              permitted_movements=[(NORTH, "L"), (SOUTH, "L")]),
        Phase(phase_id=4, effective_green=g,
              protected_movements=[(NORTH, "L"), (SOUTH, "L")]),
    ]
    return PhasePlan(phases=phases, offset=0.0)

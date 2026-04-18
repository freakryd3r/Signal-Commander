"""Network construction and scenario loading."""

from typing import Dict
from constants import (
    GRID_ROWS, GRID_COLS, GRID_X0, GRID_Y0, GRID_SPACING,
    NORTH, EAST, SOUTH, WEST, DIRECTIONS, DIRECTION_NAMES, OPPOSITE,
    LEFT_OF, RIGHT_OF,
)
from network import Link, Approach, Intersection, Network
from signals import build_default_4phase_plan


def build_3x3_network() -> Network:
    """Construct the 3x3 grid with all 48 directed links and wire approaches."""
    net = Network()

    # ---- Create 9 intersections ----
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            node_id = f"I_{r}{c}"
            x = GRID_X0 + c * GRID_SPACING
            y = GRID_Y0 + r * GRID_SPACING
            approaches = {d: Approach(direction=d) for d in DIRECTIONS}
            intx = Intersection(
                node_id=node_id, row=r, col=c, x=x, y=y,
                approaches=approaches,
                phase_plan=build_default_4phase_plan(),
            )
            net.intersections[node_id] = intx

    # ---- Create 24 internal directed links ----
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            intx = net.get_intersection(r, c)

            # East neighbor => EB link + WB link
            if c < GRID_COLS - 1:
                east = net.get_intersection(r, c + 1)
                # EB: intx -> east, arrives at east's WEST approach
                _add_internal_link(net, f"{intx.node_id}_E_{east.node_id}",
                                   intx.node_id, east.node_id, east, WEST)
                # WB: east -> intx, arrives at intx's EAST approach
                _add_internal_link(net, f"{east.node_id}_W_{intx.node_id}",
                                   east.node_id, intx.node_id, intx, EAST)

            # South neighbor => SB link + NB link
            if r < GRID_ROWS - 1:
                south = net.get_intersection(r + 1, c)
                # SB: intx -> south, arrives at south's NORTH approach
                _add_internal_link(net, f"{intx.node_id}_S_{south.node_id}",
                                   intx.node_id, south.node_id, south, NORTH)
                # NB: south -> intx, arrives at intx's SOUTH approach
                _add_internal_link(net, f"{south.node_id}_N_{intx.node_id}",
                                   south.node_id, intx.node_id, intx, SOUTH)

    # ---- Create 24 boundary directed links (12 inbound + 12 outbound) ----
    # Top edge (row 0): NORTH side of each I_0c
    for c in range(GRID_COLS):
        intx = net.get_intersection(0, c)
        _add_boundary_link(net, f"BND_N{c}_in",  intx, NORTH, inbound=True)
        _add_boundary_link(net, f"BND_N{c}_out", intx, NORTH, inbound=False)
    # Bottom edge (row 2): SOUTH side of each I_2c
    for c in range(GRID_COLS):
        intx = net.get_intersection(2, c)
        _add_boundary_link(net, f"BND_S{c}_in",  intx, SOUTH, inbound=True)
        _add_boundary_link(net, f"BND_S{c}_out", intx, SOUTH, inbound=False)
    # Left edge (col 0): WEST side of each I_r0
    for r in range(GRID_ROWS):
        intx = net.get_intersection(r, 0)
        _add_boundary_link(net, f"BND_W{r}_in",  intx, WEST, inbound=True)
        _add_boundary_link(net, f"BND_W{r}_out", intx, WEST, inbound=False)
    # Right edge (col 2): EAST side of each I_r2
    for r in range(GRID_ROWS):
        intx = net.get_intersection(r, 2)
        _add_boundary_link(net, f"BND_E{r}_in",  intx, EAST, inbound=True)
        _add_boundary_link(net, f"BND_E{r}_out", intx, EAST, inbound=False)

    # ---- Wire each approach's outbound movement links ----
    _wire_outbound_links(net)

    return net


def _add_internal_link(net: Network, link_id: str, from_id: str, to_id: str,
                       to_intx: Intersection, approach_dir: int) -> None:
    """Create an internal directed link and attach it to the downstream approach."""
    link = Link(link_id=link_id, from_node=from_id, to_node=to_id,
                downstream_approach_dir=approach_dir)
    net.links[link_id] = link
    to_intx.approaches[approach_dir].inbound_link_id = link_id


def _add_boundary_link(net: Network, link_id: str, intx: Intersection,
                       direction: int, inbound: bool) -> None:
    """Create a boundary link.

    `direction` is the compass direction from `intx` toward the outside world.
      - inbound:  traffic arrives at intx's `direction` approach from outside.
      - outbound: traffic leaves intx through its `direction` side to outside.
    """
    if inbound:
        link = Link(
            link_id=link_id,
            from_node=link_id,              # boundary point named after link
            to_node=intx.node_id,
            downstream_approach_dir=direction,
            boundary_direction=direction,
            is_boundary_inbound=True,
        )
        intx.approaches[direction].inbound_link_id = link_id
        net.boundary_inbound.append(link_id)
    else:
        link = Link(
            link_id=link_id,
            from_node=intx.node_id,
            to_node=link_id,
            downstream_approach_dir=None,
            boundary_direction=direction,
            is_boundary_outbound=True,
        )
        net.boundary_outbound.append(link_id)
    net.links[link_id] = link


def _wire_outbound_links(net: Network) -> None:
    """For each approach at each intersection, identify outbound link for
    L / T / R movements.

    Convention:
      - approach.direction = compass direction traffic COMES FROM.
      - heading = OPPOSITE[approach.direction] = where driver is going.
      - THROUGH  exits via `heading`.
      - LEFT     exits via LEFT_OF[heading].
      - RIGHT    exits via RIGHT_OF[heading].
    """
    for intx in net.intersections.values():
        for appr_dir, appr in intx.approaches.items():
            heading = OPPOSITE[appr_dir]
            through_exit = heading
            left_exit = LEFT_OF[heading]
            right_exit = RIGHT_OF[heading]

            appr.out_through = _find_departing_link(net, intx, through_exit)
            appr.out_left = _find_departing_link(net, intx, left_exit)
            appr.out_right = _find_departing_link(net, intx, right_exit)


def _find_departing_link(net: Network, intx: Intersection,
                         exit_direction: int):
    """Find the link_id that departs `intx` heading toward `exit_direction`."""
    neighbor = net.adjacent_intersection(intx.row, intx.col, exit_direction)

    if neighbor is not None:
        # Internal departing link
        dir_char = DIRECTION_NAMES[exit_direction]
        link_id = f"{intx.node_id}_{dir_char}_{neighbor.node_id}"
        if link_id in net.links:
            return link_id
        return None

    # Boundary departing link, matching naming in _add_boundary_link
    if exit_direction == NORTH:
        return f"BND_N{intx.col}_out"
    if exit_direction == SOUTH:
        return f"BND_S{intx.col}_out"
    if exit_direction == EAST:
        return f"BND_E{intx.row}_out"
    if exit_direction == WEST:
        return f"BND_W{intx.row}_out"
    return None


# =============================================================================
# Demand scenarios
# =============================================================================
def load_am_peak_scenario(net: Network) -> Dict[str, float]:
    """Return {boundary_inbound_link_id: veh_per_hour}.

    AM peak pattern: heavier inflow from east and north (assumed CBD to west/south).
    """
    demand: Dict[str, float] = {}
    for link_id in net.boundary_inbound:
        if link_id.startswith("BND_E"):
            demand[link_id] = 800.0
        elif link_id.startswith("BND_W"):
            demand[link_id] = 400.0
        elif link_id.startswith("BND_N"):
            demand[link_id] = 500.0
        elif link_id.startswith("BND_S"):
            demand[link_id] = 500.0
    return demand

"""Drawing routines with simulation visualization.

Extends Step 1 rendering to show:
  - Link color coded by volume/capacity ratio (V/C)
  - Queues as rectangles at downstream stop bars (scaled to real storage)
  - Signal heads at each intersection showing active phase state
  - Live counters (time, total delay, throughput)
"""

import pygame
from constants import (
    SCREEN_W, SCREEN_H, LEFT_PANEL_W, RIGHT_PANEL_W, CANVAS_X0,
    GRID_SPACING, NORTH, SOUTH, EAST, WEST, DIRECTIONS,
    COLOR_BG, COLOR_PANEL, COLOR_LINK, COLOR_LINK_BOUNDARY,
    COLOR_INTERSECTION, COLOR_TEXT, COLOR_TEXT_DIM,
    COLOR_VC_GOOD, COLOR_VC_OK, COLOR_VC_BAD, COLOR_VC_CRITICAL,
    COLOR_QUEUE, COLOR_SIGNAL_RED, COLOR_SIGNAL_GREEN, COLOR_SIGNAL_YELLOW,
    SAT_FLOW_BASE, LANES_PER_APPROACH,
)
from simulation import movement_is_green


# =============================================================================
# Backgrounds and panels
# =============================================================================
def draw_background(screen: pygame.Surface) -> None:
    screen.fill(COLOR_BG)


def draw_panels(screen: pygame.Surface) -> None:
    pygame.draw.rect(screen, COLOR_PANEL, (0, 0, LEFT_PANEL_W, SCREEN_H))
    pygame.draw.rect(
        screen, COLOR_PANEL,
        (SCREEN_W - RIGHT_PANEL_W, 0, RIGHT_PANEL_W, SCREEN_H),
    )


def draw_panel_headers(screen: pygame.Surface, font: pygame.font.Font) -> None:
    left_hdr = font.render("SCENARIO", True, COLOR_TEXT)
    screen.blit(left_hdr, (20, 20))
    right_hdr = font.render("CONTROLS", True, COLOR_TEXT)
    screen.blit(right_hdr, (SCREEN_W - RIGHT_PANEL_W + 20, 20))


# =============================================================================
# Geometry helpers
# =============================================================================
def _boundary_endpoint(intx, direction: int):
    off = GRID_SPACING // 2
    if direction == NORTH:
        return (intx.x, intx.y - off)
    if direction == SOUTH:
        return (intx.x, intx.y + off)
    if direction == EAST:
        return (intx.x + off, intx.y)
    if direction == WEST:
        return (intx.x - off, intx.y)
    return (intx.x, intx.y)


def _vc_color(vc: float):
    """Return color for a given V/C ratio."""
    if vc < 0.7:
        return COLOR_VC_GOOD
    if vc < 0.9:
        return COLOR_VC_OK
    if vc < 1.0:
        return COLOR_VC_BAD
    return COLOR_VC_CRITICAL


def _link_vc(link) -> float:
    """Approximate V/C using queue occupancy as a proxy (queue / storage)."""
    if link.storage_veh <= 0:
        return 0.0
    return link.queue / link.storage_veh


# =============================================================================
# Links with V/C coloring
# =============================================================================
def draw_link(screen: pygame.Surface, net, link) -> None:
    from_intx = net.intersections.get(link.from_node)
    to_intx = net.intersections.get(link.to_node)

    if from_intx is not None and to_intx is not None:
        x0, y0 = from_intx.x, from_intx.y
        x1, y1 = to_intx.x, to_intx.y
        base_color = COLOR_LINK
    elif to_intx is not None and link.is_boundary_inbound:
        x0, y0 = _boundary_endpoint(to_intx, link.boundary_direction)
        x1, y1 = to_intx.x, to_intx.y
        base_color = COLOR_LINK_BOUNDARY
    elif from_intx is not None and link.is_boundary_outbound:
        x0, y0 = from_intx.x, from_intx.y
        x1, y1 = _boundary_endpoint(from_intx, link.boundary_direction)
        base_color = COLOR_LINK_BOUNDARY
    else:
        return

    # Perpendicular offset for driver's right-hand side
    dx = x1 - x0
    dy = y1 - y0
    length = max((dx * dx + dy * dy) ** 0.5, 1.0)
    perp_x = -dy / length
    perp_y = dx / length
    offset = 6
    x0o = x0 + perp_x * offset
    y0o = y0 + perp_y * offset
    x1o = x1 + perp_x * offset
    y1o = y1 + perp_y * offset

    # Color by V/C if this link has traffic
    if link.queue > 0.1 and not link.is_boundary_outbound:
        vc = _link_vc(link)
        color = _vc_color(vc)
    else:
        color = base_color

    pygame.draw.line(screen, color, (x0o, y0o), (x1o, y1o), 3)

    # Draw queue as a thicker segment near the downstream end
    if not link.is_boundary_outbound and link.queue > 0.5:
        _draw_queue(screen, link, x0o, y0o, x1o, y1o, perp_x, perp_y)


def _draw_queue(screen, link, x0, y0, x1, y1, perp_x, perp_y):
    """Draw the queued vehicles as a thicker yellow segment at the downstream end."""
    # Queue length in meters = queue * jam_spacing / lanes
    # Our link is 300m long. Visualize as fraction of link length.
    queue_frac = min(1.0, link.queue / link.storage_veh)
    dx = x1 - x0
    dy = y1 - y0
    # Start point of queue is queue_frac * length from the downstream end
    qx0 = x1 - dx * queue_frac
    qy0 = y1 - dy * queue_frac
    pygame.draw.line(screen, COLOR_QUEUE, (qx0, qy0), (x1, y1), 6)


# =============================================================================
# Intersection with signal head
# =============================================================================
def _signal_color_for_approach(intx, direction, global_time):
    """Return the color that should be shown for this approach's signal head.

    Green: THROUGH or LEFT currently has a protected/permitted green.
    Yellow: the active phase has ENTERED its clearance interval (yellow+all_red)
            AND this approach was protected during that phase's green.
    Red: neither condition (approach is currently stopped).
    """
    from constants import (
        COLOR_SIGNAL_GREEN, COLOR_SIGNAL_YELLOW, COLOR_SIGNAL_RED,
    )
    pp = intx.phase_plan
    if pp is None or not pp.phases:
        return COLOR_SIGNAL_RED

    local_t = (global_time + pp.offset) % pp.cycle_length

    # Find active phase
    elapsed = 0.0
    active = pp.phases[0]
    for phase in pp.phases:
        if elapsed + phase.total_time > local_t:
            active = phase
            break
        elapsed += phase.total_time

    time_in_phase = local_t - elapsed
    in_green = time_in_phase < active.effective_green
    in_clearance = (
        active.effective_green <= time_in_phase < active.total_time
    )

    # Is this approach's through OR left in the active phase's movement list?
    appr_in_active = any(
        d == direction for (d, _) in active.protected_movements
    ) or any(
        d == direction for (d, _) in active.permitted_movements
    )

    if appr_in_active and in_green:
        return COLOR_SIGNAL_GREEN
    if appr_in_active and in_clearance:
        return COLOR_SIGNAL_YELLOW
    return COLOR_SIGNAL_RED


def draw_intersection(screen: pygame.Surface, intx, global_time: float,
                      selected: bool = False) -> None:
    """Draw intersection box plus 4 small signal indicators (one per approach)."""
    if selected:
        # Highlight ring
        pygame.draw.rect(
            screen, (255, 220, 80),
            (intx.x - 18, intx.y - 18, 36, 36),
            width=2, border_radius=3,
        )

    pygame.draw.rect(
        screen, COLOR_INTERSECTION,
        (intx.x - 14, intx.y - 14, 28, 28),
    )

    sig_offsets = {
        NORTH: (0, -18),
        SOUTH: (0, 18),
        EAST: (18, 0),
        WEST: (-18, 0),
    }

    for d in DIRECTIONS:
        color = _signal_color_for_approach(intx, d, global_time)
        dx, dy = sig_offsets[d]
        pygame.draw.circle(screen, color, (int(intx.x + dx), int(intx.y + dy)), 4)


# =============================================================================
# Labels
# =============================================================================
def draw_labels(screen: pygame.Surface, net, font: pygame.font.Font) -> None:
    for intx in net.intersections.values():
        label = font.render(intx.node_id, True, COLOR_TEXT_DIM)
        screen.blit(label, (intx.x - 18, intx.y - 36))


# =============================================================================
# Scoreboard (in right panel, compact bar chart + key metrics)
# =============================================================================
COLOR_BAR_BASELINE = (200, 80, 80)       # red — the floor
COLOR_BAR_WEBSTER = (220, 170, 80)       # yellow — local-only
COLOR_BAR_OPTIMUM = (80, 200, 120)       # green — the ceiling
COLOR_BAR_CURRENT = (110, 170, 230)      # blue — you
COLOR_BAR_BEST = (170, 120, 220)         # purple — best so far


def draw_scoreboard(screen: pygame.Surface, score, font: pygame.font.Font,
                    big_font: pygame.font.Font, sim=None) -> None:
    """Compact scoreboard + essential network metrics in the right panel.

    Layout (placed below the intersection editor):
      - Header "SCOREBOARD (15-min delay, veh-hr)"
      - 5 colored bars: Baseline / Webster / Optimum / Current / Best
      - Summary: % vs baseline, gap to optimum
      - Small network metrics below (sim time, throughput, spillback)
    """
    x = SCREEN_W - RIGHT_PANEL_W + 20
    y = 570
    bar_w = 220
    bar_h = 14
    bar_gap = 6
    label_w = 110

    # Separator
    pygame.draw.line(
        screen, (90, 90, 110),
        (x, y - 12), (x + RIGHT_PANEL_W - 40, y - 12), 1,
    )

    hdr = font.render("SCOREBOARD (15-min delay, veh-hr)", True, COLOR_TEXT)
    screen.blit(hdr, (x, y - 4))
    y += 18

    max_val = max(
        score.baseline.delay_vehhr,
        score.webster.delay_vehhr,
        score.optimum.delay_vehhr,
        score.current_delay_vehhr,
        0.1,
    ) * 1.05

    bars = [
        ("Baseline",  score.baseline.delay_vehhr, COLOR_BAR_BASELINE),
        ("Webster",   score.webster.delay_vehhr,  COLOR_BAR_WEBSTER),
        ("Optimum",   score.optimum.delay_vehhr,  COLOR_BAR_OPTIMUM),
        ("Current",   score.current_delay_vehhr,  COLOR_BAR_CURRENT),
    ]
    if score.best_delay_vehhr != float("inf"):
        bars.append(("Best",  score.best_delay_vehhr,  COLOR_BAR_BEST))

    for label, val, color in bars:
        lbl = font.render(label, True, COLOR_TEXT_DIM)
        screen.blit(lbl, (x, y))
        bar_x = x + label_w
        frac = val / max_val if max_val > 0 else 0
        fill_w = int(bar_w * frac)
        pygame.draw.rect(
            screen, (70, 70, 85),
            (bar_x, y, bar_w, bar_h),
            width=1, border_radius=2,
        )
        if fill_w > 0:
            pygame.draw.rect(
                screen, color,
                (bar_x, y, fill_w, bar_h),
                border_radius=2,
            )
        val_str = f"{val:5.2f}"
        val_surf = font.render(val_str, True, COLOR_TEXT)
        screen.blit(val_surf, (bar_x + bar_w + 6, y - 1))
        y += bar_h + bar_gap

    # Summary
    y += 4
    if score.current_delay_vehhr > 0:
        pct = score.percent_improvement_over_baseline()
        sign = "+" if pct >= 0 else ""
        qual = "better" if pct >= 0 else "worse"
        msg = f"{sign}{pct:.1f}% vs baseline ({qual})"
        s = font.render(msg, True, COLOR_TEXT)
        screen.blit(s, (x, y))
        y += 16

        gap = score.gap_to_optimum()
        gap_msg = f"Gap to optimum: {gap * 100:+.0f}%"
        s = font.render(gap_msg, True, COLOR_TEXT_DIM)
        screen.blit(s, (x, y))
        y += 20

    # Small net metrics below if sim passed
    if sim is not None:
        pygame.draw.line(
            screen, (90, 90, 110),
            (x, y), (x + RIGHT_PANEL_W - 40, y), 1,
        )
        y += 8

        metrics = [
            f"t = {sim.global_time:5.1f} s   ({sim.total_external_in:5.0f} in, "
            f"{sim.total_throughput:5.0f} out)",
            f"in-network: {sim.total_external_in - sim.total_throughput:5.1f} veh",
            f"spillback events: {sim.spillback_events}",
        ]
        for m in metrics:
            s = font.render(m, True, COLOR_TEXT_DIM)
            screen.blit(s, (x, y))
            y += 16


# =============================================================================
# Scenario panel (left) — show current demand levels
# =============================================================================
def draw_scenario_panel(screen: pygame.Surface, demand: dict,
                        font: pygame.font.Font) -> None:
    x = 20
    y = 60
    title = font.render("Demand (vph)", True, COLOR_TEXT_DIM)
    screen.blit(title, (x, y))
    y += 20

    # Group by edge
    edges = {"N": [], "S": [], "E": [], "W": []}
    for link_id, vph in demand.items():
        edge_char = link_id.split("_")[1][0]  # "BND_N0_in" -> "N"
        edges[edge_char].append((link_id, vph))

    for edge_char, entries in edges.items():
        hdr = font.render(f"  {edge_char}:", True, COLOR_TEXT)
        screen.blit(hdr, (x, y))
        y += 16
        for link_id, vph in entries:
            line = font.render(f"    {vph:6.0f}", True, COLOR_TEXT_DIM)
            screen.blit(line, (x, y))
            y += 14
        y += 4

"""Drawing routines. Pure functions that take (screen, data) and draw."""

import pygame
from constants import (
    SCREEN_W, SCREEN_H, LEFT_PANEL_W, RIGHT_PANEL_W,
    GRID_SPACING, NORTH, SOUTH, EAST, WEST,
    COLOR_BG, COLOR_PANEL, COLOR_LINK, COLOR_LINK_BOUNDARY,
    COLOR_INTERSECTION, COLOR_TEXT,
)


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


def _boundary_endpoint(intx, direction: int):
    """Screen position for the off-grid end of a boundary link."""
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


def draw_link(screen: pygame.Surface, net, link) -> None:
    """Draw a directed link as a line offset to the right of the driver's
    direction of travel so opposing directions render as parallel lines.
    """
    from_intx = net.intersections.get(link.from_node)
    to_intx = net.intersections.get(link.to_node)

    if from_intx is not None and to_intx is not None:
        # Internal link
        x0, y0 = from_intx.x, from_intx.y
        x1, y1 = to_intx.x, to_intx.y
        color = COLOR_LINK
    elif to_intx is not None and link.is_boundary_inbound:
        # Inbound boundary: from off-grid point TO intersection
        x0, y0 = _boundary_endpoint(to_intx, link.boundary_direction)
        x1, y1 = to_intx.x, to_intx.y
        color = COLOR_LINK_BOUNDARY
    elif from_intx is not None and link.is_boundary_outbound:
        # Outbound boundary: from intersection TO off-grid point
        x0, y0 = from_intx.x, from_intx.y
        x1, y1 = _boundary_endpoint(from_intx, link.boundary_direction)
        color = COLOR_LINK_BOUNDARY
    else:
        return

    # Right-hand perpendicular offset. In pygame the y-axis grows downward,
    # so this formula yields the correct visual "right of direction of travel":
    #   East-bound (+x): shifted down  (south visually = driver's right)
    #   West-bound (-x): shifted up    (north visually = driver's right)
    #   South-bound (+y on screen, but SOUTH compass): shifted left (west = right)
    #   North-bound (-y on screen, NORTH compass): shifted right  (east = right)
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

    pygame.draw.line(screen, color, (x0o, y0o), (x1o, y1o), 3)


def draw_intersection(screen: pygame.Surface, intx) -> None:
    pygame.draw.rect(
        screen, COLOR_INTERSECTION,
        (intx.x - 12, intx.y - 12, 24, 24),
    )


def draw_labels(screen: pygame.Surface, net, font: pygame.font.Font) -> None:
    for intx in net.intersections.values():
        label = font.render(intx.node_id, True, COLOR_TEXT)
        screen.blit(label, (intx.x - 18, intx.y - 34))

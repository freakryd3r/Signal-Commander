# =============================================================
# SIGNAL LORD — UNIT CONVENTIONS
# =============================================================
# Distance:  meters (m)
# Time:      seconds (s)
# Speed:     meters per second (m/s)
# Flow:      vehicles per hour (veh/hr)
# Density:   vehicles per kilometer (veh/km)
# Angles:    radians internally, degrees only at display
#
# World space: meters, used for all simulation logic.
# Screen space: pixels, used only for rendering.
# Convert with world_to_screen() and screen_to_world() helpers.
#
# DO NOT mix units. Convert at display time only.
# =============================================================

# (units header comment block here)

from config import (
    CANVAS_WIDTH, CANVAS_HEIGHT, WORLD_MARGIN_M,
    DEFAULT_LINK_LENGTH_M, DEFAULT_ROWS, DEFAULT_COLS
)


class CoordinateSystem:
    """Maps between world space (meters) and screen space (pixels)."""

    def __init__(self, world_width_m, world_height_m):
        self.world_width_m = world_width_m
        self.world_height_m = world_height_m
        # Fit world into canvas with margin, preserving aspect ratio
        scale_x = CANVAS_WIDTH / (world_width_m + 2 * WORLD_MARGIN_M)
        scale_y = CANVAS_HEIGHT / (world_height_m + 2 * WORLD_MARGIN_M)
        self.scale = min(scale_x, scale_y)  # pixels per meter
        # Center the world in the canvas
        self.offset_x = (CANVAS_WIDTH - world_width_m * self.scale) / 2
        self.offset_y = (CANVAS_HEIGHT - world_height_m * self.scale) / 2

    def world_to_screen(self, x_m, y_m):
        px = self.offset_x + x_m * self.scale
        py = self.offset_y + y_m * self.scale
        return int(px), int(py)

    def screen_to_world(self, px, py):
        x_m = (px - self.offset_x) / self.scale
        y_m = (py - self.offset_y) / self.scale
        return x_m, y_m


class Intersection:
    """A signalized intersection node."""
    def __init__(self, intersection_id, x_m, y_m):
        self.id = intersection_id
        self.x_m = x_m
        self.y_m = y_m
        # Signal timing (filled in later phases)
        self.cycle_length = 60.0
        self.green_ns = 25.0
        self.green_ew = 25.0
        self.yellow = 3.0
        self.all_red = 2.0
        self.offset = 0.0
        self.rtor_allowed = True
        self.protected_left = False

    def __repr__(self):
        return f"Intersection({self.id} @ {self.x_m:.0f},{self.y_m:.0f})"


class Link:
    """A directed link between two intersections."""
    def __init__(self, link_id, from_intersection, to_intersection, length_m, lanes=2):
        self.id = link_id
        self.from_int = from_intersection
        self.to_int = to_intersection
        self.length_m = length_m
        self.lanes = lanes

    def __repr__(self):
        return f"Link({self.from_int.id}->{self.to_int.id}, {self.length_m:.0f}m)"


class Network:
    """Holds intersections, links, and the coordinate system."""
    def __init__(self, rows=DEFAULT_ROWS, cols=DEFAULT_COLS,
                 link_length_m=DEFAULT_LINK_LENGTH_M):
        self.rows = rows
        self.cols = cols
        self.intersections = {}
        self.links = {}
        self._build_grid(rows, cols, link_length_m)
        world_w = (cols - 1) * link_length_m
        world_h = (rows - 1) * link_length_m
        self.coords = CoordinateSystem(world_w, world_h)

    def _build_grid(self, rows, cols, L):
        # Create intersections
        for r in range(rows):
            for c in range(cols):
                iid = f"I_{r}_{c}"
                self.intersections[iid] = Intersection(iid, c * L, r * L)
        # Create links (both directions)
        link_count = 0
        for r in range(rows):
            for c in range(cols):
                here = self.intersections[f"I_{r}_{c}"]
                if c + 1 < cols:
                    right = self.intersections[f"I_{r}_{c+1}"]
                    self._add_link(link_count, here, right, L); link_count += 1
                    self._add_link(link_count, right, here, L); link_count += 1
                if r + 1 < rows:
                    down = self.intersections[f"I_{r+1}_{c}"]
                    self._add_link(link_count, here, down, L); link_count += 1
                    self._add_link(link_count, down, here, L); link_count += 1

    def _add_link(self, lid, a, b, length_m):
        self.links[lid] = Link(lid, a, b, length_m)

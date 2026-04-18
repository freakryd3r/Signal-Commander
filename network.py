"""
network.py

Grid-based network model for Signal Lord.

This file is the source of truth for:
- grid intersections
- internal links
- terminal source/sink nodes
- terminal links
- geometry
- routing graph

Important design choice:
- self.intersections = ONLY real grid intersections
- self.links = ONLY real internal grid links
- self.terminals = ONLY terminal/source/sink nodes
- self.terminal_links = ONLY links connecting terminals to perimeter intersections

This keeps UI editing clean while still giving simulation a full graph.
"""

import math
import networkx as nx

DEFAULT_LANES = 1

class Intersection:
    def __init__(self, id, row, col, x_m, y_m, is_terminal=False, terminal_type=None):
        self.id = id
        self.row = row
        self.col = col
        self.x_m = x_m
        self.y_m = y_m

        self.is_terminal = is_terminal
        self.terminal_type = terminal_type

        self.spawn_rate = 0

        self.cycle_length = 60
        self.green_ns = 30
        self.green_ew = 30
        self.offset = 0

    def get_position(self):
        return (self.x_m, self.y_m)


class Link:
    def __init__(self, id, from_int, to_int, length_m, lanes, is_terminal_link=False):
        self.id = id
        self.from_int = from_int
        self.to_int = to_int
        self.length_m = length_m
        self.lanes = lanes
        self.is_terminal_link = is_terminal_link

    def get_midpoint(self):
        return (
            (self.from_int.x_m + self.to_int.x_m) / 2,
            (self.from_int.y_m + self.to_int.y_m) / 2,
        )

    def is_horizontal(self):
        return self.from_int.row == self.to_int.row

    def is_vertical(self):
        return self.from_int.col == self.to_int.col


class Network:
    def is_perimeter(self, intersection_id):
        inter = self.get_real_intersection_by_id(intersection_id)
        if inter is None:
            return False

        return (
            inter.row == 0 or
            inter.row == self.rows - 1 or
            inter.col == 0 or
            inter.col == self.cols - 1
        )

    def get_terminal_links(self, intersection_id):
        """
        Returns terminal Link objects attached to the given real intersection.
        Returns [] for interior intersections or unknown IDs.
        """
        if not self.is_perimeter(intersection_id):
            return []

        attached = []
        for link in self.terminal_links:
            if link.from_int.id == intersection_id or link.to_int.id == intersection_id:
                attached.append(link)
        return attached

    def _get_edge_link_object(self, from_node_id, to_node_id):
        """
        Returns the Link object for a directed edge in the full graph.
        """
        if self.graph.has_edge(from_node_id, to_node_id):
            return self.graph[from_node_id][to_node_id]["obj"]
        return None

    def shortest_path(self, origin_id, dest_id, rng):
        """
        Returns a list of Link objects from origin terminal to destination terminal.

        Uses Dijkstra with per-agent perturbed weights:
            link.length_m * (1 + rng.uniform(-0.1, 0.1))

        Expected use:
        - origin_id should usually be an inbound terminal ID
        - dest_id should usually be an outbound terminal ID
        """
        if origin_id not in self.graph.nodes or dest_id not in self.graph.nodes:
            return []

        if origin_id == dest_id:
            return []

        # Build a temporary weighted graph with perturbed edge weights
        temp_graph = nx.DiGraph()

        for node_id, node_data in self.graph.nodes(data=True):
            temp_graph.add_node(node_id, **node_data)

        for u, v, edge_data in self.graph.edges(data=True):
            link = edge_data["obj"]

            perturb = rng.uniform(-0.1, 0.1)
            weight = link.length_m * (1 + perturb)

            # Extra safety so weight never becomes zero/negative
            weight = max(weight, 1e-6)

            temp_graph.add_edge(u, v, weight=weight)

        try:
            node_path = nx.shortest_path(temp_graph, origin_id, dest_id, weight="weight")
        except nx.NetworkXNoPath:
            return []
        except nx.NodeNotFound:
            return []

        link_path = []
        for i in range(len(node_path) - 1):
            u = node_path[i]
            v = node_path[i + 1]
            link = self._get_edge_link_object(u, v)
            if link is None:
                return []
            link_path.append(link)

        return link_path
    def __init__(self, rows, cols, link_length):
        self.rows = rows
        self.cols = cols
        self.default_link_length = link_length

        # Real grid objects only
        self.intersections = []
        self.links = []

        # Terminal objects only
        self.terminals = []
        self.terminal_links = []

        # Full graph used by simulation/routing
        self.graph = nx.DiGraph()

        # Grid geometry is controlled by row/column coordinates
        self.col_x = [c * link_length for c in range(cols)]
        self.row_y = [r * link_length for r in range(rows)]

        self.build_grid()
        self.build_terminals()
        self.rebuild_graph()

    # =========================================================
    # BASIC COLLECTION HELPERS
    # =========================================================
    def get_all_nodes(self):
        return self.intersections + self.terminals

    def get_all_links(self):
        return self.links + self.terminal_links

    # =========================================================
    # GRID CREATION
    # =========================================================
    def build_grid(self):
        self.intersections = []
        self.links = []

        # Create real grid intersections
        for r in range(self.rows):
            for c in range(self.cols):
                inter_id = f"I_{r}_{c}"
                x = self.col_x[c]
                y = self.row_y[r]
                self.intersections.append(
                    Intersection(inter_id, r, c, x, y, is_terminal=False, terminal_type=None)
                )

        # Create bidirectional internal links
        for r in range(self.rows):
            for c in range(self.cols):
                current = self.get_intersection(r, c)

                if c < self.cols - 1:
                    neighbor = self.get_intersection(r, c + 1)
                    self.add_bidirectional_link(current, neighbor)

                if r < self.rows - 1:
                    neighbor = self.get_intersection(r + 1, c)
                    self.add_bidirectional_link(current, neighbor)

        self.sync_internal_link_lengths_with_geometry()

    def rebuild_geometry(self):
        # Update real intersection geometry from row/col coordinate arrays
        for inter in self.intersections:
            inter.x_m = self.col_x[inter.col]
            inter.y_m = self.row_y[inter.row]

        # Terminals depend on perimeter geometry, so rebuild them too
        self.build_terminals()

        # Recompute all link lengths from actual geometry
        self.sync_internal_link_lengths_with_geometry()
        self.sync_terminal_link_lengths_with_geometry()

        # Keep graph weights up to date
        self.rebuild_graph()

    def get_intersection(self, r, c):
        return self.intersections[r * self.cols + c]

    def add_bidirectional_link(self, a, b):
        id1 = f"L_{a.id}_to_{b.id}"
        id2 = f"L_{b.id}_to_{a.id}"

        self.links.append(Link(id1, a, b, 0, DEFAULT_LANES, is_terminal_link=False))
        self.links.append(Link(id2, b, a, 0, DEFAULT_LANES, is_terminal_link=False))

    # =========================================================
    # TERMINALS
    # =========================================================
    def build_terminals(self):
        """
        Create source/sink terminal nodes and terminal links for every perimeter intersection.

        For each perimeter intersection, create:
        - one incoming terminal node and link into the network
        - one outgoing terminal node and link out of the network

        Example:
        T_IN_TOP_1  -> I_0_1
        I_0_1       -> T_OUT_TOP_1
        """
        self.terminals = []
        self.terminal_links = []

        offset = self.default_link_length * 0.5

        # Top edge
        for c in range(self.cols):
            base = self.get_intersection(0, c)
            self.add_terminal_pair(
                boundary_name="TOP",
                index=c,
                base_intersection=base,
                dx=0,
                dy=-offset
            )

        # Bottom edge
        for c in range(self.cols):
            base = self.get_intersection(self.rows - 1, c)
            self.add_terminal_pair(
                boundary_name="BOTTOM",
                index=c,
                base_intersection=base,
                dx=0,
                dy=offset
            )

        # Left edge
        for r in range(self.rows):
            base = self.get_intersection(r, 0)
            self.add_terminal_pair(
                boundary_name="LEFT",
                index=r,
                base_intersection=base,
                dx=-offset,
                dy=0
            )

        # Right edge
        for r in range(self.rows):
            base = self.get_intersection(r, self.cols - 1)
            self.add_terminal_pair(
                boundary_name="RIGHT",
                index=r,
                base_intersection=base,
                dx=offset,
                dy=0
            )

        self.sync_terminal_link_lengths_with_geometry()

    def add_terminal_pair(self, boundary_name, index, base_intersection, dx, dy):
        """
        Create one inbound and one outbound terminal for a perimeter intersection.
        """
        x = base_intersection.x_m + dx
        y = base_intersection.y_m + dy

        in_terminal = Intersection(
            id=f"T_IN_{boundary_name}_{index}",
            row=None,
            col=None,
            x_m=x,
            y_m=y,
            is_terminal=True,
            terminal_type="in"
        )

        out_terminal = Intersection(
            id=f"T_OUT_{boundary_name}_{index}",
            row=None,
            col=None,
            x_m=x,
            y_m=y,
            is_terminal=True,
            terminal_type="out"
        )

        self.terminals.append(in_terminal)
        self.terminals.append(out_terminal)

        in_link = Link(
            id=f"L_{in_terminal.id}_to_{base_intersection.id}",
            from_int=in_terminal,
            to_int=base_intersection,
            length_m=0,
            lanes=DEFAULT_LANES,
            is_terminal_link=True
        )

        out_link = Link(
            id=f"L_{base_intersection.id}_to_{out_terminal.id}",
            from_int=base_intersection,
            to_int=out_terminal,
            length_m=0,
            lanes=DEFAULT_LANES,
            is_terminal_link=True
        )

        self.terminal_links.append(in_link)
        self.terminal_links.append(out_link)

    # =========================================================
    # GRAPH
    # =========================================================
    def rebuild_graph(self):
        self.graph.clear()

        for node in self.get_all_nodes():
            self.graph.add_node(node.id, obj=node, is_terminal=node.is_terminal)

        for link in self.get_all_links():
            self.graph.add_edge(
                link.from_int.id,
                link.to_int.id,
                weight=link.length_m,
                obj=link,
                is_terminal_link=link.is_terminal_link
            )

    def get_shortest_path(self, origin_id, dest_id):
        try:
            return nx.shortest_path(
                self.graph,
                origin_id,
                dest_id,
                weight="weight"
            )
        except:
            return []

    # =========================================================
    # SELECTION HELPERS
    # =========================================================
    def get_intersection_at_point(self, x, y, threshold=10):
        """
        UI selection helper for real intersections only.
        Terminals are intentionally excluded so normal editing stays clean.
        """
        for inter in self.intersections:
            dx = inter.x_m - x
            dy = inter.y_m - y
            if math.sqrt(dx**2 + dy**2) < threshold:
                return inter
        return None

    def get_link_at_point(self, x, y, threshold=10):
        """
        UI selection helper for real internal links only.
        Terminal links are intentionally excluded from normal editing.
        """
        for link in self.links:
            if self._point_near_line(
                x, y,
                link.from_int.x_m, link.from_int.y_m,
                link.to_int.x_m, link.to_int.y_m,
                threshold
            ):
                return link
        return None

    def _point_near_line(self, px, py, x1, y1, x2, y2, threshold):
        line_mag = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
        if line_mag < 1e-6:
            return False

        u = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / (line_mag**2)

        if u < 0 or u > 1:
            return False

        ix = x1 + u * (x2 - x1)
        iy = y1 + u * (y2 - y1)

        dist = math.sqrt((px - ix)**2 + (py - iy)**2)
        return dist < threshold

    # =========================================================
    # GEOMETRY + LENGTH SYNC
    # =========================================================
    def sync_internal_link_lengths_with_geometry(self):
        for link in self.links:
            dx = link.to_int.x_m - link.from_int.x_m
            dy = link.to_int.y_m - link.from_int.y_m
            link.length_m = math.sqrt(dx**2 + dy**2)

    def sync_terminal_link_lengths_with_geometry(self):
        for link in self.terminal_links:
            dx = link.to_int.x_m - link.from_int.x_m
            dy = link.to_int.y_m - link.from_int.y_m
            link.length_m = math.sqrt(dx**2 + dy**2)

    def sync_all_link_lengths_with_geometry(self):
        self.sync_internal_link_lengths_with_geometry()
        self.sync_terminal_link_lengths_with_geometry()
        self.rebuild_graph()

    def update_link_length(self, link_id, new_length):
        """
        Geometry-aware internal link length update.

        If the link is horizontal, update spacing between the two columns.
        If the link is vertical, update spacing between the two rows.

        The downstream side moves as a block so the grid stays structured.
        """
        target_link = None
        for link in self.links:
            if link.id == link_id:
                target_link = link
                break

        if target_link is None:
            return

        if new_length <= 0:
            return

        a = target_link.from_int
        b = target_link.to_int

        # Horizontal link => change column spacing
        if a.row == b.row and a.col != b.col:
            left_col = min(a.col, b.col)
            right_col = max(a.col, b.col)

            old_gap = self.col_x[right_col] - self.col_x[left_col]
            delta = new_length - old_gap

            for c in range(right_col, self.cols):
                self.col_x[c] += delta

            self.rebuild_geometry()
            return

        # Vertical link => change row spacing
        if a.col == b.col and a.row != b.row:
            top_row = min(a.row, b.row)
            bottom_row = max(a.row, b.row)

            old_gap = self.row_y[bottom_row] - self.row_y[top_row]
            delta = new_length - old_gap

            for r in range(bottom_row, self.rows):
                self.row_y[r] += delta

            self.rebuild_geometry()
            return

    # =========================================================
    # OTHER EDIT FUNCTIONS
    # =========================================================
    def update_lanes(self, link_id, lanes):
        for link in self.links:
            if link.id == link_id:
                link.lanes = lanes
                break

    def update_signal(self, inter_id, cycle=None, green_ns=None, green_ew=None):
        for inter in self.intersections:
            if inter.id == inter_id:
                if cycle is not None:
                    inter.cycle_length = cycle
                if green_ns is not None:
                    inter.green_ns = green_ns
                if green_ew is not None:
                    inter.green_ew = green_ew
                break

    # =========================================================
    # OPTIONAL HELPERS FOR TEAMMATES
    # =========================================================
    def get_terminal_nodes(self):
        return self.terminals

    def get_terminal_links(self):
        return self.terminal_links

    def get_real_intersections(self):
        return self.intersections

    def get_internal_links(self):
        return self.links
        def get_inbound_terminals(self):
            return [t for t in self.terminals if t.terminal_type == "in"]

    def get_outbound_terminals(self):
        return [t for t in self.terminals if t.terminal_type == "out"]

    def get_terminal_by_id(self, terminal_id):
        for terminal in self.terminals:
            if terminal.id == terminal_id:
                return terminal
        return None

    def get_real_intersection_by_id(self, intersection_id):
        for inter in self.intersections:
            if inter.id == intersection_id:
                return inter
        return None

    def get_node_by_id(self, node_id):
        node = self.get_real_intersection_by_id(node_id)
        if node is not None:
            return node
        return self.get_terminal_by_id(node_id)

    def get_link_by_id(self, link_id):
        for link in self.get_all_links():
            if link.id == link_id:
                return link
        return None

    def get_reachable_outbound_terminals(self, origin_terminal_id):
        reachable = []
        for terminal in self.get_outbound_terminals():
            if nx.has_path(self.graph, origin_terminal_id, terminal.id):
                reachable.append(terminal)
        return reachable
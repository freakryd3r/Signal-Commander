import math
import networkx as nx
from config import DEFAULT_LANES


class Intersection:
    def __init__(
        self,
        id,
        row,
        col,
        x_m,
        y_m,
        is_terminal=False,
        terminal_type=None,
    ):
        self.id = id
        self.row = row
        self.col = col
        self.x_m = x_m
        self.y_m = y_m

        self.is_terminal = is_terminal
        self.terminal_type = terminal_type  # "in", "out", or None

        # Simulation-related placeholder
        self.spawn_rate = 0

        # Signal settings for real intersections
        self.cycle_length = 60
        self.green_ns = 30
        self.green_ew = 30
        self.offset = 0
        self.yellow_time = 4
        self.all_red_time = 1

    def get_position(self):
        return self.x_m, self.y_m
    def get_phase_time(self, sim_time_s):
        cycle = max(self.cycle_length, 1)
        return (sim_time_s - self.offset) % cycle

    def get_phase_state(self, sim_time_s):
        """
        Returns one of:
        - 'NS_GREEN'
        - 'NS_YELLOW'
        - 'ALL_RED_1'
        - 'EW_GREEN'
        - 'EW_YELLOW'
        - 'ALL_RED_2'
        """
        t = self.get_phase_time(sim_time_s)

        ns_green_end = self.green_ns
        ns_yellow_end = ns_green_end + self.yellow_time
        all_red_1_end = ns_yellow_end + self.all_red_time

        ew_green_end = all_red_1_end + self.green_ew
        ew_yellow_end = ew_green_end + self.yellow_time
        all_red_2_end = ew_yellow_end + self.all_red_time

        if t < ns_green_end:
            return "NS_GREEN"
        elif t < ns_yellow_end:
            return "NS_YELLOW"
        elif t < all_red_1_end:
            return "ALL_RED_1"
        elif t < ew_green_end:
            return "EW_GREEN"
        elif t < ew_yellow_end:
            return "EW_YELLOW"
        else:
            return "ALL_RED_2"
        
    def get_approach_signal(self, sim_time_s, approach):
        """
        approach should be one of:
        'N', 'S', 'E', 'W'

        Returns:
        'green', 'yellow', or 'red'
        """
        approach = approach.upper()
        phase = self.get_phase_state(sim_time_s)

        if approach in ["N", "S"]:
            if phase == "NS_GREEN":
                return "green"
            elif phase == "NS_YELLOW":
                return "yellow"
            else:
                return "red"

        if approach in ["E", "W"]:
            if phase == "EW_GREEN":
                return "green"
            elif phase == "EW_YELLOW":
                return "yellow"
            else:
                return "red"

        return "red"


class Link:
    def __init__(
        self,
        id,
        from_int,
        to_int,
        length_m,
        lanes,
        is_terminal_link=False,
        boundary_side=None,
        in_or_out=None,
    ):
        self.id = id
        self.from_int = from_int
        self.to_int = to_int
        self.length_m = length_m
        self.lanes = lanes

        self.is_terminal_link = is_terminal_link
        self.boundary_side = boundary_side  # "N", "S", "E", "W" for terminal links
        self.in_or_out = in_or_out          # "in" or "out" for terminal links

    def get_midpoint(self):
        return (
            (self.from_int.x_m + self.to_int.x_m) / 2,
            (self.from_int.y_m + self.to_int.y_m) / 2,
        )

    def direction_vector(self):
        dx = self.to_int.x_m - self.from_int.x_m
        dy = self.to_int.y_m - self.from_int.y_m
        length = max(math.sqrt(dx * dx + dy * dy), 1e-6)
        return dx / length, dy / length

    def angle(self):
        dx = self.to_int.x_m - self.from_int.x_m
        dy = self.to_int.y_m - self.from_int.y_m
        return math.atan2(dy, dx)

    def point_at_fraction(self, f):
        x = self.from_int.x_m + f * (self.to_int.x_m - self.from_int.x_m)
        y = self.from_int.y_m + f * (self.to_int.y_m - self.from_int.y_m)
        return x, y

    def is_horizontal(self):
        if self.from_int.row is None or self.to_int.row is None:
            return False
        return self.from_int.row == self.to_int.row

    def is_vertical(self):
        if self.from_int.col is None or self.to_int.col is None:
            return False
        return self.from_int.col == self.to_int.col


class Network:
    """
    Network contract:

    - self.intersections: real editable grid intersections only
    - self.links: real editable internal links only
    - self.terminals: inbound/outbound source-sink nodes
    - self.terminal_links: links connecting terminals to perimeter intersections
    - self.graph: full directed graph including all nodes and all links

    UI code should usually use:
    - get_intersection_at_point()
    - get_link_at_point()
    - get_terminal_nodes()
    - get_terminal_links()

    Simulation code should usually use:
    - get_inbound_terminals()
    - get_outbound_terminals()
    - get_inbound_terminal_links()
    - get_outbound_terminal_links()
    - get_terminal_link(...)
    - shortest_path(...)
    - get_node_by_id()
    - get_link_by_id()
    """

    def get_signal_state(self, intersection_id, sim_time_s, approach):
        inter = self.get_real_intersection_by_id(intersection_id)
        if inter is None:
            return None
        return inter.get_approach_signal(sim_time_s, approach)
    
    def __init__(self, rows, cols, link_length):
        self.rows = rows
        self.cols = cols
        self.default_link_length = link_length

        self.intersections = []
        self.links = []

        self.terminals = []
        self.terminal_links = []

        self.graph = nx.DiGraph()

        # Structured grid geometry
        self.col_x = [c * link_length for c in range(cols)]
        self.row_y = [r * link_length for r in range(rows)]

        self.build_grid()
        self.build_terminals()
        self.rebuild_graph()

    # =========================================================
    # COLLECTION HELPERS
    # =========================================================

    def get_all_nodes(self):
        return self.intersections + self.terminals

    def get_all_links(self):
        return self.links + self.terminal_links

    def get_real_intersections(self):
        return self.intersections

    def get_internal_links(self):
        return self.links

    def get_terminal_nodes(self):
        return self.terminals

    def get_terminal_links(self):
        return self.terminal_links

    def get_inbound_terminals(self):
        return [t for t in self.terminals if t.terminal_type == "in"]

    def get_outbound_terminals(self):
        return [t for t in self.terminals if t.terminal_type == "out"]

    def get_inbound_terminal_links(self):
        return [link for link in self.terminal_links if link.in_or_out == "in"]

    def get_outbound_terminal_links(self):
        return [link for link in self.terminal_links if link.in_or_out == "out"]

    # =========================================================
    # LOOKUP HELPERS
    # =========================================================

    def get_intersection(self, row, col):
        return self.intersections[row * self.cols + col]

    def get_real_intersection_by_id(self, intersection_id):
        for inter in self.intersections:
            if inter.id == intersection_id:
                return inter
        return None

    def get_terminal_by_id(self, terminal_id):
        for terminal in self.terminals:
            if terminal.id == terminal_id:
                return terminal
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

    def get_outgoing_links(self, node_id):
        return [link for link in self.get_all_links() if link.from_int.id == node_id]

    def get_incoming_links(self, node_id):
        return [link for link in self.get_all_links() if link.to_int.id == node_id]

    def path_length(self, link_path):
        return sum(link.length_m for link in link_path)

    # =========================================================
    # GRID CREATION
    # =========================================================

    def build_grid(self):
        self.intersections = []
        self.links = []

        for r in range(self.rows):
            for c in range(self.cols):
                inter_id = f"I_{r}_{c}"
                x = self.col_x[c]
                y = self.row_y[r]
                self.intersections.append(
                    Intersection(
                        id=inter_id,
                        row=r,
                        col=c,
                        x_m=x,
                        y_m=y,
                        is_terminal=False,
                        terminal_type=None,
                    )
                )

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

    def add_bidirectional_link(self, a, b):
        link_ab = Link(
            id=f"L_{a.id}_to_{b.id}",
            from_int=a,
            to_int=b,
            length_m=0,
            lanes=DEFAULT_LANES,
            is_terminal_link=False,
        )
        link_ba = Link(
            id=f"L_{b.id}_to_{a.id}",
            from_int=b,
            to_int=a,
            length_m=0,
            lanes=DEFAULT_LANES,
            is_terminal_link=False,
        )

        self.links.append(link_ab)
        self.links.append(link_ba)

    # =========================================================
    # TERMINALS
    # =========================================================

    def build_terminals(self):
        self.terminals = []
        self.terminal_links = []

        offset = self.default_link_length * 0.5

        for c in range(self.cols):
            base = self.get_intersection(0, c)
            self.add_terminal_pair("TOP", c, base, dx=0, dy=-offset)

        for c in range(self.cols):
            base = self.get_intersection(self.rows - 1, c)
            self.add_terminal_pair("BOTTOM", c, base, dx=0, dy=offset)

        for r in range(self.rows):
            base = self.get_intersection(r, 0)
            self.add_terminal_pair("LEFT", r, base, dx=-offset, dy=0)

        for r in range(self.rows):
            base = self.get_intersection(r, self.cols - 1)
            self.add_terminal_pair("RIGHT", r, base, dx=offset, dy=0)

        self.sync_terminal_link_lengths_with_geometry()

    def add_terminal_pair(self, boundary_name, index, base_intersection, dx, dy):
        side_map = {
            "TOP": "N",
            "BOTTOM": "S",
            "LEFT": "W",
            "RIGHT": "E",
        }
        boundary_side = side_map[boundary_name]

        x = base_intersection.x_m + dx
        y = base_intersection.y_m + dy

        in_terminal = Intersection(
            id=f"T_IN_{boundary_name}_{index}",
            row=None,
            col=None,
            x_m=x,
            y_m=y,
            is_terminal=True,
            terminal_type="in",
        )

        out_terminal = Intersection(
            id=f"T_OUT_{boundary_name}_{index}",
            row=None,
            col=None,
            x_m=x,
            y_m=y,
            is_terminal=True,
            terminal_type="out",
        )

        self.terminals.append(in_terminal)
        self.terminals.append(out_terminal)

        in_link = Link(
            id=f"L_{in_terminal.id}_to_{base_intersection.id}",
            from_int=in_terminal,
            to_int=base_intersection,
            length_m=0,
            lanes=DEFAULT_LANES,
            is_terminal_link=True,
            boundary_side=boundary_side,
            in_or_out="in",
        )

        out_link = Link(
            id=f"L_{base_intersection.id}_to_{out_terminal.id}",
            from_int=base_intersection,
            to_int=out_terminal,
            length_m=0,
            lanes=DEFAULT_LANES,
            is_terminal_link=True,
            boundary_side=boundary_side,
            in_or_out="out",
        )

        self.terminal_links.append(in_link)
        self.terminal_links.append(out_link)

    # =========================================================
    # GRAPH
    # =========================================================

    def rebuild_graph(self):
        self.graph = nx.DiGraph()

        for node in self.get_all_nodes():
            self.graph.add_node(node.id, obj=node, is_terminal=node.is_terminal)

        for link in self.get_all_links():
            self.graph.add_edge(
                link.from_int.id,
                link.to_int.id,
                weight=link.length_m,
                obj=link,
                is_terminal_link=link.is_terminal_link,
            )

    # =========================================================
    # GEOMETRY
    # =========================================================

    def rebuild_geometry(self):
        for inter in self.intersections:
            inter.x_m = self.col_x[inter.col]
            inter.y_m = self.row_y[inter.row]

        self.build_terminals()
        self.sync_internal_link_lengths_with_geometry()
        self.sync_terminal_link_lengths_with_geometry()
        self.rebuild_graph()

    def sync_internal_link_lengths_with_geometry(self):
        for link in self.links:
            dx = link.to_int.x_m - link.from_int.x_m
            dy = link.to_int.y_m - link.from_int.y_m
            link.length_m = math.sqrt(dx ** 2 + dy ** 2)

    def sync_terminal_link_lengths_with_geometry(self):
        for link in self.terminal_links:
            dx = link.to_int.x_m - link.from_int.x_m
            dy = link.to_int.y_m - link.from_int.y_m
            link.length_m = math.sqrt(dx ** 2 + dy ** 2)

    def sync_all_link_lengths_with_geometry(self):
        self.sync_internal_link_lengths_with_geometry()
        self.sync_terminal_link_lengths_with_geometry()
        self.rebuild_graph()

    def update_link_length(self, link_id, new_length):
        target_link = self.get_link_by_id(link_id)

        if target_link is None:
            return

        if target_link.is_terminal_link:
            return

        if new_length <= 0:
            return

        a = target_link.from_int
        b = target_link.to_int

        if a.row == b.row and a.col != b.col:
            left_col = min(a.col, b.col)
            right_col = max(a.col, b.col)

            old_gap = self.col_x[right_col] - self.col_x[left_col]
            delta = new_length - old_gap

            for c in range(right_col, self.cols):
                self.col_x[c] += delta

            self.rebuild_geometry()
            return

        if a.col == b.col and a.row != b.row:
            top_row = min(a.row, b.row)
            bottom_row = max(a.row, b.row)

            old_gap = self.row_y[bottom_row] - self.row_y[top_row]
            delta = new_length - old_gap

            for r in range(bottom_row, self.rows):
                self.row_y[r] += delta

            self.rebuild_geometry()
            return

    def update_lanes(self, link_id, lanes):
        # Lane count affects calculation only, not drawing geometry.
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
    # UI SELECTION HELPERS
    # =========================================================

    def get_intersection_at_point(self, x, y, threshold=10):
        for inter in self.intersections:
            dx = inter.x_m - x
            dy = inter.y_m - y
            if math.sqrt(dx ** 2 + dy ** 2) < threshold:
                return inter
        return None

    def get_link_at_point(self, x, y, threshold=10):
        for link in self.links:
            if self._point_near_line(
                x,
                y,
                link.from_int.x_m,
                link.from_int.y_m,
                link.to_int.x_m,
                link.to_int.y_m,
                threshold,
            ):
                return link
        return None

    def _point_near_line(self, px, py, x1, y1, x2, y2, threshold):
        line_mag = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        if line_mag < 1e-6:
            return False

        u = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / (line_mag ** 2)

        if u < 0 or u > 1:
            return False

        ix = x1 + u * (x2 - x1)
        iy = y1 + u * (y2 - y1)

        dist = math.sqrt((px - ix) ** 2 + (py - iy) ** 2)
        return dist < threshold

    # =========================================================
    # TERMINAL / PERIMETER HELPERS
    # =========================================================

    def is_perimeter(self, intersection_id):
        inter = self.get_real_intersection_by_id(intersection_id)
        if inter is None:
            return False

        return (
            inter.row == 0
            or inter.row == self.rows - 1
            or inter.col == 0
            or inter.col == self.cols - 1
        )

    def get_terminal_links_for_intersection(self, intersection_id):
        if not self.is_perimeter(intersection_id):
            return []

        attached = []
        for link in self.terminal_links:
            if link.from_int.id == intersection_id or link.to_int.id == intersection_id:
                attached.append(link)
        return attached

    def get_terminal_link(self, intersection_id, direction, in_or_out):
        if not self.is_perimeter(intersection_id):
            return None

        direction = direction.upper()
        in_or_out = in_or_out.lower()

        for link in self.terminal_links:
            attached = (
                link.from_int.id == intersection_id
                or link.to_int.id == intersection_id
            )

            if attached and link.boundary_side == direction and link.in_or_out == in_or_out:
                return link

        return None

    def _default_terminal_side(self, intersection_id):
        inter = self.get_real_intersection_by_id(intersection_id)
        if inter is None:
            return None

        if inter.row == 0:
            return "N"
        if inter.row == self.rows - 1:
            return "S"
        if inter.col == 0:
            return "W"
        if inter.col == self.cols - 1:
            return "E"

        return None

    def get_reachable_outbound_terminals(self, origin_terminal_id):
        reachable = []
        for terminal in self.get_outbound_terminals():
            if nx.has_path(self.graph, origin_terminal_id, terminal.id):
                reachable.append(terminal)
        return reachable

    # =========================================================
    # ROUTING
    # =========================================================

    def _get_edge_link_object(self, from_node_id, to_node_id):
        if self.graph.has_edge(from_node_id, to_node_id):
            return self.graph[from_node_id][to_node_id]["obj"]
        return None

    def shortest_path(self, origin_id, dest_id, rng):
        """
        Returns a list of Link objects for the shortest path.

        Supports:
        - terminal IDs directly, e.g. "T_IN_LEFT_1" -> "T_OUT_RIGHT_1"
        - perimeter intersection IDs, e.g. "I_1_0" -> "I_1_2"
        """

        # Case 1: both are already graph node IDs (like terminal IDs)
        if origin_id in self.graph.nodes and dest_id in self.graph.nodes:
            origin_node_id = origin_id
            dest_node_id = dest_id

        # Case 2: treat them as perimeter intersection IDs
        elif self.is_perimeter(origin_id) and self.is_perimeter(dest_id):
            origin_side = self._default_terminal_side(origin_id)
            dest_side = self._default_terminal_side(dest_id)

            if origin_side is None or dest_side is None:
                return []

            origin_entry_link = self.get_terminal_link(origin_id, origin_side, "in")
            dest_exit_link = self.get_terminal_link(dest_id, dest_side, "out")

            if origin_entry_link is None or dest_exit_link is None:
                return []

            origin_node_id = origin_entry_link.from_int.id
            dest_node_id = dest_exit_link.to_int.id

        else:
            return []

        temp_graph = nx.DiGraph()

        for node_id, node_data in self.graph.nodes(data=True):
            temp_graph.add_node(node_id, **node_data)

        for u, v, edge_data in self.graph.edges(data=True):
            link = edge_data["obj"]
            weight = link.length_m * (1 + rng.uniform(-0.1, 0.1))
            weight = max(weight, 1e-6)
            temp_graph.add_edge(u, v, weight=weight)

        try:
            node_path = nx.shortest_path(
                temp_graph,
                origin_node_id,
                dest_node_id,
                weight="weight",
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
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
    # =========================================================
    # DEMAND PRESETS
    # =========================================================

    def build_preset_demand(self, pattern_name="balanced"):
        """
        Returns:
            {terminal_link_id: demand_vph}

        Demand is assigned only to inbound terminal links.
        """
        demand = {}
        inbound_links = self.get_inbound_terminal_links()

        if len(inbound_links) == 0:
            return demand

        if pattern_name == "balanced":
            for link in inbound_links:
                demand[link.id] = 300

        elif pattern_name == "horizontal_heavy":
            for link in inbound_links:
                if link.boundary_side in ["E", "W"]:
                    demand[link.id] = 500
                else:
                    demand[link.id] = 200

        elif pattern_name == "vertical_heavy":
            for link in inbound_links:
                if link.boundary_side in ["N", "S"]:
                    demand[link.id] = 500
                else:
                    demand[link.id] = 200

        elif pattern_name == "one_side_surge":
            for link in inbound_links:
                if link.boundary_side == "W":
                    demand[link.id] = 700
                else:
                    demand[link.id] = 150

        else:
            for link in inbound_links:
                demand[link.id] = 300

        return demand

    def get_total_inbound_demand(self, pattern_name="balanced"):
        demand = self.build_preset_demand(pattern_name)
        return sum(demand.values())
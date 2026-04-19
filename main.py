import pygame
import pygame_gui
import math
import os
from datetime import datetime
from simulation import Simulation
from debug import setup_debug_one_car, setup_am_peak
from metrics import MetricsEngine, websters_optimal_cycle_simple
from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT, SIDEBAR_WIDTH, CANVAS_WIDTH,
    CANVAS_HEIGHT, FPS, BG_COLOR, GRID_BG, LINK_COLOR,
    INTERSECTION_COLOR, DEFAULT_LINK_LENGTH_M
)
from network import Network


TERMINAL_LINK_COLOR = (120, 120, 120)
TERMINAL_NODE_IN_COLOR = (80, 170, 255)
TERMINAL_NODE_OUT_COLOR = (255, 140, 140)
SELECTED_COLOR = (255, 220, 80)


def get_world_bounds(network):
    all_nodes = network.get_all_nodes()
    min_x = min(node.x_m for node in all_nodes)
    max_x = max(node.x_m for node in all_nodes)
    min_y = min(node.y_m for node in all_nodes)
    max_y = max(node.y_m for node in all_nodes)
    return min_x, max_x, min_y, max_y


def make_transform(network, canvas_width, canvas_height, margin=80):
    min_x, max_x, min_y, max_y = get_world_bounds(network)

    world_w = max(max_x - min_x, 1)
    world_h = max(max_y - min_y, 1)

    scale_x = (canvas_width - 2 * margin) / world_w
    scale_y = (canvas_height - 2 * margin) / world_h
    scale = min(scale_x, scale_y)

    def world_to_screen(x_m, y_m):
        sx = int((x_m - min_x) * scale + margin)
        sy = int((y_m - min_y) * scale + margin)
        return sx, sy

    def screen_to_world(x_px, y_px):
        wx = (x_px - margin) / scale + min_x
        wy = (y_px - margin) / scale + min_y
        return wx, wy

    return world_to_screen, screen_to_world


def safe_int(text, fallback):
    try:
        return int(text)
    except:
        return fallback

def draw_signal_head(screen, center_x, center_y, approach_angle_rad, phase_state):
    """
    Draw a vertical traffic signal head (red/yellow/green) at (center_x, center_y),
    oriented so the head faces the approaching traffic (pointing upstream).

    phase_state is one of "green", "yellow", "red".

    Head layout: three stacked circles. Unlit = dim, lit = bright.
    """
    # Small housing rectangle behind the lights for visual contrast
    housing_w = 14
    housing_h = 34
    # The housing is oriented perpendicular to approach direction
    perp_angle = approach_angle_rad + math.pi / 2

    # Compute the 4 corners of the housing rect (rotated)
    cx, cy = center_x, center_y
    cos_a = math.cos(approach_angle_rad)
    sin_a = math.sin(approach_angle_rad)

    def rotated_point(dx, dy):
        return (cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a)

    corners = [
        rotated_point(-housing_w / 2, -housing_h / 2),
        rotated_point(housing_w / 2, -housing_h / 2),
        rotated_point(housing_w / 2, housing_h / 2),
        rotated_point(-housing_w / 2, housing_h / 2),
    ]
    pygame.draw.polygon(screen, (30, 30, 35), corners)

    # Three circles, red (top) → yellow → green (bottom) along the perpendicular axis.
    # "Top" in the signal head is the side facing upstream traffic — we use -dy
    # along the approach direction to place it "in front of" the intersection.
    light_radius = 4
    light_spacing = 10

    bright_red = (240, 40, 40)
    dim_red = (70, 20, 20)
    bright_yel = (255, 210, 50)
    dim_yel = (70, 60, 20)
    bright_grn = (40, 220, 80)
    dim_grn = (20, 60, 25)

    red_color = bright_red if phase_state == "red" else dim_red
    yel_color = bright_yel if phase_state == "yellow" else dim_yel
    grn_color = bright_grn if phase_state == "green" else dim_grn

    # The three light positions along the housing's long axis
    # (which is the perpendicular to approach direction)
    red_pos = rotated_point(0, -light_spacing)
    yel_pos = rotated_point(0, 0)
    grn_pos = rotated_point(0, light_spacing)

    pygame.draw.circle(screen, red_color, (int(red_pos[0]), int(red_pos[1])), light_radius)
    pygame.draw.circle(screen, yel_color, (int(yel_pos[0]), int(yel_pos[1])), light_radius)
    pygame.draw.circle(screen, grn_color, (int(grn_pos[0]), int(grn_pos[1])), light_radius)

def main():
    pygame.init()
    pygame.display.set_caption("Signal Lord")
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.RESIZABLE)
    clock = pygame.time.Clock()

    manager = pygame_gui.UIManager((WINDOW_WIDTH, WINDOW_HEIGHT))

    pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 10), (SIDEBAR_WIDTH - 20, 30)),
        text="SIGNAL LORD",
        manager=manager,
        object_id="#sidebar_title"
    )

    setup_title_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 50), (SIDEBAR_WIDTH - 20, 24)),
        text="Create Network",
        manager=manager
    )
    network, sim = setup_am_peak()
    sim.pause()
    metrics_engine = MetricsEngine()
    heatmap_enabled = False
    pending_webster_recommendation = None

    # Phase 8 Block D: metrics update throttling
    # We recompute network + per-intersection metrics every 10 sim-seconds
    # to avoid unnecessary work on every frame. Cached here between updates.
    METRICS_UPDATE_INTERVAL_S = 10.0
    last_metrics_update_s = -1.0  # force immediate first update once time >= 0
    cached_net_metrics = None
    cached_intersection_metrics = {}  # keyed by intersection id

    rows_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 85), (120, 24)),
        text="Rows",
        manager=manager
    )
    rows_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 140, 85), (120, 28)),
        manager=manager
    )
    rows_input.set_text("3")

    cols_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 120), (120, 24)),
        text="Columns",
        manager=manager
    )
    cols_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 140, 120), (120, 28)),
        manager=manager
    )
    cols_input.set_text("3")

    default_length_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 155), (120, 24)),
        text="Link Length",
        manager=manager
    )
    default_length_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 140, 155), (120, 28)),
        manager=manager
    )
    default_length_input.set_text(str(DEFAULT_LINK_LENGTH_M))

    create_network_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 195), (160, 32)),
        text="Create Network",
        manager=manager
    )

    # Simulation control buttons
    start_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 580), (80, 32)),
        text="Start",
        manager=manager
    )

    pause_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 100, 580), (80, 32)),
        text="Pause",
        manager=manager
    )

    reset_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 190, 580), (80, 32)),
        text="Reset",
        manager=manager
    )

    realtime_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 535), (70, 32)),
        text="1x",
        manager=manager
    )
    fast5_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 90, 535), (70, 32)),
        text="5x",
        manager=manager
    )
    fast20_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 170, 535), (70, 32)),
        text="20x",
        manager=manager
    )
    fast60_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 250, 535), (70, 32)),
        text="60x",
        manager=manager
    )

    sim_status_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 620), (SIDEBAR_WIDTH - 20, 24)),
        text="PAUSED  |  t = 0.0s / 3600s  |  Speed: 1x",
        manager=manager
    )

    # ===== Phase 8 Block B: Metrics panel and action buttons =====

    # Horizontal separator visual (a simple thin label)
    pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 660), (SIDEBAR_WIDTH - 20, 24)),
        text="— NETWORK METRICS —",
        manager=manager
    )

    # Network metrics readout: 6 lines of key numbers
    net_completed_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 690), (SIDEBAR_WIDTH - 20, 22)),
        text="Completed trips: 0",
        manager=manager
    )

    net_active_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 712), (SIDEBAR_WIDTH - 20, 22)),
        text="Active vehicles: 0",
        manager=manager
    )

    net_delay_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 734), (SIDEBAR_WIDTH - 20, 22)),
        text="Mean delay: 0.0 s",
        manager=manager
    )

    net_tt_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 756), (SIDEBAR_WIDTH - 20, 22)),
        text="Mean travel time: 0.0 s",
        manager=manager
    )

    net_p85_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 778), (SIDEBAR_WIDTH - 20, 22)),
        text="85th %ile travel: 0.0 s",
        manager=manager
    )

    net_denied_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 800), (SIDEBAR_WIDTH - 20, 22)),
        text="Denied entries: 0",
        manager=manager
    )

    # Action buttons row
    webster_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 835), (170, 30)),
        text="Webster Optimal",
        manager=manager
    )

    apply_webster_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 185, 835), (80, 30)),
        text="Apply",
        manager=manager
    )
    apply_webster_button.disable()  # disabled until a recommendation is computed

    webster_result_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 870), (SIDEBAR_WIDTH - 20, 22)),
        text="",
        manager=manager
    )

    heatmap_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 905), (170, 30)),
        text="Heatmap: OFF",
        manager=manager
    )

    csv_export_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 185, 905), (80, 30)),
        text="Export CSV",
        manager=manager
    )

    info_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 245), (SIDEBAR_WIDTH - 20, 24)),
        text="Click an intersection or link",
        manager=manager
    )

    object_type_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 280), (SIDEBAR_WIDTH - 20, 24)),
        text="Type: None",
        manager=manager
    )

    field1_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 330), (120, 24)),
        text="Field 1",
        manager=manager
    )
    field1_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 140, 330), (120, 28)),
        manager=manager
    )

    field2_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 370), (120, 24)),
        text="Field 2",
        manager=manager
    )
    field2_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 140, 370), (120, 28)),
        manager=manager
    )

    field3_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 410), (120, 24)),
        text="Field 3",
        manager=manager
    )
    field3_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 140, 410), (120, 28)),
        manager=manager
    )

    apply_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 460), (120, 32)),
        text="Apply",
        manager=manager
    )

    status_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 500), (SIDEBAR_WIDTH - 20, 24)),
        text="",
        manager=manager
    )

    selected_intersection = None
    selected_link = None
    current_mode = "none"
    sim_time_accumulator = 0.0
    prev_agent_positions = {}

    def clear_fields():
        field1_input.set_text("")
        field2_input.set_text("")
        field3_input.set_text("")

    def load_intersection_fields(inter):
        nonlocal current_mode
        current_mode = "intersection"

        object_type_label.set_text("Type: Intersection")

        field1_label.set_text("Cycle")
        field2_label.set_text("Green NS")
        field3_label.set_text("Green EW")

        field1_input.set_text(str(inter.cycle_length))
        field2_input.set_text(str(inter.green_ns))
        field3_input.set_text(str(inter.green_ew))

        field3_label.show()
        field3_input.show()

        status_label.set_text("")

    def load_link_fields(link):
        nonlocal current_mode
        current_mode = "link"

        object_type_label.set_text("Type: Link")

        field1_label.set_text("Length")
        field2_label.set_text("Lanes")
        field3_label.set_text("")

        field1_input.set_text(str(int(link.length_m)))
        field2_input.set_text(str(link.lanes))
        field3_input.set_text("")

        field3_label.hide()
        field3_input.hide()

        status_label.set_text("")

    def clear_selection_ui():
        nonlocal current_mode
        current_mode = "none"

        object_type_label.set_text("Type: None")
        field1_label.set_text("Field 1")
        field2_label.set_text("Field 2")
        field3_label.set_text("Field 3")

        field3_label.show()
        field3_input.show()

        clear_fields()
        status_label.set_text("")

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                if hasattr(manager, 'set_window_resolution'):
                    manager.set_window_resolution((event.w, event.h))

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos

                if network is not None and mx < CANVAS_WIDTH:
                    wx, wy = screen_to_world(mx, my)

                    clicked_intersection = network.get_intersection_at_point(wx, wy, threshold=15)
                    clicked_link = None

                    if clicked_intersection is None:
                        clicked_link = network.get_link_at_point(wx, wy, threshold=12)

                    selected_intersection = clicked_intersection
                    selected_link = clicked_link

                    if selected_intersection is not None:
                        info_label.set_text(f"Intersection: {selected_intersection.id}")
                        load_intersection_fields(selected_intersection)

                    elif selected_link is not None:
                        info_label.set_text(f"Link: {selected_link.id}")
                        load_link_fields(selected_link)

                    else:
                        info_label.set_text("Click an intersection or link")
                        clear_selection_ui()

            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == create_network_button:
                    rows = safe_int(rows_input.get_text(), 3)
                    cols = safe_int(cols_input.get_text(), 3)
                    link_length = safe_int(default_length_input.get_text(), DEFAULT_LINK_LENGTH_M)

                    rows = max(1, min(rows, 10))
                    cols = max(1, min(cols, 10))
                    link_length = max(10, link_length)

                    network = Network(
                        rows=rows,
                        cols=cols,
                        link_length=link_length
                    )
                    sim = Simulation(network, seed=42)
                    sim.pause()

                    metrics_engine = MetricsEngine()
                    heatmap_enabled = False
                    pending_webster_recommendation = None
                    sim_time_accumulator = 0.0
                    selected_intersection = None
                    selected_link = None
                    info_label.set_text("Network created. Click an intersection or link.")
                    clear_selection_ui()
                    status_label.set_text("Network created (paused)")

                if event.ui_element == start_button and sim is not None:
                    if sim.state.sim_completed:
                        status_label.set_text("Simulation complete — press Reset")
                    else:
                        sim.resume()
                        status_label.set_text("Simulation started")

                if event.ui_element == pause_button and sim is not None:
                    sim.pause()
                    status_label.set_text("Simulation paused")

                if event.ui_element == reset_button and sim is not None:
                    # Full reset: clear agents and restart the scenario.
                    # Rebuild the debug scenario so cars re-spawn at t=0 and t=3.
                    network, sim = setup_am_peak()
                    sim.pause()
                    sim.set_speed(1)
                    metrics_engine = MetricsEngine()
                    pending_webster_recommendation = None
                    sim_time_accumulator = 0.0
                    selected_intersection = None
                    selected_link = None
                    status_label.set_text("Simulation reset (paused)")

                if event.ui_element == realtime_button and sim is not None:
                    sim.set_speed(1)
                    status_label.set_text("Speed: 1x (real time)")

                if event.ui_element == fast5_button and sim is not None:
                    sim.set_speed(5)
                    status_label.set_text("Speed: 5x")

                if event.ui_element == fast20_button and sim is not None:
                    sim.set_speed(20)
                    status_label.set_text("Speed: 20x")

                if event.ui_element == fast60_button and sim is not None:
                    sim.set_speed(60)
                    status_label.set_text("Speed: 60x")
                
                # ===== Phase 8 Block C: action button handlers =====

                if event.ui_element == webster_button and sim is not None:
                    # Compute Webster's optimal cycle for the currently
                    # selected intersection based on its measured last-cycle flows.
                    if current_mode != "intersection" or selected_intersection is None:
                        webster_result_label.set_text(
                            "Select an intersection first"
                        )
                    else:
                        istate = sim.state.intersections[selected_intersection.id]
                        try:
                            rec = websters_optimal_cycle_simple(
                                istate,
                                yellow_s=3.0,
                                all_red_s=2.0,
                            )
                            pending_webster_recommendation = {
                                "intersection_id": selected_intersection.id,
                                "cycle_length_s": rec["optimal_cycle_s"],
                                "green_ns_s": rec["green_ns_s"],
                                "green_ew_s": rec["green_ew_s"],
                                "was_clamped": rec["was_y_clamped"],
                            }
                            clamp_note = " [Y CLAMPED]" if rec["was_y_clamped"] else ""
                            webster_result_label.set_text(
                                f"C={rec['optimal_cycle_s']:.0f}s "
                                f"NS={rec['green_ns_s']:.0f} "
                                f"EW={rec['green_ew_s']:.0f}"
                                f"{clamp_note}"
                            )
                            apply_webster_button.enable()
                        except ValueError as err:
                            webster_result_label.set_text(f"Error: {err}")
                            pending_webster_recommendation = None
                            apply_webster_button.disable()

                if event.ui_element == apply_webster_button and sim is not None:
                    if pending_webster_recommendation is None:
                        webster_result_label.set_text("No recommendation pending")
                    else:
                        iid = pending_webster_recommendation["intersection_id"]
                        istate = sim.state.intersections.get(iid)
                        if istate is None:
                            webster_result_label.set_text("Intersection not found")
                        else:
                            # Queue the timing change at next NS_GREEN boundary.
                            # simulation.py applies pending_* fields on cycle entry.
                            istate.pending_cycle_length_s = pending_webster_recommendation["cycle_length_s"]
                            istate.pending_green_ns_s = pending_webster_recommendation["green_ns_s"]
                            istate.pending_green_ew_s = pending_webster_recommendation["green_ew_s"]
                            webster_result_label.set_text(
                                f"Applied to {iid} at next cycle"
                            )
                            pending_webster_recommendation = None
                            apply_webster_button.disable()

                if event.ui_element == heatmap_button:
                    heatmap_enabled = not heatmap_enabled
                    heatmap_button.set_text(
                        f"Heatmap: {'ON' if heatmap_enabled else 'OFF'}"
                    )

                if event.ui_element == csv_export_button and sim is not None:
                    # Export two CSV files with a timestamped suffix so
                    # multiple exports don't overwrite each other.
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    per_int_path = f"metrics_per_intersection_{timestamp}.csv"
                    net_path = f"metrics_network_{timestamp}.csv"
                    try:
                        metrics_engine.export_csv(
                            sim_state=sim.get_state(),
                            per_intersection_path=per_int_path,
                            network_path=net_path,
                        )
                        status_label.set_text(
                            f"CSV saved: {os.path.basename(per_int_path)}"
                        )
                    except Exception as err:
                        status_label.set_text(f"Export failed: {err}")

                if event.ui_element == apply_button and network is not None:
                    if current_mode == "intersection" and selected_intersection is not None:
                        cycle = safe_int(field1_input.get_text(), selected_intersection.cycle_length)
                        green_ns = safe_int(field2_input.get_text(), selected_intersection.green_ns)
                        green_ew = safe_int(field3_input.get_text(), selected_intersection.green_ew)

                        if cycle <= 0:
                            status_label.set_text("Cycle must be > 0")
                        elif green_ns < 0 or green_ew < 0:
                            status_label.set_text("Green times must be >= 0")
                        elif green_ns + green_ew > cycle:
                            status_label.set_text("Green NS + Green EW > cycle")
                        else:
                            network.update_signal(
                                selected_intersection.id,
                                cycle=cycle,
                                green_ns=green_ns,
                                green_ew=green_ew
                            )
                            load_intersection_fields(selected_intersection)
                            status_label.set_text("Intersection updated")

                    elif current_mode == "link" and selected_link is not None:
                        length_m = safe_int(field1_input.get_text(), int(selected_link.length_m))
                        lanes = safe_int(field2_input.get_text(), selected_link.lanes)

                        if length_m <= 0:
                            status_label.set_text("Length must be > 0")
                        elif lanes <= 0:
                            status_label.set_text("Lanes must be > 0")
                        else:
                            network.update_link_length(selected_link.id, length_m)
                            network.update_lanes(selected_link.id, lanes)
                            load_link_fields(selected_link)
                            status_label.set_text("Link updated")

            manager.process_events(event)

        manager.update(dt)

        # Refresh the sim status label every frame
        # Refresh the sim status label every frame
        if sim is not None:
            if sim.state.sim_completed:
                running_text = "COMPLETED"
            elif sim.state.sim_running:
                running_text = "RUNNING"
            else:
                running_text = "PAUSED"
            sim_status_label.set_text(
                f"{running_text}  |  t = {sim.state.time_s:.1f}s / 3600s  |  Speed: {sim.speed_multiplier}x"
            )

        # Refresh metric panels every METRICS_UPDATE_INTERVAL_S simulated seconds
        if sim is not None and sim.state.time_s - last_metrics_update_s >= METRICS_UPDATE_INTERVAL_S:
            last_metrics_update_s = sim.state.time_s
            state = sim.get_state()

            # Network-level metrics
            cached_net_metrics = metrics_engine.get_network_metrics()
            cached_intersection_metrics = metrics_engine.get_intersection_metrics(state)

            # Update sidebar labels
            net_completed_label.set_text(
                f"Completed trips: {int(cached_net_metrics['total_completed_trips'])}"
            )
            active_count = len([a for a in state.agents if a.active])
            net_active_label.set_text(f"Active vehicles: {active_count}")
            net_delay_label.set_text(
                f"Mean delay: {cached_net_metrics['network_mean_delay_s']:.1f} s"
            )
            net_tt_label.set_text(
                f"Mean travel time: {cached_net_metrics['mean_travel_time_s']:.1f} s"
            )
            net_p85_label.set_text(
                f"85th %ile travel: {cached_net_metrics['p85_travel_time_s']:.1f} s"
            )
            net_denied_label.set_text(
                f"Denied entries: {int(cached_net_metrics['denied_entries'])}"
            )

            # If an intersection is selected, update its live LOS info
            if (current_mode == "intersection"
                    and selected_intersection is not None
                    and selected_intersection.id in cached_intersection_metrics):
                im = cached_intersection_metrics[selected_intersection.id]
                info_label.set_text(
                    f"Intersection {selected_intersection.id} "
                    f"— LOS {im['los']} ({im['mean_delay_sec_per_veh']:.1f}s)"
                )

        # Physics stepping: accumulate wall-clock time × speed_multiplier,
        # advance sim at fixed 1-second timesteps to keep car-following stable.
        if sim is not None:
            sim_time_accumulator += sim.speed_multiplier * dt
            max_steps_per_frame = 500
            steps_taken = 0
            while sim_time_accumulator >= 1.0 and steps_taken < max_steps_per_frame:
                # Snapshot BEFORE stepping so we know where each agent was.
                # This becomes the "from" endpoint of interpolation.
                prev_agent_positions = {
                    a.id: (a.x_m, a.y_m, a.heading_rad)
                    for a in sim.agents
                    if a.active
                }
                sim.step(1.0)
                metrics_engine.update(sim.get_state())
                sim_time_accumulator -= 1.0
                steps_taken += 1
        if network is not None:
            world_to_screen, screen_to_world = make_transform(
                network,
                CANVAS_WIDTH,
                CANVAS_HEIGHT,
                margin=80
            )
        else:
            world_to_screen = None
            screen_to_world = None

        screen.fill(BG_COLOR)
        pygame.draw.rect(
            screen,
            GRID_BG,
            pygame.Rect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT)
        )

        if network is not None:
            for link in network.get_terminal_links():
                x1, y1 = world_to_screen(link.from_int.x_m, link.from_int.y_m)
                x2, y2 = world_to_screen(link.to_int.x_m, link.to_int.y_m)
                pygame.draw.line(screen, TERMINAL_LINK_COLOR, (x1, y1), (x2, y2), 2)

            for link in network.links:
                x1, y1 = world_to_screen(link.from_int.x_m, link.from_int.y_m)
                x2, y2 = world_to_screen(link.to_int.x_m, link.to_int.y_m)

                color = LINK_COLOR
                width = 4

                # Heatmap overlay: color by live link density
                if heatmap_enabled and sim is not None:
                    lstate = sim.state.links.get(link.id)
                    if lstate is not None:
                        color = metrics_engine.get_link_heatmap_color(
                            lstate.density_veh_per_km
                        )
                        width = 6

                if selected_link is not None and link.id == selected_link.id:
                    color = SELECTED_COLOR
                    width = 7

                pygame.draw.line(screen, color, (x1, y1), (x2, y2), width)

            for terminal in network.get_terminal_nodes():
                x, y = world_to_screen(terminal.x_m, terminal.y_m)

                if terminal.terminal_type == "in":
                    color = TERMINAL_NODE_IN_COLOR
                else:
                    color = TERMINAL_NODE_OUT_COLOR

                pygame.draw.circle(screen, color, (x, y), 6)

            for inter in network.intersections:
                x, y = world_to_screen(inter.x_m, inter.y_m)

                color = INTERSECTION_COLOR
                radius = 10

                if selected_intersection is not None and inter.id == selected_intersection.id:
                    color = SELECTED_COLOR
                    radius = 14

                pygame.draw.circle(screen, color, (x, y), radius)

            # Signal heads on each approach of each intersection.
            # Approach offset pulls the head back from the intersection center
            # so it sits on the approaching side of each link.
            signal_head_offset_px = 28

            for inter in network.intersections:
                cx, cy = world_to_screen(inter.x_m, inter.y_m)

                sig = sim.signals.get(inter.id) if sim is not None else None
                if sig is None:
                    continue

                # For each of the four approaches, determine angle and state.
                # Angle points from intersection outward toward approach origin.
                approaches = {
                    "N": -math.pi / 2,   # North approach: traffic comes from above
                    "S":  math.pi / 2,   # South approach: traffic comes from below
                    "E":  0.0,           # East approach: traffic comes from the right
                    "W":  math.pi,       # West approach: traffic comes from the left
                }

                for approach, angle in approaches.items():
                    # Place signal head slightly upstream on the approach side
                    hx = cx + signal_head_offset_px * math.cos(angle)
                    hy = cy + signal_head_offset_px * math.sin(angle)

                    if sig.is_green_for(approach):
                        state = "green"
                    elif sig.is_yellow_for(approach):
                        state = "yellow"
                    else:
                        state = "red"

                    draw_signal_head(screen, hx, hy, angle, state)

            # LOS badges: colored letter rendered above each intersection.
            # Uses the cached_intersection_metrics which refreshes every
            # METRICS_UPDATE_INTERVAL_S sim-seconds.
            los_badge_offset_px = 45  # how far above the intersection center
            los_font = pygame.font.SysFont("Arial", 18, bold=True)

            for inter in network.intersections:
                im = cached_intersection_metrics.get(inter.id)
                if im is None:
                    continue
                cx, cy = world_to_screen(inter.x_m, inter.y_m)
                badge_color = im["los_color"]
                badge_letter = im["los"]

                # Draw small circle backdrop + the letter inside it
                pygame.draw.circle(screen, badge_color, (cx, cy - los_badge_offset_px), 12)
                pygame.draw.circle(screen, (30, 30, 30), (cx, cy - los_badge_offset_px), 12, 1)
                text_surface = los_font.render(badge_letter, True, (255, 255, 255))
                text_rect = text_surface.get_rect(center=(cx, cy - los_badge_offset_px))
                screen.blit(text_surface, text_rect)


        manager.draw_ui(screen)
        if sim is not None:
            # Blend fraction: 0 right after a physics tick, approaching 1
            # just before the next tick fires.
            blend = min(sim_time_accumulator, 1.0)

            for agent in sim.get_agents():
                current_x = agent.x_m
                current_y = agent.y_m
                # If we have a prior snapshot of this agent, interpolate from there.
                # Otherwise render at current position (first frame after spawn).
                prev = prev_agent_positions.get(agent.id)
                if prev is not None:
                    prev_x, prev_y, _prev_heading = prev
                    interp_x = prev_x + (current_x - prev_x) * blend
                    interp_y = prev_y + (current_y - prev_y) * blend
                else:
                    interp_x = current_x
                    interp_y = current_y

                ax, ay = world_to_screen(interp_x, interp_y)

                if agent.agent_type == "bus":
                    color = (220, 80, 80)
                    radius = 7
                else:
                    color = (70, 130, 220)
                    radius = 5
                pygame.draw.circle(screen, color, (ax, ay), radius)
        
        # Simulation Complete overlay
        if sim is not None and sim.state.sim_completed:
            # Semi-transparent dark panel across the middle of the canvas
            overlay_w = 400
            overlay_h = 120
            overlay_x = (CANVAS_WIDTH - overlay_w) // 2
            overlay_y = (CANVAS_HEIGHT - overlay_h) // 2

            # Dark translucent background
            overlay_surface = pygame.Surface((overlay_w, overlay_h), pygame.SRCALPHA)
            overlay_surface.fill((20, 25, 35, 220))
            screen.blit(overlay_surface, (overlay_x, overlay_y))

            # Gold border
            pygame.draw.rect(
                screen,
                (220, 180, 60),
                pygame.Rect(overlay_x, overlay_y, overlay_w, overlay_h),
                3,
            )

            # Main text
            big_font = pygame.font.SysFont("Arial", 32, bold=True)
            small_font = pygame.font.SysFont("Arial", 16)
            line1 = big_font.render("SIMULATION COMPLETE", True, (255, 255, 255))
            line2 = small_font.render(
                f"1-hour run finished — click Reset to restart",
                True,
                (200, 200, 210),
            )
            line1_rect = line1.get_rect(center=(overlay_x + overlay_w // 2, overlay_y + 45))
            line2_rect = line2.get_rect(center=(overlay_x + overlay_w // 2, overlay_y + 85))
            screen.blit(line1, line1_rect)
            screen.blit(line2, line2_rect)

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
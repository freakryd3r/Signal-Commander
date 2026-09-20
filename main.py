import pygame
import pygame_gui
import math
import os
from datetime import datetime
from simulation import Simulation
from debug import setup_am_peak
from metrics import MetricsEngine, compute_network_score
from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT, SIDEBAR_WIDTH,
    FPS, BG_COLOR, GRID_BG, LINK_COLOR,
    INTERSECTION_COLOR, DEFAULT_LINK_LENGTH_M, INTERGREEN_S,
    SIM_DURATION_S,
)
from network import Network


TERMINAL_LINK_COLOR = (120, 120, 120)
TERMINAL_NODE_IN_COLOR = (80, 170, 255)
TERMINAL_NODE_OUT_COLOR = (255, 140, 140)
SELECTED_COLOR = (255, 220, 80)
SIDEBAR_TOP_OFFSET = 85  # pushes sidebar widgets below the SIGNAL COMMANDER title

# These are recomputed in main() from the live window width so the sidebar
# anchors to the right edge of any resolution instead of a hardcoded 1400.
SIDEBAR_LEFT = WINDOW_WIDTH - SIDEBAR_WIDTH
SIDEBAR_INPUT_X = SIDEBAR_LEFT + 130
SIDEBAR_CENTER = SIDEBAR_LEFT + SIDEBAR_WIDTH // 2

# Click-hit thresholds in SCREEN PIXELS. Converted to world meters at click
# time using the live transform's pixels_per_meter, so click tolerance stays
# constant regardless of network size or window size.
INT_CLICK_PX = 15
LINK_CLICK_PX = 12
TERMINAL_NODE_CLICK_PX = 10
TERMINAL_LINK_CLICK_PX = 12


def center_x(widget_width):
    """Return x-coordinate to center a widget of given width on the sidebar centerline."""
    return SIDEBAR_CENTER - widget_width // 2

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
    scale = min(scale_x, scale_y)  # pixels per meter

    def world_to_screen(x_m, y_m):
        sx = int((x_m - min_x) * scale + margin)
        sy = int((y_m - min_y) * scale + margin)
        return sx, sy

    def screen_to_world(x_px, y_px):
        wx = (x_px - margin) / scale + min_x
        wy = (y_px - margin) / scale + min_y
        return wx, wy

    return world_to_screen, screen_to_world, scale


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
    global SIDEBAR_LEFT, SIDEBAR_INPUT_X, SIDEBAR_CENTER

    pygame.init()
    pygame.display.set_caption("Signal Commander")
    info = pygame.display.Info()
    screen = pygame.display.set_mode(
        (info.current_w, info.current_h),
        pygame.FULLSCREEN | pygame.RESIZABLE,
    )
    clock = pygame.time.Clock()

    # Anchor sidebar to the right edge of the actual display, not the
    # hardcoded 1400 in the config fallback. All center_x() calls and
    # widget rects below read these module-level anchors, so setting them
    # here before any widget is created is what makes the initial layout
    # right on any resolution.
    SIDEBAR_LEFT = info.current_w - SIDEBAR_WIDTH
    SIDEBAR_INPUT_X = SIDEBAR_LEFT + 130
    SIDEBAR_CENTER = SIDEBAR_LEFT + SIDEBAR_WIDTH // 2

    manager = pygame_gui.UIManager((info.current_w, info.current_h))

    # Pre-create fonts once — SysFont per frame allocates a new font object
    # every tick, which is wasteful. All render loops below reuse these.
    los_font = pygame.font.SysFont("Arial", 18, bold=True)
    try:
        header_title_font = pygame.font.SysFont("Impact", 32, bold=False)
    except Exception:
        header_title_font = pygame.font.SysFont("Arial", 32, bold=False)
    overlay_title_font = pygame.font.SysFont("Arial", 22, bold=False)
    overlay_score_font = pygame.font.SysFont("Impact", 58, bold=False)
    overlay_rating_font = pygame.font.SysFont("Arial", 22, bold=False)
    overlay_small_font = pygame.font.SysFont("Arial", 14)
    overlay_grid_font = pygame.font.SysFont("Arial", 14)

    # Setup title label (centered)
    setup_title_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(60), 50), (160, 32)),
        text="Create Network",
        manager=manager
    )

    network, sim = setup_am_peak()
    sim.pause()
    metrics_engine = MetricsEngine()
    heatmap_enabled = False

    METRICS_UPDATE_INTERVAL_S = 10.0
    last_metrics_update_s = -1.0
    cached_net_metrics = None
    cached_intersection_metrics = {}

    # Rows row (label + input, combined width 250, centered)
    row_y = 85
    rows_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(110), row_y), (120, 24)),
        text="Rows",
        manager=manager
    )
    rows_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((center_x(200) + 130, row_y), (120, 28)),
        manager=manager
    )
    rows_input.set_text("3")

    row_y = 120
    cols_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(130), row_y), (120, 24)),
        text="Columns",
        manager=manager
    )
    cols_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((center_x(200) + 130, row_y), (120, 28)),
        manager=manager
    )
    cols_input.set_text("3")

    row_y = 155
    default_length_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(150), row_y), (120, 24)),
        text="Link Length",
        manager=manager
    )
    default_length_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((center_x(200) + 130, row_y), (120, 28)),
        manager=manager
    )
    default_length_input.set_text(str(DEFAULT_LINK_LENGTH_M))

    create_network_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((center_x(60), 195), (160, 32)),
        text="Create Network",
        manager=manager
    )

    # Info + type labels (centered)
    info_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(SIDEBAR_WIDTH), 235), (SIDEBAR_WIDTH + 80, 24)),
        text="Click an intersection or link",
        manager=manager
    )
    object_type_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(SIDEBAR_WIDTH), 265), (SIDEBAR_WIDTH +80, 24)),
        text="Type: None",
        manager=manager
    )

    # Fields (label + input rows, centered)
    row_y = 295
    field1_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(250), row_y), (150, 24)),
        text="Field 1",
        manager=manager
    )
    field1_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((center_x(250) + 130, row_y), (150, 28)),
        manager=manager
    )

    row_y = 330
    field2_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(250), row_y), (150, 24)),
        text="Field 2",
        manager=manager
    )
    field2_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((center_x(250) + 130, row_y), (150, 28)),
        manager=manager
    )

    row_y = 365
    field3_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(250), row_y), (150, 24)),
        text="Field 3",
        manager=manager
    )
    field3_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((center_x(250) + 130, row_y), (150, 28)),
        manager=manager
    )

    row_y = 400
    field4_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(250), row_y), (150, 24)),
        text="Field 4",
        manager=manager
    )
    field4_input = pygame_gui.elements.UITextEntryLine(
        relative_rect=pygame.Rect((center_x(250) + 130, row_y), (150, 28)),
        manager=manager
    )

    apply_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((center_x(85), 440), (200, 32)),
        text="Apply",
        manager=manager
    )

    status_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(SIDEBAR_WIDTH), 480), (SIDEBAR_WIDTH + 80, 24)),
        text="",
        manager=manager
    )

    # Speed buttons (1x / 5x / 20x / 60x) — 4 buttons in a row, centered
    # Each 70px wide, 10px gap → total width 310
    fast_row_total = 4 * 70 + 3 * 10  # 310
    fast_row_left = center_x(fast_row_total)
    row_y = 515
    realtime_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((fast_row_left +50, row_y), (70, 32)),
        text="1x",
        manager=manager
    )
    fast5_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((fast_row_left + 130, row_y), (70, 32)),
        text="5x",
        manager=manager
    )
    fast20_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((fast_row_left + 210, row_y), (70, 32)),
        text="20x",
        manager=manager
    )
    fast60_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((fast_row_left + 290, row_y), (70, 32)),
        text="60x",
        manager=manager
    )

    # Sim control buttons (Start / Pause / Reset) — 3 buttons, centered
    sim_row_total = 3 * 80 + 2 * 10  # 260
    sim_row_left = center_x(sim_row_total)
    row_y = 550
    start_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((sim_row_left+ 50, row_y), (80, 32)),
        text="Start",
        manager=manager
    )
    pause_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((sim_row_left + 140, row_y), (80, 32)),
        text="Pause",
        manager=manager
    )
    reset_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((sim_row_left + 230, row_y), (80, 32)),
        text="Reset",
        manager=manager
    )

    sim_status_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(SIDEBAR_WIDTH + 50), 585), (SIDEBAR_WIDTH + 150, 24)),
        text=f"PAUSED | t = 0.0s / {int(SIM_DURATION_S)}s | Speed: 1x",
        manager=manager
    )

    # Network metrics separator
    # Horizontal separator visual — toggles between network and intersection mode
    metrics_header_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(SIDEBAR_WIDTH - 20), 620), (SIDEBAR_WIDTH + 80, 24)),
        text="— NETWORK METRICS —",
        manager=manager
    )

    # Network metrics labels (centered)
    net_completed_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(SIDEBAR_WIDTH - 20), 642), (SIDEBAR_WIDTH + 80, 22)),
        text="Completed trips: 0",
        manager=manager
    )
    net_active_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(SIDEBAR_WIDTH - 20), 664), (SIDEBAR_WIDTH + 80, 22)),
        text="Active vehicles: 0",
        manager=manager
    )
    net_delay_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(SIDEBAR_WIDTH - 20), 686), (SIDEBAR_WIDTH + 80, 22)),
        text="Mean delay: 0.0 s",
        manager=manager
    )
    net_tt_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(SIDEBAR_WIDTH - 20), 708), (SIDEBAR_WIDTH + 80, 22)),
        text="Mean travel time: 0.0 s",
        manager=manager
    )
    net_p85_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(SIDEBAR_WIDTH - 20), 730), (SIDEBAR_WIDTH + 80, 22)),
        text="85th %ile travel: 0.0 s",
        manager=manager
    )
    net_denied_label = pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect((center_x(SIDEBAR_WIDTH - 20), 752), (SIDEBAR_WIDTH + 80, 22)),
        text="Denied entries: 0",
        manager=manager
    )

    # Heatmap + CSV row (170 + 10 + 80 = 260 wide, centered)
    heatmap_row_left = center_x(260)
    row_y = 820
    heatmap_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((heatmap_row_left + 40, row_y), (170, 30)),
        text="Heatmap: OFF",
        manager=manager
    )
    csv_export_button = pygame_gui.elements.UIButton(
        relative_rect=pygame.Rect((heatmap_row_left + 220, row_y), (80, 30)),
        text="Export CSV",
        manager=manager
    )


    selected_intersection = None
    selected_link = None
    current_mode = "none"
    sim_time_accumulator = 0.0
    cached_final_score = None
    is_fullscreen = True
    windowed_size = (WINDOW_WIDTH, WINDOW_HEIGHT)
    prev_agent_positions = {}


    def clear_fields():
        field1_input.set_text("")
        field2_input.set_text("")
        field3_input.set_text("")
        field4_input.set_text("")

    def load_intersection_fields(inter):
        nonlocal current_mode
        current_mode = "intersection"

        object_type_label.set_text(
            f"Type: Intersection  (Cycle auto: {int(inter.cycle_length)} s)"
        )

        field1_label.set_text("Green NS")
        field2_label.set_text("Green EW")
        field3_label.set_text("Offset")
        field4_label.set_text("")

        field1_input.set_text(str(inter.green_ns))
        field2_input.set_text(str(inter.green_ew))
        field3_input.set_text(str(inter.offset))
        field4_input.set_text("")

        field2_label.show()
        field2_input.show()
        field3_label.show()
        field3_input.show()
        field4_label.hide()
        field4_input.hide()

        status_label.set_text("")

    def load_link_fields(link):
        nonlocal current_mode
        current_mode = "link"

        object_type_label.set_text("Type: Link")

        field1_label.set_text("Length")
        field2_label.set_text("Lanes")
        field3_label.set_text("")
        field4_label.set_text("")

        field1_input.set_text(str(int(link.length_m)))
        field2_input.set_text(str(link.lanes))
        field3_input.set_text("")
        field4_input.set_text("")

        field2_label.show()
        field2_input.show()
        field3_label.hide()
        field3_input.hide()
        field4_label.hide()
        field4_input.hide()

        status_label.set_text("")
    
    def load_terminal_fields(terminal_link):
        nonlocal current_mode
        current_mode = "terminal"

        # Effective demand shown in the type label. If the terminal has no
        # manual override, this reflects the OD-derived contribution so the
        # user sees what the scenario is actually sending through this
        # terminal, not just the (zero) override.
        effective_vph = 0.0
        if sim is not None:
            effective_vph = sim.effective_inflow_vph(terminal_link)
        source = "manual" if terminal_link.inflow_vph > 0 else "OD"
        object_type_label.set_text(
            f"Type: Inbound Terminal  (effective {int(effective_vph)} veh/hr, {source})"
        )

        field1_label.set_text("Inflow (veh/hr)")
        field2_label.set_text("")
        field3_label.set_text("")
        field4_label.set_text("")

        # Manual override value only — 0 means "no override, use OD".
        field1_input.set_text(str(int(terminal_link.inflow_vph)))
        field2_input.set_text("")
        field3_input.set_text("")
        field4_input.set_text("")

        field2_label.hide()
        field2_input.hide()
        field3_label.hide()
        field3_input.hide()
        field4_label.hide()
        field4_input.hide()

        status_label.set_text("")

    def clear_selection_ui():
        nonlocal current_mode
        current_mode = "none"

        object_type_label.set_text("Type: None")
        field1_label.set_text("Field 1")
        field2_label.set_text("Field 2")
        field3_label.set_text("Field 3")
        field4_label.set_text("Field 4")

        field2_label.show()
        field2_input.show()
        field3_label.show()
        field3_input.show()
        field4_label.show()
        field4_input.show()

        clear_fields()
        status_label.set_text("")

    # Initialize transforms before the first frame so the first-frame click
    # handler can call screen_to_world without a NameError. They are
    # recomputed each frame below from the live window size.
    pixels_per_meter = 1.0
    if network is not None:
        world_to_screen, screen_to_world, pixels_per_meter = make_transform(
            network,
            SIDEBAR_LEFT,
            info.current_h,
            margin=80,
        )
    else:
        world_to_screen = None
        screen_to_world = None

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                windowed_size = (event.w, event.h)  # remember size for fullscreen toggle
                if hasattr(manager, 'set_window_resolution'):
                    manager.set_window_resolution((event.w, event.h))

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos

                if network is not None and mx < SIDEBAR_LEFT:
                    wx, wy = screen_to_world(mx, my)

                    # Convert pixel-radius click targets to world meters using
                    # the live transform, so click tolerance is constant on
                    # screen regardless of network size or window size.
                    m_per_px = 1.0 / max(pixels_per_meter, 1e-6)
                    int_threshold_m = INT_CLICK_PX * m_per_px
                    link_threshold_m = LINK_CLICK_PX * m_per_px
                    tnode_threshold_m = TERMINAL_NODE_CLICK_PX * m_per_px
                    tlink_threshold_m = TERMINAL_LINK_CLICK_PX * m_per_px

                    clicked_intersection = network.get_intersection_at_point(wx, wy, threshold=int_threshold_m)
                    clicked_link = None
                    clicked_terminal_link = None

                    # Check for terminal node click first (blue in / red out dots)
                    if clicked_intersection is None:
                        for terminal in network.get_terminal_nodes():
                            dx = terminal.x_m - wx
                            dy = terminal.y_m - wy
                            if (dx * dx + dy * dy) ** 0.5 < tnode_threshold_m:
                                # Find the attached terminal link
                                for link in network.terminal_links:
                                    if link.from_int.id == terminal.id or link.to_int.id == terminal.id:
                                        if link.in_or_out == "in":
                                            clicked_terminal_link = link
                                            break
                                break

                    # Interior link click (only if no intersection/terminal matched)
                    if clicked_intersection is None and clicked_terminal_link is None:
                        clicked_link = network.get_link_at_point(wx, wy, threshold=link_threshold_m)

                    # Also check for direct click on terminal link (line itself)
                    if (clicked_intersection is None
                            and clicked_terminal_link is None
                            and clicked_link is None):
                        for link in network.terminal_links:
                            if link.in_or_out != "in":
                                continue
                            if network._point_near_line(
                                wx, wy,
                                link.from_int.x_m, link.from_int.y_m,
                                link.to_int.x_m, link.to_int.y_m,
                                tlink_threshold_m,
                            ):
                                clicked_terminal_link = link
                                break

                    selected_intersection = clicked_intersection
                    selected_link = clicked_link if clicked_terminal_link is None else clicked_terminal_link

                    if selected_intersection is not None:
                        info_label.set_text(f"Intersection: {selected_intersection.id}")
                        load_intersection_fields(selected_intersection)
                        # Trigger immediate metrics refresh on new selection
                        last_metrics_update_s = -1.0

                    elif clicked_terminal_link is not None:
                        info_label.set_text(f"Terminal: {clicked_terminal_link.id}")
                        load_terminal_fields(clicked_terminal_link)

                    elif selected_link is not None:
                        info_label.set_text(f"Link: {selected_link.id}")
                        load_link_fields(selected_link)

                    else:
                        info_label.set_text("Click an intersection, link, or terminal")
                        clear_selection_ui()
                        # Trigger immediate refresh back to network metrics
                        last_metrics_update_s = -1.0

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if is_fullscreen:
                        # Tear down and rebuild the display to clear NOFRAME flag
                        pygame.display.quit()
                        pygame.display.init()
                        pygame.display.set_caption("Signal Commander")
                        screen = pygame.display.set_mode(windowed_size, pygame.RESIZABLE)
                        is_fullscreen = False
                        if hasattr(manager, 'set_window_resolution'):
                            manager.set_window_resolution(windowed_size)
                    else:
                        # Go fullscreen
                        info = pygame.display.Info()
                        screen = pygame.display.set_mode(
                            (info.current_w, info.current_h),
                            pygame.FULLSCREEN | pygame.NOFRAME,
                        )
                        is_fullscreen = True
                        if hasattr(manager, 'set_window_resolution'):
                            manager.set_window_resolution((info.current_w, info.current_h))

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
                    heatmap_button.set_text("Heatmap: OFF")
                    sim_time_accumulator = 0.0
                    cached_final_score = None
                    selected_intersection = None
                    selected_link = None
                    last_metrics_update_s = -1.0
                    cached_intersection_metrics = {}
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
                    # Full reset: clear agents and dynamic sim state on the
                    # current network. Custom timings, lanes, and inflows
                    # are preserved.
                    sim.reset_simulation()
                    sim.pause()
                    sim.set_speed(1)
                    metrics_engine = MetricsEngine()
                    sim_time_accumulator = 0.0
                    cached_final_score = None
                    selected_intersection = None
                    selected_link = None
                    last_metrics_update_s = -1.0
                    cached_intersection_metrics = {}
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
                    # Lockdown: disallow edits while simulation is running
                    if sim is not None and sim.state.sim_running:
                        status_label.set_text("Pause or reset to edit")
                    elif current_mode == "intersection" and selected_intersection is not None:
                        green_ns = safe_int(field1_input.get_text(), selected_intersection.green_ns)
                        green_ew = safe_int(field2_input.get_text(), selected_intersection.green_ew)
                        offset = safe_int(field3_input.get_text(), selected_intersection.offset)

                        derived_cycle = green_ns + green_ew + int(INTERGREEN_S)
                        if green_ns <= 0 or green_ew <= 0:
                            status_label.set_text("Green times must be > 0")
                        elif offset < 0 or offset >= derived_cycle:
                            status_label.set_text(f"Offset must be 0 to {derived_cycle - 1}")
                        else:
                            network.update_signal(
                                selected_intersection.id,
                                green_ns=green_ns,
                                green_ew=green_ew,
                            )
                            selected_intersection.offset = offset

                            # Sync IntersectionState so simulation and metrics see the change.
                            # cycle_length_s is always the derived value.
                            if sim is not None:
                                istate = sim.state.intersections.get(selected_intersection.id)
                                if istate is not None:
                                    istate.green_ns_s = float(green_ns)
                                    istate.green_ew_s = float(green_ew)
                                    istate.cycle_length_s = float(derived_cycle)

                            load_intersection_fields(selected_intersection)
                            status_label.set_text(f"Intersection updated (cycle {derived_cycle} s)")

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
                    
                    elif current_mode == "terminal" and selected_link is not None:
                        inflow_vph = safe_int(field1_input.get_text(), int(selected_link.inflow_vph))
                        if inflow_vph < 0:
                            status_label.set_text("Inflow must be >= 0")
                        else:
                            network.update_inflow_vph(selected_link.id, inflow_vph)
                            load_terminal_fields(selected_link)
                            status_label.set_text("Inflow updated")

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
                f"{running_text}  |  t = {sim.state.time_s:.1f}s / {int(SIM_DURATION_S)}s  |  Speed: {sim.speed_multiplier}x"
            )

        # Refresh metric panels every METRICS_UPDATE_INTERVAL_S simulated seconds
        # Refresh metric panels every METRICS_UPDATE_INTERVAL_S simulated seconds
        if sim is not None and sim.state.time_s - last_metrics_update_s >= METRICS_UPDATE_INTERVAL_S:
            last_metrics_update_s = sim.state.time_s
            state = sim.get_state()

            cached_net_metrics = metrics_engine.get_network_metrics()
            cached_intersection_metrics = metrics_engine.get_intersection_metrics(state)

            # If an intersection is selected, display its metrics in place of network metrics
            if (current_mode == "intersection"
                    and selected_intersection is not None
                    and selected_intersection.id in cached_intersection_metrics):
                im = cached_intersection_metrics[selected_intersection.id]
                iid = selected_intersection.id

                metrics_header_label.set_text(f"— {iid} METRICS —")

                net_completed_label.set_text(f"[{iid}]  LOS {im['los']}")
                net_active_label.set_text(
                    f"Mean delay: {im['mean_delay_sec_per_veh']:.1f} s"
                )
                net_delay_label.set_text(
                    f"Throughput: {int(im['throughput_veh_hr'])} veh/hr"
                )
                net_tt_label.set_text(
                    f"V/C ratio: {im['vc_ratio']:.2f}"
                )
                # Queue per approach, compact format
                q = im['queue_by_approach']
                net_p85_label.set_text(
                    f"Queue N:{q['N']} S:{q['S']} E:{q['E']} W:{q['W']}"
                )
                net_denied_label.set_text(
                    f"Total queue: {im['total_queue_veh']} ({im['max_queue_approach']}:{im['max_queue_veh']} max)"
                )

                info_label.set_text(
                    f"Intersection {iid} — LOS {im['los']} ({im['mean_delay_sec_per_veh']:.1f}s)"
                )
            else:
                # Default: network-level metrics
                metrics_header_label.set_text("— NETWORK METRICS —")
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
            # Derive canvas dimensions from live window size so everything
            # fits whether fullscreen, windowed, or user-resized.
            window_w, window_h = screen.get_size()
            canvas_w = SIDEBAR_LEFT
            canvas_h = window_h
            world_to_screen, screen_to_world, pixels_per_meter = make_transform(
                network,
                canvas_w,
                canvas_h,
                margin=80,
            )
        else:
            world_to_screen = None
            screen_to_world = None
            pixels_per_meter = 1.0

        screen.fill(BG_COLOR)
        window_w, window_h = screen.get_size()
        canvas_w = SIDEBAR_LEFT 
        pygame.draw.rect(
            screen,
            GRID_BG,
            pygame.Rect(0, 0, canvas_w, window_h)
        )

        if network is not None:
            for link in network.get_terminal_links():
                x1, y1 = world_to_screen(link.from_int.x_m, link.from_int.y_m)
                x2, y2 = world_to_screen(link.to_int.x_m, link.to_int.y_m)

                color = TERMINAL_LINK_COLOR
                width = 2
                if selected_link is not None and link.id == selected_link.id:
                    color = SELECTED_COLOR
                    width = 5

                pygame.draw.line(screen, color, (x1, y1), (x2, y2), width)
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

        # ===== Title rendering: SIGNAL COMMANDER =====
        # Shadow layer — slight offset, subtle dark color
        shadow = header_title_font.render("SIGNAL COMMANDER", True, (30, 30, 35))
        title_surface = header_title_font.render("SIGNAL COMMANDER", True, (240, 200, 60))

        title_x = title_x = SIDEBAR_LEFT + (SIDEBAR_WIDTH - title_surface.get_width()) // 2 + 40
        title_y = 7

        screen.blit(shadow, (title_x + 2, title_y + 2))
        screen.blit(title_surface, (title_x, title_y))

        # Decorative underline
        underline_y = title_y + title_surface.get_height() + 4
        underline_x1 = SIDEBAR_LEFT + 30 + 40
        underline_x2 = SIDEBAR_LEFT + SIDEBAR_WIDTH - 30 + 40

        pygame.draw.line(
            screen,
            (240, 200, 60),
            (underline_x1, underline_y),
            (underline_x2, underline_y),
            2,
        )

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

        # Simulation Complete overlay with score
        if sim is not None and sim.state.sim_completed:
            # Compute score once on first frame after completion, cache it
            if cached_final_score is None:
                cached_final_score = compute_network_score(sim.get_state())

            # Expanded overlay: 500x380 for score breakdown
            overlay_w = 500
            overlay_h = 380
            # Center on the canvas area, using the LIVE window size so the
            # overlay tracks the actual display instead of the config fallback.
            window_w, window_h = screen.get_size()
            canvas_w = SIDEBAR_LEFT
            overlay_x = (canvas_w - overlay_w) // 2
            overlay_y = (window_h - overlay_h) // 2

            # Dark translucent background
            overlay_surface = pygame.Surface((overlay_w, overlay_h), pygame.SRCALPHA)
            overlay_surface.fill((15, 18, 25, 235))
            screen.blit(overlay_surface, (overlay_x, overlay_y))

            # Gold border
            pygame.draw.rect(
                screen,
                (220, 180, 60),
                pygame.Rect(overlay_x, overlay_y, overlay_w, overlay_h),
                3,
            )

            # Title
            title = overlay_title_font.render("SIMULATION COMPLETE", True, (255, 255, 255))
            title_rect = title.get_rect(center=(overlay_x + overlay_w // 2, overlay_y + 30))
            screen.blit(title, title_rect)

            # Big score number
            score_text = f"{int(round(cached_final_score['network_score']))}"
            score_surface = overlay_score_font.render(score_text, True, cached_final_score["color"])
            score_rect = score_surface.get_rect(center=(overlay_x + overlay_w // 2, overlay_y + 95))
            screen.blit(score_surface, score_rect)

            # "/ 100" subtitle
            score_sub = overlay_small_font.render("/ 100", True, (180, 180, 190))
            score_sub_rect = score_sub.get_rect(
                center=(overlay_x + overlay_w // 2, overlay_y + 140)
            )
            screen.blit(score_sub, score_sub_rect)

            # Rating text
            rating = overlay_rating_font.render(
                cached_final_score["rating"], True, cached_final_score["color"]
            )
            rating_rect = rating.get_rect(center=(overlay_x + overlay_w // 2, overlay_y + 170))
            screen.blit(rating, rating_rect)

            # Per-intersection breakdown header
            breakdown_label = overlay_small_font.render(
                "Per-intersection scores:", True, (200, 200, 210)
            )
            breakdown_rect = breakdown_label.get_rect(
                center=(overlay_x + overlay_w // 2, overlay_y + 205)
            )
            screen.blit(breakdown_label, breakdown_rect)

            # Per-intersection grid — sized to the actual network, not a
            # hardcoded 3x3. Cell widths shrink to fit larger networks so
            # the overlay never overflows.
            int_scores = cached_final_score["intersection_scores"]
            rows = network.rows if network is not None else 0
            cols = network.cols if network is not None else 0
            grid_area_w = overlay_w - 40
            grid_area_h = overlay_h - 260
            grid_cell_w = min(115, grid_area_w // max(cols, 1))
            grid_cell_h = min(30, grid_area_h // max(rows, 1))
            grid_start_x = overlay_x + (overlay_w - grid_cell_w * max(cols, 1)) // 2
            grid_start_y = overlay_y + 230

            for row in range(rows):
                for col in range(cols):
                    iid = f"I_{row}_{col}"
                    score = int_scores.get(iid)
                    cell_x = grid_start_x + col * grid_cell_w
                    cell_y = grid_start_y + row * grid_cell_h

                    if score is None:
                        text = f"{iid}: —"
                        color = (120, 120, 130)
                    else:
                        text = f"{iid}: {int(round(score))}"
                        # Color-code per-intersection scores too
                        if score >= 90:
                            color = (0, 200, 0)
                        elif score >= 75:
                            color = (100, 220, 0)
                        elif score >= 60:
                            color = (200, 200, 0)
                        elif score >= 40:
                            color = (255, 150, 0)
                        else:
                            color = (255, 60, 60)

                    cell_surface = overlay_grid_font.render(text, True, color)
                    screen.blit(cell_surface, (cell_x, cell_y))

            # Footer: reset instruction
            footer = overlay_small_font.render(
                "Click Reset to try again", True, (200, 200, 210)
            )
            footer_rect = footer.get_rect(
                center=(overlay_x + overlay_w // 2, overlay_y + overlay_h - 25)
            )
            screen.blit(footer, footer_rect)

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
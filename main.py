import pygame
import pygame_gui
from simulation import Simulation
from debug import setup_debug_one_car
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


def main():
    pygame.init()
    pygame.display.set_caption("Signal Lord")
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
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
    network, sim = setup_debug_one_car()
    sim.resume()

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
        relative_rect=pygame.Rect((CANVAS_WIDTH + 10, 510), (SIDEBAR_WIDTH - 20, 24)),
        text="",
        manager=manager
    )

    network, sim = setup_debug_one_car() 
    sim.resume()

    selected_intersection = None
    selected_link = None
    current_mode = "none"

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

                    selected_intersection = None
                    selected_link = None
                    info_label.set_text("Click an intersection or link")
                    clear_selection_ui()
                    status_label.set_text("Network created")

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
        if sim is not None:
            sim.step(dt)
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

        manager.draw_ui(screen)
        if sim is not None:
            for agent in sim.get_agents():
                ax, ay = world_to_screen(agent.x_m, agent.y_m)
                color = (70, 130, 220) if agent.agent_type == "car" else (220, 80, 80)
                pygame.draw.circle(screen, color, (ax, ay), 5)
                pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
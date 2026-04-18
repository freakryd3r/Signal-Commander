import pygame
import pygame_gui
from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT, SIDEBAR_WIDTH, CANVAS_WIDTH,
    CANVAS_HEIGHT, FPS, BG_COLOR, GRID_BG, LINK_COLOR,
    INTERSECTION_COLOR, TEXT_COLOR
)
from network import Network


def main():
    pygame.init()
    pygame.display.set_caption("Signal Lord")
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    clock = pygame.time.Clock()

    manager = pygame_gui.UIManager((WINDOW_WIDTH, WINDOW_HEIGHT))

    # Sidebar title
    pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect(
            (CANVAS_WIDTH + 10, 10), (SIDEBAR_WIDTH - 20, 30)
        ),
        text="SIGNAL LORD",
        manager=manager,
        object_id="#sidebar_title"
    )

    # Placeholder label
    pygame_gui.elements.UILabel(
        relative_rect=pygame.Rect(
            (CANVAS_WIDTH + 10, 50), (SIDEBAR_WIDTH - 20, 24)
        ),
        text="Click an intersection or link",
        manager=manager
    )

    network = Network()

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            manager.process_events(event)

        manager.update(dt)

        # Draw canvas
        screen.fill(BG_COLOR)
        pygame.draw.rect(screen, GRID_BG,
                         pygame.Rect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT))

        # Draw links
        for link in network.links.values():
            x1, y1 = network.coords.world_to_screen(link.from_int.x_m, link.from_int.y_m)
            x2, y2 = network.coords.world_to_screen(link.to_int.x_m, link.to_int.y_m)
            pygame.draw.line(screen, LINK_COLOR, (x1, y1), (x2, y2), 4)

        # Draw intersections
        for inter in network.intersections.values():
            x, y = network.coords.world_to_screen(inter.x_m, inter.y_m)
            pygame.draw.circle(screen, INTERSECTION_COLOR, (x, y), 10)

        manager.draw_ui(screen)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()

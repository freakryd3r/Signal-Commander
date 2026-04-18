"""Pygame entry point. Step 4: network + simulation + editor + scoreboard.

Keys:
  SPACE       pause / resume
  R           reset simulation (keeps selected intersection)
  UP / DOWN   speed up / slow down (1x..20x sim steps per frame)
  S           single-step (while paused)
  TAB         cycle through intersections (I_00..I_22)
  ESC         deselect current editor
  Q           quit
"""

import sys
import pygame

from constants import (
    SCREEN_W, SCREEN_H, FPS, DEFAULT_CYCLE,
    DIRECTION_NAMES, SOUTH, CANVAS_X0, CANVAS_X1, COLOR_TEXT, COLOR_BG,
)
from scenarios import build_3x3_network, load_am_peak_scenario
from simulation import Simulator
import rendering
from ui import IntersectionEditor
from benchmarks import compute_all
from scoring import ScoreBoard


def run_integrity_checks(net) -> None:
    assert len(net.intersections) == 9
    assert len(net.links) == 48
    assert len(net.boundary_inbound) == 12
    assert len(net.boundary_outbound) == 12

    for intx in net.intersections.values():
        for d, appr in intx.approaches.items():
            assert appr.inbound_link_id is not None
            assert appr.out_through is not None
            assert appr.out_left is not None
            assert appr.out_right is not None
        assert intx.phase_plan is not None
        assert len(intx.phase_plan.phases) == 4
        assert abs(intx.phase_plan.cycle_length - DEFAULT_CYCLE) < 0.1

    i11 = net.intersections["I_11"]
    appr = i11.approaches[SOUTH]
    assert appr.out_through == "I_11_N_I_01"
    assert appr.out_left == "I_11_W_I_10"
    assert appr.out_right == "I_11_E_I_12"
    print("All integrity checks passed.")


def build_sim():
    net = build_3x3_network()
    demand = load_am_peak_scenario(net)
    sim = Simulator(net, demand)
    return net, demand, sim


def find_clicked_intersection(net, pos):
    x, y = pos
    if x < CANVAS_X0 or x > CANVAS_X1:
        return None
    for intx in net.intersections.values():
        if (intx.x - 14 <= x <= intx.x + 14
                and intx.y - 14 <= y <= intx.y + 14):
            return intx
    return None


def draw_loading_screen(screen, font, big_font, message):
    screen.fill(COLOR_BG)
    title = big_font.render("Signal Commander — computing benchmarks...", True, COLOR_TEXT)
    msg = font.render(message, True, COLOR_TEXT)
    screen.blit(title, (SCREEN_W // 2 - title.get_width() // 2, SCREEN_H // 2 - 30))
    screen.blit(msg, (SCREEN_W // 2 - msg.get_width() // 2, SCREEN_H // 2 + 10))
    pygame.display.flip()


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("Signal Commander - Step 4")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Arial", 13)
    big_font = pygame.font.SysFont("Arial", 18, bold=True)

    # Build network first
    net, demand, sim = build_sim()
    run_integrity_checks(net)

    # Compute benchmarks (this takes 2-3 seconds)
    draw_loading_screen(screen, font, big_font,
                        "Running Baseline / Webster / Optimum (3 × 15-min sims)...")
    bench = compute_all(demand)
    print(f"Benchmarks: baseline={bench['baseline']['delay_vehhr']:.2f}, "
          f"webster={bench['webster']['delay_vehhr']:.2f}, "
          f"optimum={bench['optimum']['delay_vehhr']:.2f} veh-hr")

    score = ScoreBoard.from_benchmarks(bench)

    # Build editor
    def get_demand():
        return demand

    editor = IntersectionEditor(net, get_demand)

    paused = False
    steps_per_frame = 4

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    running = False
                elif event.key == pygame.K_ESCAPE:
                    editor.deselect()
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key == pygame.K_r:
                    selected_id = (editor.selected.node_id
                                   if editor.selected else None)
                    # Reset sim but KEEP benchmarks and best-so-far
                    net, demand, sim = build_sim()
                    editor = IntersectionEditor(net, lambda: demand)
                    if selected_id is not None:
                        editor.select(net.intersections[selected_id])
                    score.reset_current()  # clear stale current-run metrics
                elif event.key == pygame.K_UP:
                    steps_per_frame = min(20, steps_per_frame + 1)
                elif event.key == pygame.K_DOWN:
                    steps_per_frame = max(1, steps_per_frame - 1)
                elif event.key == pygame.K_s and paused:
                    sim.step()
                elif event.key == pygame.K_TAB:
                    ids = sorted(net.intersections.keys())
                    if editor.selected is None:
                        editor.select(net.intersections[ids[0]])
                    else:
                        idx = ids.index(editor.selected.node_id)
                        editor.select(net.intersections[ids[(idx + 1) % 9]])
            else:
                consumed = editor.handle_event(event)
                if not consumed and event.type == pygame.MOUSEBUTTONDOWN \
                        and event.button == 1:
                    clicked = find_clicked_intersection(net, event.pos)
                    if clicked is not None:
                        editor.select(clicked)

        # Advance sim
        if not paused:
            for _ in range(steps_per_frame):
                sim.step()

        # Update scoreboard (read from live sim)
        score.update(sim)

        # --- Render ---
        rendering.draw_background(screen)
        rendering.draw_panels(screen)
        rendering.draw_panel_headers(screen, font)
        rendering.draw_scenario_panel(screen, demand, font)

        for link in net.links.values():
            rendering.draw_link(screen, net, link)

        selected_id = editor.selected.node_id if editor.selected else None
        for intx in net.intersections.values():
            is_sel = (intx.node_id == selected_id)
            rendering.draw_intersection(screen, intx, sim.global_time,
                                        selected=is_sel)
        rendering.draw_labels(screen, net, font)

        # Editor in top of right panel
        editor.draw(screen, font, big_font)
        # Scoreboard (in right panel, below editor; includes key metrics)
        rendering.draw_scoreboard(screen, score, font, big_font, sim=sim)

        # Footer help
        help_line = ("SPACE pause | R reset | UP/DN speed | "
                     "TAB next intx | CLICK intx to edit | ESC deselect | Q quit")
        surf = font.render(help_line, True, COLOR_TEXT)
        screen.blit(surf, (20, SCREEN_H - 24))

        if paused:
            surf = big_font.render("PAUSED (SPACE to resume)", True,
                                   (255, 200, 80))
            screen.blit(surf, (SCREEN_W // 2 - 140, 20))

        speed = big_font.render(f"{steps_per_frame}x", True, COLOR_TEXT)
        screen.blit(speed, (SCREEN_W // 2 - 15, SCREEN_H - 30))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()

"""Scenario editor — the professor's control panel (left side).

Controls:
  - 4 preset buttons: AM peak / PM peak / Balanced / NS heavy
  - 4 per-edge demand sliders: N, S, E, W (0-1500 vph each)
  - 2 "theater" buttons: +50% surge / Reset demand
  - 2 incident buttons: Incident on I_11 / Clear incident

Callers:
  - main.py creates an instance, passing the demand dict (mutated in place)
    and the network, and callbacks for "scenario changed" (triggers benchmark
    recomputation) and "scoreboard reset".
"""

from typing import Callable, Dict, List, Optional
import pygame

from constants import (
    LEFT_PANEL_W, SCREEN_H, NORTH, SOUTH, EAST, WEST,
    COLOR_TEXT, COLOR_TEXT_DIM,
)
from network import Network
from widgets import Slider, Button
from scenarios import (
    SCENARIO_PRESETS, set_edge_demand, apply_surge,
    apply_incident, clear_incident,
)


# Panel layout
PANEL_INSET = 15
WIDGET_W = LEFT_PANEL_W - 2 * PANEL_INSET  # ~170 px


class ScenarioEditor:
    """Professor's scenario control panel on the left."""

    def __init__(self, net: Network, demand: Dict[str, float],
                 on_scenario_change: Callable[[], None],
                 on_demand_nudge: Callable[[], None]):
        """
        net: network
        demand: demand dict (mutated in place by this editor)
        on_scenario_change: called after a preset button — recompute benchmarks
        on_demand_nudge: called after a slider drag — reset current score
        """
        self.net = net
        self.demand = demand
        self.on_scenario_change = on_scenario_change
        self.on_demand_nudge = on_demand_nudge

        self._incident_state: Optional[dict] = None

        self.widgets: List = []
        self._edge_sliders: Dict[str, Slider] = {}
        self._build_widgets()

    # -------------------------------------------------------------------------
    # Widget construction
    # -------------------------------------------------------------------------
    def _build_widgets(self) -> None:
        self.widgets = []
        self._edge_sliders = {}

        x = PANEL_INSET
        y = 50   # below the "SCENARIO" header drawn by rendering

        # Preset buttons
        btn_h = 24
        for name, loader in SCENARIO_PRESETS.items():
            self.widgets.append(Button(
                x, y, WIDGET_W, btn_h, name,
                on_click=lambda n=name: self._apply_preset(n),
            ))
            y += btn_h + 6
        y += 10

        # Per-edge demand sliders
        header_y = y
        y += 16  # space for "Edge demand (vph)" header
        for edge_char in ("N", "S", "E", "W"):
            initial = self._current_edge_average(edge_char)
            slider = Slider(
                x, y, WIDGET_W, 32,
                label=f"{edge_char} edge",
                vmin=0.0, vmax=1500.0,
                value=initial, step=50.0, fmt="{:.0f}",
                on_change=lambda v, ec=edge_char: self._on_edge_slider(ec, v),
            )
            self.widgets.append(slider)
            self._edge_sliders[edge_char] = slider
            y += 46
        self._edge_header_y = header_y

        y += 6
        # Surge / Reset row
        btn_w = (WIDGET_W - 6) // 2
        self.widgets.append(Button(
            x, y, btn_w, btn_h, "+50% surge",
            on_click=self._trigger_surge,
        ))
        self.widgets.append(Button(
            x + btn_w + 6, y, btn_w, btn_h, "Reset dem",
            on_click=self._reset_demand,
        ))
        y += btn_h + 10

        # Incident buttons
        self.widgets.append(Button(
            x, y, WIDGET_W, btn_h, "Incident @I_11",
            on_click=self._trigger_incident,
        ))
        y += btn_h + 6
        self.widgets.append(Button(
            x, y, WIDGET_W, btn_h, "Clear incident",
            on_click=self._clear_incident,
        ))
        y += btn_h + 6

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _current_edge_average(self, edge_char: str) -> float:
        """Return the average vph across the 3 boundary inbound links on one edge."""
        prefix = f"BND_{edge_char}"
        vals = [v for lid, v in self.demand.items() if lid.startswith(prefix)]
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    def _resync_sliders(self) -> None:
        """After demand change, update slider values to reflect new state."""
        for ec, slider in self._edge_sliders.items():
            slider.value = self._current_edge_average(ec)

    # -------------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------------
    def _apply_preset(self, name: str) -> None:
        """Load a named preset and fire the scenario-change callback."""
        if name not in SCENARIO_PRESETS:
            return
        # Clear incident if any
        if self._incident_state is not None:
            clear_incident(self.net, self._incident_state)
            self._incident_state = None

        new_demand = SCENARIO_PRESETS[name](self.net)
        # Mutate in place so main.py's reference stays valid
        self.demand.clear()
        self.demand.update(new_demand)
        self._resync_sliders()
        self.on_scenario_change()   # trigger benchmark recompute

    def _on_edge_slider(self, edge_char: str, vph: float) -> None:
        """Update one edge's demand without firing full scenario change."""
        set_edge_demand(self.demand, edge_char, vph)
        self.on_demand_nudge()  # lighter-weight: just reset current score

    def _trigger_surge(self) -> None:
        apply_surge(self.demand, factor=1.5)
        self._resync_sliders()
        self.on_scenario_change()

    def _reset_demand(self) -> None:
        self._apply_preset("AM peak")

    def _trigger_incident(self) -> None:
        if self._incident_state is not None:
            return  # already active
        self._incident_state = apply_incident(self.net, "I_11")
        self.on_demand_nudge()  # incident changes network; reset score

    def _clear_incident(self) -> None:
        if self._incident_state is None:
            return
        clear_incident(self.net, self._incident_state)
        self._incident_state = None
        self.on_demand_nudge()

    # -------------------------------------------------------------------------
    # Event + draw
    # -------------------------------------------------------------------------
    def handle_event(self, event) -> bool:
        for w in self.widgets:
            if w.handle_event(event):
                return True
        return False

    def draw(self, screen: pygame.Surface,
             font: pygame.font.Font) -> None:
        # Header label for edge sliders section
        hdr = font.render("Edge demand (vph)", True, COLOR_TEXT_DIM)
        screen.blit(hdr, (PANEL_INSET, self._edge_header_y))

        # Draw all widgets
        for w in self.widgets:
            w.draw(screen, font)

        # Small indicator if incident is active
        if self._incident_state is not None:
            y = SCREEN_H - 50
            surf = font.render("INCIDENT ACTIVE @ I_11", True, (240, 120, 120))
            screen.blit(surf, (PANEL_INSET, y))

"""Intersection editor panel — the student's toolkit.

When an intersection is selected, the right panel shows:
  - Intersection ID header
  - Cycle length slider (30..180 sec)
  - Four phase split sliders (effective green per phase)
  - Offset slider (0..C)
  - Permitted-vs-Protected LT dropdown for EW and NS
  - RTOR and LT-prohibition checkboxes
  - Preset buttons: Equal / Webster / Default
  - Scoreboard comparing current vs. baseline / Webster / pre-tuned optimum

Design principle: every change takes effect IMMEDIATELY. No "Apply" button.
This requires tight constraint enforcement so phase splits always sum correctly
to the cycle length.
"""

from typing import Optional, List, Callable
import pygame

from constants import (
    SCREEN_W, RIGHT_PANEL_W, SCREEN_H,
    YELLOW_TIME, ALL_RED_TIME, MIN_CYCLE, MAX_CYCLE, DEFAULT_CYCLE,
    LOST_TIME_PER_PHASE,
    COLOR_TEXT, COLOR_TEXT_DIM,
    NORTH, EAST, SOUTH, WEST,
)
from network import Intersection, Network, Phase
from signals import build_default_4phase_plan
from widgets import Slider, Button, Checkbox, Dropdown
from webster import (
    apply_webster_to_intersection, estimate_approach_volumes,
    webster_cycle_and_splits,
)


# Right panel layout
PANEL_X = SCREEN_W - RIGHT_PANEL_W
PANEL_INSET = 20
WIDGET_W = RIGHT_PANEL_W - 2 * PANEL_INSET


class IntersectionEditor:
    """Manages the right-panel editor for a selected intersection."""

    def __init__(self, net: Network, demand_vph_fn: Callable[[], dict]):
        """
        net: the network
        demand_vph_fn: callable returning current demand dict {link_id: vph}
                       (used for Webster calculation)
        """
        self.net = net
        self.demand_vph_fn = demand_vph_fn
        self.selected: Optional[Intersection] = None

        # Widgets — all created lazily when an intersection is selected
        self.widgets: List = []

        # Sliders held as references so we can re-sync after preset clicks
        self._cycle_slider: Optional[Slider] = None
        self._phase_sliders: List[Slider] = []
        self._offset_slider: Optional[Slider] = None

    # -------------------------------------------------------------------------
    # Selection management
    # -------------------------------------------------------------------------
    def select(self, intx: Intersection) -> None:
        """Select an intersection and rebuild widgets for its editor."""
        self.selected = intx
        self._build_widgets()

    def deselect(self) -> None:
        self.selected = None
        self.widgets = []
        self._cycle_slider = None
        self._phase_sliders = []
        self._offset_slider = None

    # -------------------------------------------------------------------------
    # Widget construction
    # -------------------------------------------------------------------------
    def _build_widgets(self) -> None:
        """Create all widgets for the current selected intersection."""
        self.widgets = []
        self._phase_sliders = []

        if self.selected is None:
            return

        intx = self.selected
        pp = intx.phase_plan

        y = 60  # start below the "CONTROLS" header
        x = PANEL_X + PANEL_INSET

        # Cycle slider
        self._cycle_slider = Slider(
            x, y, WIDGET_W, 32,
            label="Cycle length (sec)",
            vmin=MIN_CYCLE, vmax=MAX_CYCLE,
            value=pp.cycle_length, step=1.0,
            fmt="{:.0f}",
            on_change=self._on_cycle_change,
        )
        self.widgets.append(self._cycle_slider)
        y += 50

        # Four phase sliders — one per phase's effective green
        phase_labels = [
            "Phase 1 green: EW through",
            "Phase 2 green: EW left",
            "Phase 3 green: NS through",
            "Phase 4 green: NS left",
        ]
        min_g, max_g = self._green_bounds(pp.cycle_length)
        for i, (phase, label) in enumerate(zip(pp.phases, phase_labels)):
            slider = Slider(
                x, y, WIDGET_W, 32,
                label=label, vmin=min_g, vmax=max_g,
                value=phase.effective_green, step=1.0, fmt="{:.0f}",
                on_change=lambda v, idx=i: self._on_phase_green_change(idx, v),
            )
            self.widgets.append(slider)
            self._phase_sliders.append(slider)
            y += 48

        # Offset slider
        self._offset_slider = Slider(
            x, y, WIDGET_W, 32,
            label="Offset (sec)", vmin=0.0, vmax=pp.cycle_length,
            value=pp.offset, step=1.0, fmt="{:.0f}",
            on_change=self._on_offset_change,
        )
        self.widgets.append(self._offset_slider)
        y += 50

        # Checkboxes: RTOR for each approach (grouped for compactness)
        cb_rtor = Checkbox(
            x, y, "Right-turn-on-red allowed (all approaches)",
            checked=all(a.rtor_allowed for a in intx.approaches.values()),
            on_change=self._on_rtor_toggle,
        )
        self.widgets.append(cb_rtor)
        y += 24

        cb_lt_ew = Checkbox(
            x, y, "Prohibit left turns on E-W",
            checked=(intx.approaches[EAST].lt_prohibited
                     and intx.approaches[WEST].lt_prohibited),
            on_change=self._on_lt_ew_toggle,
        )
        self.widgets.append(cb_lt_ew)
        y += 24

        cb_lt_ns = Checkbox(
            x, y, "Prohibit left turns on N-S",
            checked=(intx.approaches[NORTH].lt_prohibited
                     and intx.approaches[SOUTH].lt_prohibited),
            on_change=self._on_lt_ns_toggle,
        )
        self.widgets.append(cb_lt_ns)
        y += 32

        # Preset buttons (row of 3)
        btn_w = (WIDGET_W - 16) // 3
        self.widgets.append(Button(x, y, btn_w, 28, "Equal",
                                   on_click=self._preset_equal))
        self.widgets.append(Button(x + btn_w + 8, y, btn_w, 28, "Webster",
                                   on_click=self._preset_webster))
        self.widgets.append(Button(x + 2 * (btn_w + 8), y, btn_w, 28, "Default",
                                   on_click=self._preset_default))
        y += 40

        # Deselect button
        self.widgets.append(Button(
            x, y, WIDGET_W, 24, "Close editor",
            on_click=self.deselect,
        ))
        y += 34

    def _green_bounds(self, cycle: float) -> tuple:
        """Given a cycle length, what are the min/max greens each phase can have?

        With 4 phases and 4 sec clearance each, total clearance = 16 sec.
        Effective green available per cycle = C - 16.
        Per phase max ~ (C - 16) - 3*min_green_other ... complex constraint.

        Simplification: per-slider range is [min_g, C - 16 - 3*min_g].
        """
        available = cycle - 4 * (YELLOW_TIME + ALL_RED_TIME)
        min_g = 5.0
        max_g = max(min_g, available - 3 * min_g)
        return (min_g, max_g)

    # -------------------------------------------------------------------------
    # Change handlers
    # -------------------------------------------------------------------------
    def _on_cycle_change(self, new_cycle: float) -> None:
        """Rescale phase greens proportionally to the new cycle length."""
        if self.selected is None:
            return
        pp = self.selected.phase_plan
        old_cycle = pp.cycle_length
        if old_cycle <= 0:
            return
        old_greens = [p.effective_green for p in pp.phases]
        new_available = new_cycle - 4 * (YELLOW_TIME + ALL_RED_TIME)
        old_available = old_cycle - 4 * (YELLOW_TIME + ALL_RED_TIME)
        if old_available <= 0:
            return
        # Proportional rescale
        for i, p in enumerate(pp.phases):
            p.effective_green = old_greens[i] * (new_available / old_available)
            if p.effective_green < 5.0:
                p.effective_green = 5.0
        # Clamp offset to new cycle
        if pp.offset >= pp.cycle_length:
            pp.offset = pp.offset % pp.cycle_length
        # Resync sliders
        self._resync_sliders()

    def _on_phase_green_change(self, idx: int, new_green: float) -> None:
        """When one phase's green changes, redistribute the delta across the
        others while respecting minimum-green constraints.

        Algorithm:
          1. Cap `new_green` to feasible range: [min_green, available - 3*min_green].
          2. Compute remaining budget for the other 3 phases = available - new_green.
          3. Distribute `remaining` among others proportional to their CURRENT values
             (so a phase that was big stays bigger than one that was small).
          4. Iteratively pin below-min phases to min_green and redistribute the
             freed budget among the non-pinned. This avoids the
             clamp-then-residual drift that a single-pass scale produces.
        """
        if self.selected is None:
            return
        pp = self.selected.phase_plan
        cycle = pp.cycle_length
        available = cycle - 4 * (YELLOW_TIME + ALL_RED_TIME)
        min_green = 5.0
        n = 4

        # Feasible max for idx: available minus (n-1) phases at their minimum
        feasible_max = available - (n - 1) * min_green
        new_green = max(min_green, min(new_green, feasible_max))

        remaining = available - new_green  # budget for the other phases

        others = [i for i in range(n) if i != idx]
        current_others = [pp.phases[i].effective_green for i in others]
        current_total = sum(current_others)

        # Initial distribution proportional to current values
        if current_total <= 1e-9:
            new_others = [remaining / len(others)] * len(others)
        else:
            new_others = [remaining * c / current_total for c in current_others]

        # Iteratively pin below-min and redistribute
        pinned = [False] * len(others)
        for _ in range(len(others)):
            violations = [
                j for j in range(len(others))
                if not pinned[j] and new_others[j] < min_green
            ]
            if not violations:
                break
            for j in violations:
                pinned[j] = True
                new_others[j] = min_green
            unpinned = [j for j in range(len(others)) if not pinned[j]]
            if not unpinned:
                break
            pinned_sum = sum(min_green for j in range(len(others)) if pinned[j])
            free_budget = remaining - pinned_sum
            if free_budget < 0:
                # Infeasible; pinned phases keep min, unpinned get zero
                for j in unpinned:
                    new_others[j] = 0.0
                break
            # Redistribute proportional to unpinned phases' current values
            u_current = [current_others[j] for j in unpinned]
            u_total = sum(u_current)
            if u_total <= 1e-9:
                for j in unpinned:
                    new_others[j] = free_budget / len(unpinned)
            else:
                for j, c in zip(unpinned, u_current):
                    new_others[j] = free_budget * c / u_total

        # Apply
        for i, val in zip(others, new_others):
            pp.phases[i].effective_green = val
        pp.phases[idx].effective_green = new_green

        # Resync the non-dragged sliders to reflect actual values
        for i, slider in enumerate(self._phase_sliders):
            if i != idx:
                slider.value = pp.phases[i].effective_green

    def _on_offset_change(self, new_offset: float) -> None:
        if self.selected is None:
            return
        self.selected.phase_plan.offset = new_offset % self.selected.phase_plan.cycle_length

    def _on_rtor_toggle(self, checked: bool) -> None:
        if self.selected is None:
            return
        for appr in self.selected.approaches.values():
            appr.rtor_allowed = checked

    def _on_lt_ew_toggle(self, checked: bool) -> None:
        if self.selected is None:
            return
        self.selected.approaches[EAST].lt_prohibited = checked
        self.selected.approaches[WEST].lt_prohibited = checked

    def _on_lt_ns_toggle(self, checked: bool) -> None:
        if self.selected is None:
            return
        self.selected.approaches[NORTH].lt_prohibited = checked
        self.selected.approaches[SOUTH].lt_prohibited = checked

    # -------------------------------------------------------------------------
    # Presets
    # -------------------------------------------------------------------------
    def _preset_equal(self) -> None:
        if self.selected is None:
            return
        pp = self.selected.phase_plan
        available = pp.cycle_length - 4 * (YELLOW_TIME + ALL_RED_TIME)
        g = available / 4.0
        for p in pp.phases:
            p.effective_green = g
        self._resync_sliders()

    def _preset_webster(self) -> None:
        if self.selected is None:
            return
        # Get current demand and compute approach volumes
        demand = self.demand_vph_fn()
        approach_vols = estimate_approach_volumes(self.net, demand)
        intx_vols = approach_vols[self.selected.node_id]
        C, greens = webster_cycle_and_splits(self.selected, intx_vols)
        pp = self.selected.phase_plan
        for i, p in enumerate(pp.phases):
            p.effective_green = greens[i]
        # Cycle is now derived from new greens. Wrap offset if it exceeds new cycle.
        if pp.offset >= pp.cycle_length:
            pp.offset = pp.offset % pp.cycle_length
        self._resync_sliders()

    def _preset_default(self) -> None:
        if self.selected is None:
            return
        # Keep same offset, reset cycle to 60 with equal splits
        old_offset = self.selected.phase_plan.offset
        new_pp = build_default_4phase_plan(DEFAULT_CYCLE)
        new_pp.offset = old_offset
        self.selected.phase_plan = new_pp
        # Rebuild widgets since phase plan was replaced
        self._build_widgets()

    def _resync_sliders(self) -> None:
        """Update slider values to match the current phase plan."""
        if self.selected is None:
            return
        pp = self.selected.phase_plan
        if self._cycle_slider is not None:
            self._cycle_slider.value = pp.cycle_length
        if self._offset_slider is not None:
            self._offset_slider.vmax = pp.cycle_length
            # Ensure slider value is in [0, cycle_length) — wrap if needed.
            # pp.offset is already wrapped by callers; slider.value tracks it.
            self._offset_slider.value = pp.offset
        for i, slider in enumerate(self._phase_sliders):
            slider.value = pp.phases[i].effective_green
            min_g, max_g = self._green_bounds(pp.cycle_length)
            slider.vmin = min_g
            slider.vmax = max_g

    # -------------------------------------------------------------------------
    # Event + draw
    # -------------------------------------------------------------------------
    def handle_event(self, event) -> bool:
        """Return True if event was consumed by a widget."""
        if self.selected is None:
            return False
        for w in self.widgets:
            if w.handle_event(event):
                return True
        return False

    def draw(self, screen: pygame.Surface,
             font: pygame.font.Font,
             big_font: pygame.font.Font) -> None:
        if self.selected is None:
            # Draw a hint
            hint = font.render(
                "Click an intersection to edit", True, COLOR_TEXT_DIM,
            )
            screen.blit(hint, (PANEL_X + PANEL_INSET, 60))
            return

        # Header
        title = big_font.render(f"Editing {self.selected.node_id}", True, COLOR_TEXT)
        screen.blit(title, (PANEL_X + PANEL_INSET, 30))

        # Draw all widgets
        for w in self.widgets:
            w.draw(screen, font)

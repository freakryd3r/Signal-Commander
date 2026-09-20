# Window (defaults used in windowed mode only). At runtime the app reads
# the live display size and anchors the sidebar to the right edge, so these
# only matter for the fallback windowed geometry.
WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 1000
SIDEBAR_WIDTH = 300

FPS = 30

# Colors (R, G, B). Only the ones imported by main.py live here.
BG_COLOR = (25, 28, 35)
GRID_BG = (35, 40, 50)
LINK_COLOR = (120, 130, 145)
INTERSECTION_COLOR = (200, 210, 220)

# Network defaults
DEFAULT_ROWS = 3
DEFAULT_COLS = 3
DEFAULT_LINK_LENGTH_M = 100
DEFAULT_LANES = 1

# Traffic engineering — single source of truth. Imported by metrics.py.
SATURATION_FLOW_VPH = 1900
FREE_FLOW_SPEED = 15

# Simulation timing — single source of truth. Imported by simulation.py
# and read by main.py for the "t = X / SIM_DURATION_S" status label.
TIMESTEP = 1.0
SIM_DURATION_S = 3600.0
WARMUP_DURATION = 180
ROLLING_WINDOW_S = 300

# Signal intergreen — must match the Signal state machine in simulation.py.
# Cycle length is derived as green_ns + green_ew + INTERGREEN_S, so scoring
# and the played state machine always see the same number.
YELLOW_S = 3.0
ALL_RED_S = 2.0
INTERGREEN_S = 2 * YELLOW_S + 2 * ALL_RED_S

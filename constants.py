"""All magic numbers and defaults in one place. Do not duplicate elsewhere.

References:
  - HCM 7th Ed. (TRB 2022), Ch. 19 (Signalized Intersections)
  - Roess, Prassas, McShane (2019), Traffic Engineering, 5th ed.
  - Webster (1958), RRL Technical Paper 39
  - Akcelik (1981), ARRB Report 123 (incremental delay term)
"""

# =============================================================================
# Screen / layout
# =============================================================================
SCREEN_W = 1600
SCREEN_H = 900
FPS = 60

LEFT_PANEL_W = 200
RIGHT_PANEL_W = 400
CANVAS_X0 = LEFT_PANEL_W
CANVAS_X1 = SCREEN_W - RIGHT_PANEL_W

# =============================================================================
# Network grid
# =============================================================================
GRID_ROWS = 3
GRID_COLS = 3
GRID_SPACING = 300          # px == meters (1 px : 1 m)
GRID_X0 = 350               # x of top-left intersection
GRID_Y0 = 200               # y of top-left intersection

# =============================================================================
# Physical parameters (HCM 7th Ed. defaults)
# =============================================================================
SAT_FLOW_BASE = 1900.0      # pc/hr/ln, HCM Eq. 19-8 s_o
LANES_PER_APPROACH = 2
FREE_FLOW_SPEED = 15.0      # m/s (~34 mph urban arterial)
JAM_SPACING = 6.7           # m per vehicle at jam density
JAM_DENSITY = 1.0 / JAM_SPACING   # veh/m

# =============================================================================
# Signal timing defaults
# =============================================================================
DEFAULT_CYCLE = 60.0        # sec
MIN_CYCLE = 40.0            # sec (physical floor: 4 phases x 5s min + 16s clearance = 36s,
                            #      we add 4s margin so sliders behave cleanly)
MAX_CYCLE = 180.0

YELLOW_TIME = 3.0           # sec
ALL_RED_TIME = 1.0          # sec
STARTUP_LOST = 2.0          # sec
EXTENSION_INTO_YELLOW = 2.0 # sec

# Net lost time per phase (HCM Eq. 19-5):
#   t_L = startup_lost + (yellow + all_red) - extension_into_yellow
#       = 2 + (3 + 1) - 2 = 4 sec
LOST_TIME_PER_PHASE = (STARTUP_LOST + YELLOW_TIME + ALL_RED_TIME
                       - EXTENSION_INTO_YELLOW)

# =============================================================================
# Turning ratios (default; scenario can override per-approach)
# =============================================================================
DEFAULT_P_LEFT = 0.15
DEFAULT_P_THROUGH = 0.70
DEFAULT_P_RIGHT = 0.15

# =============================================================================
# Simulation
# =============================================================================
DT = 1.0                    # sec per time step
SIM_DURATION = 900          # sec = 15-min analysis period
ANALYSIS_PERIOD_T = 0.25    # hours, used in HCM d2 (Eq. 19-20)

# HCM d2 parameters
K_PRETIMED = 0.5            # incremental delay factor for pretimed signals
I_ISOLATED = 1.0            # upstream filtering factor (1.0 = isolated)

# =============================================================================
# LOS thresholds, sec/veh (HCM 7th Ed. Exhibit 19-8)
# =============================================================================
LOS_A_MAX = 10
LOS_B_MAX = 20
LOS_C_MAX = 35
LOS_D_MAX = 55
LOS_E_MAX = 80
# > LOS_E_MAX or X > 1.0 => LOS F

# =============================================================================
# Colors (RGB)
# =============================================================================
COLOR_BG = (30, 30, 40)
COLOR_PANEL = (45, 45, 60)
COLOR_LINK = (120, 120, 130)
COLOR_LINK_BOUNDARY = (90, 90, 100)
COLOR_INTERSECTION = (200, 200, 210)
COLOR_VC_GOOD = (80, 200, 120)
COLOR_VC_OK = (220, 200, 80)
COLOR_VC_BAD = (230, 140, 70)
COLOR_VC_CRITICAL = (220, 70, 70)
COLOR_TEXT = (230, 230, 235)
COLOR_TEXT_DIM = (150, 150, 160)
COLOR_QUEUE = (255, 180, 80)
COLOR_SIGNAL_RED = (220, 60, 60)
COLOR_SIGNAL_YELLOW = (240, 210, 60)
COLOR_SIGNAL_GREEN = (80, 220, 100)

# =============================================================================
# Directions
# Approach direction = direction vehicle is COMING FROM.
# Heading direction = direction vehicle is TRAVELING TOWARD = OPPOSITE[approach].
# =============================================================================
NORTH, EAST, SOUTH, WEST = 0, 1, 2, 3
DIRECTIONS = [NORTH, EAST, SOUTH, WEST]
DIRECTION_NAMES = {NORTH: "N", EAST: "E", SOUTH: "S", WEST: "W"}
OPPOSITE = {NORTH: SOUTH, SOUTH: NORTH, EAST: WEST, WEST: EAST}

# LEFT_OF and RIGHT_OF are defined from the DRIVER's perspective relative to
# their HEADING direction.
#   Heading NORTH: left = WEST,  right = EAST
#   Heading EAST:  left = NORTH, right = SOUTH
#   Heading SOUTH: left = EAST,  right = WEST
#   Heading WEST:  left = SOUTH, right = NORTH
LEFT_OF = {NORTH: WEST, EAST: NORTH, SOUTH: EAST, WEST: SOUTH}
RIGHT_OF = {NORTH: EAST, EAST: SOUTH, SOUTH: WEST, WEST: NORTH}

# Movement type codes
MOVEMENT_LEFT = "L"
MOVEMENT_THROUGH = "T"
MOVEMENT_RIGHT = "R"

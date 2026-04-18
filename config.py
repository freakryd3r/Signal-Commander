# Window
WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900
SIDEBAR_WIDTH = 350
CANVAS_WIDTH = WINDOW_WIDTH - SIDEBAR_WIDTH
CANVAS_HEIGHT = WINDOW_HEIGHT
FPS = 30

# Colors (R, G, B)
BG_COLOR = (25, 28, 35)
GRID_BG = (35, 40, 50)
LINK_COLOR = (120, 130, 145)
INTERSECTION_COLOR = (200, 210, 220)
CAR_COLOR = (70, 130, 220)
BUS_COLOR = (220, 80, 80)
TEXT_COLOR = (230, 230, 235)

# Network defaults
DEFAULT_ROWS = 3
DEFAULT_COLS = 3
DEFAULT_LINK_LENGTH_M = 200.0     # meters
WORLD_MARGIN_M = 50.0             # meters of padding around grid

# Traffic engineering constants
SATURATION_FLOW = 1800            # veh/hr/lane
STARTUP_LOST_TIME = 2.0           # seconds
FREE_FLOW_SPEED = 13.89           # m/s (~50 km/h)

# Simulation
TIMESTEP = 1.0                    # seconds, fixed
SIM_DURATION = 900                # seconds (15 minutes)
WARMUP_DURATION = 180             # seconds (3 minutes)
ROLLING_WINDOW = 300              # seconds (5 minutes)

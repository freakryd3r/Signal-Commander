# =============================================================
# SIGNAL LORD — UNIT CONVENTIONS
# =============================================================
# Distance:  meters (m)
# Time:      seconds (s)
# Speed:     meters per second (m/s)
# Flow:      vehicles per hour (veh/hr)
# Density:   vehicles per kilometer (veh/km)
# Angles:    radians internally, degrees only at display
#
# World space: meters, used for all simulation logic.
# Screen space: pixels, used only for rendering.
# Convert with world_to_screen() and screen_to_world() helpers.
#
# DO NOT mix units. Convert at display time only.
# =============================================================

# (units header)

def websters_optimal_cycle(L_total, Y):
    """Webster's optimal cycle length. Clamp Y at 0.95."""
    Y = min(Y, 0.95)
    return (1.5 * L_total + 5) / (1 - Y)

def level_of_service(delay_s):
    """HCM LOS thresholds."""
    if delay_s <= 10: return "A"
    if delay_s <= 20: return "B"
    if delay_s <= 35: return "C"
    if delay_s <= 55: return "D"
    if delay_s <= 80: return "E"
    return "F"

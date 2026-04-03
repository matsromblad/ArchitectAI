"""
SE Dimensions — Swedish building dimension standards for ArchitectAI.

All dimensions in millimetres (mm) unless the variable name ends in _M (metres).

Sources:
  - SS 91 42 21:2017  Projektering av vårdlokaler (healthcare)
  - BBR 2023 (BFS 2011:6)  Boverkets byggregler
  - AFS 2009:2  Arbetsplatsutformning
  - HIN 4 (BFS 2013:9)  Tillgänglighet och användbarhet

Usage:
    from src.tools.se_dimensions import SE, snap_mm, snap_grid, GRID_HEALTHCARE

    # Snap a calculated value to the nearest preferred grid
    w = snap_mm(2340, grid=SE.GRID_MODULE)          # → 2400
    span = snap_grid(6150, allowed=GRID_HEALTHCARE)  # → 6000

    # Inject dimension constants into an agent prompt
    SE.prompt_block("healthcare")   # returns a formatted string for system prompts
"""

from __future__ import annotations

import math
from typing import Sequence


# ---------------------------------------------------------------------------
# Preferred structural grids (mm) — SE healthcare and general office/resi
# ---------------------------------------------------------------------------

# Healthcare ward: SS 91 42 21 recommends patient bay module 3600–4200 mm.
# Typical Swedish concrete frame: 6000 mm or 7200 mm spans.
GRID_HEALTHCARE_MM = [3600, 4200, 6000, 7200, 8400]

# General office/commercial
GRID_OFFICE_MM = [6000, 7200, 8400, 9000]

# Residential
GRID_RESI_MM = [3600, 4800, 6000]

# Stair core / lift module
GRID_CORE_MM = [2800, 3200, 5600, 6400]

# Preferred wall-to-wall dimensions (grid module) in mm
PREFERRED_GRID_MM = 1200  # 1200-module is standard in Sweden


# ---------------------------------------------------------------------------
# Class: SE — all constants as class attributes for easy import + prompt use
# ---------------------------------------------------------------------------

class SE:
    """Swedish building dimension constants (all in mm unless noted)."""

    # ── Structural grid ──────────────────────────────────────────────────────
    GRID_MODULE           = 1200   # Base planning module (mm) per SS-ISO 1006
    GRID_HEALTHCARE_SPANS = GRID_HEALTHCARE_MM
    GRID_OFFICE_SPANS     = GRID_OFFICE_MM

    # ── Storey heights ───────────────────────────────────────────────────────
    FLOOR_HEIGHT_HEALTHCARE = 3600   # mm floor-to-floor (typ. 3600–4200 for clinical)
    FLOOR_HEIGHT_OFFICE     = 3300   # mm floor-to-floor
    FLOOR_HEIGHT_RESI       = 2700   # mm floor-to-floor (min BBR: 2400 net clear)
    CLEAR_HEIGHT_MIN        = 2400   # mm net clear (BBR minimum habitale room)
    CLEAR_HEIGHT_HEALTHCARE = 2800   # mm net clear for clinical rooms (SS 91 42 21)

    # ── Corridor widths (mm clear between walls) ─────────────────────────────
    CORRIDOR_MIN_ACCESSIBILITY = 1500  # HIN 4 wheelchair passing
    CORRIDOR_HEALTHCARE_MIN    = 2400  # SS 91 42 21 ward corridor minimum
    CORRIDOR_HEALTHCARE_REC    = 2700  # Recommended (bed + wheelchair passing)
    CORRIDOR_HEALTHCARE_WIDE   = 3000  # Double-loaded ward, preferred

    # ── Door openings (mm clear passage) ─────────────────────────────────────
    DOOR_MIN_ACCESSIBILITY     = 800   # HIN 4 / BBR 8:232 min clear
    DOOR_PATIENT_ROOM          = 1100  # SS 91 42 21 patient room (bed passage)
    DOOR_ISOLATION             = 1200  # Isolation room (wide for bed + staff)
    DOOR_WC_ACCESSIBLE         = 900   # Accessible WC (HIN 4)

    # ── Window dimensions ────────────────────────────────────────────────────
    WINDOW_SILL_HEIGHT_MIN     = 600   # mm (BBR — views from seated position)
    WINDOW_SILL_HEALTHCARE     = 600   # mm (patient bed eye level)
    WINDOW_HEAD_HEALTHCARE     = 2100  # mm (top of glazing, comfortable daylight)
    WINDOW_WIDTH_PATIENT_MIN   = 1200  # mm clear glazing per patient bay
    WINDOW_DAYLIGHT_RATIO      = 0.10  # min 10% of floor area as glazing (BBR)

    # ── Wall thicknesses ──────────────────────────────────────────────────────
    WALL_EXTERNAL_MIN          = 300   # mm (incl. insulation, SE climate)
    WALL_EXTERNAL_HEALTHCARE   = 350   # mm (incl. thermal bridge break)
    WALL_INTERNAL_PARTITION    = 100   # mm (non-structural, gypsum stud)
    WALL_INTERNAL_LOADBEARING  = 200   # mm (concrete or masonry)
    WALL_INFECTION_CONTROL     = 150   # mm (isolation room, easy-clean finish)

    # ── Structural members ────────────────────────────────────────────────────
    COLUMN_SIZE_MIN            = 300   # mm (square concrete, min practical)
    COLUMN_SIZE_TYPICAL        = 400   # mm (square, common SE healthcare)
    SLAB_THICKNESS_TYPICAL     = 250   # mm (flat plate, spans ≤ 8m)
    BEAM_DEPTH_TYPICAL         = 600   # mm (incl. slab depth, spans 6–8m)

    # ── Ramp / accessibility ──────────────────────────────────────────────────
    RAMP_MAX_GRADIENT          = 5     # % (BBR 8:232 — 1:20 for public buildings)
    RAMP_WIDTH_MIN             = 1500  # mm (HIN 4)

    @classmethod
    def prompt_block(cls, building_type: str = "healthcare") -> str:
        """
        Return a formatted dimension reference block for injection into agent prompts.

        Args:
            building_type: "healthcare" | "office" | "residential"

        Returns:
            Multiline string listing relevant SE dimension rules.
        """
        bt = building_type.lower()
        if "health" in bt or "care" in bt or "ward" in bt:
            grid_spans = cls.GRID_HEALTHCARE_SPANS
            floor_h    = cls.FLOOR_HEIGHT_HEALTHCARE
            clear_h    = cls.CLEAR_HEIGHT_HEALTHCARE
            corridor_w = cls.CORRIDOR_HEALTHCARE_REC
            door_room  = cls.DOOR_PATIENT_ROOM
            win_sill   = cls.WINDOW_SILL_HEALTHCARE
            win_head   = cls.WINDOW_HEAD_HEALTHCARE
            win_w_min  = cls.WINDOW_WIDTH_PATIENT_MIN
        elif "office" in bt:
            grid_spans = cls.GRID_OFFICE_SPANS
            floor_h    = cls.FLOOR_HEIGHT_OFFICE
            clear_h    = cls.CLEAR_HEIGHT_MIN
            corridor_w = cls.CORRIDOR_MIN_ACCESSIBILITY
            door_room  = cls.DOOR_MIN_ACCESSIBILITY
            win_sill   = 900
            win_head   = 2400
            win_w_min  = 1200
        else:
            grid_spans = [3600, 4800, 6000]
            floor_h    = cls.FLOOR_HEIGHT_RESI
            clear_h    = cls.CLEAR_HEIGHT_MIN
            corridor_w = cls.CORRIDOR_MIN_ACCESSIBILITY
            door_room  = cls.DOOR_MIN_ACCESSIBILITY
            win_sill   = 900
            win_head   = 2400
            win_w_min  = 900

        spans_str = ", ".join(f"{s} mm" for s in grid_spans)

        return f"""
SE DIMENSION STANDARDS (all in mm — Swedish BBR / SS 91 42 21):
- Structural grid: preferred spans {spans_str}
- Planning module: {cls.GRID_MODULE} mm (all dimensions should be multiples of {cls.GRID_MODULE} where possible)
- Storey height floor-to-floor: {floor_h} mm
- Net clear room height: ≥ {clear_h} mm
- Corridor clear width: ≥ {corridor_w} mm
- Patient/room door clear: ≥ {door_room} mm
- Accessible door min: ≥ {cls.DOOR_MIN_ACCESSIBILITY} mm
- Window sill height: ≥ {win_sill} mm AFF (above finished floor)
- Window head height: {win_head} mm AFF (top of glazing)
- Min window width per bay: {win_w_min} mm glazing
- External wall thickness: {cls.WALL_EXTERNAL_HEALTHCARE} mm (incl. insulation)
- Internal partition: {cls.WALL_INTERNAL_PARTITION} mm
- Load-bearing wall: {cls.WALL_INTERNAL_LOADBEARING} mm
- Column size (concrete): {cls.COLUMN_SIZE_TYPICAL} × {cls.COLUMN_SIZE_TYPICAL} mm
- Slab thickness: {cls.SLAB_THICKNESS_TYPICAL} mm (spans ≤ 8 m)
- All output dimensions must be multiples of 50 mm; prefer multiples of 100 mm.
- Spans, room widths and depths must snap to the nearest allowed structural grid.
""".strip()


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def snap_mm(value_mm: float, grid: int = 100) -> int:
    """
    Round value_mm to the nearest multiple of grid (mm).

    Examples:
        snap_mm(2340, 600)  → 2400
        snap_mm(1180, 100)  → 1200
        snap_mm(3750, 50)   → 3750  (already on grid)
    """
    return int(round(value_mm / grid) * grid)


def snap_grid(value_mm: float, allowed: Sequence[int]) -> int:
    """
    Snap value_mm to the nearest value in the allowed list.

    Examples:
        snap_grid(6150, GRID_HEALTHCARE_MM)  → 6000
        snap_grid(4000, GRID_HEALTHCARE_MM)  → 4200
        snap_grid(7000, GRID_HEALTHCARE_MM)  → 7200
    """
    return min(allowed, key=lambda x: abs(x - value_mm))


def m_to_mm(value_m: float, grid: int = 100) -> int:
    """Convert metres to mm and snap to grid."""
    return snap_mm(value_m * 1000, grid)


def mm_to_m(value_mm: float) -> float:
    """Convert mm to metres, rounded to 3 decimal places."""
    return round(value_mm / 1000, 3)


def room_dims_snapped(area_m2: float,
                       width_hint_m: float | None = None,
                       depth_hint_m: float | None = None,
                       building_type: str = "healthcare") -> dict:
    """
    Return snapped room dimensions (mm and m) for a given area.

    Prefers width_hint / depth_hint if supplied, otherwise computes a
    near-square aspect ratio and snaps to the SE planning module.

    Returns:
        {
            "width_mm": int, "depth_mm": int,
            "width_m": float, "depth_m": float,
            "area_m2": float,            # actual after snap
            "grid_module": int,
        }
    """
    grid = SE.GRID_MODULE  # 1200 mm

    if "health" in building_type.lower():
        spans = GRID_HEALTHCARE_MM
    else:
        spans = GRID_OFFICE_MM

    if width_hint_m and depth_hint_m:
        w_mm = snap_mm(width_hint_m * 1000, 100)
        d_mm = snap_mm(depth_hint_m * 1000, 100)
    elif width_hint_m:
        w_mm = snap_mm(width_hint_m * 1000, 100)
        # derive depth from area
        d_mm = snap_mm((area_m2 / (w_mm / 1000)) * 1000, 100)
    else:
        # Compute near-square from area and snap both dims
        side = math.sqrt(area_m2 * 1_000_000)  # in mm
        w_mm = snap_mm(side, 100)
        d_mm = snap_mm((area_m2 * 1_000_000 / w_mm), 100)

    actual_area = round((w_mm / 1000) * (d_mm / 1000), 2)

    return {
        "width_mm":  w_mm,
        "depth_mm":  d_mm,
        "width_m":   mm_to_m(w_mm),
        "depth_m":   mm_to_m(d_mm),
        "area_m2":   actual_area,
        "grid_module": grid,
    }

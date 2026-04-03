"""
SE Fire — Swedish fire safety standards for ArchitectAI.

Sources:
  - BBR 2023 (BFS 2011:6), avsnitt 5:  Brand
  - SS-EN 13501-1:2018  Brandklassificering av byggprodukter
  - AFS 2021:1  Systematiskt brandskyddsarbete
  - SRVFS 2004:3  Sprinkler i vårdinrättningar
  - MSB riktlinje 2013:5  Utrymning av vårdinrättningar

Usage:
    from src.tools.se_fire import SE_FIRE, FireClass, escape_route_ok

    # Check if building class requires sprinkler
    SE_FIRE.requires_sprinkler(building_class="Vk3C")   # → True

    # Max travel distance to nearest exit for this class
    SE_FIRE.max_travel_distance_m("Vk3C")  # → 30

    # Inject into agent prompt
    SE_FIRE.prompt_block("healthcare")
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Building classes (Verksamhetsklass) — BBR 5:21
# ---------------------------------------------------------------------------
# Vk1   Dwellings
# Vk2   Offices, schools (persons awake, familiar)
# Vk3   Healthcare (persons may be asleep / unable to self-evacuate)
#   Vk3A  Outpatient, no overnight
#   Vk3B  Residential care (nursing homes)
#   Vk3C  Hospital wards (bed-ridden patients)
# Vk4   Hotels / accommodation
# Vk5   Assembly (theatres, arenas)
# Vk6   Retail
# ---------------------------------------------------------------------------

BUILDING_CLASS_HEALTHCARE_WARD = "Vk3C"
BUILDING_CLASS_NURSING_HOME    = "Vk3B"
BUILDING_CLASS_OUTPATIENT      = "Vk3A"


@dataclass(frozen=True)
class FireClassSpec:
    """Specification for a Swedish fire protection class (Br-klass)."""
    code: str             # e.g. "Br1"
    description: str
    max_height_m: float   # Max building height for this class
    requires_sprinkler_always: bool
    max_floors: int       # Indicative (BBR defines by height, not floors)
    notes: str = ""


FIRE_CLASSES: dict[str, FireClassSpec] = {
    "Br0": FireClassSpec(
        code="Br0",
        description="Highest fire protection — critical infrastructure, tunnels",
        max_height_m=9999, requires_sprinkler_always=True, max_floors=99,
        notes="Special design — case-by-case with authority",
    ),
    "Br1": FireClassSpec(
        code="Br1",
        description="High fire protection — buildings > 16 m, healthcare wards",
        max_height_m=9999, requires_sprinkler_always=True, max_floors=99,
        notes="Standard for Swedish hospital wards (Vk3C). Sprinkler always required.",
    ),
    "Br2": FireClassSpec(
        code="Br2",
        description="Medium fire protection — buildings 8–16 m",
        max_height_m=16.0, requires_sprinkler_always=False, max_floors=4,
        notes="Sprinkler required if Vk3 occupancy.",
    ),
    "Br3": FireClassSpec(
        code="Br3",
        description="Low fire protection — buildings ≤ 8 m, 1–2 storey",
        max_height_m=8.0, requires_sprinkler_always=False, max_floors=2,
        notes="Sprinkler rarely required unless mixed Vk3.",
    ),
}


# ---------------------------------------------------------------------------
# Fire compartment limits — BBR 5:52 (area in m²)
# ---------------------------------------------------------------------------

# Max fire compartment floor area by occupancy class and Br-klass
COMPARTMENT_MAX_AREA_M2: dict[str, dict[str, float]] = {
    "Vk3C": {"Br1": 1250.0, "Br2": 800.0,  "Br3": 400.0},
    "Vk3B": {"Br1": 1500.0, "Br2": 1000.0, "Br3": 500.0},
    "Vk3A": {"Br1": 2500.0, "Br2": 1500.0, "Br3": 800.0},
    "Vk2":  {"Br1": 5000.0, "Br2": 2500.0, "Br3": 1250.0},
    "Vk1":  {"Br1": 9999.0, "Br2": 9999.0, "Br3": 200.0},   # dwelling: per unit
}

DEFAULT_COMPARTMENT_MAX_M2 = 1250.0  # safe default for healthcare


# ---------------------------------------------------------------------------
# Escape routes — BBR 5:3
# ---------------------------------------------------------------------------

# Max travel distance (m) from any point to the nearest exit
# (direct path, not via another compartment)
MAX_TRAVEL_DISTANCE_M: dict[str, float] = {
    "Vk3C": 30.0,   # Bed-ridden — very short (staff must assist)
    "Vk3B": 30.0,
    "Vk3A": 45.0,
    "Vk2":  45.0,
    "Vk1":  30.0,   # Per apartment (BBR 5:332)
}

# Min number of independent escape routes per floor
MIN_ESCAPE_ROUTES: dict[str, int] = {
    "Vk3C": 2,
    "Vk3B": 2,
    "Vk3A": 2,
    "Vk2":  2,
    "Vk1":  1,   # Single stair allowed for small buildings
}

# Min stair clear width (mm)
STAIR_WIDTH_MIN_MM: dict[str, int] = {
    "Vk3C": 1400,   # Must allow bed evacuation (BBR 5:351)
    "Vk3B": 1200,
    "Vk3A": 1200,
    "Vk2":  1200,
    "Vk1":  900,
}

# Min corridor clear width for evacuation (mm) — may differ from design width
EVACUATION_CORRIDOR_MM: dict[str, int] = {
    "Vk3C": 2400,   # Bed + wheelchair passing = SS 91 42 21
    "Vk3B": 1800,
    "default": 1500,
}


# ---------------------------------------------------------------------------
# Fire resistance ratings — SS-EN 13501-2
# ---------------------------------------------------------------------------

# Minimum fire resistance (minutes) for structural elements by Br-klass
STRUCTURAL_FIRE_RESISTANCE_MIN: dict[str, int] = {
    "Br1": 90,   # R90 — columns, beams, load-bearing walls
    "Br2": 60,   # R60
    "Br3": 30,   # R30
}

# Compartment walls / floors (EI — integrity + insulation)
COMPARTMENT_WALL_EI_MIN: dict[str, int] = {
    "Br1": 90,
    "Br2": 60,
    "Br3": 30,
}

# Door fire rating in compartment boundary (minutes)
FIRE_DOOR_EI_MIN: dict[str, int] = {
    "Br1": 60,
    "Br2": 30,
    "Br3": 30,
}


# ---------------------------------------------------------------------------
# Surface material classes — SS-EN 13501-1
# ---------------------------------------------------------------------------

# Min reaction-to-fire class for internal surfaces by space type and Br-klass
# Format: "classification" (D, C, B, A2, A1 — A1 is best)
SURFACE_CLASS_MIN: dict[str, dict[str, str]] = {
    "wall_ceiling": {
        "Br1_Vk3": "B-s1,d0",    # Hospital corridor / ward
        "Br1_general": "C-s2,d1",
        "Br2": "D-s2,d2",
        "Br3": "D-s3,d2",
    },
    "floor": {
        "Br1_Vk3": "Cfl-s1",
        "Br1_general": "Cfl-s1",
        "Br2": "Dfl-s1",
        "Br3": "Efl",
    },
}


# ---------------------------------------------------------------------------
# Helper class
# ---------------------------------------------------------------------------

class SE_FIRE:
    """Swedish fire safety rules — query interface for ArchitectAI agents."""

    @staticmethod
    def building_class_for(building_type: str) -> str:
        """Return the most appropriate Verksamhetsklass for a building type."""
        bt = building_type.lower()
        if "ward" in bt or "inpatient" in bt or "hospital" in bt:
            return BUILDING_CLASS_HEALTHCARE_WARD   # Vk3C
        if "nursing" in bt or "care home" in bt or "äldreboende" in bt:
            return BUILDING_CLASS_NURSING_HOME      # Vk3B
        if "outpatient" in bt or "clinic" in bt or "mottagning" in bt:
            return BUILDING_CLASS_OUTPATIENT        # Vk3A
        return "Vk2"  # safe default

    @staticmethod
    def requires_sprinkler(building_class: str, fire_class: str = "Br1") -> bool:
        """True if sprinkler is mandatory for this class combination."""
        spec = FIRE_CLASSES.get(fire_class)
        if spec and spec.requires_sprinkler_always:
            return True
        # Vk3 always requires sprinkler regardless of Br-class per SRVFS 2004:3
        return building_class.startswith("Vk3")

    @staticmethod
    def max_compartment_area_m2(building_class: str = "Vk3C",
                                 fire_class: str = "Br1") -> float:
        """Return max fire compartment area (m²) for this class combination."""
        by_bclass = COMPARTMENT_MAX_AREA_M2.get(building_class, {})
        return by_bclass.get(fire_class, DEFAULT_COMPARTMENT_MAX_M2)

    @staticmethod
    def max_travel_distance_m(building_class: str = "Vk3C") -> float:
        """Max travel distance (m) to nearest escape route."""
        return MAX_TRAVEL_DISTANCE_M.get(building_class, 45.0)

    @staticmethod
    def min_stair_width_mm(building_class: str = "Vk3C") -> int:
        """Minimum stair clear width in mm."""
        return STAIR_WIDTH_MIN_MM.get(building_class, 1200)

    @staticmethod
    def structural_fire_resistance_min(fire_class: str = "Br1") -> int:
        """Required fire resistance of structural elements (minutes)."""
        return STRUCTURAL_FIRE_RESISTANCE_MIN.get(fire_class, 60)

    @staticmethod
    def compartment_wall_ei_min(fire_class: str = "Br1") -> int:
        """Required EI rating for compartment walls/floors (minutes)."""
        return COMPARTMENT_WALL_EI_MIN.get(fire_class, 60)

    @staticmethod
    def prompt_block(building_type: str = "healthcare",
                     fire_class: str = "Br1") -> str:
        """Formatted fire safety reference block for agent prompts."""
        bc = SE_FIRE.building_class_for(building_type)
        max_area    = SE_FIRE.max_compartment_area_m2(bc, fire_class)
        max_travel  = SE_FIRE.max_travel_distance_m(bc)
        stair_w     = SE_FIRE.min_stair_width_mm(bc)
        struct_r    = SE_FIRE.structural_fire_resistance_min(fire_class)
        wall_ei     = SE_FIRE.compartment_wall_ei_min(fire_class)
        door_ei     = FIRE_DOOR_EI_MIN.get(fire_class, 60)
        sprinkler   = SE_FIRE.requires_sprinkler(bc, fire_class)
        n_escapes   = MIN_ESCAPE_ROUTES.get(bc, 2)
        evac_corr   = EVACUATION_CORRIDOR_MM.get(bc, EVACUATION_CORRIDOR_MM["default"])

        return f"""
SE FIRE SAFETY (BBR 2023 avsnitt 5 / SS-EN 13501):
- Building class: {bc} | Fire protection class: {fire_class}
- Sprinkler required: {"YES — mandatory (SRVFS 2004:3)" if sprinkler else "No (verify with Br-klass)"}
- Max fire compartment area: {max_area:.0f} m²
- Max travel distance to exit: {max_travel:.0f} m
- Min escape routes per floor: {n_escapes}
- Min stair clear width: {stair_w} mm (bed evacuation)
- Min evacuation corridor width: {evac_corr} mm
- Structural fire resistance: R{struct_r} (columns, beams, load-bearing walls)
- Compartment walls/floors: EI{wall_ei}
- Fire doors in compartment boundary: EI{door_ei}
- Surface class (walls/ceiling, ward): B-s1,d0
- Surface class (floor, ward): Cfl-s1
- Compartment boundaries must align with structural grid lines.
- Shafts penetrating compartments require fire-dampers + fire-stopping.
""".strip()

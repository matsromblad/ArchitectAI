"""
SE Lighting — Swedish lighting and daylight standards for ArchitectAI.

Sources:
  - SS-EN 12464-1:2021  Belysning på arbetsplatser inomhus
  - BBR 2023 avsnitt 6:32  Dagsljus
  - AFS 2009:2  Arbetsplatsers utformning (§13–14 belysning)
  - SS 91 42 21:2017  Projektering av vårdlokaler (klinisk belysning)
  - Ljuskultur riktlinje 2020  Belysning i vård och omsorg

Usage:
    from src.tools.se_lighting import SE_LIGHTING, RoomLightSpec

    spec = SE_LIGHTING.spec_for("patient_room")
    spec.maintained_lux       # 100 general, 500 reading/exam
    spec.ugr_max              # unified glare rating limit
    spec.ra_min               # colour rendering index min

    SE_LIGHTING.prompt_block("healthcare")
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class RoomLightSpec:
    """Lighting specification for a room type (SS-EN 12464-1 + SE additions)."""
    room_type:          str
    maintained_lux:     int          # Em — maintained illuminance (general)
    exam_lux:           Optional[int]  # Higher task illuminance (clinical)
    ugr_max:            int          # Unified Glare Rating limit
    ra_min:             int          # Colour Rendering Index (CRI) minimum
    kelvin_range:       tuple        # Colour temperature range (K)
    emergency_lux:      int          # Min during power failure (SS-EN 1838)
    daylight_factor_min: float       # Min daylight factor % (BBR 6:32)
    notes:              str = ""


# ---------------------------------------------------------------------------
# Room lighting specs
# ---------------------------------------------------------------------------

LIGHT_SPECS: dict[str, RoomLightSpec] = {
    "patient_room": RoomLightSpec(
        room_type="patient_room",
        maintained_lux=100,
        exam_lux=300,           # Reading light at bedhead
        ugr_max=19,
        ra_min=90,              # High CRI for clinical observation (SS 91 42 21)
        kelvin_range=(2700, 4000),  # Tunable white recommended
        emergency_lux=1,
        daylight_factor_min=1.0,   # BBR 6:32 — residential/patient rooms
        notes="Tunable white 2700–4000 K (circadian support). Bedhead reading lamp 300 lux."
              " Glare-free ceiling fittings critical for bed-bound patients.",
    ),
    "isolation_room": RoomLightSpec(
        room_type="isolation_room",
        maintained_lux=200,
        exam_lux=500,
        ugr_max=19,
        ra_min=90,
        kelvin_range=(3000, 4000),
        emergency_lux=1,
        daylight_factor_min=1.0,
        notes="Higher maintained lux for clinical tasks. All fittings IP44 for cleaning.",
    ),
    "nurse_station": RoomLightSpec(
        room_type="nurse_station",
        maintained_lux=500,
        exam_lux=None,
        ugr_max=19,
        ra_min=80,
        kelvin_range=(3500, 5000),
        emergency_lux=5,
        daylight_factor_min=0.5,
        notes="SS-EN 12464-1 table 5.4.4 — healthcare workstation. Emergency 5 lux for evacuation.",
    ),
    "examination_room": RoomLightSpec(
        room_type="examination_room",
        maintained_lux=500,
        exam_lux=1000,           # Procedure lighting (shadowless if surgical)
        ugr_max=19,
        ra_min=90,
        kelvin_range=(4000, 5000),
        emergency_lux=5,
        daylight_factor_min=0.5,
        notes="CRI 90+ mandatory for skin tone assessment. Procedure light on mobile arm.",
    ),
    "clean_utility": RoomLightSpec(
        room_type="clean_utility",
        maintained_lux=300,
        exam_lux=None,
        ugr_max=22,
        ra_min=80,
        kelvin_range=(4000, 5000),
        emergency_lux=1,
        daylight_factor_min=0.0,  # No window required
        notes="IP44 fittings for wet cleaning. Cool white for sterile visual checks.",
    ),
    "dirty_utility": RoomLightSpec(
        room_type="dirty_utility",
        maintained_lux=300,
        exam_lux=None,
        ugr_max=22,
        ra_min=80,
        kelvin_range=(4000, 5000),
        emergency_lux=1,
        daylight_factor_min=0.0,
        notes="IP44. No natural light required but appreciated.",
    ),
    "corridor": RoomLightSpec(
        room_type="corridor",
        maintained_lux=200,
        exam_lux=None,
        ugr_max=22,
        ra_min=80,
        kelvin_range=(3000, 4000),
        emergency_lux=1,
        daylight_factor_min=0.0,
        notes="Night-mode lighting (5–10 lux at floor) for patient safety. SS-EN 12464-1 §5.4.3.",
    ),
    "day_room": RoomLightSpec(
        room_type="day_room",
        maintained_lux=200,
        exam_lux=None,
        ugr_max=19,
        ra_min=80,
        kelvin_range=(2700, 4000),
        emergency_lux=1,
        daylight_factor_min=2.0,   # Higher daylight factor — social space
        notes="Tunable white for circadian support. Large windows preferred.",
    ),
    "bathroom_wc": RoomLightSpec(
        room_type="bathroom_wc",
        maintained_lux=200,
        exam_lux=None,
        ugr_max=25,
        ra_min=80,
        kelvin_range=(2700, 4000),
        emergency_lux=1,
        daylight_factor_min=0.0,
        notes="IP44/IP65 over shower/bath. Night light 5 lux for patient safety.",
    ),
    "office": RoomLightSpec(
        room_type="office",
        maintained_lux=500,
        exam_lux=None,
        ugr_max=19,
        ra_min=80,
        kelvin_range=(3500, 4500),
        emergency_lux=1,
        daylight_factor_min=0.5,   # BBR: workplaces must have daylight access
        notes="SS-EN 12464-1 §5.3.1 — screen work. Anti-glare on luminaires mandatory.",
    ),
}

_FALLBACK_SPEC = RoomLightSpec(
    room_type="general",
    maintained_lux=200, exam_lux=None,
    ugr_max=22, ra_min=80,
    kelvin_range=(3000, 4000),
    emergency_lux=1, daylight_factor_min=0.5,
    notes="Default spec — verify against room type.",
)


# ---------------------------------------------------------------------------
# Daylight rules (BBR 6:32)
# ---------------------------------------------------------------------------

# Min window area as fraction of floor area for habitable rooms
DAYLIGHT_WINDOW_FRACTION_MIN = 0.10   # 10% of floor area as glazing

# Min daylight factor at working plane (1.0 = 1%)
DAYLIGHT_FACTOR_HABITABLE_MIN = 1.0   # %

# Max depth a room can be from a window and still meet BBR daylight rules
# Rule of thumb: room depth ≤ 2.5 × window head height
DAYLIGHT_DEPTH_FACTOR = 2.5


# ---------------------------------------------------------------------------
# Helper class
# ---------------------------------------------------------------------------

class SE_LIGHTING:
    """Swedish lighting rules — query interface for ArchitectAI agents."""

    @staticmethod
    def spec_for(room_type_key: str) -> RoomLightSpec:
        """Return the lighting spec for a room type key."""
        return LIGHT_SPECS.get(room_type_key, _FALLBACK_SPEC)

    @staticmethod
    def classify_room(room_name: str) -> str:
        """Best-effort room type key from room name (matches SE_HVAC.classify_room keys)."""
        n = room_name.lower()
        if "isolation" in n and "anteroom" not in n:
            return "isolation_room"
        if "patient" in n or "bedroom" in n or "patientrum" in n:
            return "patient_room"
        if "exam" in n or "undersök" in n:
            return "examination_room"
        if "nurse" in n or "expedition" in n:
            return "nurse_station"
        if "clean" in n and "util" in n:
            return "clean_utility"
        if "dirty" in n or "smutsrum" in n:
            return "dirty_utility"
        if "corridor" in n or "korridor" in n:
            return "corridor"
        if "day" in n or "dagrum" in n:
            return "day_room"
        if "wc" in n or "toalett" in n or "bath" in n or "shower" in n:
            return "bathroom_wc"
        if "office" in n or "kontor" in n:
            return "office"
        return "general"

    @staticmethod
    def window_area_min_m2(floor_area_m2: float) -> float:
        """Min glazing area (m²) for a room to meet BBR 6:32."""
        return round(floor_area_m2 * DAYLIGHT_WINDOW_FRACTION_MIN, 2)

    @staticmethod
    def max_room_depth_m(window_head_height_m: float) -> float:
        """Max usable room depth from window to still achieve daylight (rule of thumb)."""
        return round(window_head_height_m * DAYLIGHT_DEPTH_FACTOR, 1)

    @staticmethod
    def prompt_block(building_type: str = "healthcare") -> str:
        """Formatted lighting reference block for agent prompts."""
        is_hc = "health" in building_type.lower() or "ward" in building_type.lower()

        if is_hc:
            key_rooms = [
                ("patient_room",    LIGHT_SPECS["patient_room"]),
                ("isolation_room",  LIGHT_SPECS["isolation_room"]),
                ("nurse_station",   LIGHT_SPECS["nurse_station"]),
                ("examination_room",LIGHT_SPECS["examination_room"]),
                ("corridor",        LIGHT_SPECS["corridor"]),
                ("day_room",        LIGHT_SPECS["day_room"]),
                ("bathroom_wc",     LIGHT_SPECS["bathroom_wc"]),
            ]
        else:
            key_rooms = [
                ("office",   LIGHT_SPECS["office"]),
                ("corridor", LIGHT_SPECS["corridor"]),
            ]

        rows = []
        for key, spec in key_rooms:
            task = f" (task:{spec.exam_lux})" if spec.exam_lux else ""
            rows.append(
                f"  {key:<22}: {spec.maintained_lux:>4} lux{task:<13}  "
                f"UGR≤{spec.ugr_max}  Ra≥{spec.ra_min}  "
                f"{spec.kelvin_range[0]}–{spec.kelvin_range[1]}K  "
                f"DF≥{spec.daylight_factor_min}%"
            )
        table = "\n".join(rows)

        return f"""
SE LIGHTING (SS-EN 12464-1 / BBR 6:32 / AFS 2009:2):
Room lighting requirements (Em = maintained lux):
{table}
General rules:
- Habitable rooms: window area ≥ {DAYLIGHT_WINDOW_FRACTION_MIN*100:.0f}% of floor area (BBR 6:32)
- Max room depth from window: {DAYLIGHT_DEPTH_FACTOR}× window head height
- Min daylight factor (habitable rooms): {DAYLIGHT_FACTOR_HABITABLE_MIN}%
- Clinical areas: CRI (Ra) ≥ 90 for skin tone assessment
- Emergency lighting: SS-EN 1838 — corridors 1 lux min, stairs 5 lux
- Night mode (wards, 22:00–06:00): 5–10 lux at floor level
- All luminaires in wet rooms: min IP44
""".strip()

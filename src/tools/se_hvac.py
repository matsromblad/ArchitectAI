"""
SE HVAC — Swedish ventilation and indoor climate standards for ArchitectAI.

Sources:
  - BBR 2023 (BFS 2011:6), avsnitt 6:  Hygien, hälsa och miljö
  - AFS 2015:4  Organisatorisk och social arbetsmiljö (thermal comfort)
  - SS-EN 13779:2007  Ventilation för byggnader (OVK basis)
  - SS 25268:2007+T1:2017  Ljud i byggnader (max sound from HVAC)
  - Arbetsmiljöverkets riktlinje ADI 468  Ventilation i sjukvård
  - Socialstyrelsen SOSFS 2013:7  Vård och omsorg vid demenssjukdom

Usage:
    from src.tools.se_hvac import SE_HVAC, RoomVentSpec

    spec = SE_HVAC.spec_for("patient_room")
    print(spec.supply_l_s_per_m2)        # l/s per m²
    print(spec.min_ach)                  # air changes/hour
    print(spec.pressure_regime)          # "positive" | "negative" | "neutral"
    print(spec.max_sound_dB)             # NR/dB limit from HVAC

    SE_HVAC.prompt_block("healthcare")   # full formatted string for agent prompts
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RoomVentSpec:
    """Ventilation specification for a room type."""
    room_type:         str
    supply_l_s_per_m2: float   # litre/second per m² floor area (BBR 6:251)
    min_ach:           float   # minimum air changes per hour
    pressure_regime:   str     # "positive" | "negative" | "neutral"
    filtration:        str     # e.g. "H14-HEPA", "F7", "G4"
    max_sound_db:      int     # max sound level from HVAC (NR/dB), SS 25268
    temp_min_c:        float   # min operative temperature (°C)
    temp_max_c:        float   # max operative temperature (°C)
    humidity_min_rh:   int     # min relative humidity %
    humidity_max_rh:   int     # max relative humidity %
    notes:             str = ""


# ---------------------------------------------------------------------------
# Room ventilation specs — Swedish healthcare + general
# ---------------------------------------------------------------------------

VENT_SPECS: dict[str, RoomVentSpec] = {
    # ── Patient areas ─────────────────────────────────────────────────────
    "patient_room": RoomVentSpec(
        room_type="patient_room",
        supply_l_s_per_m2=1.5, min_ach=6.0,
        pressure_regime="neutral",
        filtration="F7",
        max_sound_db=30,
        temp_min_c=20.0, temp_max_c=24.0,
        humidity_min_rh=30, humidity_max_rh=60,
        notes="BBR 6:251 + ADI 468. Individual temp control recommended.",
    ),
    "isolation_room": RoomVentSpec(
        room_type="isolation_room",
        supply_l_s_per_m2=2.0, min_ach=12.0,
        pressure_regime="negative",     # Airborne infection control
        filtration="H14-HEPA",
        max_sound_db=35,
        temp_min_c=20.0, temp_max_c=24.0,
        humidity_min_rh=30, humidity_max_rh=60,
        notes="Negative pressure vs corridor. HEPA on exhaust. Anteroom at neutral.",
    ),
    "isolation_anteroom": RoomVentSpec(
        room_type="isolation_anteroom",
        supply_l_s_per_m2=2.0, min_ach=10.0,
        pressure_regime="neutral",
        filtration="F7",
        max_sound_db=35,
        temp_min_c=20.0, temp_max_c=24.0,
        humidity_min_rh=30, humidity_max_rh=60,
        notes="Buffer between corridor (neutral) and isolation room (negative).",
    ),
    "clean_utility": RoomVentSpec(
        room_type="clean_utility",
        supply_l_s_per_m2=1.5, min_ach=6.0,
        pressure_regime="positive",     # Prevent contamination entry
        filtration="F7",
        max_sound_db=40,
        temp_min_c=18.0, temp_max_c=25.0,
        humidity_min_rh=30, humidity_max_rh=60,
        notes="Positive pressure to protect sterile supplies.",
    ),
    "dirty_utility": RoomVentSpec(
        room_type="dirty_utility",
        supply_l_s_per_m2=2.0, min_ach=10.0,
        pressure_regime="negative",
        filtration="F7",
        max_sound_db=45,
        temp_min_c=18.0, temp_max_c=25.0,
        humidity_min_rh=30, humidity_max_rh=70,
        notes="Negative pressure — exhausted directly outside, not recirculated.",
    ),
    "nurse_station": RoomVentSpec(
        room_type="nurse_station",
        supply_l_s_per_m2=1.5, min_ach=5.0,
        pressure_regime="neutral",
        filtration="F7",
        max_sound_db=35,
        temp_min_c=20.0, temp_max_c=23.0,
        humidity_min_rh=30, humidity_max_rh=60,
        notes="Higher cognitive load — temp control important. AFS 2015:4.",
    ),
    "day_room": RoomVentSpec(
        room_type="day_room",
        supply_l_s_per_m2=1.2, min_ach=4.0,
        pressure_regime="neutral",
        filtration="F7",
        max_sound_db=35,
        temp_min_c=20.0, temp_max_c=24.0,
        humidity_min_rh=30, humidity_max_rh=60,
    ),
    "bathroom_wc": RoomVentSpec(
        room_type="bathroom_wc",
        supply_l_s_per_m2=0.0, min_ach=10.0,  # exhaust only, no supply
        pressure_regime="negative",
        filtration="G4",
        max_sound_db=45,
        temp_min_c=22.0, temp_max_c=26.0,
        humidity_min_rh=30, humidity_max_rh=75,
        notes="Extract only. 10 ACH min. Direct exhaust to outside (BBR 6:253).",
    ),
    # ── General / office ──────────────────────────────────────────────────
    "office": RoomVentSpec(
        room_type="office",
        supply_l_s_per_m2=1.0, min_ach=3.0,
        pressure_regime="neutral",
        filtration="F7",
        max_sound_db=35,
        temp_min_c=20.0, temp_max_c=24.0,
        humidity_min_rh=25, humidity_max_rh=60,
        notes="BBR 6:251 — min 0.35 l/s/m² for occupied rooms.",
    ),
    "corridor": RoomVentSpec(
        room_type="corridor",
        supply_l_s_per_m2=0.5, min_ach=2.0,
        pressure_regime="neutral",
        filtration="F7",
        max_sound_db=40,
        temp_min_c=18.0, temp_max_c=25.0,
        humidity_min_rh=25, humidity_max_rh=65,
    ),
}

_FALLBACK_SPEC = RoomVentSpec(
    room_type="general",
    supply_l_s_per_m2=1.0, min_ach=3.0,
    pressure_regime="neutral",
    filtration="F7",
    max_sound_db=40,
    temp_min_c=18.0, temp_max_c=25.0,
    humidity_min_rh=25, humidity_max_rh=65,
    notes="Default spec — verify against specific room type.",
)


# ---------------------------------------------------------------------------
# Shaft sizing rules of thumb (mm)
# ---------------------------------------------------------------------------

# Min shaft dimensions (clear internal) for riser bundles
SHAFT_MIN_WIDTH_MM  = 600   # smallest practical shaft
SHAFT_TYPICAL_MM    = 1200  # for combined HVAC + plumbing riser
SHAFT_HEPA_MIN_MM   = 800   # HEPA duct needs more space

# Duct velocities (m/s) — determines duct sizing, informs sound levels
DUCT_VELOCITY_SUPPLY_MAX  = 5.0   # m/s supply (above = noise risk)
DUCT_VELOCITY_EXHAUST_MAX = 6.0   # m/s exhaust


# ---------------------------------------------------------------------------
# OVK (Obligatorisk Ventilationskontroll) — mandatory inspection intervals
# ---------------------------------------------------------------------------

OVK_INTERVAL_YEARS: dict[str, int] = {
    "Vk3_healthcare": 3,   # Vk3 + Vk4: 3 years (SFS 2011:338)
    "Vk2_office":     6,   # Offices, schools
    "Vk1_resi":       6,   # Dwellings with FT/FTX
}


# ---------------------------------------------------------------------------
# Helper class
# ---------------------------------------------------------------------------

class SE_HVAC:
    """Swedish HVAC/ventilation rules — query interface for ArchitectAI agents."""

    @staticmethod
    def min_shaft_size_m() -> float:
        """Minimum shaft clear dimension in metres (smallest practical riser)."""
        return SHAFT_MIN_WIDTH_MM / 1000

    @staticmethod
    def max_duct_velocity_m_s(duct_type: str = "supply") -> float:
        """Max duct air velocity (m/s) for occupied zones."""
        if duct_type == "return":
            return DUCT_VELOCITY_EXHAUST_MAX
        return DUCT_VELOCITY_SUPPLY_MAX

    @staticmethod
    def spec_for(room_type_key: str) -> RoomVentSpec:
        """
        Return the ventilation spec for a room type key.

        Keys: "patient_room", "isolation_room", "isolation_anteroom",
              "clean_utility", "dirty_utility", "nurse_station",
              "day_room", "bathroom_wc", "office", "corridor"
        """
        return VENT_SPECS.get(room_type_key, _FALLBACK_SPEC)

    @staticmethod
    def classify_room(room_name: str) -> str:
        """Best-effort room type key from room name."""
        n = room_name.lower()
        if "isolation" in n and "anteroom" in n:
            return "isolation_anteroom"
        if "isolation" in n:
            return "isolation_room"
        if "patient" in n or "bedroom" in n or "ward room" in n or "patientrum" in n:
            return "patient_room"
        if "clean" in n and ("util" in n or "förråd" in n):
            return "clean_utility"
        if "dirty" in n or "smutsrum" in n or "sluice" in n:
            return "dirty_utility"
        if "nurse" in n or "expedition" in n or "sjuksköterska" in n:
            return "nurse_station"
        if "day" in n or "dagrum" in n or "dining" in n:
            return "day_room"
        if "wc" in n or "toalett" in n or "bath" in n or "shower" in n or "dusch" in n:
            return "bathroom_wc"
        if "corridor" in n or "korridor" in n:
            return "corridor"
        if "office" in n or "kontor" in n:
            return "office"
        return "general"

    @staticmethod
    def prompt_block(building_type: str = "healthcare") -> str:
        """Formatted HVAC reference block for injection into agent prompts."""
        is_hc = "health" in building_type.lower() or "ward" in building_type.lower()

        if is_hc:
            key_rooms = [
                ("patient_room",        VENT_SPECS["patient_room"]),
                ("isolation_room",      VENT_SPECS["isolation_room"]),
                ("isolation_anteroom",  VENT_SPECS["isolation_anteroom"]),
                ("clean_utility",       VENT_SPECS["clean_utility"]),
                ("dirty_utility",       VENT_SPECS["dirty_utility"]),
                ("bathroom_wc",         VENT_SPECS["bathroom_wc"]),
                ("nurse_station",       VENT_SPECS["nurse_station"]),
            ]
        else:
            key_rooms = [
                ("office",   VENT_SPECS["office"]),
                ("corridor", VENT_SPECS["corridor"]),
            ]

        rows = []
        for key, spec in key_rooms:
            rows.append(
                f"  {key:<25}: {spec.supply_l_s_per_m2} l/s/m²  "
                f"≥{spec.min_ach} ACH  {spec.pressure_regime:<9}  "
                f"filter:{spec.filtration}  NR≤{spec.max_sound_db}dB  "
                f"{spec.temp_min_c}–{spec.temp_max_c}°C"
            )
        table = "\n".join(rows)

        return f"""
SE HVAC / VENTILATION (BBR 2023 avsnitt 6 / ADI 468 / SS 25268):
Room ventilation requirements:
{table}
General rules:
- Pressure cascade: positive (clean utility) > neutral (patient/corridor) > negative (dirty/WC/isolation)
- Isolation room: negative pressure, H14-HEPA on exhaust, anteroom as airlock
- WC/bathroom: extract only, 10 ACH min, direct exhaust (no recirculation)
- Duct supply velocity ≤ {DUCT_VELOCITY_SUPPLY_MAX} m/s (noise limit)
- OVK inspection: every {OVK_INTERVAL_YEARS.get("Vk3_healthcare", 3)} years for Vk3 healthcare
- Shaft min width: {SHAFT_MIN_WIDTH_MM} mm; typical riser: {SHAFT_TYPICAL_MM} mm
""".strip()

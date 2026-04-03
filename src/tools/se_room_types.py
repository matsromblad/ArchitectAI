"""
SE Room Types — canonical room type definitions for Swedish healthcare buildings.

Provides a single source of truth for room type keys, minimum areas,
IFC space types, and BIM classification codes.

Sources:
  - SS 91 42 21:2017  Projektering av vårdlokaler
  - BSAB 96  Swedish building classification (room type codes)
  - SfB / UNICLASS 2015  BIM classification
  - SS-EN ISO 9836:2017  Areabegrepp (area definitions)

Usage:
    from src.tools.se_room_types import SE_ROOMS, RoomTypeDef, lookup_room

    defn = SE_ROOMS.lookup("patient_room")
    defn.min_area_m2           # 12.0
    defn.preferred_area_m2     # 18.0
    defn.bsab_code             # "62B"
    defn.ifc_space_type        # "BEDROOM"
    defn.zone                  # "clean"
    defn.required_in_ward      # True

    # Find best match for a room name
    defn = SE_ROOMS.match_name("Patientrum B")
    defn.ifc_space_type        # "BEDROOM"
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class RoomTypeDef:
    """Canonical definition of a Swedish healthcare room type."""
    key:                    str             # Internal key, e.g. "patient_room"
    display_name_sv:        str             # Swedish name
    display_name_en:        str             # English name
    min_area_m2:            float           # Absolute minimum (SS 91 42 21)
    preferred_area_m2:      float           # Recommended / comfortable size
    min_width_m:            float           # Min clear width (m)
    min_depth_m:            float           # Min clear depth (m)
    zone:                   str             # clean | dirty | staff | public | service
    access_type:            str             # restricted | staff | public
    ifc_space_type:         str             # IfcSpace PredefinedType or custom
    bsab_code:              str             # BSAB 96 code (Swedish standard)
    required_in_ward:       bool            # Must be present in a standard SE ward
    requires_window:        bool            # Natural light required (BBR)
    requires_sink:          bool            # Clinical hand-wash sink required
    requires_ensuite:       bool            # Has/needs attached WC/shower
    max_occupants:          int             # Design occupancy (persons)
    name_keywords_sv:       tuple           # Keywords for name matching (Swedish)
    name_keywords_en:       tuple           # Keywords for name matching (English)
    notes:                  str = ""


# ---------------------------------------------------------------------------
# Room type definitions — Swedish healthcare ward
# ---------------------------------------------------------------------------

_ROOM_TYPES: list[RoomTypeDef] = [
    # ── Patient rooms ─────────────────────────────────────────────────────
    RoomTypeDef(
        key="patient_room",
        display_name_sv="Patientrum (enkelrum)",
        display_name_en="Patient Bedroom (single)",
        min_area_m2=12.0, preferred_area_m2=18.0,
        min_width_m=3.6, min_depth_m=3.6,
        zone="clean", access_type="restricted",
        ifc_space_type="BEDROOM",
        bsab_code="62B",
        required_in_ward=True, requires_window=True,
        requires_sink=True, requires_ensuite=True,
        max_occupants=1,
        name_keywords_sv=("patientrum", "enkelsängsrum", "vårdrum"),
        name_keywords_en=("patient room", "patient bedroom", "ward room", "inpatient room"),
        notes="SS 91 42 21 §6.2: min 12 m² netto, 18 m² recommended for geriatric. "
              "Ensuite WC+shower mandatory. Handwash at entrance.",
    ),
    RoomTypeDef(
        key="isolation_room",
        display_name_sv="Isoleringsrum",
        display_name_en="Isolation Room",
        min_area_m2=16.0, preferred_area_m2=20.0,
        min_width_m=4.0, min_depth_m=4.0,
        zone="clean", access_type="restricted",
        ifc_space_type="BEDROOM",
        bsab_code="62B-ISO",
        required_in_ward=True, requires_window=True,
        requires_sink=True, requires_ensuite=True,
        max_occupants=1,
        name_keywords_sv=("isoleringsrum", "isolerums"),
        name_keywords_en=("isolation room", "iso room", "isolation"),
        notes="Must only be accessible via anteroom. Negative pressure ventilation.",
    ),
    RoomTypeDef(
        key="isolation_anteroom",
        display_name_sv="Isoleringsförrum / Sluss",
        display_name_en="Isolation Anteroom",
        min_area_m2=4.0, preferred_area_m2=8.0,
        min_width_m=1.8, min_depth_m=2.2,
        zone="clean", access_type="restricted",
        ifc_space_type="LOBBY",
        bsab_code="62S",
        required_in_ward=True, requires_window=False,
        requires_sink=True, requires_ensuite=False,
        max_occupants=2,
        name_keywords_sv=("förrum", "isoleringsförrum", "sluss", "airlock"),
        name_keywords_en=("anteroom", "airlock", "pre-room", "ante-room"),
        notes="Buffer between corridor and isolation room. Neutral pressure. Handwash mandatory.",
    ),
    RoomTypeDef(
        key="patient_ensuite",
        display_name_sv="Ensuite (WC+dusch)",
        display_name_en="Patient Ensuite (WC + shower)",
        min_area_m2=4.5, preferred_area_m2=6.0,
        min_width_m=1.8, min_depth_m=2.5,
        zone="dirty", access_type="restricted",
        ifc_space_type="SANITARYFACILITY",
        bsab_code="64E",
        required_in_ward=True, requires_window=False,
        requires_sink=True, requires_ensuite=False,
        max_occupants=1,
        name_keywords_sv=("ensuite", "badrum", "toalett", "wc", "dusch"),
        name_keywords_en=("ensuite", "bathroom", "toilet", "wc", "shower room"),
        notes="Min HIN 4 roll-in shower for geriatric. Grab rails mandatory (AFS 2009:2).",
    ),
    # ── Staff / clinical rooms ─────────────────────────────────────────────
    RoomTypeDef(
        key="nurse_station",
        display_name_sv="Expeditionsrum / Sjuksköterskestation",
        display_name_en="Nurse Station",
        min_area_m2=15.0, preferred_area_m2=22.0,
        min_width_m=4.0, min_depth_m=3.5,
        zone="staff", access_type="staff",
        ifc_space_type="OFFICE",
        bsab_code="63A",
        required_in_ward=True, requires_window=True,
        requires_sink=True, requires_ensuite=False,
        max_occupants=4,
        name_keywords_sv=("expeditionsrum", "sjuksköterskestation", "expedition", "nurses"),
        name_keywords_en=("nurse station", "nursing station", "staff base", "ward office"),
        notes="Central sightlines to corridor preferred. Medication room adjacent.",
    ),
    RoomTypeDef(
        key="medication_room",
        display_name_sv="Läkemedelsrum",
        display_name_en="Medication Room",
        min_area_m2=8.0, preferred_area_m2=12.0,
        min_width_m=2.5, min_depth_m=3.0,
        zone="staff", access_type="staff",
        ifc_space_type="STORAGE",
        bsab_code="63C",
        required_in_ward=True, requires_window=False,
        requires_sink=True, requires_ensuite=False,
        max_occupants=2,
        name_keywords_sv=("läkemedelsrum", "läkemedel", "medrum"),
        name_keywords_en=("medication room", "drug room", "pharmacy room", "medicines"),
        notes="LFSS 2012:9 — controlled drug storage. Lockable cupboards. Adjacent to nurse station.",
    ),
    RoomTypeDef(
        key="clean_utility",
        display_name_sv="Rent förråd (rent arbetsrum)",
        display_name_en="Clean Utility Room",
        min_area_m2=8.0, preferred_area_m2=12.0,
        min_width_m=2.4, min_depth_m=3.0,
        zone="staff", access_type="staff",
        ifc_space_type="STORAGE",
        bsab_code="64R",
        required_in_ward=True, requires_window=False,
        requires_sink=True, requires_ensuite=False,
        max_occupants=2,
        name_keywords_sv=("rent förråd", "rent arbetsrum", "förråd", "clean utility"),
        name_keywords_en=("clean utility", "clean store", "linen store", "clean room"),
        notes="SOSFS 2015:10 — strict separation from dirty utility. Positive pressure.",
    ),
    RoomTypeDef(
        key="dirty_utility",
        display_name_sv="Smutsrum (orent arbetsrum)",
        display_name_en="Dirty Utility Room",
        min_area_m2=8.0, preferred_area_m2=10.0,
        min_width_m=2.4, min_depth_m=3.0,
        zone="dirty", access_type="staff",
        ifc_space_type="STORAGE",
        bsab_code="64S",
        required_in_ward=True, requires_window=False,
        requires_sink=True, requires_ensuite=False,
        max_occupants=2,
        name_keywords_sv=("smutsrum", "orensrum", "smutsig", "sluice"),
        name_keywords_en=("dirty utility", "sluice room", "soiled utility", "dirty room"),
        notes="SOSFS 2015:10 — must not adjoin clean utility. Negative pressure. Bedpan washer.",
    ),
    RoomTypeDef(
        key="examination_room",
        display_name_sv="Undersökningsrum",
        display_name_en="Examination Room",
        min_area_m2=14.0, preferred_area_m2=18.0,
        min_width_m=3.6, min_depth_m=4.0,
        zone="clean", access_type="restricted",
        ifc_space_type="MEDICAL",
        bsab_code="62U",
        required_in_ward=False, requires_window=True,
        requires_sink=True, requires_ensuite=False,
        max_occupants=3,
        name_keywords_sv=("undersökningsrum", "undersökning"),
        name_keywords_en=("examination room", "exam room", "treatment room"),
        notes="Min 18 m² if bed examination required. 1000 lux task lighting.",
    ),
    # ── Communal / welfare ─────────────────────────────────────────────────
    RoomTypeDef(
        key="day_room",
        display_name_sv="Dagrum / Matsal",
        display_name_en="Day Room / Dining",
        min_area_m2=20.0, preferred_area_m2=30.0,
        min_width_m=4.8, min_depth_m=4.8,
        zone="clean", access_type="public",
        ifc_space_type="LOUNGE",
        bsab_code="65A",
        required_in_ward=True, requires_window=True,
        requires_sink=False, requires_ensuite=False,
        max_occupants=12,
        name_keywords_sv=("dagrum", "matsal", "allrum", "sällskapsrum"),
        name_keywords_en=("day room", "lounge", "dining", "social room", "dayroom"),
        notes="SS 91 42 21 §6.7 — min 2 m²/patient. Daylight factor ≥ 2%. BBR 6:32.",
    ),
    RoomTypeDef(
        key="visitor_wc",
        display_name_sv="Besöks-WC",
        display_name_en="Visitor WC",
        min_area_m2=3.5, preferred_area_m2=5.0,
        min_width_m=1.6, min_depth_m=2.2,
        zone="public", access_type="public",
        ifc_space_type="SANITARYFACILITY",
        bsab_code="64T",
        required_in_ward=True, requires_window=False,
        requires_sink=True, requires_ensuite=False,
        max_occupants=1,
        name_keywords_sv=("besöks-wc", "besökstoalett", "besökare"),
        name_keywords_en=("visitor wc", "visitor toilet", "public wc", "guest wc"),
        notes="HIN 4 — must be wheelchair accessible. 5 m² recommended for turning radius.",
    ),
    RoomTypeDef(
        key="staff_wc",
        display_name_sv="Personaltoalett",
        display_name_en="Staff WC",
        min_area_m2=3.0, preferred_area_m2=4.5,
        min_width_m=1.5, min_depth_m=2.0,
        zone="staff", access_type="staff",
        ifc_space_type="SANITARYFACILITY",
        bsab_code="64P",
        required_in_ward=True, requires_window=False,
        requires_sink=True, requires_ensuite=False,
        max_occupants=1,
        name_keywords_sv=("personaltoalett", "personal-wc", "personalwc"),
        name_keywords_en=("staff wc", "staff toilet", "staff bathroom"),
        notes="AFS 2009:2 — 1 per 15 staff. Wheelchair accessible if only one per floor.",
    ),
    # ── Infrastructure ─────────────────────────────────────────────────────
    RoomTypeDef(
        key="corridor",
        display_name_sv="Korridor (stångkorridor)",
        display_name_en="Ward Corridor Spine",
        min_area_m2=50.0, preferred_area_m2=70.0,
        min_width_m=2.4, min_depth_m=20.0,
        zone="staff", access_type="public",
        ifc_space_type="CORRIDOR",
        bsab_code="61K",
        required_in_ward=True, requires_window=False,
        requires_sink=False, requires_ensuite=False,
        max_occupants=99,
        name_keywords_sv=("korridor", "gång", "stångkorridor"),
        name_keywords_en=("corridor", "hallway", "ward spine", "circulation"),
        notes="Min 2400 mm clear (SS 91 42 21). 2700 mm recommended for geriatric (bed turning).",
    ),
    RoomTypeDef(
        key="stair_core",
        display_name_sv="Trapphus + kärna",
        display_name_en="Stair Core",
        min_area_m2=12.0, preferred_area_m2=18.0,
        min_width_m=2.8, min_depth_m=4.0,
        zone="staff", access_type="public",
        ifc_space_type="STAIRWELL",
        bsab_code="61T",
        required_in_ward=True, requires_window=True,
        requires_sink=False, requires_ensuite=False,
        max_occupants=99,
        name_keywords_sv=("trapphus", "trapphuskärna", "trappa"),
        name_keywords_en=("stair", "stairwell", "fire stair", "egress stair"),
        notes="Min stair width 1400 mm for bed evacuation (BBR 5:351). Natural light required.",
    ),
    RoomTypeDef(
        key="lift",
        display_name_sv="Sänghiss",
        display_name_en="Bed Lift",
        min_area_m2=5.0, preferred_area_m2=6.0,
        min_width_m=2.0, min_depth_m=2.5,
        zone="staff", access_type="staff",
        ifc_space_type="LIFT",
        bsab_code="61H",
        required_in_ward=True, requires_window=False,
        requires_sink=False, requires_ensuite=False,
        max_occupants=6,
        name_keywords_sv=("hiss", "sänghiss", "sjukhushiss"),
        name_keywords_en=("lift", "elevator", "bed lift", "hospital lift"),
        notes="Min 1400 × 2400 mm cabin (bed + 2 attendants). EN 81-70 accessibility.",
    ),
    RoomTypeDef(
        key="entrance",
        display_name_sv="Entré / Reception",
        display_name_en="Ward Entrance / Reception",
        min_area_m2=10.0, preferred_area_m2=15.0,
        min_width_m=3.6, min_depth_m=3.0,
        zone="public", access_type="public",
        ifc_space_type="ENTRANCE",
        bsab_code="61E",
        required_in_ward=True, requires_window=True,
        requires_sink=False, requires_ensuite=False,
        max_occupants=8,
        name_keywords_sv=("entré", "reception", "mottagning", "ingång"),
        name_keywords_en=("entrance", "reception", "lobby", "entry"),
        notes="HIN 4 — automatic door, 1400 mm min clear. Visitor sign-in.",
    ),
]

# Build lookup maps
_BY_KEY:     dict[str, RoomTypeDef] = {r.key: r for r in _ROOM_TYPES}
_BY_BSAB:    dict[str, RoomTypeDef] = {r.bsab_code: r for r in _ROOM_TYPES}
_BY_IFC:     dict[str, list[RoomTypeDef]] = {}
for _rt in _ROOM_TYPES:
    _BY_IFC.setdefault(_rt.ifc_space_type, []).append(_rt)


class SE_ROOMS:
    """Swedish healthcare room type catalogue — query interface for ArchitectAI agents."""

    @staticmethod
    def lookup(key: str) -> Optional[RoomTypeDef]:
        """Look up a room type by key. Returns None if not found."""
        return _BY_KEY.get(key)

    @staticmethod
    def by_bsab(code: str) -> Optional[RoomTypeDef]:
        """Look up by BSAB 96 code."""
        return _BY_BSAB.get(code)

    @staticmethod
    def match_name(room_name: str) -> RoomTypeDef:
        """Find best-matching room type definition from a room name string."""
        n = room_name.lower()
        best: Optional[RoomTypeDef] = None
        best_score = 0
        for rt in _ROOM_TYPES:
            score = 0
            for kw in rt.name_keywords_sv + rt.name_keywords_en:
                if kw in n:
                    score += len(kw)  # longer match = more specific
            if score > best_score:
                best_score = score
                best = rt
        return best or _ROOM_TYPES[0]  # fallback to patient_room

    @staticmethod
    def required_rooms() -> list[RoomTypeDef]:
        """Return all room types that are mandatory in a standard SE ward."""
        return [r for r in _ROOM_TYPES if r.required_in_ward]

    @staticmethod
    def all_types() -> list[RoomTypeDef]:
        """Return all defined room types."""
        return list(_ROOM_TYPES)

    @staticmethod
    def prompt_block(building_type: str = "healthcare") -> str:
        """Formatted room type reference block for agent prompts."""
        req = SE_ROOMS.required_rooms()
        rows = [
            f"  {r.key:<22}: min {r.min_area_m2:>5.1f} m²  "
            f"pref {r.preferred_area_m2:>5.1f} m²  "
            f"zone:{r.zone:<8}  BSAB:{r.bsab_code}  IFC:{r.ifc_space_type}"
            for r in req
        ]
        table = "\n".join(rows)
        return f"""
SE ROOM TYPE CATALOGUE (SS 91 42 21 / BSAB 96) — mandatory rooms:
{table}
Rules:
- All rooms with requires_window=True must have direct daylight access (BBR 6:32)
- All rooms with requires_sink=True must have a clinical hand-wash basin at entry
- patient_room min width {_BY_KEY['patient_room'].min_width_m:.1f} m, min depth {_BY_KEY['patient_room'].min_depth_m:.1f} m
- isolation_room only accessible via isolation_anteroom (no direct corridor)
- dirty_utility must not adjoin clean_utility (SOSFS 2015:10)
""".strip()


# Make Optional importable
from typing import Optional

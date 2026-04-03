"""
IFC Codes — IFC4 space and element classification codes for ArchitectAI.

Provides deterministic, code-level mapping from ArchitectAI room types
to IFC4 IfcSpace PredefinedTypes, IfcWall types, and Swedish SfB/BSAB codes.
Prevents LLM hallucination of IFC class names.

Sources:
  - ISO 16739-1:2024  IFC4 ADD2 TC1
  - buildingSMART IFC4 Reference (https://standards.buildingsmart.org/IFC/RELEASE/IFC4/)
  - BSAB 96  Swedish building classification
  - SfB  Swedish BIM classification (aligned with UNICLASS 2015)

Usage:
    from src.tools.ifc_codes import IFC, IfcSpaceType

    ifc_type = IFC.space_type("patient_room")       # → "USERDEFINED"
    ifc_tag  = IFC.space_tag("patient_room")         # → "PATIENT_BEDROOM"
    wall_t   = IFC.wall_type("external_loadbearing") # → "IfcWall" + params

    IFC.prompt_block()  # formatted string for IFC Builder agent
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# IFC4 IfcSpace PredefinedType options
# (ISO 16739 §IfcSpaceTypeEnum)
# ---------------------------------------------------------------------------

IFC_SPACE_PREDEFINED = {
    "USERDEFINED",   # Custom — ObjectType defines the meaning
    "NOTDEFINED",    # Unknown
    "EXTERNAL",      # Outdoor space
    "INTERNAL",      # Indoor space (general)
    "PARKING",
    "SPACE",         # Generic
}


# ---------------------------------------------------------------------------
# IFC4 IfcWall type (PredefinedType)
# ---------------------------------------------------------------------------

IFC_WALL_TYPES = {
    "STANDARD",           # Standard wall (most common)
    "POLYGONAL",          # Non-rectangular section
    "SHEAR",              # Shear wall (structural)
    "ELEMENTEDWALL",      # Prefabricated element wall
    "PLUMBINGWALL",       # Contains pipes
    "MOVABLE",            # Partition / operable
    "PARAPET",
    "NOTDEFINED",
}


# ---------------------------------------------------------------------------
# Room → IFC mapping
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IfcSpaceMapping:
    """IFC4 classification for a room type."""
    room_key:           str
    predefined_type:    str    # IfcSpace.PredefinedType
    object_type:        str    # IfcSpace.ObjectType (when USERDEFINED)
    long_name:          str    # IfcSpace.LongName (human-readable)
    bsab_code:          str    # BSAB 96 code
    pset_name:          str    # Recommended Pset_ for this space
    required_psets:     tuple  # Additional property sets to attach


IFC_SPACE_MAPPINGS: dict[str, IfcSpaceMapping] = {
    "patient_room": IfcSpaceMapping(
        room_key="patient_room",
        predefined_type="USERDEFINED",
        object_type="PATIENT_BEDROOM",
        long_name="Patient Bedroom",
        bsab_code="62B",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon", "Pset_SpaceOccupancyRequirements"),
    ),
    "isolation_room": IfcSpaceMapping(
        room_key="isolation_room",
        predefined_type="USERDEFINED",
        object_type="ISOLATION_ROOM",
        long_name="Isolation Room",
        bsab_code="62B-ISO",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
    "isolation_anteroom": IfcSpaceMapping(
        room_key="isolation_anteroom",
        predefined_type="USERDEFINED",
        object_type="ISOLATION_ANTEROOM",
        long_name="Isolation Anteroom",
        bsab_code="62S",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
    "patient_ensuite": IfcSpaceMapping(
        room_key="patient_ensuite",
        predefined_type="USERDEFINED",
        object_type="PATIENT_ENSUITE",
        long_name="Patient Ensuite (WC + Shower)",
        bsab_code="64E",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
    "nurse_station": IfcSpaceMapping(
        room_key="nurse_station",
        predefined_type="USERDEFINED",
        object_type="NURSES_STATION",
        long_name="Nurses Station",
        bsab_code="63A",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon", "Pset_SpaceOccupancyRequirements"),
    ),
    "medication_room": IfcSpaceMapping(
        room_key="medication_room",
        predefined_type="USERDEFINED",
        object_type="MEDICATION_ROOM",
        long_name="Medication Room",
        bsab_code="63C",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
    "clean_utility": IfcSpaceMapping(
        room_key="clean_utility",
        predefined_type="USERDEFINED",
        object_type="CLEAN_UTILITY",
        long_name="Clean Utility Room",
        bsab_code="64R",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
    "dirty_utility": IfcSpaceMapping(
        room_key="dirty_utility",
        predefined_type="USERDEFINED",
        object_type="DIRTY_UTILITY",
        long_name="Dirty Utility / Sluice Room",
        bsab_code="64S",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
    "examination_room": IfcSpaceMapping(
        room_key="examination_room",
        predefined_type="USERDEFINED",
        object_type="EXAMINATION_ROOM",
        long_name="Examination Room",
        bsab_code="62U",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
    "day_room": IfcSpaceMapping(
        room_key="day_room",
        predefined_type="USERDEFINED",
        object_type="DAY_ROOM",
        long_name="Day Room / Patient Lounge",
        bsab_code="65A",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
    "visitor_wc": IfcSpaceMapping(
        room_key="visitor_wc",
        predefined_type="USERDEFINED",
        object_type="VISITOR_WC",
        long_name="Visitor WC",
        bsab_code="64T",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
    "staff_wc": IfcSpaceMapping(
        room_key="staff_wc",
        predefined_type="USERDEFINED",
        object_type="STAFF_WC",
        long_name="Staff WC",
        bsab_code="64P",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
    "corridor": IfcSpaceMapping(
        room_key="corridor",
        predefined_type="USERDEFINED",
        object_type="WARD_CORRIDOR",
        long_name="Ward Corridor Spine",
        bsab_code="61K",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
    "stair_core": IfcSpaceMapping(
        room_key="stair_core",
        predefined_type="USERDEFINED",
        object_type="STAIRWELL",
        long_name="Stairwell",
        bsab_code="61T",
        pset_name="Pset_StairCommon",
        required_psets=("Pset_StairCommon",),
    ),
    "lift": IfcSpaceMapping(
        room_key="lift",
        predefined_type="USERDEFINED",
        object_type="LIFT_SHAFT",
        long_name="Bed Lift Shaft",
        bsab_code="61H",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
    "entrance": IfcSpaceMapping(
        room_key="entrance",
        predefined_type="USERDEFINED",
        object_type="WARD_ENTRANCE",
        long_name="Ward Entrance / Reception",
        bsab_code="61E",
        pset_name="Pset_SpaceCommon",
        required_psets=("Pset_SpaceCommon",),
    ),
}

_FALLBACK_MAPPING = IfcSpaceMapping(
    room_key="generic",
    predefined_type="NOTDEFINED",
    object_type="GENERIC_SPACE",
    long_name="Generic Space",
    bsab_code="",
    pset_name="Pset_SpaceCommon",
    required_psets=("Pset_SpaceCommon",),
)


# ---------------------------------------------------------------------------
# IFC Wall type mappings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IfcWallSpec:
    ifc_class:          str    # "IfcWall" | "IfcWallStandardCase"
    predefined_type:    str    # IfcWallTypeEnum
    name:               str
    thickness_mm:       int
    load_bearing:       bool
    fire_rating_min:    int    # EI minutes (0 = not rated)
    notes:              str = ""


IFC_WALL_SPECS: dict[str, IfcWallSpec] = {
    "external_loadbearing": IfcWallSpec(
        ifc_class="IfcWall", predefined_type="STANDARD",
        name="External Load-Bearing Wall",
        thickness_mm=350, load_bearing=True, fire_rating_min=90,
        notes="Includes insulation + cladding. Br1 rating.",
    ),
    "internal_loadbearing": IfcWallSpec(
        ifc_class="IfcWall", predefined_type="SHEAR",
        name="Internal Load-Bearing Wall",
        thickness_mm=200, load_bearing=True, fire_rating_min=90,
    ),
    "partition": IfcWallSpec(
        ifc_class="IfcWall", predefined_type="STANDARD",
        name="Internal Partition (non-structural)",
        thickness_mm=100, load_bearing=False, fire_rating_min=0,
        notes="Gypsum stud. Replace with MOVABLE if operable.",
    ),
    "fire_compartment": IfcWallSpec(
        ifc_class="IfcWall", predefined_type="STANDARD",
        name="Fire Compartment Wall",
        thickness_mm=200, load_bearing=False, fire_rating_min=60,
        notes="EI60 min. Fire-stopping at all penetrations.",
    ),
    "infection_control": IfcWallSpec(
        ifc_class="IfcWall", predefined_type="STANDARD",
        name="Infection Control Wall (isolation room)",
        thickness_mm=150, load_bearing=False, fire_rating_min=30,
        notes="Easy-clean finish. No exposed joints. Coved skirting.",
    ),
}


# ---------------------------------------------------------------------------
# Helper class
# ---------------------------------------------------------------------------

class IFC:
    """IFC4 code mappings — query interface for ArchitectAI IFC Builder Agent."""

    @staticmethod
    def space_mapping(room_key: str) -> IfcSpaceMapping:
        """Return the IFC space mapping for a room type key."""
        return IFC_SPACE_MAPPINGS.get(room_key, _FALLBACK_MAPPING)

    @staticmethod
    def space_type(room_key: str) -> str:
        """Return IfcSpace.PredefinedType for a room type."""
        return IFC.space_mapping(room_key).predefined_type

    @staticmethod
    def space_tag(room_key: str) -> str:
        """Return IfcSpace.ObjectType (used when PredefinedType=USERDEFINED)."""
        return IFC.space_mapping(room_key).object_type

    @staticmethod
    def wall_spec(wall_key: str) -> Optional[IfcWallSpec]:
        """Return the IFC wall spec for a wall type key."""
        return IFC_WALL_SPECS.get(wall_key)

    @staticmethod
    def all_space_mappings() -> list[IfcSpaceMapping]:
        """Return all defined space mappings."""
        return list(IFC_SPACE_MAPPINGS.values())

    @staticmethod
    def prompt_block() -> str:
        """Formatted IFC code reference block for the IFC Builder agent prompt."""
        rows = [
            f"  {m.room_key:<22}: PredefinedType={m.predefined_type:<15}"
            f" ObjectType={m.object_type:<25} BSAB={m.bsab_code}"
            for m in IFC_SPACE_MAPPINGS.values()
        ]
        space_table = "\n".join(rows)

        wall_rows = [
            f"  {k:<25}: {v.ifc_class} / {v.predefined_type:<12}"
            f" t={v.thickness_mm}mm  LB={'Y' if v.load_bearing else 'N'}  EI{v.fire_rating_min}"
            for k, v in IFC_WALL_SPECS.items()
        ]
        wall_table = "\n".join(wall_rows)

        return f"""
IFC4 CLASSIFICATION (ISO 16739-1 / buildingSMART):
IfcSpace mappings (use these — do NOT invent PredefinedType values):
{space_table}

IfcWall types:
{wall_table}

IFC4 rules:
- All IfcSpace: PredefinedType=USERDEFINED, ObjectType from table above
- IfcSpace.LongName: human-readable Swedish/English room name
- Attach Pset_SpaceCommon to every IfcSpace (GrossFloorArea, NetFloorArea)
- IfcProject.UnitsInContext: METRE for geometry, MILLIMETRE for explicit dims
- Do NOT use IFC2x3 classes (IfcSpace predefined types differ in IFC4)
- Coordinate origin: [0,0,0] = SW corner of ground floor at finished floor level
- All geometry in metres (IFC internal unit = METRE unless overridden)
""".strip()


from typing import Optional

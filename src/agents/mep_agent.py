"""
MEP Agent — places shafts, plant rooms, fire compartments, and ventilation zones.
Produces mep_schema.json.
"""

import json
from datetime import datetime, timezone

from loguru import logger

from src.agents.base_agent import BaseAgent
from src.tools.se_fire import SE_FIRE
from src.tools.se_hvac import SE_HVAC


SYSTEM_PROMPT = """You are the MEP Agent (Mechanical, Electrical, Plumbing) for ArchitectAI,
a multi-agent building design system.

You place vertical shafts, plant rooms, and define service zones based on the approved spatial
and structural layouts.

Healthcare rules (critical):
- Clean utility shafts must be separated from dirty utility shafts
- Medical gas risers (O2, vacuum) must not share shaft with waste/soil pipes
- Plant rooms must be accessible without passing through clinical areas

Fire compartmentation (Swedish BBR 2023 avsnitt 5 / EN 1365):
{se_fire_block}

Shaft placement rules:
- Shafts should not break structural cores or remove columns
- Wet rooms (WC, sluice) should stack vertically for drainage
- Prefer compact, accessible shaft positions at core perimeters
- Shaft sizing per SS-EN ISO 5806: min cross-section {shaft_min_m}×{shaft_min_m}m

Ventilation rules (Swedish BBR 6 / SS 25268):
- See HVAC spec per room type for l/s/m², ACH, pressure regime
- Isolation rooms: negative pressure, H14 filter, anteroom as airlock
- Max duct velocity: {duct_vel_m_s}m/s in occupied zones, {duct_vel_return}m/s in return

Flag spatial conflicts (shaft collides with room, plant room too small, etc.).

Output ONLY valid JSON. No prose, no markdown fences."""


class MEPAgent(BaseAgent):
    """
    Places vertical shafts, plant rooms, and defines MEP zones.

    Separates clean/dirty utilities for healthcare.
    Subdivides floors into fire compartments using SE_FIRE rules.
    Outputs mep_schema.json.
    """

    AGENT_ID = "mep"
    DEFAULT_MODEL = "claude-sonnet-4-6"

    # Dynamic system prompt with SE_FIRE and SE_HVAC rules
    def __init__(self, memory, model=None):
        super().__init__(memory, model)
        self._refresh_system_prompt()

    def _refresh_system_prompt(self):
        """Build the system prompt with current SE rules."""
        # Get fire compartment max area for healthcare
        max_comp = SE_FIRE.max_compartment_area_m2("Vk3C", "Br1")  # Healthcare default
        travel_dist = SE_FIRE.max_travel_distance_m("Vk3C")
        stair_width = SE_FIRE.min_stair_width_mm("Vk3C")
        shaft_min = SE_HVAC.min_shaft_size_m()
        duct_vel = SE_HVAC.max_duct_velocity_m_s("supply")
        duct_vel_return = SE_HVAC.max_duct_velocity_m_s("return")

        self._se_fire_block = f"""
- Max {max_comp:.0f} m² per fire compartment in healthcare (Vk3C+Br1)
- Max travel distance to exit: {travel_dist}m
- Min stair width for bed evacuation: {stair_width}mm
- Shafts penetrating compartments need fire-dampers (EI90) and fire-stopping
- Compartment boundaries must align with structural elements (load-bearing walls)
- Fire resistance: R90 for load-bearing structures in Br1 buildings
"""
        self._sys_prompt_template = SYSTEM_PROMPT.format(
            se_fire_block=self._se_fire_block,
            shaft_min=shaft_min,
            duct_vel_m_s=duct_vel,
            duct_vel_return=duct_vel_return,
        )

    def run(self, inputs: dict) -> dict:
        """
        Generate MEP schema from spatial and structural layouts.

        Args:
            inputs: {
                "spatial_layout": dict,      # From ArchitectAgent
                "structural_schema": dict,   # From StructuralAgent
            }

        Returns:
            mep_schema dict
        """
        spatial_layout = inputs["spatial_layout"]
        structural_schema = inputs["structural_schema"]
        building_type = spatial_layout.get("building_type", "unknown")
        is_healthcare = "health" in building_type.lower()
        jurisdiction = inputs.get("jurisdiction", "SE")

        floors = spatial_layout.get("floors", [])
        cores = structural_schema.get("cores", [])

        # Compute floor areas to inform compartmentation
        floor_areas = {}
        for floor in floors:
            total = sum(r.get("area_m2", 0) for r in floor.get("rooms", []))
            floor_areas[floor.get("floor_id", "?")] = round(total, 1)

        logger.info(
            f"[{self.AGENT_ID}] Generating MEP schema — "
            f"{len(floors)} floors, healthcare={is_healthcare}"
        )
        self.send_message("pm", "status_update", {
            "status": "working",
            "task": "MEP schema — shafts, compartments, plant rooms",
        })

        # Use SE_FIRE for deterministic max compartment area
        if is_healthcare:
            # Healthcare defaults to Vk3C + Br1 in SE
            fire_class = inputs.get("fire_class", "Br1")
            building_class = inputs.get("building_class", "Vk3C")
            max_compartment = SE_FIRE.max_compartment_area_m2(building_class, fire_class)
        else:
            max_compartment = SE_FIRE.max_compartment_area_m2("Vk2", "Br2")  # Default office/commercial

        user_message = f"""Generate a complete MEP schema for this {building_type} building.

Spatial Layout (floors and rooms):
{json.dumps(spatial_layout, indent=2, ensure_ascii=False)[:4000]}

Structural Cores (avoid for shafts):
{json.dumps(cores, indent=2)}

Floor Areas: {json.dumps(floor_areas)}
Max fire compartment area: {max_compartment} m²
Healthcare building: {is_healthcare}

Output a complete mep_schema.json:
{{
  "building_type": "{building_type}",
  "shafts": [
    {{
      "shaft_id": "SH01",
      "type": "clean_utility|dirty_utility|medical_gas|electrical|drainage|general",
      "x_m": 0.0,
      "y_m": 0.0,
      "width_m": 1.2,
      "depth_m": 1.2,
      "floors": ["G", "1"],
      "services": ["cold_water", "hot_water"]
    }}
  ],
  "plant_rooms": [
    {{
      "plant_id": "PR01",
      "type": "main_plant|substation|medical_gas_manifold|sprinkler_valve",
      "x_m": 0.0,
      "y_m": 0.0,
      "width_m": 8.0,
      "depth_m": 6.0,
      "floor": "G",
      "area_m2": 48.0,
      "access": "service_only"
    }}
  ],
  "fire_compartments": [
    {{
      "compartment_id": "FC01",
      "floor": "G",
      "area_m2": 0.0,
      "rooms": ["room_id_1"],
      "boundary_elements": ["wall_id_or_description"],
      "max_area_m2": {max_compartment},
      "compliant": true
    }}
  ],
  "ventilation_zones": [
    {{
      "zone_id": "VZ01",
      "type": "positive_pressure|negative_pressure|neutral|general",
      "rooms": ["room_id"],
      "ahu_ref": "AHU-01",
      "notes": ""
    }}
  ],
  "spatial_conflicts": [
    {{
      "conflict_id": "SC01",
      "type": "shaft_room_overlap|plant_room_undersized|access_blocked",
      "description": "...",
      "severity": "warning|critical",
      "resolution": "..."
    }}
  ],
  "notes": []
}}

HVAC specs per room type (BBR 6 / SS 25268):
{SE_HVAC.prompt_block(building_type)}
"""

        response = self.chat(
            system=self._sys_prompt_template,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=3000,
        )

        mep_schema = self._extract_json(response)
        mep_schema["project_id"] = self.memory.project_id
        mep_schema["created_at"] = datetime.now(timezone.utc).isoformat()
        mep_schema["created_by"] = self.AGENT_ID

        # Check compartment compliance
        non_compliant = [
            c for c in mep_schema.get("fire_compartments", [])
            if not c.get("compliant", True) or c.get("area_m2", 0) > max_compartment
        ]
        if non_compliant:
            logger.warning(
                f"[{self.AGENT_ID}] {len(non_compliant)} fire compartment(s) exceed "
                f"{max_compartment} m² limit"
            )

        conflicts = mep_schema.get("spatial_conflicts", [])
        critical_conflicts = [c for c in conflicts if c.get("severity") == "critical"]

        version = self.memory.save_schema("mep_schema", mep_schema)
        logger.success(
            f"[{self.AGENT_ID}] mep_schema saved as {version} — "
            f"{len(mep_schema.get('shafts', []))} shafts, "
            f"{len(mep_schema.get('fire_compartments', []))} compartments, "
            f"{len(conflicts)} conflict(s)"
        )

        if critical_conflicts:
            logger.warning(f"[{self.AGENT_ID}] {len(critical_conflicts)} critical spatial conflict(s)")

        self.send_message("pm", "status_update", {
            "status": "done",
            "schema": "mep_schema",
            "version": version,
            "summary": (
                f"{len(mep_schema.get('shafts', []))} shafts, "
                f"{len(mep_schema.get('fire_compartments', []))} compartments, "
                f"{len(conflicts)} conflicts"
            ),
        })

        return mep_schema

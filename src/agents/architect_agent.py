"""
Architect Agent — places rooms onto the site and designs circulation.
Produces spatial_layout.json.
"""

import json
from datetime import datetime, timezone

from loguru import logger

from src.agents.base_agent import BaseAgent


SYSTEM_PROMPT = """You are the Architect Agent for ArchitectAI, a multi-agent building design system.

You place rooms from the room program onto the site, design circulation (corridors, stairs, lifts),
and optimize for adjacency requirements.

Healthcare buildings require strict clean/dirty flow separation:
- Clean zones: patient rooms, nurse stations, clean utility
- Dirty zones: dirty utility, sluice rooms, waste disposal
- Never place dirty zones adjacent to clean zones without buffer corridor

Your output is spatial_layout.json — a structured spatial description (not pixel-perfect CAD).

Room placement rules:
- Each room is a rectangle with x, y (metres from site origin), width, depth
- Corridors connect rooms and must be ≥ 2.4m wide (healthcare min)
- Stairs and lifts must be placed at logical circulation nodes
- Group rooms by functional zone (clean/staff/public/service)

Output ONLY valid JSON. No prose, no markdown fences."""


class ArchitectAgent(BaseAgent):
    """
    Places rooms from the room program onto the site grid and designs circulation.

    Outputs spatial_layout.json containing room positions, corridor geometry,
    vertical circulation, and functional zone assignments.
    """

    AGENT_ID = "architect"
    DEFAULT_MODEL = "claude-sonnet-4-5"

    def run(self, inputs: dict) -> dict:
        """
        Generate a spatial layout from room program and site data.

        Args:
            inputs: {
                "room_program": dict,         # From BriefAgent
                "site_data": dict,            # From InputParserAgent
                "component_templates": dict,  # From ComponentLibraryAgent
            }

        Returns:
            spatial_layout dict
        """
        room_program = inputs["room_program"]
        site_data = inputs.get("site_data", {})
        component_templates = inputs.get("component_templates", {})

        rooms = room_program.get("rooms", [])
        building_type = room_program.get("building_type", "unknown")
        jurisdiction = room_program.get("jurisdiction", "SE")

        logger.info(f"[{self.AGENT_ID}] Laying out {len(rooms)} rooms on site")
        self.send_message("pm", "status_update", {
            "status": "working",
            "task": f"Spatial layout — placing {len(rooms)} rooms",
        })

        site_area = site_data.get("boundary", {}).get("area_m2", 5000)
        site_width = site_data.get("boundary", {}).get("width_m", 60)
        site_depth = site_data.get("boundary", {}).get("depth_m", 80)

        user_message = f"""Generate a spatial layout for this {building_type} building.

Site:
- Area: {site_area} m²
- Width: {site_width} m
- Depth: {site_depth} m
- Jurisdiction: {jurisdiction}
- Constraints: {json.dumps(site_data.get('constraints', {}), indent=2)}

Room Program ({len(rooms)} rooms, {room_program.get('total_area_m2', 0)} m² total):
{json.dumps(rooms, indent=2, ensure_ascii=False)[:4000]}

Component Templates (geometry hints):
{json.dumps({k: v.get('geometry', {}) for k, v in list(component_templates.items())[:10]}, indent=2)}

Output a complete spatial_layout.json with:
{{
  "building_type": "{building_type}",
  "floors": [
    {{
      "floor_id": "G",
      "level_m": 0.0,
      "rooms": [
        {{
          "room_id": "unique_id",
          "name": "Room Name",
          "room_type": "room_type_key",
          "x_m": 0.0,
          "y_m": 0.0,
          "width_m": 5.0,
          "depth_m": 4.0,
          "area_m2": 20.0,
          "zone": "clean|dirty|public|staff|service",
          "access_type": "public|staff|restricted|service",
          "floor": "G"
        }}
      ],
      "corridors": [
        {{
          "corridor_id": "C01",
          "from_room": "room_id",
          "to_room": "room_id",
          "width_m": 2.4,
          "path": [[x1,y1],[x2,y2]]
        }}
      ],
      "stairs": [{{"stair_id": "ST01", "x_m": 0, "y_m": 0, "width_m": 2.8, "depth_m": 5.0, "type": "primary"}}],
      "lifts": [{{"lift_id": "LF01", "x_m": 0, "y_m": 0, "width_m": 1.8, "depth_m": 2.5, "type": "passenger"}}]
    }}
  ],
  "clean_dirty_flow": {{
    "clean_corridor": "corridor_id",
    "dirty_corridor": "corridor_id",
    "separation_notes": "..."
  }},
  "adjacency_violations": [],
  "layout_notes": []
}}"""

        response = self.chat(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=8000,
        )

        spatial_layout = self._extract_json(response)
        spatial_layout["project_id"] = self.memory.project_id
        spatial_layout["created_at"] = datetime.now(timezone.utc).isoformat()
        spatial_layout["created_by"] = self.AGENT_ID

        # Count total rooms across all floors
        total_rooms = sum(
            len(floor.get("rooms", []))
            for floor in spatial_layout.get("floors", [])
        )
        floors_count = len(spatial_layout.get("floors", []))

        version = self.memory.save_schema("spatial_layout", spatial_layout)
        logger.success(
            f"[{self.AGENT_ID}] spatial_layout saved as {version} — "
            f"{total_rooms} rooms across {floors_count} floor(s)"
        )

        self.send_message("pm", "status_update", {
            "status": "done",
            "schema": "spatial_layout",
            "version": version,
            "summary": f"{total_rooms} rooms, {floors_count} floors",
        })

        return spatial_layout

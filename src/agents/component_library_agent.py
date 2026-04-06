"""
Component Library Agent — manages room/component templates stored as JSON files.
Templates live in /component_library/<building_type>/<room_type>.json
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from src.agents.base_agent import BaseAgent


SYSTEM_PROMPT = """You are the Component Library Agent for ArchitectAI, a multi-agent building design system.

You generate detailed room/component templates for building types and room types.

A template captures everything an architect needs to know about a room type:
- Geometry requirements (minimum dimensions, preferred area)
- MEP requirements (sinks, WC adjacency, medical gases, nurse call)
- Compliance references (regulation codes by jurisdiction)
- Adjacency rules (must be near / must not adjoin)
- Notes (special requirements, fit-out guidelines)

For healthcare buildings, follow Swedish healthcare standards:
- SOSFS 2013:7 (Socialstyrelsens föreskrifter och allmänna råd om anmälan av händelser)
- BBR (Boverkets byggregler) for fire, accessibility, ventilation
- Specifik healthcare: hygienzones, medical gas points, nurse call systems

Output ONLY valid JSON. No prose, no markdown fences."""


class ComponentLibraryAgent(BaseAgent):
    """
    Manages a library of room/component templates stored as JSON files.

    Template location: <COMPONENT_LIBRARY_DIR>/<building_type>/<room_type>.json

    Methods:
    - get_template(): load from file if exists
    - create_template(): ask Claude to generate, save to file
    - get_or_create(): try get first, create if missing
    - list_templates(): list templates for a building type
    - run(): return all templates for rooms in a room program
    """

    AGENT_ID = "component_library"
    DEFAULT_MODEL = "gemini-3-flash"

    def __init__(self, memory, model: str = None):
        super().__init__(memory, model)
        self.library_dir = Path(
            os.getenv("COMPONENT_LIBRARY_DIR", "./component_library")
        )
        self.library_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[{self.AGENT_ID}] Library directory: {self.library_dir.resolve()}")

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_template(
        self,
        building_type: str,
        room_type: str,
        jurisdiction: str = "SE",
    ) -> Optional[dict]:
        """
        Load a template from file.

        Returns the template dict, or None if it doesn't exist.
        """
        path = self._template_path(building_type, room_type)
        if not path.exists():
            logger.debug(f"[{self.AGENT_ID}] No template: {path}")
            return None
        template = json.loads(path.read_text(encoding="utf-8"))
        logger.debug(f"[{self.AGENT_ID}] Loaded template: {path.name}")
        return template

    def create_template(
        self,
        building_type: str,
        room_type: str,
        jurisdiction: str = "SE",
        context: dict = None,
    ) -> dict:
        """
        Ask Claude to generate a template, then save it to file.

        Args:
            building_type: e.g. "healthcare"
            room_type: e.g. "patient_room"
            jurisdiction: e.g. "SE"
            context: optional extra context (room from room_program, etc.)

        Returns:
            Generated template dict
        """
        context = context or {}
        template_id = f"{building_type}.{room_type}"

        logger.info(f"[{self.AGENT_ID}] Generating template: {template_id} ({jurisdiction})")

        user_message = f"""Generate a component template for:
- Building type: {building_type}
- Room type: {room_type}
- Jurisdiction: {jurisdiction}
- Template ID: {template_id}

Additional context:
{json.dumps(context, indent=2, ensure_ascii=False)}

Output a JSON template matching exactly this schema:
{{
  "id": "{template_id}",
  "building_type": "{building_type}",
  "room_type": "{room_type}",
  "name": "Human-readable room name",
  "jurisdiction": "{jurisdiction}",
  "geometry": {{
    "min_width_m": 3.0,
    "min_depth_m": 3.0,
    "min_area_m2": 9.0,
    "preferred_area_m2": 12.0,
    "ceiling_height_min_m": 2.7
  }},
  "mep": {{
    "requires_sink": false,
    "requires_wc_adjacent": false,
    "medical_gas_points": [],
    "nurse_call": false,
    "ventilation": "supply_and_exhaust|exhaust_only|supply_only|natural",
    "electrical_sockets_min": 2
  }},
  "compliance_refs": [],
  "adjacencies": {{
    "must_be_near": [],
    "must_not_adjoin": [],
    "preferred_near": []
  }},
  "access_type": "public|staff|restricted|service",
  "zone": "clean|dirty|public|staff|service",
  "notes": []
}}"""

        response = self.chat(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=2000,
        )

        template = self._extract_json(response)

        # Ensure required fields
        template.setdefault("id", template_id)
        template.setdefault("building_type", building_type)
        template.setdefault("room_type", room_type)
        template.setdefault("jurisdiction", jurisdiction)
        template["generated_at"] = datetime.now(timezone.utc).isoformat()
        template["generated_by"] = self.AGENT_ID

        # Save to library
        path = self._template_path(building_type, room_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.success(f"[{self.AGENT_ID}] Saved template: {path}")

        return template

    def get_or_create(
        self,
        building_type: str,
        room_type: str,
        jurisdiction: str = "SE",
        context: dict = None,
    ) -> dict:
        """
        Return existing template or create one if missing.

        Args:
            building_type: e.g. "healthcare"
            room_type: e.g. "patient_room"
            jurisdiction: e.g. "SE"
            context: optional extra context for generation

        Returns:
            Template dict
        """
        template = self.get_template(building_type, room_type, jurisdiction)
        if template is not None:
            return template
        logger.info(f"[{self.AGENT_ID}] Template not found — generating: {building_type}/{room_type}")
        return self.create_template(building_type, room_type, jurisdiction, context)

    def list_templates(self, building_type: str) -> list[str]:
        """
        List all template room_types available for a building type.

        Returns:
            List of room_type strings
        """
        type_dir = self.library_dir / building_type
        if not type_dir.exists():
            return []
        return [p.stem for p in sorted(type_dir.glob("*.json"))]

    def run(self, inputs: dict) -> dict:
        """
        Fetch or generate templates for all room types in a room program.

        Args:
            inputs: {
                "room_program": dict,    # From BriefAgent
                "jurisdiction": str,     # e.g. "SE"
            }

        Returns:
            dict mapping room_type -> template dict
        """
        room_program = inputs["room_program"]
        jurisdiction = inputs.get("jurisdiction", room_program.get("jurisdiction", "SE"))
        building_type = room_program.get("building_type", "generic")
        rooms = room_program.get("rooms", [])

        logger.info(
            f"[{self.AGENT_ID}] Fetching templates for {len(rooms)} room type(s), "
            f"building={building_type}, jurisdiction={jurisdiction}"
        )
        self.send_message("pm", "status_update", {
            "status": "working",
            "task": f"Fetching {len(rooms)} component templates",
        })

        templates: dict[str, dict] = {}
        seen_types: set[str] = set()

        for room in rooms:
            room_type = room.get("room_type") or room.get("type", "generic_room")
            if room_type in seen_types:
                continue
            seen_types.add(room_type)

            template = self.get_or_create(
                building_type=building_type,
                room_type=room_type,
                jurisdiction=jurisdiction,
                context=room,
            )
            templates[room_type] = template

        logger.success(
            f"[{self.AGENT_ID}] Retrieved {len(templates)} template(s) "
            f"({sum(1 for t in templates.values() if t.get('generated_by') == self.AGENT_ID)} newly generated)"
        )

        self.send_message("pm", "status_update", {
            "status": "done",
            "task": "component_templates",
            "summary": f"{len(templates)} templates for {building_type}",
        })

        return templates

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _template_path(self, building_type: str, room_type: str) -> Path:
        """Return the filesystem path for a template file."""
        # Sanitise keys for filesystem
        safe_bt = building_type.replace(" ", "_").lower()
        safe_rt = room_type.replace(" ", "_").lower()
        return self.library_dir / safe_bt / f"{safe_rt}.json"

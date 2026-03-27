"""
Brief Agent — generates room_program.json from user prompt + site data
"""

import json
from datetime import datetime, timezone

from loguru import logger

from src.agents.base_agent import BaseAgent


SYSTEM_PROMPT = """You are the Brief Agent for ArchitectAI, a multi-agent building design system.

Your job is to interpret the user's building brief (natural language prompt) and produce a structured room program.

You will receive:
1. The user's prompt (e.g. "Design a geriatric ward for Gävle Hospital")
2. Site data (area, constraints)
3. Jurisdiction (for area minimums)

You must output a JSON room program with:
- A list of all required rooms with quantities, minimum areas, adjacency requirements
- Clean/dirty flow separation (critical in healthcare)
- Access types (public/staff/restricted/service)
- Adjacency matrix

Rules:
- Be thorough — do not omit service rooms, storage, or sanitary facilities
- Mark rooms where you're uncertain about the minimum area — flag for Compliance Agent review
- Include a "notes" array for ambiguities that should be discussed with PM

Output ONLY valid JSON matching the room_program schema. No prose, no markdown.
"""


class BriefAgent(BaseAgent):
    AGENT_ID = "brief"
    DEFAULT_MODEL = "claude-sonnet-4-5"

    def run(self, inputs: dict) -> dict:
        """
        Generate a room program from user prompt and site data.

        Args:
            inputs: {
                "prompt": str,          # User's building brief
                "site_data": dict,      # From InputParserAgent
                "jurisdiction": str,    # e.g. "SE"
            }

        Returns:
            room_program dict
        """
        prompt = inputs["prompt"]
        site_data = inputs.get("site_data", {})
        jurisdiction = inputs.get("jurisdiction", site_data.get("jurisdiction", "SE"))

        logger.info(f"[{self.AGENT_ID}] Generating room program for: {prompt[:80]}...")
        self.send_message("pm", "status_update", {"status": "working", "task": "Generating room program"})

        user_message = f"""User brief: "{prompt}"

Site data:
- Total site area: {site_data.get('boundary', {}).get('area_m2', 'unknown')} m²
- Jurisdiction: {jurisdiction}
- Constraints: {json.dumps(site_data.get('constraints', {}), indent=2)}

Generate a complete room program for this building. Include all necessary spaces.
Flag any areas where you need Compliance Agent input on minimum dimensions."""

        response = self.chat(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=6000,
        )

        room_program = self._extract_json(response)
        room_program["project_id"] = self.memory.project_id
        room_program["jurisdiction"] = jurisdiction
        room_program["created_at"] = datetime.now(timezone.utc).isoformat()
        room_program["created_by"] = self.AGENT_ID

        # Calculate total area
        total = sum(
            r.get("min_area_m2", 0) * r.get("quantity", 1)
            for r in room_program.get("rooms", [])
        )
        room_program["total_area_m2"] = round(total, 1)

        version = self.memory.save_schema("room_program", room_program)
        logger.success(f"[{self.AGENT_ID}] room_program saved as {version} — {len(room_program.get('rooms', []))} rooms, {total:.0f} m² total")

        self.send_message("pm", "status_update", {
            "status": "done",
            "schema": "room_program",
            "version": version,
            "summary": f"{len(room_program.get('rooms', []))} rooms, {total:.0f} m²",
        })

        return room_program

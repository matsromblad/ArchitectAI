"""
Client Agent — acts as the building commissioner/client.
Interprets the user's raw prompt and generates a complete, realistic project brief
with sensible defaults for building size, programme, budget class, and constraints.

This agent sits BEFORE the Brief Agent. It turns a vague user request into a
structured design brief that all other agents can work from.
"""

from datetime import datetime, timezone
from loguru import logger
from src.agents.base_agent import BaseAgent


SYSTEM_PROMPT = """You are the Client Agent for ArchitectAI. Output ONLY valid JSON, no prose.

Schema (compact — omit unused fields):
{"project_name":"str","building_type":"healthcare","jurisdiction":"SE","brief_summary":"1 sentence","programme":{"patient_beds":10,"key_rooms":["list max 8 items"],"isolation_rooms_required":1},"size":{"target_net_area_m2":440,"target_gross_area_m2":660,"gross_factor":1.5,"floors":1,"site_width_m":50,"site_depth_m":20},"constraints":{"min_corridor_width_m":2.4,"accessible":true,"fire_class":"Br1"},"applicable_standards":["SS 91 42 21","BBR 2023","AFS 2009:2"]}

Rules: JSON only. Healthcare gross_factor=1.5. 10-bed ward≈440m² net. Site=footprint+10m buffer."""


class ClientAgent(BaseAgent):
    AGENT_ID = "client"
    DEFAULT_MODEL = "claude-sonnet-4-6"

    def run(self, inputs: dict) -> dict:
        """
        Generate a structured project brief from user prompt.

        Args:
            inputs: {
                "prompt": str,         # raw user brief
                "jurisdiction": str,   # e.g. "SE"
            }

        Returns:
            project_brief dict
        """
        prompt      = inputs["prompt"]
        jurisdiction = inputs.get("jurisdiction", "SE")

        logger.info(f"[{self.AGENT_ID}] Generating project brief from: {prompt[:80]}...")
        self.send_message("pm", "status_update", {"status": "working", "task": "Interpreting client brief"})

        response = self.chat(
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    f'User request: "{prompt}"\n'
                    f'Jurisdiction: {jurisdiction}\n\n'
                    f'Generate a complete, realistic project brief JSON. '
                    f'Fill in ALL fields with sensible values. '
                    f'Size the building correctly for the programme described.'
                )
            }],
            max_tokens=4000,
        )

        brief = self._extract_json(response)

        # Unwrap if nested
        if "project_brief" in brief:
            brief = brief["project_brief"]

        # Enrich with metadata
        brief["project_id"]  = self.memory.project_id
        brief["created_at"]  = datetime.now(timezone.utc).isoformat()
        brief["created_by"]  = self.AGENT_ID
        brief["raw_prompt"]  = prompt

        # Derive site dimensions from gross area if not set
        size = brief.setdefault("size", {})
        if not size.get("site_width_m"):
            gross = float(size.get("target_gross_area_m2") or 420)
            import math
            side = round(math.sqrt(gross) * 1.3, 0)  # ~30% larger than footprint
            size["site_width_m"] = side
            size["site_depth_m"] = round(gross / side + 6, 0)
            size["site_area_m2"] = round(size["site_width_m"] * size["site_depth_m"], 0)

        version = self.memory.save_schema("project_brief", brief)
        logger.success(
            f"[{self.AGENT_ID}] project_brief saved as {version} — "
            f"{size.get('target_gross_area_m2','?')}m² gross, "
            f"{size.get('site_width_m','?')}×{size.get('site_depth_m','?')}m site"
        )

        self.send_message("pm", "status_update", {
            "status": "done",
            "schema": "project_brief",
            "version": version,
        })

        return brief

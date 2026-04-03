"""
Structural Agent — proposes structural grid from spatial layout.
Produces structural_schema.json. Flags long spans for engineer review.
"""

import json
from datetime import datetime, timezone

from loguru import logger

from src.agents.base_agent import BaseAgent


SYSTEM_PROMPT = """You are the Structural Agent for ArchitectAI, a multi-agent building design system.

You review the spatial layout and propose a structural grid (columns, load-bearing walls, cores).

Rules:
- Propose a regular column grid where possible (typically 6m–9m for concrete frames)
- Identify load-bearing walls (for masonry or cross-laminated timber)
- Identify structural cores (around stairs/lifts — these resist lateral loads)
- Flag any spans > 8m as requiring special structure (transfer beam, long-span slab)
- Flag any cantilevers > 3m as requiring engineer review
- Do NOT perform calculations — flag for human engineer review

Output ONLY valid JSON. No prose, no markdown fences."""


class StructuralAgent(BaseAgent):
    """
    Reviews the spatial layout and proposes a structural grid.

    Flags spans > 8m or cantilevers > 3m as warnings for human engineer review.
    Outputs structural_schema.json.
    """

    AGENT_ID = "structural"
    DEFAULT_MODEL = "claude-sonnet-4-6"

    # Thresholds that trigger engineering review flags
    MAX_SPAN_M = 8.0
    MAX_CANTILEVER_M = 3.0

    def run(self, inputs: dict) -> dict:
        """
        Propose structural grid from spatial layout.

        Args:
            inputs: {
                "spatial_layout": dict,   # From ArchitectAgent
            }

        Returns:
            structural_schema dict
        """
        spatial_layout = inputs["spatial_layout"]
        floors = spatial_layout.get("floors", [])
        building_type = spatial_layout.get("building_type", "unknown")

        logger.info(f"[{self.AGENT_ID}] Proposing structural grid for {len(floors)} floor(s)")
        self.send_message("pm", "status_update", {
            "status": "working",
            "task": "Structural grid proposal",
        })

        user_message = f"""Propose a structural grid for this {building_type} building.

Spatial Layout:
{json.dumps(spatial_layout, indent=2, ensure_ascii=False)[:6000]}

Output a complete structural_schema.json:
{{
  "structural_system": "concrete_frame|steel_frame|masonry|clt",
  "grid": {{
    "x_spacing_m": [6.0, 6.0, 6.0],
    "y_spacing_m": [8.0, 8.0],
    "origin": [0, 0]
  }},
  "columns": [
    {{
      "column_id": "C01",
      "x_m": 0.0,
      "y_m": 0.0,
      "size_mm": "400x400",
      "floors": ["G", "1"]
    }}
  ],
  "load_bearing_walls": [
    {{
      "wall_id": "W01",
      "from": [x1, y1],
      "to": [x2, y2],
      "thickness_mm": 200,
      "floors": ["G"]
    }}
  ],
  "cores": [
    {{
      "core_id": "CORE01",
      "type": "stair_lift",
      "x_m": 0.0,
      "y_m": 0.0,
      "width_m": 5.0,
      "depth_m": 6.0,
      "floors": ["G", "1", "2"]
    }}
  ],
  "transfer_structures": [],
  "engineering_flags": [
    {{
      "flag_id": "F01",
      "type": "long_span|cantilever|transfer|other",
      "severity": "warning|critical",
      "location": "describe location",
      "span_m": 0.0,
      "detail": "human engineer review required",
      "affected_rooms": []
    }}
  ],
  "notes": []
}}

Flag any spans > {self.MAX_SPAN_M}m and cantilevers > {self.MAX_CANTILEVER_M}m."""

        response = self.chat(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=2500,
        )

        structural_schema = self._extract_json(response)
        structural_schema["project_id"] = self.memory.project_id
        structural_schema["created_at"] = datetime.now(timezone.utc).isoformat()
        structural_schema["created_by"] = self.AGENT_ID
        structural_schema["span_threshold_m"] = self.MAX_SPAN_M
        structural_schema["cantilever_threshold_m"] = self.MAX_CANTILEVER_M

        flags = structural_schema.get("engineering_flags", [])
        critical = [f for f in flags if f.get("severity") == "critical"]
        warnings = [f for f in flags if f.get("severity") == "warning"]

        version = self.memory.save_schema("structural_schema", structural_schema)
        logger.success(
            f"[{self.AGENT_ID}] structural_schema saved as {version} — "
            f"{len(flags)} flags ({len(critical)} critical, {len(warnings)} warnings)"
        )

        if critical:
            logger.warning(f"[{self.AGENT_ID}] {len(critical)} critical structural flag(s) require engineer review")

        self.send_message("pm", "status_update", {
            "status": "done",
            "schema": "structural_schema",
            "version": version,
            "summary": f"{len(flags)} engineering flags ({len(critical)} critical)",
        })

        return structural_schema

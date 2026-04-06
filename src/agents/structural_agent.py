"""
Structural Agent — proposes structural grid from spatial layout.
Produces structural_schema.json. Flags long spans for engineer review.

Stomlinjer definieras TIDIGT i pipelinen (första agent efter Brief/Input Parser)
så att Architect, MEP och IFC Builder alla kan referera till samma grid.

All dimension output in mm. Spans snap to GRID_HEALTHCARE_MM or GRID_OFFICE_MM.
"""

import json
from datetime import datetime, timezone

from loguru import logger

from src.agents.base_agent import BaseAgent
from src.tools.se_dimensions import SE, snap_grid, snap_mm, GRID_HEALTHCARE_MM, GRID_OFFICE_MM


SYSTEM_PROMPT = """You are the Structural Agent for ArchitectAI, a multi-agent building design system.

You define the structural grid (stomlinjer) FIRST — before the architect places rooms.
All other agents snap their geometry to this grid.

Rules:
- Propose a regular column grid; all spans must snap to the allowed SE structural grids
- Sweden uses mm for all dimension output — never metres in the structural_schema
- Identify load-bearing walls (for masonry or cross-laminated timber)
- Identify structural cores (around stairs/lifts — these resist lateral loads)
- Flag any spans > 8000 mm as requiring special structure (transfer beam, long-span slab)
- Flag any cantilevers > 3000 mm as requiring engineer review
- Do NOT perform calculations — flag for human engineer review
- All grid spacings, column sizes, wall thicknesses must be multiples of 100 mm

Output ONLY valid JSON. No prose, no markdown fences."""


class StructuralAgent(BaseAgent):
    """
    Reviews the spatial layout and proposes a structural grid.

    Flags spans > 8m or cantilevers > 3m as warnings for human engineer review.
    Outputs structural_schema.json.
    """

    AGENT_ID = "structural"
    DEFAULT_MODEL = "gemini-3.1-pro"

    # Thresholds that trigger engineering review flags (in mm)
    MAX_SPAN_MM       = 8000   # 8 000 mm = 8 m
    MAX_CANTILEVER_MM = 3000   # 3 000 mm = 3 m
    # Legacy aliases (metres) kept for backwards compat
    MAX_SPAN_M        = 8.0
    MAX_CANTILEVER_M  = 3.0

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

        # Pick allowed spans for this building type
        is_healthcare = "health" in building_type.lower() or "ward" in building_type.lower()
        allowed_spans = GRID_HEALTHCARE_MM if is_healthcare else GRID_OFFICE_MM
        spans_str = ", ".join(str(s) for s in allowed_spans)

        # SE dimension reference block for the prompt
        se_dims = SE.prompt_block(building_type)

        user_message = f"""Define the structural grid (stomlinjer) for this {building_type} building.

{se_dims}

Allowed span values (mm): {spans_str}
Max span before flag: {self.MAX_SPAN_MM} mm
Max cantilever before flag: {self.MAX_CANTILEVER_MM} mm

Spatial Layout (summary):
{json.dumps(spatial_layout, indent=2, ensure_ascii=False)[:4000]}

Output a complete structural_schema.json.
ALL dimensions in mm (never metres). All values multiples of 100 mm.

Schema:
{{
  "structural_system": "concrete_frame|steel_frame|masonry|clt",
  "grid": {{
    "x_spacings_mm": [6000, 6000, 6000],
    "y_spacings_mm": [7200, 7200],
    "origin_mm": [0, 0],
    "total_width_mm": 18000,
    "total_depth_mm": 14400
  }},
  "columns": [
    {{
      "column_id": "C01",
      "x_mm": 0,
      "y_mm": 0,
      "size_mm": "400x400",
      "floors": ["G"]
    }}
  ],
  "load_bearing_walls": [
    {{
      "wall_id": "W01",
      "from_mm": [0, 0],
      "to_mm": [18000, 0],
      "thickness_mm": 200,
      "floors": ["G"]
    }}
  ],
  "cores": [
    {{
      "core_id": "CORE01",
      "type": "stair_lift",
      "x_mm": 0,
      "y_mm": 0,
      "width_mm": 5600,
      "depth_mm": 6400,
      "floors": ["G"]
    }}
  ],
  "floor_heights_mm": {{
    "G": {SE.FLOOR_HEIGHT_HEALTHCARE if is_healthcare else SE.FLOOR_HEIGHT_OFFICE}
  }},
  "slab_thickness_mm": {SE.SLAB_THICKNESS_TYPICAL},
  "transfer_structures": [],
  "engineering_flags": [],
  "notes": []
}}"""

        response = self.chat(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=2500,
        )

        structural_schema = self._extract_json(response)
        structural_schema["project_id"]             = self.memory.project_id
        structural_schema["created_at"]             = datetime.now(timezone.utc).isoformat()
        structural_schema["created_by"]             = self.AGENT_ID
        structural_schema["span_threshold_mm"]      = self.MAX_SPAN_MM
        structural_schema["cantilever_threshold_mm"]= self.MAX_CANTILEVER_MM
        # Legacy metre fields for any consumer that still reads them
        structural_schema["span_threshold_m"]       = self.MAX_SPAN_M
        structural_schema["cantilever_threshold_m"] = self.MAX_CANTILEVER_M

        # ── Code-level snap: enforce all grid spacings are on allowed grid ──
        grid = structural_schema.get("grid", {})
        for axis in ("x_spacings_mm", "y_spacings_mm"):
            raw = grid.get(axis, [])
            if raw:
                snapped = [snap_grid(v, allowed_spans) for v in raw]
                if snapped != raw:
                    logger.info(
                        f"[{self.AGENT_ID}] Snapped {axis}: {raw} → {snapped}"
                    )
                    grid[axis] = snapped

        # Snap column sizes to multiples of 100 mm
        for col in structural_schema.get("columns", []):
            sz = str(col.get("size_mm", "400x400"))
            if "x" in sz:
                parts = sz.split("x")
                try:
                    snapped_sz = "x".join(str(snap_mm(int(p), 100)) for p in parts)
                    col["size_mm"] = snapped_sz
                except ValueError:
                    pass

        # Snap wall thicknesses
        for wall in structural_schema.get("load_bearing_walls", []):
            t = wall.get("thickness_mm", 0)
            if t:
                wall["thickness_mm"] = snap_mm(t, 50)

        # Snap slab thickness
        slab = structural_schema.get("slab_thickness_mm", SE.SLAB_THICKNESS_TYPICAL)
        structural_schema["slab_thickness_mm"] = snap_mm(slab, 50)

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

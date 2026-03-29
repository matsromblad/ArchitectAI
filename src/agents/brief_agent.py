"""
Brief Agent — generates room_program.json from user prompt + site data
"""

import json
from datetime import datetime, timezone

from loguru import logger

from src.agents.base_agent import BaseAgent


SYSTEM_PROMPT = """You are the Brief Agent for ArchitectAI, a multi-agent building design system.

Your job is to produce a COMPACT, COMPLETE room program JSON from a building brief.

CRITICAL: Output ONLY valid JSON. No prose, no markdown, no code fences.
CRITICAL: Keep all string values SHORT (max 80 chars). No long explanations inside JSON.
CRITICAL: The entire JSON must fit within 8000 tokens. Be concise.
CRITICAL: NEVER include corridors as room entries. Corridors are NOT rooms.
CRITICAL: Each patient bedroom = SEPARATE entry with quantity=1. Use R01a/R01b/R01c/R01d.

Output schema:
{
  "building_type": "healthcare",
  "jurisdiction": "SE",
  "rooms": [
    {
      "room_id": "R01a",
      "room_name": "Patient Bedroom A",
      "quantity": 1,
      "zone": "clean",
      "access_type": "restricted",
      "min_area_m2": 16.0,
      "width_hint_m": 4.0,
      "depth_hint_m": 4.0,
      "adjacencies": ["R02a","R09"],
      "compliance_flag": false,
      "notes": "SS 91 42 21 min 16m2"
    }
  ],
  "total_net_area_m2": 0,
  "clean_dirty_separation": "brief max 100 chars"
}

Rules:
- DO NOT add corridors/hallways/circulation as room entries — the architect handles those
- Zone must be one of: clean, dirty, staff, public, service
- Each patient bedroom = SEPARATE entry (R01a, R01b, R01c, R01d)
- Each patient ensuite = SEPARATE entry (R02a, R02b, R02c, R02d)
- adjacencies must be bidirectional — if A lists B then B must list A
- compliance_flag=false by default; true only for genuine unresolved compliance issues
"""


class BriefAgent(BaseAgent):
    AGENT_ID = "brief"
    DEFAULT_MODEL = "claude-sonnet-4-6"

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
        qa_feedback = inputs.get("qa_feedback")

        attempt_label = "REVISION" if qa_feedback else "INITIAL"
        logger.info(f"[{self.AGENT_ID}] [{attempt_label}] Generating room program for: {prompt[:80]}...")
        self.send_message("pm", "status_update", {"status": "working", "task": f"Room program ({attempt_label})"})

        feedback_section = ""
        if qa_feedback:
            feedback_section = f"""
PREVIOUS ATTEMPT WAS REJECTED BY QA. Fix these issues in your new output:
{qa_feedback}

Key lessons from rejection:
- Keep all room descriptions SHORT (max 60 chars per string field)
- Do NOT include verbose compliance text inside the JSON
- Ensure JSON is COMPLETE — never truncate mid-document
"""

        user_message = f"""User brief: "{prompt}"

Site: area={site_data.get('boundary', {}).get('area_m2', 'unknown')}m², jurisdiction={jurisdiction}
{feedback_section}
Generate a compact room program JSON. Max 15 rooms total. Keep string values short."""

        response = self.chat(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=16000,
        )

        room_program = self._extract_json(response)
        # Unwrap nested structure if Claude returned {"room_program": {...}}
        if "room_program" in room_program and isinstance(room_program["room_program"], dict):
            room_program = room_program["room_program"]

        # ── Code-level sanitisation (fixes common LLM inconsistencies) ──────
        rooms = room_program.get("rooms", [])
        for r in rooms:
            # Ensure min_area >= width_hint * depth_hint
            w = float(r.get("width_hint_m") or 0)
            d = float(r.get("depth_hint_m") or 0)
            if w > 0 and d > 0:
                hint_area = round(w * d, 2)
                if hint_area < float(r.get("min_area_m2", 0)):
                    # Fix dims to match area
                    target = float(r["min_area_m2"])
                    r["depth_hint_m"] = round(target / w, 2)
            # Remove duplicate area fields — keep only min_area_m2
            r.pop("area_m2", None)
            # Ensure zone is valid
            valid_zones = {"clean", "dirty", "staff", "public", "service", "restricted"}
            if r.get("zone") not in valid_zones:
                r["zone"] = "staff"
            # Make adjacency lists bidirectional
            # (we do a second pass below)
        
        # Second pass: enforce bidirectional adjacencies
        room_by_id = {r.get("room_id"): r for r in rooms if r.get("room_id")}
        for r in rooms:
            rid = r.get("room_id")
            if not rid:
                continue
            for adj_id in list(r.get("adjacencies", [])):
                adj = room_by_id.get(adj_id)
                if adj is not None:
                    adj_list = adj.setdefault("adjacencies", [])
                    if rid not in adj_list:
                        adj_list.append(rid)

        # Authoritative area calculation (single field, no duplicates)
        total = round(sum(
            float(r.get("min_area_m2", 0)) * int(r.get("quantity", 1))
            for r in rooms
        ), 1)

        # Remove conflicting area fields — leave only total_net_area_m2
        for key in ("total_area_m2", "total_gross_area_m2", "total_net_area_m2"):
            room_program.pop(key, None)
        room_program["total_net_area_m2"] = total
        room_program["gross_area_m2"] = round(total * 1.35, 1)
        room_program["gross_factor"] = 1.35
        room_program["rooms"] = rooms

        room_program["project_id"] = self.memory.project_id
        room_program["jurisdiction"] = jurisdiction
        room_program["created_at"] = datetime.now(timezone.utc).isoformat()
        room_program["created_by"] = self.AGENT_ID
        # Remove open compliance_queries (not needed downstream)
        room_program.pop("compliance_queries", None)
        room_program["total_area_m2"] = total  # keep for backward compat

        version = self.memory.save_schema("room_program", room_program)
        logger.success(f"[{self.AGENT_ID}] room_program saved as {version} — {len(room_program.get('rooms', []))} rooms, {total:.0f} m² total")

        self.send_message("pm", "status_update", {
            "status": "done",
            "schema": "room_program",
            "version": version,
            "summary": f"{len(room_program.get('rooms', []))} rooms, {total:.0f} m²",
        })

        return room_program

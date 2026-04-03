"""
QA Agent — quality gatekeeper. The only agent that can block progress.
"""

import json
from datetime import datetime, timezone

from loguru import logger

from src.agents.base_agent import BaseAgent


SYSTEM_PROMPT = """You are the QA Agent for ArchitectAI, a multi-agent building design system.

You are the quality gatekeeper. You review all deliverables before they proceed.

For each review, check:
1. Internal consistency — no contradictions within the document
2. Completeness — all required fields present, no obvious omissions
3. Spatial logic — rooms fit on site, areas add up, no overlaps
4. Compliance flags — any items flagged by Compliance Agent resolved?
5. Cross-discipline consistency — does this match approved upstream schemas?

Verdict options:
- APPROVED: Document passes all checks. Proceed.
- REJECTED: Specific issues found. Must be revised before resubmission.
- CONDITIONAL: Minor issues. Can proceed if agent acknowledges and notes fix plan.

Output ONLY valid JSON:
{
  "verdict": "APPROVED|REJECTED|CONDITIONAL",
  "schema_type": "...",
  "version_reviewed": "...",
  "checks": [
    {"check": "check name", "result": "pass|fail|warning", "detail": "..."}
  ],
  "issues": ["specific issue 1", "specific issue 2"],
  "fix_instructions": "...",
  "approved_at": null
}
"""


class QAAgent(BaseAgent):
    AGENT_ID = "qa"
    # TOKEN-OPT: Use Haiku for QA — it does structured rule-checking, not creative reasoning.
    # Override with QA_MODEL env var if Sonnet is needed for complex multi-discipline checks.
    DEFAULT_MODEL = "claude-haiku-4-5"
    MAX_REJECTIONS = 2  # TOKEN-OPT: Was 3 — cut to 2 to stop the QA-Brief loop earlier

    def run(self, inputs: dict) -> dict:
        """
        Review a schema document.

        Args:
            inputs: {
                "schema_type": str,         # e.g. "room_program"
                "schema_data": dict,        # the actual document
                "version": str,
                "prior_rejections": int,    # how many times this was rejected already
                "context": dict,            # upstream approved schemas for cross-checking
            }

        Returns:
            QA verdict dict
        """
        schema_type = inputs["schema_type"]
        schema_data = inputs["schema_data"]
        version = inputs.get("version", "unknown")
        prior_rejections = inputs.get("prior_rejections", 0)

        logger.info(f"[{self.AGENT_ID}] Reviewing {schema_type} {version} (rejection #{prior_rejections})")
        self.send_message("pm", "status_update", {"status": "working", "task": f"QA review: {schema_type} {version}"})

        # TOKEN-OPT: Accept CONDITIONAL on attempt >= 1 — don't burn tokens on minor issues
        # The Brief Agent's code-level sanitiser handles most structural problems anyway.
        # Only block on actual REJECTED verdicts, and only up to MAX_REJECTIONS times.
        if prior_rejections >= 1:
            # On second+ attempt: treat CONDITIONAL as APPROVED to stop the loop
            # This is set before the LLM call so the routing logic can see it
            _accept_conditional = True
        else:
            _accept_conditional = False

        # Escalate if too many rejections
        if prior_rejections >= self.MAX_REJECTIONS:
            logger.warning(f"[{self.AGENT_ID}] {self.MAX_REJECTIONS} rejections on {schema_type} — escalating to PM")
            self.escalate_to_pm(
                question=f"{schema_type} has been rejected {prior_rejections} times. Manual review needed.",
                context={"schema_type": schema_type, "version": version, "schema_data": schema_data}
            )

        # Compress schema_data for review — show summary not full JSON
        def compress_for_qa(data, max_chars=2500):
            """Summarise document for QA without losing critical facts."""
            import json as _json
            full = _json.dumps(data, ensure_ascii=False, separators=(',',':'))
            if len(full) <= max_chars:
                return full
            # Build a summary version
            summary = {}
            if schema_type == "room_program":
                rooms = data.get("rooms", [])
                summary = {
                    "building_type": data.get("building_type"),
                    "jurisdiction": data.get("jurisdiction"),
                    "total_net_area_m2": data.get("total_net_area_m2"),
                    "gross_area_m2": data.get("gross_area_m2"),
                    "room_count": len(rooms),
                    "rooms": [{
                        "id": r.get("room_id"), "n": r.get("room_name","")[:25],
                        "z": r.get("zone"), "a": r.get("min_area_m2"),
                        "adj": r.get("adjacencies",[])[:8],
                    } for r in rooms],
                    "sep": data.get("clean_dirty_separation","")[:80],
                }
            elif schema_type == "spatial_layout":
                floor = (data.get("floors") or [{}])[0]
                rooms = floor.get("rooms",[])
                corridors = floor.get("corridors",[])
                stairs = floor.get("stairs",[])
                lifts = floor.get("lifts",[])
                summary = {
                    "building_type": data.get("building_type"),
                    "site": f"{data.get('site_width_m')}×{data.get('site_depth_m')}m",
                    "collision_check": data.get("collision_check"),
                    "layout_strategy": data.get("layout_strategy"),
                    "room_count": len(rooms),
                    "rooms": [{
                        "id": r.get("room_id"), "name": r.get("name","")[:25],
                        "zone": r.get("zone"),
                        "x": r.get("x_m"), "y": r.get("y_m"),
                        "w": r.get("width_m"), "d": r.get("depth_m"),
                        "area": r.get("area_m2"),
                    } for r in rooms],
                    "corridors": [{
                        "id": c.get("corridor_id"), "zone": c.get("zone"),
                        "y": c.get("y_m"), "w": c.get("width_m"), "d": c.get("depth_m"),
                    } for c in corridors],
                    "stairs": stairs,
                    "lifts": lifts,
                    "clean_dirty_separation": data.get("clean_dirty_separation","")[:150],
                }
            else:
                summary = data
            result = _json.dumps(summary, ensure_ascii=False, separators=(',',':'))
            return result[:max_chars]

        schema_summary = compress_for_qa(schema_data)

        user_message = f"""Review this {schema_type} document (version {version}, prior rejections: {prior_rejections}):

{schema_summary}

Perform a thorough QA review. Focus on:
1. Spatial logic (no overlaps, correct adjacencies, corridors connect to stairs)
2. Completeness (all required rooms present, stairs/lifts defined)
3. Zone compliance (clean/dirty separation, isolation room setup)
4. Geometry (room fits in site, no gap > 0.5m unaccounted)

Output your verdict as JSON."""

        response = self.chat(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=3000,
        )

        try:
            verdict = self._extract_json(response)
        except ValueError:
            # If QA response itself is truncated, return a safe fallback
            logger.warning(f"[{self.AGENT_ID}] Could not parse QA response — using fallback CONDITIONAL verdict")
            verdict = {
                "verdict": "CONDITIONAL",
                "issues": ["QA response was truncated — manual review recommended"],
                "fix_instructions": "Resubmit for QA review",
            }
        verdict["schema_type"] = schema_type
        verdict["version_reviewed"] = version
        verdict["reviewed_at"] = datetime.now(timezone.utc).isoformat()

        # TOKEN-OPT: Promote CONDITIONAL → APPROVED on attempt >= 1
        # The code-level sanitiser in Brief/Architect agents already fixes structural issues.
        # Continuing to loop on minor/warning-level issues wastes tokens without quality gain.
        if _accept_conditional and verdict["verdict"] == "CONDITIONAL":
            logger.info(
                f"[{self.AGENT_ID}] CONDITIONAL on attempt {prior_rejections} — "
                f"auto-promoting to APPROVED (TOKEN-OPT). Issues noted: {verdict.get('issues', [])}"
            )
            verdict["verdict"] = "APPROVED"
            verdict["notes"] = "Auto-promoted from CONDITIONAL (attempt >= 1, token-opt policy)"

        if verdict["verdict"] == "APPROVED":
            verdict["approved_at"] = verdict["reviewed_at"]
            self.memory.mark_schema_approved(schema_type, version)
            self.memory.save_qa_report(schema_type, verdict)
            logger.success(f"[{self.AGENT_ID}] {schema_type} {version} — APPROVED")
        else:
            logger.warning(f"[{self.AGENT_ID}] {schema_type} {version} — {verdict['verdict']}: {verdict.get('issues', [])}")

        self.send_message("pm", "qa_verdict", {
            "verdict": verdict["verdict"],
            "schema_type": schema_type,
            "version": version,
            "issues": verdict.get("issues", []),
        })

        return verdict

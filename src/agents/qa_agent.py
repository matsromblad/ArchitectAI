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
    DEFAULT_MODEL = "claude-sonnet-4-6"
    MAX_REJECTIONS = 3  # Escalate to PM after this many rejections

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

        # Escalate if too many rejections
        if prior_rejections >= self.MAX_REJECTIONS:
            logger.warning(f"[{self.AGENT_ID}] {self.MAX_REJECTIONS} rejections on {schema_type} — escalating to PM")
            self.escalate_to_pm(
                question=f"{schema_type} has been rejected {prior_rejections} times. Manual review needed.",
                context={"schema_type": schema_type, "version": version, "schema_data": schema_data}
            )

        user_message = f"""Review this {schema_type} document (version {version}):

{json.dumps(schema_data, indent=2, ensure_ascii=False)[:6000]}

Context (approved upstream schemas):
{json.dumps(inputs.get('context', {}), indent=2)[:2000]}

Prior rejections on this document: {prior_rejections}

Perform a thorough QA review and output your verdict as JSON."""

        response = self.chat(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=8000,
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

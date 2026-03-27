"""
Compliance Agent — regulatory expert.
Self-sources documents, answers compliance queries, escalates unknown rules to PM.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from src.agents.base_agent import BaseAgent


SYSTEM_PROMPT = """You are the Compliance Agent for ArchitectAI, a multi-agent building design system.

You are the ONLY agent with jurisdiction-specific regulatory knowledge. You are the expert on:
- Building codes (BBR in Sweden, UAE Civil Defence codes, etc.)
- Healthcare facility standards (Socialstyrelsen SOSFS in SE, JCI internationally)
- Fire safety regulations
- Accessibility standards (ADA, EN 17210)
- Any other applicable local regulations

Rules you MUST follow:
1. NEVER invent a regulation. If you don't know, say so.
2. Always cite the specific document, section, and clause when referencing a rule.
3. If a document is in your knowledge base, use it. If not, flag it as "source needed".
4. Give verdict as: PASS, FAIL, CONDITIONAL, or UNKNOWN.
5. For CONDITIONAL and FAIL: always suggest a fix.
6. Output ONLY valid JSON.

Output format:
{
  "verdict": "PASS|FAIL|CONDITIONAL|UNKNOWN",
  "rule_ref": "BBR 3:412 — Gangbredd i vårdutrymmen",
  "rule_text": "...",
  "proposed_value": "...",
  "required_value": "...",
  "fix": "...",  // only for FAIL/CONDITIONAL
  "confidence": "high|medium|low",
  "source_status": "verified|inferred|source_needed",
  "notes": "..."
}
"""


class ComplianceAgent(BaseAgent):
    AGENT_ID = "compliance"
    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, memory, model=None):
        super().__init__(memory, model)
        self.kb_dir = Path(os.getenv("COMPLIANCE_KB_DIR", "./compliance_kb"))

    def run(self, inputs: dict) -> dict:
        """
        Answer a compliance query.

        Args:
            inputs: {
                "query": str,               # Natural language question
                "jurisdiction": str,        # e.g. "SE"
                "building_type": str,       # e.g. "healthcare"
                "proposed_value": Any,      # What the agent wants to do
                "unit": str,                # e.g. "mm"
                "context": dict,            # Additional context
            }

        Returns:
            compliance response dict
        """
        query = inputs["query"]
        jurisdiction = inputs.get("jurisdiction", "SE")
        building_type = inputs.get("building_type", "general")

        logger.info(f"[{self.AGENT_ID}] Query [{jurisdiction}/{building_type}]: {query}")
        self.send_message("pm", "status_update", {"status": "working", "task": f"Compliance check: {query[:60]}"})

        # Check if we need to source documents first
        kb_context = self._get_kb_context(jurisdiction, building_type, query)

        user_message = f"""Compliance query:

Jurisdiction: {jurisdiction}
Building type: {building_type}
Question: {query}
Proposed value: {inputs.get('proposed_value', 'N/A')} {inputs.get('unit', '')}

Additional context:
{json.dumps(inputs.get('context', {}), indent=2)}

Knowledge base context:
{kb_context}

Provide your compliance verdict as JSON."""

        response = self.chat(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=2048,
        )

        result = self._extract_json(response)
        result["query"] = query
        result["jurisdiction"] = jurisdiction
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        # If source is needed, escalate to PM
        if result.get("source_status") == "source_needed":
            logger.warning(f"[{self.AGENT_ID}] Source needed for: {result.get('rule_ref', query)}")
            self.escalate_to_pm(
                question=f"Need regulatory document: {result.get('rule_ref', query)} for {jurisdiction}",
                context={"query": query, "jurisdiction": jurisdiction, "building_type": building_type}
            )

        self.send_message("pm", "compliance_response", {
            "verdict": result.get("verdict"),
            "query": query,
            "rule_ref": result.get("rule_ref"),
        })

        return result

    def _get_kb_context(self, jurisdiction: str, building_type: str, query: str) -> str:
        """Try to retrieve relevant context from local knowledge base."""
        kb_path = self.kb_dir / jurisdiction
        if not kb_path.exists():
            return f"No local knowledge base found for {jurisdiction}. Relying on training knowledge."

        # List available documents
        docs = list(kb_path.glob("*.pdf")) + list(kb_path.glob("*.txt"))
        if not docs:
            return f"Knowledge base directory exists for {jurisdiction} but contains no documents."

        doc_list = "\n".join(f"- {d.name}" for d in docs)
        return f"Available regulatory documents for {jurisdiction}:\n{doc_list}\n\n(ChromaDB RAG integration pending — use training knowledge for now)"

    def check_room_program(self, room_program: dict) -> dict:
        """Validate an entire room program against regulations."""
        jurisdiction = room_program.get("jurisdiction", "SE")
        building_type = room_program.get("building_type", "general")
        results = []

        for room in room_program.get("rooms", []):
            if room.get("min_area_m2"):
                result = self.run({
                    "query": f"Minimum area for {room['name']} in {building_type} facility",
                    "jurisdiction": jurisdiction,
                    "building_type": building_type,
                    "proposed_value": room["min_area_m2"],
                    "unit": "m²",
                    "context": {"room_type": room.get("room_type"), "access_type": room.get("access_type")},
                })
                results.append({"room_id": room["id"], "room_name": room["name"], **result})

        return {
            "jurisdiction": jurisdiction,
            "building_type": building_type,
            "checks": results,
            "summary": {
                "pass": sum(1 for r in results if r.get("verdict") == "PASS"),
                "fail": sum(1 for r in results if r.get("verdict") == "FAIL"),
                "conditional": sum(1 for r in results if r.get("verdict") == "CONDITIONAL"),
                "unknown": sum(1 for r in results if r.get("verdict") == "UNKNOWN"),
            }
        }

"""
Compliance Agent — regulatory expert.
Self-sources documents, answers compliance queries, escalates unknown rules to PM.
Uses deterministic rule lookups from SE_FIRE, SE_HVAC, SE_LIGHTING modules.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from src.agents.base_agent import BaseAgent
from src.tools.se_fire import SE_FIRE
from src.tools.se_hvac import SE_HVAC
from src.tools.se_lighting import SE_LIGHTING
from src.memory.kb_loader import get_loader


_SYSTEM_PROMPT_TEMPLATE = """\
You are the Compliance Agent for ArchitectAI, a multi-agent building design system.

You are the ONLY agent with jurisdiction-specific regulatory knowledge. You are the expert on:
- Building codes (BBR in Sweden, UAE Civil Defence codes, etc.)
- Swedish PTS (Program för Teknisk Standard) for regional healthcare facilities.
- Healthcare facility standards (Socialstyrelsen SOSFS in SE, JCI internationally)
- Fire safety regulations
- Accessibility standards (ADA, EN 17210)
- Any other applicable local regulations

You have deterministic rule lookups injected below.
Use these for Swedish rules — do NOT rely solely on LLM training for BBR values.

{se_fire_block}

{hvac_block}

{lighting_block}

### PTS & HEALTHCARE KNOWLEDGE BASE (Extracted from regulatory documents)

{kb_tekniska_krav}

{kb_miljokrav}

{kb_brand}

Rules you MUST follow:
1. NEVER invent a regulation. If you don't know, say so.
2. Always cite the specific document, section, and clause when referencing a rule.
3. If a document is in your knowledge base, use it. If not, flag it as "source needed".
4. Give verdict as: PASS, FAIL, CONDITIONAL, or UNKNOWN.
5. For CONDITIONAL and FAIL: always suggest a fix.
6. Output ONLY valid JSON.

Output format:
{{
  "verdict": "PASS|FAIL|CONDITIONAL|UNKNOWN",
  "rule_ref": "BBR 3:412 — Gangbredd i vårdutrymmen",
  "rule_text": "...",
  "proposed_value": "...",
  "required_value": "...",
  "fix": "...",
  "confidence": "high|medium|low",
  "source_status": "verified|inferred|source_needed",
  "notes": "..."
}}
"""


class ComplianceAgent(BaseAgent):
    AGENT_ID = "compliance"
    DEFAULT_MODEL = "gemini-3-flash"

    def __init__(self, memory, model=None):
        super().__init__(memory, model)
        self.kb_dir = Path(os.getenv("COMPLIANCE_KB_DIR", "./compliance_kb"))

        # Load KB documents and store strings on self so run() can use them
        # per-call when the building_type changes the SE rule blocks.
        kb_loader = get_loader()
        kb_docs = kb_loader.get_documents_for_agent("compliance")

        # Store KB strings — use the new larger limits from kb_loader
        self._kb_tekniska = (
            f"**TEKNISKA KRAV (Technical Requirements):**\n"
            + kb_docs["tekniska_krav"][:10_000]
            if kb_docs.get("tekniska_krav") else ""
        )
        self._kb_miljokrav = (
            f"**MILJÖKRAV (Environmental Requirements):**\n"
            + kb_docs["miljokrav"][:5_000]
            if kb_docs.get("miljokrav") else ""
        )
        self._kb_brand = (
            f"**BRAND (Fire Safety):**\n"
            + kb_docs["brand"][:6_000]
            if kb_docs.get("brand") else ""
        )

        # Pre-build default prompt (healthcare / no specific building_type yet)
        self._sys_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            se_fire_block=SE_FIRE.prompt_block(),
            hvac_block=SE_HVAC.prompt_block(),
            lighting_block=SE_LIGHTING.prompt_block(),
            kb_tekniska_krav=self._kb_tekniska,
            kb_miljokrav=self._kb_miljokrav,
            kb_brand=self._kb_brand,
        )

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
        query         = inputs["query"]
        jurisdiction  = inputs.get("jurisdiction", "SE")
        building_type = inputs.get("building_type", "general")

        logger.info(f"[{self.AGENT_ID}] Query [{jurisdiction}/{building_type}]: {query}")
        self.send_message("pm", "status_update", {
            "status": "working",
            "task": f"Compliance check: {query[:60]}",
        })

        # Rebuild prompt with building-type-specific SE rule blocks + KB context.
        # Previously this was missing the kb_* variables, causing a KeyError crash
        # or silently omitting the KB from every live query.
        sys_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            se_fire_block=SE_FIRE.prompt_block(building_type),
            hvac_block=SE_HVAC.prompt_block(building_type),
            lighting_block=SE_LIGHTING.prompt_block(building_type),
            kb_tekniska_krav=self._kb_tekniska,
            kb_miljokrav=self._kb_miljokrav,
            kb_brand=self._kb_brand,
        )

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
            system=sys_prompt,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=2048,
        )

        result = self._extract_json(response)
        result["query"]        = query
        result["jurisdiction"] = jurisdiction
        result["timestamp"]    = datetime.now(timezone.utc).isoformat()

        # Escalate if source needed
        if result.get("source_status") == "source_needed":
            logger.warning(f"[{self.AGENT_ID}] Source needed for: {result.get('rule_ref', query)}")
            self.escalate_to_pm(
                question=f"Need regulatory document: {result.get('rule_ref', query)} for {jurisdiction}",
                context={"query": query, "jurisdiction": jurisdiction, "building_type": building_type},
            )

        self.send_message("pm", "compliance_response", {
            "verdict":  result.get("verdict"),
            "query":    query,
            "rule_ref": result.get("rule_ref"),
        })

        return result

    def _get_kb_context(self, jurisdiction: str, building_type: str, query: str) -> str:
        """Fetch targeted semantic context from the KB based on the specific query."""
        if jurisdiction != "SE" or building_type != "healthcare":
            return ""

        # Use semantic search for the specific compliance query
        return self.kb_loader.get_semantic_context(
            query,
            self.AGENT_ID,
            n_results=5
        )

    def check_room_program(self, room_program: dict) -> dict:
        """Validate an entire room program against regulations."""
        jurisdiction  = room_program.get("jurisdiction", "SE")
        building_type = room_program.get("building_type", "general")
        results = []

        for room in room_program.get("rooms", []):
            if room.get("min_area_m2"):
                result = self.run({
                    "query":          f"Minimum area for {room.get('room_name', room.get('name', '?'))} in {building_type} facility",
                    "jurisdiction":   jurisdiction,
                    "building_type":  building_type,
                    "proposed_value": room["min_area_m2"],
                    "unit":           "m²",
                    "context": {
                        "room_id":    room.get("room_id"),
                        "zone":       room.get("zone"),
                        "access":     room.get("access_type"),
                    },
                })
                results.append({
                    "room_id":   room.get("room_id"),
                    "room_name": room.get("room_name", room.get("name")),
                    **result,
                })

        return {
            "jurisdiction": jurisdiction,
            "building_type": building_type,
            "checks": results,
            "summary": {
                "pass":        sum(1 for r in results if r.get("verdict") == "PASS"),
                "fail":        sum(1 for r in results if r.get("verdict") == "FAIL"),
                "conditional": sum(1 for r in results if r.get("verdict") == "CONDITIONAL"),
                "unknown":     sum(1 for r in results if r.get("verdict") == "UNKNOWN"),
            },
        }

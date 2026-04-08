"""
Project Manager Agent — orchestrator. Runs on claude-opus-4-6.
Coordinates all agents, resolves conflicts, manages milestones, gates user approvals.
"""

import json
import os
from datetime import datetime, timezone

from loguru import logger

from src.agents.base_agent import BaseAgent
from src.memory.project_memory import ProjectMemory


SYSTEM_PROMPT = """You are the Project Manager Agent for ArchitectAI, a multi-agent building design system.

You are the orchestrator. You:
1. Receive the user's initial brief and coordinate the full design process
2. Assign tasks to specialist agents in the correct order
3. Resolve conflicts between disciplines (e.g. architect vs structural)
4. Decide whether to resolve questions internally or escalate to the user
5. Manage milestone gates — pause and request user approval before proceeding
6. Track the overall project state

Escalate to user when:
- A decision requires client preference (e.g. number of isolation rooms)
- A milestone is complete and needs formal approval
- You receive 3+ rejections on the same item without resolution
- Regulatory documents are unavailable and needed

Handle internally when:
- A question has a clear best-practice answer
- A conflict can be resolved with a standard design solution
- The question is purely technical with no client preference involved

You always respond with a structured JSON action:
{
  "action": "assign_task | escalate_to_user | resolve_conflict | approve_milestone | request_info",
  "target_agent": "agent_id or null",
  "message": "...",
  "reasoning": "...",
  "escalate": false
}
"""


class PMAgent(BaseAgent):
    AGENT_ID = "pm"
    DEFAULT_MODEL = "gemini-3.1-pro-preview"

    def run(self, inputs: dict) -> dict:
        """
        Process an incoming event/message and decide what to do next.

        Args:
            inputs: {
                "event_type": str,      # "kickoff" | "agent_done" | "escalation" | "qa_verdict" | "user_response"
                "from_agent": str,
                "payload": dict,
                "project_summary": dict,
            }

        Returns:
            PM decision dict
        """
        event_type = inputs.get("event_type", "unknown")
        from_agent = inputs.get("from_agent", "unknown")
        payload = inputs.get("payload", {})
        project_summary = inputs.get("project_summary", self.memory.get_project_summary())

        logger.info(f"[{self.AGENT_ID}] Processing event: {event_type} from {from_agent}")

        user_message = f"""Project state:
{json.dumps(project_summary, indent=2)}

Incoming event: {event_type}
From: {from_agent}
Payload: {json.dumps(payload, indent=2)}

Recent messages:
{json.dumps(self.memory.get_recent_messages(10), indent=2)}

What should happen next? Provide your decision as JSON."""

        response = self.chat(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=2048,
            temperature=0.1,  # PM should be consistent
        )

        decision = self._extract_json(response)

        # Log PM decision
        self.memory.log_decision(
            agent=self.AGENT_ID,
            decision=decision.get("action", "unknown"),
            context=decision.get("reasoning", ""),
        )

        # If escalating to user, log a milestone waiting state
        if decision.get("escalate") or decision.get("action") == "escalate_to_user":
            self.send_message("dashboard", "user_approval_request", {
                "message": decision.get("message"),
                "context": payload,
                "requires_response": True,
            })
            logger.warning(f"[{self.AGENT_ID}] Escalated to user: {decision.get('message', '')[:100]}")

        return decision

    def kickoff(self, user_prompt: str, site_data: dict, jurisdiction: str = "SE") -> dict:
        """Start a new project from a user prompt."""
        logger.info(f"[{self.AGENT_ID}] Project kickoff: {user_prompt[:80]}")

        # Store basic project info
        self.memory.state["jurisdiction"] = jurisdiction
        self.memory.state["building_type"] = self._infer_building_type(user_prompt)
        self.memory.state["phase"] = "m1_brief"
        self.memory.state["user_prompt"] = user_prompt
        self.memory._save_state()

        return self.run({
            "event_type": "kickoff",
            "from_agent": "user",
            "payload": {
                "prompt": user_prompt,
                "jurisdiction": jurisdiction,
                "site_area_m2": (site_data.get("boundary", {}) if isinstance(site_data.get("boundary"), dict) else {}).get("area_m2") or site_data.get("area_m2"),
            },
        })

    def _infer_building_type(self, prompt: str) -> str:
        """Quick heuristic to infer building type from prompt."""
        prompt_lower = prompt.lower()
        if any(w in prompt_lower for w in ["hospital", "ward", "clinic", "healthcare", "medical", "geriatric", "psych"]):
            return "healthcare"
        if any(w in prompt_lower for w in ["school", "university", "campus", "classroom"]):
            return "education"
        if any(w in prompt_lower for w in ["office", "workspace", "headquarters"]):
            return "office"
        if any(w in prompt_lower for w in ["residential", "apartment", "housing", "dwelling"]):
            return "residential"
        return "general"

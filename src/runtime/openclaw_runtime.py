"""
OpenClaw Runtime Adapter — Mode B orchestration.

This is a temporary adapter that delegates agent work to OpenClaw
subagents/sessions instead of calling the Anthropic API directly.

Use when: direct Anthropic API billing/auth is unavailable.
Replace with direct API calls when Mode A is ready.
"""

from loguru import logger
from typing import Any


class OpenClawRuntime:
    """
    Delegates intelligent agent tasks to OpenClaw orchestration.
    Acts as a drop-in interface until direct Anthropic API is available.
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        logger.info(f"[OpenClawRuntime] Initialized for project: {project_id} (Mode B)")

    def submit_task(self, agent_name: str, prompt: str, context: dict | None = None) -> dict:
        """
        Submit a task to an agent via OpenClaw orchestration.

        In Mode B, this logs the task and returns a structured stub.
        Replace with actual session dispatch when integrating deeper.

        Args:
            agent_name: e.g. "architect", "compliance", "brief"
            prompt: the task prompt for the agent
            context: optional dict with additional context

        Returns:
            dict with agent response (stub in Mode B)
        """
        logger.info(f"[OpenClawRuntime] → {agent_name}: {prompt[:80]}")
        # TODO: replace with actual OpenClaw session dispatch
        return {
            "agent": agent_name,
            "status": "stub",
            "mode": "B",
            "note": f"Task submitted to {agent_name} via OpenClaw orchestration. Awaiting real dispatch integration.",
            "prompt_preview": prompt[:200],
        }

    def request_pm_decision(self, prompt: str, context: dict | None = None) -> dict:
        """
        Ask the Project Manager agent to make a decision.

        Args:
            prompt: the decision request
            context: optional project state context

        Returns:
            dict with PM decision (stub in Mode B)
        """
        logger.info(f"[OpenClawRuntime] → PM decision: {prompt[:80]}")
        return {
            "agent": "pm",
            "action": "stub_decision",
            "mode": "B",
            "note": "PM decision requested via OpenClaw. Real dispatch pending.",
            "prompt_preview": prompt[:200],
        }

    def submit_qa_review(self, schema_type: str, payload: dict) -> dict:
        """
        Submit a schema to the QA Agent for review.

        Args:
            schema_type: e.g. "room_program", "spatial_layout"
            payload: the schema content to review

        Returns:
            dict with QA verdict (stub in Mode B)
        """
        logger.info(f"[OpenClawRuntime] → QA review: {schema_type}")
        return {
            "agent": "qa",
            "verdict": "STUB",
            "schema_type": schema_type,
            "mode": "B",
            "note": "QA review requested via OpenClaw. Real dispatch pending.",
        }

"""
Base Agent — shared foundation for all ArchitectAI agents.
All agents inherit from this class.
"""

import os
from abc import ABC, abstractmethod
from typing import Any, Optional

import anthropic
from loguru import logger

from src.memory.project_memory import ProjectMemory


class BaseAgent(ABC):
    """
    Base class for all ArchitectAI agents.

    Provides:
    - Anthropic client setup
    - Shared message logging via ProjectMemory
    - Standard call() interface
    - Structured response parsing helpers
    """

    # Override in subclass
    AGENT_ID: str = "base"
    DEFAULT_MODEL: str = "claude-sonnet-4-5"

    def __init__(self, memory: ProjectMemory, model: str = None):
        self.memory = memory
        self.model = model or os.getenv(f"{self.AGENT_ID.upper()}_MODEL", self.DEFAULT_MODEL)
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        logger.info(f"[{self.AGENT_ID}] Initialized with model: {self.model}")

    def chat(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        """Send a chat request to Claude. Returns the text response."""
        logger.debug(f"[{self.AGENT_ID}] → Claude ({self.model}), {len(messages)} messages")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
        )
        content = response.content[0].text
        logger.debug(f"[{self.AGENT_ID}] ← {len(content)} chars")
        return content

    def send_message(
        self,
        to: str,
        msg_type: str,
        payload: dict,
        reply_to: str = None,
    ) -> str:
        """Log a message to the project message bus. Returns msg_id."""
        return self.memory.log_message(
            from_agent=self.AGENT_ID,
            to_agent=to,
            msg_type=msg_type,
            payload=payload,
            reply_to=reply_to,
        )

    def escalate_to_pm(self, question: str, context: dict = None) -> str:
        """Send an escalation message to the Project Manager."""
        logger.warning(f"[{self.AGENT_ID}] Escalating to PM: {question}")
        return self.send_message(
            to="pm",
            msg_type="escalation",
            payload={"question": question, "context": context or {}},
        )

    @abstractmethod
    def run(self, inputs: dict) -> dict:
        """
        Execute the agent's main task.

        Args:
            inputs: dict with task-specific inputs

        Returns:
            dict with task-specific outputs
        """
        ...

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from a Claude response that may contain prose + JSON."""
        import json
        import re
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try to find JSON block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # Try to find raw JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Could not extract JSON from response: {text[:200]}...")

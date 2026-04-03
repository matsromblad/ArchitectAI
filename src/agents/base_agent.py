"""
Base Agent — shared foundation for all ArchitectAI agents.
All agents inherit from this class.
"""

import os
from abc import ABC, abstractmethod
from typing import Any, Optional

from loguru import logger
from openai import OpenAI

from src.memory.project_memory import ProjectMemory

# ---------------------------------------------------------------------------
# Runtime: OpenClaw Gateway proxy (OpenAI-compatible endpoint)
#
# The gateway proxies requests via its own OAuth token to Anthropic —
# no separate ANTHROPIC_API_KEY credits needed.
#
# Config (env or .env):
#   OPENCLAW_GATEWAY_URL   default: http://127.0.0.1:18789
#   OPENCLAW_GATEWAY_TOKEN gateway auth token
#   OPENCLAW_MODEL         override model (default: openclaw, uses gateway default)
# ---------------------------------------------------------------------------

_GATEWAY_URL   = os.getenv("OPENCLAW_GATEWAY_URL",   "http://127.0.0.1:18789")
_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "cab520cf9a791d18bb18246f58e8dc8e89624944f3915e5c")
_OPENCLAW_MODEL = os.getenv("OPENCLAW_MODEL",        "openclaw")


class BaseAgent(ABC):
    """
    Base class for all ArchitectAI agents.

    Provides:
    - OpenClaw Gateway client (OpenAI-compat, proxied via OAuth)
    - Shared message logging via ProjectMemory
    - Standard call() interface
    - Structured response parsing helpers
    """

    # Override in subclass
    AGENT_ID: str = "base"
    DEFAULT_MODEL: str = "claude-sonnet-4-6"

    def __init__(self, memory: ProjectMemory, model: str = None):
        self.memory = memory
        self.model = model or os.getenv(f"{self.AGENT_ID.upper()}_MODEL", self.DEFAULT_MODEL)
        self.client = OpenAI(
            base_url=f"{_GATEWAY_URL}/v1",
            api_key=_GATEWAY_TOKEN,
        )
        logger.info(f"[{self.AGENT_ID}] Initialized → OpenClaw gateway ({_GATEWAY_URL}) model hint: {self.model}")

    def chat(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        """Send a chat request via OpenClaw gateway. Returns the text response."""
        logger.debug(f"[{self.AGENT_ID}] → gateway ({_OPENCLAW_MODEL}), {len(messages)} messages")

        # Prepend system message as OpenAI-style system role
        full_messages = [{"role": "system", "content": system}] + messages

        response = self.client.chat.completions.create(
            model=_OPENCLAW_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=full_messages,
            extra_headers={"x-openclaw-model": f"anthropic/{self.model}"},
        )
        content = response.choices[0].message.content

        # TOKEN-OPT: Log per-call token usage for cost visibility
        usage = getattr(response, "usage", None)
        if usage:
            in_tok  = getattr(usage, "prompt_tokens", 0)
            out_tok = getattr(usage, "completion_tokens", 0)
            logger.info(
                f"[{self.AGENT_ID}] ← {len(content)} chars | "
                f"tokens: {in_tok} in / {out_tok} out (model: {self.model})"
            )
        else:
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

        # Strip markdown code fences and try again
        stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped.strip())
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        # Find the first { and last } and try to parse
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError as e:
                logger.debug(f"[_extract_json] slice parse failed at pos {e.pos}: {repr(text[start:end+1][max(0,e.pos-30):e.pos+30])}")

        # Last resort: try to fix common issues (trailing commas, etc.)
        try:
            import ast
            # ast.literal_eval can handle some JSON-like structures
            candidate = text[text.find("{"):text.rfind("}")+1] if "{" in text else text
            return json.loads(candidate)
        except Exception:
            pass

        raise ValueError(f"Could not extract JSON from response (len={len(text)}): {repr(text[:300])}...")

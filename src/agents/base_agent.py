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

_GATEWAY_URL   = os.getenv("OLLAMA_URL",   "http://127.0.0.1:11434")
_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "dummy")
_OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "gemma")


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
    DEFAULT_MODEL = "gemini-3.1-pro"

    def __init__(self, memory: ProjectMemory, model: str = None):
        self.memory = memory
        self.model = model or os.getenv(f"{self.AGENT_ID.upper()}_MODEL", self.DEFAULT_MODEL)
        self.client = OpenAI(
            base_url=f"{_GATEWAY_URL}/v1",
            api_key=_GATEWAY_TOKEN or "dummy",
        )
        logger.info(f"[{self.AGENT_ID}] Initialized → Model pref: {self.model} (Ollama fallback: {_OLLAMA_MODEL})")

    def chat(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.2,
        response_format: dict = None,
    ) -> str:
        """Send a chat request. If model is Gemini or Claude, routes to them first, then falls back to Ollama."""
        
        if self.model.startswith("gemini"):
            try:
                gemini_key = os.getenv("GEMINI_API_KEY")
                
                # Map marketing names to actual API endpoints
                api_model_name = self.model
                if "3.1-pro" in self.model:
                    api_model_name = "gemini-3.1-pro-preview"
                elif "3-flash" in self.model:
                    api_model_name = "gemini-3-flash-preview"
                    
                if gemini_key and gemini_key != "dummy":
                    gemini_client = OpenAI(
                        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                        api_key=gemini_key,
                    )
                    logger.debug(f"[{self.AGENT_ID}] → Google Gemini API ({self.model})")
                    
                    full_messages = [{"role": "system", "content": system}] + messages
                    kwargs = {
                        "model": api_model_name,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "messages": full_messages,
                    }
                    if response_format:
                        kwargs["response_format"] = response_format
                        
                    response = gemini_client.chat.completions.create(**kwargs)
                    content = response.choices[0].message.content
                    
                    usage = getattr(response, "usage", None)
                    in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
                    out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
                    
                    # Rough cost tracking for Gemini 1.5 (varies by context length)
                    cost = (in_tok / 1_000_000) * 1.25 + (out_tok / 1_000_000) * 5.00
                    self.memory.log_cost(cost)
                    logger.info(f"[{self.AGENT_ID}] ← {len(content)} chars | tokens: {in_tok} in / {out_tok} out | cost: ${cost:.4f} (Gemini: {self.model})")
                    return content
                else:
                    logger.warning(f"[{self.AGENT_ID}] No valid GEMINI_API_KEY found, falling back to Ollama.")
            except Exception as e:
                logger.warning(f"[{self.AGENT_ID}] Gemini API failed: {e}. Falling back to Ollama.")
                
        # 1. Try OpenClaw if model is Claude
        if self.model.startswith("claude"):
            try:
                openclaw_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
                # Fallback to the known user hardcoded token if missing
                openclaw_token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "cab520cf9a791d18bb18246f58e8dc8e89624944f3915e5c")
                
                openclaw_client = OpenAI(
                    base_url=f"{openclaw_url}/v1",
                    api_key=openclaw_token,
                )
                logger.debug(f"[{self.AGENT_ID}] → OpenClaw API ({self.model})")
                
                full_messages = [{"role": "system", "content": system}] + messages
                
                response = openclaw_client.chat.completions.create(
                    model="openclaw",
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=full_messages,
                    extra_headers={"x-openclaw-model": f"anthropic/{self.model}"},
                )
                content = response.choices[0].message.content
                
                usage = getattr(response, "usage", None)
                in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
                out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
                
                cost = (in_tok / 1_000_000) * 15.0 + (out_tok / 1_000_000) * 75.0
                self.memory.log_cost(cost)
                logger.info(f"[{self.AGENT_ID}] ← {len(content)} chars | tokens: {in_tok} in / {out_tok} out | cost: ${cost:.4f} (OpenClaw: {self.model})")
                return content
            except Exception as e:
                logger.warning(f"[{self.AGENT_ID}] OpenClaw failed: {e}. Falling back to Ollama.")

        # 2. Ollama Request (Default or Fallback)
        logger.debug(f"[{self.AGENT_ID}] → Ollama ({_OLLAMA_MODEL}), {len(messages)} messages")

        # Prepend system message as OpenAI-style system role
        full_messages = [{"role": "system", "content": system}] + messages

        response = self.client.chat.completions.create(
            model=_OLLAMA_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=full_messages,
        )
        content = response.choices[0].message.content

        # TOKEN-OPT: Log per-call token usage for cost visibility
        usage = getattr(response, "usage", None)
        if usage:
            in_tok  = getattr(usage, "prompt_tokens", 0)
            out_tok = getattr(usage, "completion_tokens", 0)
            
            # Simple cost model per 1M tokens
            model_name = self.model.lower()
            if "opus" in model_name:
                cost = (in_tok / 1_000_000) * 15.0 + (out_tok / 1_000_000) * 75.0
            elif "sonnet" in model_name:
                cost = (in_tok / 1_000_000) * 3.0 + (out_tok / 1_000_000) * 15.0
            else:
                cost = (in_tok / 1_000_000) * 1.0 + (out_tok / 1_000_000) * 5.0
                
            self.memory.log_cost(cost)
            
            logger.info(
                f"[{self.AGENT_ID}] ← {len(content)} chars | "
                f"tokens: {in_tok} in / {out_tok} out | cost: ${cost:.4f} (model: {self.model})"
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

    def reflect(self, milestone: str, context: dict) -> str:
        """Have the agent reflect on the recent tasks and store learnings."""
        system_msg = "You are a professional architectural agent. Reflect on what went well and what could be improved in this recent milestone, given the context. Keep it short (2-3 sentences)."
        logger.info(f"[{self.AGENT_ID}] Reflecting on milestone {milestone}...")
        reflection = self.chat(system_msg, [{"role": "user", "content": str(context)}], max_tokens=150)
        self.memory.log_reflection(self.AGENT_ID, milestone, reflection)
        return reflection

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

        # Truncation repair: Gemini Flash often cuts output mid-stream.
        # Find last complete JSON value boundary then close open structures.
        def _repair_truncated(s: str) -> str:
            """Trim to last complete value/boundary, then close all open brackets in order."""
            import re as _re
            s = s.rstrip()
            # Find last complete JSON value using regex
            tail_re = _re.compile(r'(?:"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null|[}\]])(?=\s*(?:,|\n|]|}|$))')
            last_m = None
            for m in tail_re.finditer(s):
                last_m = m
            if last_m:
                s = s[:last_m.end()].rstrip()
            s = s.rstrip(',')
            # Walk the trimmed string to build the open-bracket stack (respecting strings)
            stack = []
            in_str = False
            esc = False
            for ch in s:
                if esc:
                    esc = False; continue
                if ch == '\\' and in_str:
                    esc = True; continue
                if ch == '"':
                    in_str = not in_str; continue
                if in_str:
                    continue
                if ch == '{':
                    stack.append('}')
                elif ch == '[':
                    stack.append(']')
                elif ch in ('}', ']') and stack:
                    stack.pop()
            # Close all open structures innermost-first
            if stack:
                s += ''.join(reversed(stack))
            return s

        start = text.find("{")
        if start == -1:
            start = text.find("[")
        if start != -1:
            try:
                repaired = _repair_truncated(text[start:])
                result = json.loads(repaired)
                logger.warning(f"[_extract_json] Repaired truncated JSON — response was cut mid-stream (repaired to {len(repaired)} chars)")
                return result
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not extract JSON from response (len={len(text)}): {repr(text[:300])}...")

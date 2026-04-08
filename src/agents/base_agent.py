import os
import json
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Optional

from loguru import logger
from openai import OpenAI
from dotenv import load_dotenv

from src.memory.project_memory import ProjectMemory

# Load environment variables (critical for standalone tests and scripts)
load_dotenv()

# ---------------------------------------------------------------------------
# Runtime: OpenClaw Gateway proxy (OpenAI-compatible endpoint)
#
# Config (env or .env):
#   OLLAMA_URL             default: http://127.0.0.1:11434
#   OLLAMA_MODEL           default: gemma
#   OPENCLAW_GATEWAY_URL   Anthropic proxy
#   OPENCLAW_GATEWAY_TOKEN gateway auth token
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
    DEFAULT_MODEL = "gemini-3.1-pro-preview"

    def __init__(self, memory: ProjectMemory, model: str = None):
        self.memory = memory
        self.model = model or os.getenv(f"{self.AGENT_ID.upper()}_MODEL", self.DEFAULT_MODEL)
        self.client = OpenAI(
            base_url=f"{_GATEWAY_URL}/v1",
            api_key=_GATEWAY_TOKEN or "dummy",
        )
        logger.info(f"[{self.AGENT_ID}] Initialized → Model pref: {self.model} (Ollama fallback: {_OLLAMA_MODEL})")

    def _chat_gemini_rest(
        self,
        model: str,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        """Call Gemini via direct REST API (bypass OpenAI-compat)."""
        import ssl
        import gzip
        
        key = os.getenv("GEMINI_API_KEY")
        # Ensure model has models/ prefix
        if not model.startswith("models/"):
            model = f"models/{model}"
            
        url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={key}"
        
        # Prepare payload
        payload = {
            "contents": [],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            }
        }

        # System instruction in its own field (v1beta)
        if system:
            payload["system_instruction"] = {
                "parts": [{"text": system}]
            }
            
        # Role alternation check
        for m in messages:
            role = "user" if m["role"] in ["user", "system"] else "model"
            parts = []
            
            # Handle multi-modal content list (OpenAI-style)
            content = m["content"]
            if isinstance(content, list):
                for part in content:
                    if part["type"] == "text":
                        parts.append({"text": part["text"]})
                    elif part["type"] == "image_url":
                        # data:image/png;base64,xxxx
                        url_data = part["image_url"]["url"]
                        if url_data.startswith("data:"):
                            header, data = url_data.split(",", 1)
                            mime = header.split(";")[0].split(":")[1]
                            parts.append({"inline_data": {"mime_type": mime, "data": data}})
            else:
                parts.append({"text": content})
            
            # Prevent consecutive same-role messages
            if payload["contents"] and payload["contents"][-1]["role"] == role:
                payload["contents"][-1]["parts"].extend(parts)
            else:
                payload["contents"].append({"role": role, "parts": parts})

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept-Encoding": "gzip"},
            method="POST"
        )
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                raw = resp.read()
                if resp.info().get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                    
                try:
                    data = json.loads(raw.decode("utf-8"))
                except UnicodeDecodeError as ue:
                    logger.error(f"Response not UTF-8. First 50 bytes: {raw[:50].hex()}")
                    raise ue
                except json.JSONDecodeError as je:
                    logger.error(f"JSON decode failed. First 50 bytes: {raw[:50]}")
                    raise je
                    
                if "candidates" not in data or not data["candidates"]:
                    raise Exception(f"Unexpected response: {data}")
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                
                # Simple usage tracking
                in_tok = len(str(payload)) // 4 # Rough approximation
                out_tok = len(content) // 4
                cost = (in_tok / 1_000_000) * 1.25 + (out_tok / 1_000_000) * 5.00
                self.memory.log_cost(cost)
                
                logger.info(f"[{self.AGENT_ID}] ← {len(content)} chars (Gemini REST: {model}) | cost ${cost:.4f}")
                return content
        except Exception as e:
            if hasattr(e, 'read'):
                err_data = e.read()
                logger.error(f"Gemini REST Error (code {getattr(e, 'code', '???')}): {err_data[:100]}")
            raise e

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
            # Map marketing names
            api_model_name = self.model
            if "3.1-pro" in self.model:
                api_model_name = "models/gemini-3.1-pro-preview"
            elif "flash-lite" in self.model:
                api_model_name = "models/gemini-3.1-flash-lite-preview"
            elif "3-flash" in self.model:
                api_model_name = "models/gemini-3-flash-preview"
            elif not api_model_name.startswith("models/"):
                api_model_name = f"models/{api_model_name}"
                
            if os.getenv("GEMINI_API_KEY") and os.getenv("GEMINI_API_KEY") != "dummy":
                # For Phase 4 verification, we DO NOT catch this exception to see it in logs
                return self._chat_gemini_rest(api_model_name, system, messages, max_tokens, temperature)
            else:
                logger.warning(f"[{self.AGENT_ID}] No valid GEMINI_API_KEY found, falling back to Ollama.")
                
        # 1. Try OpenClaw if model is Claude
        if self.model.startswith("claude"):
            try:
                openclaw_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
                openclaw_token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "dummy")
                
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

        full_messages = [{"role": "system", "content": system}] + messages

        response = self.client.chat.completions.create(
            model=_OLLAMA_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=full_messages,
        )
        content = response.choices[0].message.content

        usage = getattr(response, "usage", None)
        if usage:
            in_tok  = getattr(usage, "prompt_tokens", 0)
            out_tok = getattr(usage, "completion_tokens", 0)
            cost = (in_tok / 1_000_000) * 1.0 + (out_tok / 1_000_000) * 5.0
            self.memory.log_cost(cost)
            logger.info(f"[{self.AGENT_ID}] ← {len(content)} chars | tokens: {in_tok} in / {out_tok} out | cost: ${cost:.4f} (model: {self.model})")
        else:
            logger.debug(f"[{self.AGENT_ID}] ← {len(content)} chars")
        return content

    def send_message(self, to: str, msg_type: str, payload: dict, reply_to: str = None) -> str:
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
        """Execute the agent's main task."""
        ...

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from a response that may contain prose + JSON."""
        import json
        import re
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped.strip())
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Could not extract JSON from response (len={len(text)})")

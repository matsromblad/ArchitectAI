# ArchitectAI — Runtime Modes

## Overview

ArchitectAI supports two runtime modes for the AI agent layer:

---

## Mode A — Direct Anthropic API (future)

Agents call the Anthropic API directly from Python:
```python
client = anthropic.Anthropic(api_key=...)
client.messages.create(model="claude-sonnet-4-6", ...)
```

**Pros:**
- Fully self-contained Python app
- No dependency on OpenClaw at runtime
- Easy to dockerize and deploy anywhere
- Clear cost-per-run visibility

**Cons:**
- Requires separate Anthropic billing and API key management
- Needs credits and org configuration to be correct before any testing

**Status:** Deferred — Anthropic billing/auth setup is required. Code is ready in `src/agents/*.py`.

---

## Mode B — OpenClaw Orchestration (current default)

Agent work is delegated to OpenClaw subagents and sessions. The `OpenClawRuntime` adapter in `src/runtime/openclaw_runtime.py` provides the interface.

**Pros:**
- No separate Anthropic billing in the app layer
- Uses the same model access that is already working in the main session
- Allows rapid prototyping without auth/billing issues

**Cons:**
- Depends on OpenClaw being available
- Less portable as a standalone app
- Slightly more complex orchestration flow

**Status:** Current default for prototyping.

---

## What Stays Reusable Across Both Modes

The following components are mode-agnostic and require no changes when migrating:

| Component | Notes |
|-----------|-------|
| `src/memory/` | Project memory, versioned schemas, message log |
| `src/schemas/*.json` | JSON schema definitions |
| `src/orchestration/pipeline.py` | LangGraph state machine |
| `src/server/ws_server.py` | WebSocket dashboard server |
| `dashboard/` | Full pixel-art dashboard |
| `website/` | Marketing/intake site |

---

## Migration Plan: Mode B → Mode A

When Anthropic billing/auth is confirmed working:

1. Run smoke test: `python -c "import anthropic; ..."` confirms `messages.create` works
2. Set `RUNTIME_MODE=api` in `.env`
3. Agents automatically use direct API via `BaseAgent.chat()`
4. Remove `OpenClawRuntime` dependency from orchestration
5. Archive `src/runtime/openclaw_runtime.py`

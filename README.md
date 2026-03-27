# ⬛ ArchitectAI

**Multi-agent AI system that autonomously designs buildings from a natural language prompt and a site plan.**

> "Design a geriatric ward for Gävle Hospital on this site. Empty floor plan attached."
> → Complete IFC4 building model.

---

## What is it?

ArchitectAI is a pipeline of 10 specialized AI agents — each owning a domain of the building design process — coordinated by a Project Manager agent. The system produces a standards-compliant IFC4 model from a plain language brief and a site drawing.

**Agents:** PM · Input Parser · Brief · Compliance · Architect · Structural · MEP · Component Library · IFC Builder · QA

---

## Current Status

**Prototype — Phase 1 complete**

- ✅ Architecture designed + documented (COMPENDIUM.md)
- ✅ All 10 agents implemented in Python
- ✅ LangGraph orchestration pipeline
- ✅ JSON schema system (versioned, disk-persisted)
- ✅ Pixel-art live dashboard
- ✅ Marketing website + intake UI
- ⏳ End-to-end test pending (Anthropic API billing)
- ⏳ Live dashboard ↔ WebSocket connection
- ⏳ IFC output verification in BIM viewer

**Current runtime mode: OpenClaw orchestration (Mode B)**
See `docs/RUNTIME_MODES.md` for details.

---

## Links

- **Dashboard:** https://matsromblad.github.io/ArchitectAI/dashboard/
- **Website:** https://matsromblad.github.io/ArchitectAI/website/
- **Intake UI:** https://matsromblad.github.io/ArchitectAI/website/input.html
- **Compendium:** COMPENDIUM.md

---

## Quick Start (when Anthropic API is ready)

```bash
git clone https://github.com/matsromblad/ArchitectAI
cd ArchitectAI
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add ANTHROPIC_API_KEY
python main.py \
  --project-id my-project \
  --prompt "Design a geriatric ward..." \
  --site-file inputs/floorplan.png \
  --jurisdiction SE
```

---

## Project Structure

```
src/
  agents/       10 specialized agents
  memory/       Project memory + versioned schemas
  orchestration/ LangGraph pipeline
  server/       WebSocket server for live dashboard
  runtime/      OpenClaw runtime adapter (Mode B)
  schemas/      JSON schema definitions
dashboard/      Pixel-art live dashboard (HTML)
website/        Marketing site + intake UI (HTML)
docs/           Architecture docs
projects/       Per-project data (gitignored)
compliance_kb/  Regulatory document store (gitignored)
```

---

## Compendium

See [COMPENDIUM.md](COMPENDIUM.md) for full architecture documentation including agent roles, model assignments, memory design, and development roadmap.

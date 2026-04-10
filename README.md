# ⬛ ArchitectAI

**Multi-agent AI system that autonomously designs buildings from a natural language prompt and a site plan.**

> "Design a geriatric ward for Gävle Hospital on this site. Empty floor plan attached."
> → Complete IFC4 building model.

---

## What is it?

ArchitectAI is a pipeline of 11 specialized AI agents — each owning a domain of the building design process — coordinated by a Project Manager agent. The system produces a standards-compliant IFC4 model from a plain language brief and a site drawing.

**Agents:** PM · Input Parser · Client · Brief · Compliance · Architect · Structural · MEP · Component Library · IFC Builder · QA

The system is currently focused on **Swedish healthcare buildings** (geriatric wards, care centres, clinics), grounded in PTS (Program för Teknisk Standard) regulatory documents and BBR 2023 fire safety rules.

---

## Current Status

**Prototype — Phases 1–6 complete**

- ✅ All 11 agents implemented in Python (~7 300 lines)
- ✅ LangGraph orchestration pipeline with milestone gates (M1–M5)
- ✅ JSON schema system (versioned, disk-persisted)
- ✅ Pixel-art live dashboard (HTML5 Canvas + WebSocket)
- ✅ FastAPI WebSocket server with live file-watching
- ✅ PTS knowledge base integrated (6 regulatory documents)
- ✅ ChromaDB vector store + semantic RAG
- ✅ Brief Agent exports `rumsfunktionsprogram.md` at M1
- ✅ Swedish regulatory tools (fire, HVAC, lighting, dimensions, room types)
- ✅ Marketing website + intake UI
- ⏳ End-to-end run with a real brief (validation pending)
- ⏳ IFC output verification in BIM viewer

**Current runtime mode: OpenClaw orchestration (Mode B)**  
See [docs/RUNTIME_MODES.md](docs/RUNTIME_MODES.md) for details.

---

## Links

- **Website:** [https://matsromblad.github.io/ArchitectAI/website/](https://matsromblad.github.io/ArchitectAI/website/)
- **Compendium:** [COMPENDIUM.md](COMPENDIUM.md) — full architecture documentation
- **KB docs:** [docs/KB_INTEGRATION.md](docs/KB_INTEGRATION.md) — knowledge base + RAG design
- **Runtime modes:** [docs/RUNTIME_MODES.md](docs/RUNTIME_MODES.md) — OpenClaw vs direct API

---

## Quick Start

```bash
git clone https://github.com/matsromblad/ArchitectAI
cd ArchitectAI
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add OPENCLAW_GATEWAY_TOKEN or ANTHROPIC_API_KEY

# (Optional) Build the knowledge base from PDFs in docs/
python scripts/extract_pdf_kb.py
python scripts/vectorize_kb.py

# Run a design
python main.py \
  --project-id my-project \
  --prompt "Design a geriatric ward for Gävle Hospital, 20 single-bed rooms." \
  --site-file inputs/floorplan.png \
  --jurisdiction SE
```

**Live dashboard** (separate terminal):
```bash
python -m src.server.ws_server
# Open dashboard/index.html in a browser
```

---

## Project Structure

```
src/
  agents/        11 specialized agents (base_agent.py + 10 domain agents)
  memory/        Project memory, KB loader, ChromaDB vector store
  orchestration/ LangGraph pipeline (state machine, routing, milestones)
  server/        FastAPI + WebSocket server for live dashboard
  runtime/       OpenClaw runtime adapter (Mode B)
  tools/         Swedish regulatory lookups (fire, HVAC, lighting, dimensions, room types, IFC codes)
  schemas/       JSON schema definitions
scripts/
  extract_pdf_kb.py   Convert PTS PDFs → .txt knowledge base
  vectorize_kb.py     Populate ChromaDB index
  run_qa.py           Run QA agent as isolated subprocess
dashboard/       Pixel-art live dashboard (HTML5 Canvas + WebSocket)
website/         Marketing site + intake UI (HTML)
docs/            Architecture docs + source PDFs (PTS, BBR, Gävleborg fire guidelines)
projects/        Per-project data — state.json, versioned schemas, IFC output (gitignored)
compliance_kb/   Extracted regulatory texts + ChromaDB vector index (gitignored)
```

---

## Compendium

See [COMPENDIUM.md](COMPENDIUM.md) for full architecture documentation including agent roles, model assignments, memory design, and development roadmap.

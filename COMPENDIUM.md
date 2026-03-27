# ArchitectAI — Project Compendium
**Version:** 0.1 — Initial Draft  
**Date:** 2026-03-27  
**Author:** James (AI Assistant) & Mats Romblad  
**Status:** Living document — update as the project evolves

---

## 1. Vision

ArchitectAI is a multi-agent system that autonomously designs buildings from a natural language prompt and a site input file. Given a prompt such as:

> *"Design a geriatric ward for Gävle Hospital on this site. Empty floor plan attached."*

...the system produces a complete, standards-compliant IFC building model, with structured room programs, spatial layouts, technical systems, and quality-assured documentation.

The system is designed to be globally applicable — equally capable of producing a compliant building in Sweden or Dubai — by delegating all regulatory knowledge to a dedicated Compliance Agent.

---

## 2. Goals

### Primary Goal
Produce a complete, IFC-compliant building model from a natural language prompt + site input.

### Secondary Goals
- Enforce local building codes and regulations through a dedicated agent
- Support iterative design with feedback loops and QA gates
- Visualize the agent organization and work-in-progress in a real-time dashboard
- Scale from expert user (BIM/IT) to general user (anyone in a project team)

### Out of Scope (initially)
- Revit as a native output target (IFC is the output; Revit can consume IFC)
- Full drawing production (nice-to-have, deferred)
- Structural calculations (agent flags issues, does not compute)

---

## 3. Input

The system accepts multi-modal site inputs:

| Format | Handling |
|--------|----------|
| **DWG** | Parsed via ezdxf or ODA File Converter → geometry extraction |
| **PDF** | Parsed via pdfplumber/pymupdf → image or vector extraction |
| **PNG / JPG** | Vision model interpretation → spatial understanding |
| **IFC** | Native ifcopenshell parsing → existing context |

All inputs are processed by the **Input Parser Agent**, which normalizes them into a structured site data schema (JSON) before other agents act on it.

---

## 4. Output

- **IFC file** (IFC4) — complete building model
- **Room Program** — structured JSON/PDF listing all spaces, areas, and requirements
- **QA Report** — compliance checklist per discipline
- **Dashboard visualization** — live status of all agents and work items
- *(Future)* Drawing sheets — plans, sections, elevations as SVG/PDF via BlenderBIM/Bonsai

---

## 5. Agent Organization

The system is structured as a classic construction project organization. Each agent has a defined role, input, output, and communication protocol.

---

### 5.1 Project Manager Agent
**Role:** Orchestrator. Coordinates all agents, tracks milestones, triggers user approval gates, and resolves conflicts between disciplines.

**Responsibilities:**
- Maintain project state machine (milestones, current phase)
- Route tasks between agents
- Detect deadlocks or circular dependencies
- Request user input at milestone gates
- Log all decisions

**Inputs:** User prompt, site data, milestone status  
**Outputs:** Task assignments, status updates, user approval requests  
**Model:** High-capability reasoning model (e.g., Claude Sonnet / GPT-4o)

---

### 5.2 Input Parser Agent
**Role:** Translates raw site input (DWG/PDF/PNG/IFC) into a structured site data schema.

**Responsibilities:**
- Detect file type and select appropriate parsing strategy
- Extract boundary geometry, existing structures, orientation, scale
- Identify constraints (setbacks, max height, access points)
- Output normalized JSON site data

**Inputs:** Raw file (DWG, PDF, PNG, IFC)  
**Outputs:** `site_data.json` — boundary polygon, constraints, metadata  
**Model:** Vision-capable model for images; code execution for DWG/IFC  
**Libraries:** ezdxf, pdfplumber, ifcopenshell

---

### 5.3 Brief Agent
**Role:** Creates a detailed room program and functional brief from the user's prompt.

**Responsibilities:**
- Parse the natural language prompt
- Identify building type, department, and program requirements
- Generate a structured room list (room type, quantity, area, adjacency requirements)
- Flag ambiguities for user clarification

**Inputs:** User prompt, building type taxonomy  
**Outputs:** `room_program.json` — room list with areas, requirements, adjacency matrix  
**Model:** High-capability language model  
**Communicates with:** Compliance Agent (to validate area requirements)

---

### 5.4 Compliance Agent
**Role:** The regulatory expert. Owns all local building codes, standards, and regulations. All other agents consult this agent before finalizing decisions.

**Responsibilities:**
- Maintain a knowledge base of regulations (BBR, Eurocodes, local fire codes, healthcare standards, ADA/accessibility, etc.)
- Answer compliance queries from other agents ("Is a 2.2m corridor width sufficient for a geriatric ward in Sweden?")
- Validate proposed solutions against applicable codes
- Flag non-compliant proposals with specific rule references
- Adapt to jurisdiction (Sweden, UAE, UK, US, etc.) based on project location

**Inputs:** Compliance query + jurisdiction context  
**Outputs:** Compliance verdict (pass/fail/conditional) + rule reference + suggested fix  
**Model:** RAG-augmented language model with regulatory document library  
**Note:** This agent is the only one that holds jurisdiction-specific knowledge. All others are jurisdiction-agnostic.

---

### 5.5 Architect Agent
**Role:** Spatial design. Creates the floor plan layout — room placement, circulation, adjacencies, and spatial flow.

**Responsibilities:**
- Place rooms from the room program onto the site
- Optimize for adjacency requirements (e.g., dirty/clean flow separation in healthcare)
- Design circulation (corridors, stairs, lifts)
- Iterate based on feedback from QA Agent and Compliance Agent
- Produce a spatial layout schema

**Inputs:** `room_program.json`, `site_data.json`, compliance rules  
**Outputs:** `spatial_layout.json` — room positions, dimensions, circulation paths  
**Model:** Reasoning model with geometric reasoning capability  
**Communicates with:** Compliance Agent, QA Agent, Structural Agent

---

### 5.6 Structural Agent
**Role:** Structural logic. Reviews and proposes structural systems compatible with the architectural layout.

**Responsibilities:**
- Identify structural grid based on architectural layout
- Flag spans that are structurally problematic
- Propose column/wall/core placement
- Ensure structural continuity between floors

**Inputs:** `spatial_layout.json`  
**Outputs:** `structural_schema.json` — grid, load-bearing elements, core positions  
**Model:** Reasoning model  
**Communicates with:** Architect Agent (may require layout changes), QA Agent, Compliance Agent

---

### 5.7 MEP Agent (Mechanical, Electrical, Plumbing)
**Role:** Technical systems. Handles HVAC, electrical distribution, plumbing, and fire safety.

**Responsibilities:**
- Identify MEP zones based on layout and building type
- Place shafts, plant rooms, and main distribution routes
- Flag spatial conflicts with architecture/structure
- Ensure compliance with technical standards (ventilation rates, fire compartments, etc.)

**Inputs:** `spatial_layout.json`, `structural_schema.json`  
**Outputs:** `mep_schema.json` — shaft positions, plant rooms, distribution strategy  
**Model:** Reasoning model  
**Communicates with:** Compliance Agent, QA Agent, Architect Agent

---

### 5.8 IFC Builder Agent
**Role:** The constructor. Translates all approved schemas into a valid IFC4 building model.

**Responsibilities:**
- Consume spatial, structural, and MEP schemas
- Generate IFC entities: walls, slabs, columns, doors, windows, spaces, zones
- Maintain correct IFC relationships (IfcRelContainedInSpatialStructure, etc.)
- Produce a valid, openable IFC4 file

**Inputs:** Approved `spatial_layout.json`, `structural_schema.json`, `mep_schema.json`  
**Outputs:** `building.ifc`  
**Model:** Code execution agent  
**Libraries:** ifcopenshell, ifcopenshell-utils  
**Note:** This agent only runs after QA approval of all upstream schemas.

---

### 5.9 QA Agent
**Role:** Quality gatekeeper. Reviews all deliverables from all disciplines and approves or rejects them before they proceed.

**Responsibilities:**
- Check spatial layout for internal consistency (room areas, overlaps, circulation dead-ends)
- Verify structural schema doesn't conflict with architecture
- Verify MEP schema doesn't conflict with architecture or structure
- Verify IFC output is valid and complete
- Produce a QA report with pass/fail per checklist item
- Send rejected items back to the originating agent with specific feedback

**Inputs:** Any agent's output schema  
**Outputs:** QA verdict (approved / rejected + comments)  
**Model:** Reasoning model  
**Note:** The QA Agent is the only agent that can block progress. Its approvals are logged and visible in the dashboard.

---

## 6. Inter-Agent Communication

All agents communicate through a shared message bus. Messages are structured JSON:

```json
{
  "from": "architect_agent",
  "to": "compliance_agent",
  "type": "compliance_query",
  "payload": {
    "jurisdiction": "SE",
    "building_type": "healthcare",
    "query": "Minimum corridor width for geriatric ward",
    "proposed_value": 2200,
    "unit": "mm"
  }
}
```

The Project Manager Agent monitors all messages and maintains a project state log.

---

## 7. Milestones & User Approval Gates

The system pauses and requests user approval at the following milestones:

| # | Milestone | What user reviews |
|---|-----------|-------------------|
| **M1** | Brief confirmed | Room program, area schedule, adjacency requirements |
| **M2** | Concept layout approved | Floor plan sketch, circulation strategy, key dimensions |
| **M3** | Technical systems approved | Structural grid, MEP strategy, shaft positions |
| **M4** | Full building model approved | Complete multi-floor layout, all disciplines coordinated |
| **M5** | Final IFC export | Validated IFC file, QA report |

The user can approve, request modifications, or reject and restart a milestone. All decisions are logged.

---

## 8. Feedback Loops

The system has two types of feedback loops:

**Internal (automatic):**
- QA Agent rejects → originating agent revises → resubmits to QA
- Max 3 automatic iterations before escalating to user

**External (user-triggered):**
- At any milestone, user can add comments or modify requirements
- Project Manager translates user input into updated task assignments

---

## 9. Technical Stack

| Component | Technology |
|-----------|------------|
| Agent framework | Python — LangGraph or custom orchestrator |
| IFC generation | ifcopenshell + ifcopenshell-utils |
| DWG parsing | ezdxf |
| PDF parsing | pdfplumber / pymupdf |
| Image understanding | Vision-capable LLM (Claude / GPT-4o) |
| Compliance knowledge | RAG over regulatory documents (LlamaIndex / Chroma) |
| Dashboard | Web app — React + canvas (pixelart animation) |
| Message bus | Redis pub/sub or simple in-process queue (MVP) |
| Storage | Local filesystem → future: object storage |

---

## 10. Dashboard

The dashboard visualizes the live state of all agents as pixel-art characters moving between workstations.

**Visual language:**
- Each discipline has a color theme (e.g., Architect = blue, Structure = grey, MEP = orange, QA = red, PM = gold)
- Agents are represented as small pixel-art figures
- Workstations: Design Table, Compliance Check, QA Review, IFC Build, User Approval
- Agents animate between stations based on their current task
- QA Review station shows a queue — if agents pile up, it's visually obvious

**Information displayed:**
- Current phase / active milestone
- Each agent's status (working / waiting / blocked / approved)
- QA queue and recent verdicts
- Milestone progress bar
- Last user interaction timestamp

---

## 11. Development Roadmap

### Phase 1 — Foundation
- [ ] Define data schemas (site_data, room_program, spatial_layout, structural_schema, mep_schema)
- [ ] Implement Input Parser Agent (PNG first, then PDF, then DWG)
- [ ] Implement Brief Agent
- [ ] Implement basic Compliance Agent with Swedish healthcare rules
- [ ] Build message bus and Project Manager orchestration

### Phase 2 — Design Loop
- [ ] Implement Architect Agent (simple room placement)
- [ ] Implement QA Agent (basic validation rules)
- [ ] Connect feedback loop between Architect ↔ QA
- [ ] Reach Milestone M2 with a single-floor healthcare layout

### Phase 3 — Technical Systems
- [ ] Implement Structural Agent
- [ ] Implement MEP Agent
- [ ] Full three-discipline coordination
- [ ] Reach Milestone M3

### Phase 4 — IFC Output
- [ ] Implement IFC Builder Agent
- [ ] Generate valid IFC4 from approved schemas
- [ ] Verify in BlenderBIM/Bonsai
- [ ] Reach Milestone M5

### Phase 5 — Dashboard
- [ ] Build pixel-art dashboard UI
- [ ] Connect to live agent state
- [ ] Deploy as local web app

### Phase 6 — Multi-floor & Full Building
- [ ] Extend spatial model to multiple floors
- [ ] Vertical coordination (structure, MEP shafts)
- [ ] Full building IFC output

### Phase 7 — Hardening & UX
- [ ] Add more jurisdictions to Compliance Agent
- [ ] Improve input parsing (more formats, better accuracy)
- [ ] User-facing interface for non-expert users
- [ ] Drawing export (nice-to-have)

---

## 12. Open Questions

- What is the primary development environment? (local Python, cloud, Docker?)
- What LLM provider(s) are preferred? (Anthropic, OpenAI, local models?)
- Should the dashboard be a standalone app or embedded in the agent system?
- How are regulatory documents sourced and kept up to date?

---

*This document is the single source of truth for the ArchitectAI project. Update it when decisions change.*

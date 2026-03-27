# ArchitectAI — Project Compendium
**Version:** 0.2 — Architecture Decisions  
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
**Model:** `claude-opus-4-5` — Opus for complex reasoning, conflict resolution, and orchestration decisions. PM errors propagate to all agents, so highest capability is warranted.

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
**Model:** `claude-sonnet-4-5` with vision capability for images; code execution for DWG/IFC  
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
**Model:** `claude-sonnet-4-5` — well-defined extraction task from structured prompt  
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
**Model:** `claude-sonnet-4-5` with RAG over regulatory documents — upgrade to Opus if complex legal interpretation is required (e.g., conflicting local ordinances)  

**Knowledge acquisition strategy:**
1. **Self-sourcing first:** Agent uses web search to find and download applicable regulations for the given jurisdiction + building type combination. It caches PDFs locally and indexes them into ChromaDB.
2. **Ask PM if stuck:** If the agent cannot find a required document (paywalled, unavailable, jurisdiction unknown), it sends an `escalation` message to PM with a specific request: *"Need: Socialstyrelsen SOSFS 2013:7 — URL or PDF"*. PM decides whether to ask the user or provide an alternative source.
3. **No hallucination policy:** If a rule cannot be sourced and verified, the agent must report `unknown` — never invent a regulation.

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
**Model:** `claude-sonnet-4-5` — well-scoped spatial reasoning task with structured input/output  
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
**Model:** `claude-sonnet-4-5`  
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
**Model:** `claude-sonnet-4-5`  
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
**Model:** `claude-sonnet-4-5` — primarily code generation; consider `claude-haiku-4-5` for cost if tasks are repetitive and well-templated  
**Libraries:** ifcopenshell, ifcopenshell-utils  
**Note:** This agent only runs after QA approval of all upstream schemas.

---

### 5.9 Component Library Agent
**Role:** Owns the library of parametric room templates and building element definitions. The IFC equivalent of Revit families.

**Responsibilities:**
- Maintain a library of room templates per building type (healthcare, education, office, etc.)
- Each template defines: geometry parameters, required MEP connections, accessibility requirements, standard furnishing zones
- Serve templates to the Architect Agent (room placement) and IFC Builder (geometry generation)
- Grow the library over time — templates are created/refined per project and reused across projects
- Flag when a requested room type has no existing template (triggers template creation)

**Example templates:**
- `healthcare.geriatric_patient_room` — 12 m², bed zone, hygiene unit, nurse call point, window required
- `healthcare.isolation_room` — 16 m² + 4 m² airlock, negative pressure zone, sealed surfaces
- `healthcare.nurse_station` — L-shape, min 8 m², direct sightline to corridor
- `healthcare.clean_utility` — 6 m², shelving, sink, adjacency to dirty utility

**Inputs:** Room type request (building_type + room_name + jurisdiction)
**Outputs:** `component_template.json` — geometry params, MEP hookups, compliance refs, adjacency rules
**Model:** No LLM needed for lookup — template retrieval is deterministic. LLM only invoked to *generate* a new template when one doesn't exist.
**Storage:** `/component_library/<building_type>/<room_type>.json` — shared across all projects
**Note:** This is the IFC-native equivalent of Revit families. No separate family files needed — geometry is described parametrically in JSON and realized by the IFC Builder.

---

### 5.10 QA Agent
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
**Model:** `claude-sonnet-4-5` — upgrade to Opus if QA decisions involve complex multi-discipline trade-offs  
**Note:** The QA Agent is the only agent that can block progress. Its approvals are logged and visible in the dashboard.

---

## 6. Inter-Agent Communication

**Decision: LangGraph state machine with structured JSON messages.**

LangGraph is chosen over a raw message bus (Redis/Celery) for the MVP because:
- Built-in state persistence and checkpoint/resume capability
- Native support for conditional routing (QA approve → next agent, QA reject → back to originator)
- Integrates directly with Anthropic Claude via LangChain
- Easier to debug and visualize than a raw pub/sub system
- Can be upgraded to distributed (Redis) later without changing agent logic

### Message Schema

All inter-agent messages follow this envelope:

```json
{
  "msg_id": "uuid-v4",
  "timestamp": "2026-03-27T08:00:00Z",
  "from": "architect_agent",
  "to": "compliance_agent",
  "type": "compliance_query | task_assignment | qa_submission | qa_verdict | escalation | user_approval_request",
  "project_id": "gävle-geriatric-001",
  "payload": { ... },
  "reply_to": "uuid-of-original-msg-or-null"
}
```

### Message Types

| Type | Sender | Receiver | Description |
|------|--------|----------|-------------|
| `task_assignment` | PM | Any agent | PM assigns work to an agent |
| `compliance_query` | Any | Compliance | Ask about a regulation |
| `compliance_response` | Compliance | Any | Verdict + rule reference |
| `qa_submission` | Any | QA | Submit work for review |
| `qa_verdict` | QA | PM + originator | Approved or rejected with comments |
| `escalation` | Any | PM | Agent can't proceed, needs PM decision |
| `user_approval_request` | PM | Dashboard | PM requests user input at milestone |
| `user_approval_response` | Dashboard | PM | User approves/rejects/modifies |

### Routing Rules (LangGraph nodes)

```
START → PM (kickoff)
PM → Input Parser → Brief Agent
Brief Agent ↔ Compliance Agent (query loop)
Brief Agent → QA Agent
QA Agent → [APPROVED: PM] | [REJECTED: originating agent]
PM → [milestone gate] → Dashboard (user approval)
Dashboard → PM (user decision) → next phase
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
| Agent framework | Python + **LangGraph** (state machine, checkpointing) |
| LLM provider | **Anthropic** (Claude API, local API key) |
| IFC generation | ifcopenshell + ifcopenshell-utils |
| DWG parsing | ezdxf |
| PDF parsing | pdfplumber / pymupdf |
| Image understanding | claude-sonnet-4-5 (vision) |
| Compliance knowledge | Web search + RAG over downloaded regulatory PDFs (LlamaIndex + ChromaDB) |
| Message bus | LangGraph state (MVP) → Redis pub/sub (scale-out) |
| Dashboard | Standalone HTML + Canvas + WebSocket for live state |
| Storage | Local filesystem (`/project/<id>/`) — structured by phase |
| User interaction | Dashboard (browser) — milestone gates, approval buttons |
| Notifications | Future: Telegram/OpenClaw push notifications |
| Dev environment | **Stationär dator** (development), **RPi5** (deployment/serving) |

### Model Assignment Summary

| Agent | Model | Rationale |
|-------|-------|-----------|
| Project Manager | `claude-opus-4-5` | Complex orchestration, conflict resolution, escalation decisions |
| Input Parser | `claude-sonnet-4-5` | Vision + structured extraction |
| Brief Agent | `claude-sonnet-4-5` | Prompt-to-JSON extraction |
| Compliance Agent | `claude-sonnet-4-5` *(→ Opus if needed)* | RAG-augmented rule lookup; upgrade for complex legal interpretation |
| Architect Agent | `claude-sonnet-4-5` | Spatial reasoning with structured I/O |
| Structural Agent | `claude-sonnet-4-5` | Structural logic, well-scoped task |
| MEP Agent | `claude-sonnet-4-5` | Technical system routing |
| Component Library | none (deterministic) *(→ Sonnet for new templates)* | Template lookup is code; LLM only for generating new templates |
| IFC Builder | `claude-sonnet-4-5` *(→ Haiku if templated)* | Code generation; downgrade possible for repetitive tasks |
| QA Agent | `claude-sonnet-4-5` *(→ Opus if needed)* | Checklist validation; upgrade for complex multi-discipline trade-offs |

---

## 10. Memory Architecture

Each project has a structured memory hierarchy. Memory is scoped to a project ID and persists on disk.

### Three Levels of Memory

**1. Working Memory (LangGraph state)**
- Lives in LangGraph checkpoint — the active state machine snapshot
- Contains: current phase, last messages per agent, pending tasks, QA queue
- Persists across restarts (SQLite checkpoint store)
- Scope: single project session

**2. Project Memory (structured files)**
Stored in `/projects/<project_id>/`:
```
/projects/gävle-geriatric-001/
  ├── state.json              ← project phase, milestone, decisions log
  ├── inputs/
  │   └── floorplan.png
  ├── schemas/
  │   ├── site_data.json
  │   ├── room_program.json    ← versioned (v1, v2...)
  │   ├── spatial_layout.json
  │   ├── structural_schema.json
  │   └── mep_schema.json
  ├── outputs/
  │   ├── building.ifc
  │   └── qa_reports/
  │       ├── qa_m1.json
  │       └── ...
  └── messages/
      └── message_log.jsonl   ← full audit trail of all agent messages
```
- All schema files are **versioned** (v1, v2...) — old versions never deleted
- `state.json` tracks which version of each file is the current approved version
- Dashboard reads from this directory for the Outputs tab

**3. Compliance Knowledge Base (vector store)**
Stored in `/compliance_kb/<jurisdiction>/`:
```
/compliance_kb/
  ├── SE/
  │   ├── BBR_2023.pdf
  │   ├── SOSFS_2013-7.pdf
  │   └── chroma/             ← ChromaDB vector index
  └── AE/
      └── ...
```
- Shared across projects (jurisdiction-scoped, not project-scoped)
- Compliance Agent self-populates by downloading + indexing documents
- ChromaDB persists embeddings — only re-indexed when source docs change

### Memory & Dashboard Integration
- Dashboard reads `state.json` + `schemas/` for the Outputs tab (live file status)
- A lightweight Python WebSocket server (`server.py`) watches the project directory and pushes updates to the dashboard in real time
- No database required for MVP — filesystem is the source of truth

---

## 11. Dashboard

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

## 13. Deployment

| Role | Machine | Why |
|------|---------|-----|
| Development | Stationär Windows/Linux-dator | Fast iteration, VS Code, heavy parsing |
| Production server | RPi5 | Always-on, serves dashboard + runs agents via API calls |
| LLM compute | Anthropic cloud (API) | Opus/Sonnet — no local GPU needed |
| Vector store | Local disk (RPi5 or dev machine) | ChromaDB is lightweight, no cloud needed |

**RPi5 note:** The RPi5 does not run models locally — it only orchestrates API calls. This makes it perfectly capable as a deployment target. CPU-heavy tasks (DWG parsing, IFC generation) may be slow but are not blocking.

---

## 14. Open Questions — RESOLVED

| Question | Decision |
|----------|----------|
| LLM provider | Anthropic (local API key) |
| Agent communication | LangGraph state machine + structured JSON messages |
| Dashboard interaction | Browser-based, WebSocket for live updates |
| Regulatory documents | Self-sourced by Compliance Agent; escalates to PM if unavailable |
| Deployment | Dev on workstation, serve on RPi5 |
| Notifications | Future: Telegram/OpenClaw push (post-MVP) |
| Dashboard type | Standalone HTML + lightweight Python WebSocket server |

---

*This document is the single source of truth for the ArchitectAI project. Update it when decisions change.*

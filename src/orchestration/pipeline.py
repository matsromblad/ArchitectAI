"""
LangGraph Pipeline — orchestrates the full M1 build loop for ArchitectAI.

State machine:
  parse_input → generate_brief → fetch_components → compliance_check
    → architect → structural → mep → ifc_build → qa → pm_decision
    ↺ (rejection loops back to originating node, up to 3 times)
    → user_approval (on escalation)
"""

import os
from typing import Annotated, Any, Optional, TypedDict

from loguru import logger

try:
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import MemorySaver
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False
    logger.warning(
        "[pipeline] langgraph not installed — "
        "run: pip install langgraph  to enable the pipeline."
    )

from src.memory.project_memory import ProjectMemory
from src.agents.input_parser import InputParserAgent
from src.agents.brief_agent import BriefAgent
from src.agents.compliance_agent import ComplianceAgent
from src.agents.qa_agent import QAAgent
from src.agents.architect_agent import ArchitectAgent
from src.agents.structural_agent import StructuralAgent
from src.agents.mep_agent import MEPAgent
from src.agents.component_library_agent import ComponentLibraryAgent
from src.agents.ifc_builder_agent import IFCBuilderAgent

try:
    from src.agents.pm_agent import PMAgent
    _PM_AVAILABLE = True
except ImportError:
    _PM_AVAILABLE = False
    logger.warning("[pipeline] PMAgent not found — pm_decision_node will be limited")


# --------------------------------------------------------------------------- #
# State schema                                                                  #
# --------------------------------------------------------------------------- #

class PipelineState(TypedDict, total=False):
    """Full state carried through the LangGraph pipeline."""

    # Identity
    project_id: str
    phase: str
    user_prompt: str
    jurisdiction: str

    # Data produced by agents
    site_data: dict
    room_program: dict
    component_templates: dict
    spatial_layout: dict
    structural_schema: dict
    mep_schema: dict

    # QA tracking
    qa_results: dict          # schema_type → {"verdict": str, "version": str}
    rejection_counts: dict    # schema_type → int

    # Human-in-the-loop
    awaiting_user_approval: bool
    user_approval_response: Optional[str]

    # Misc
    messages: list            # recent agent messages (last ~20)
    error: Optional[str]

    # Internal routing
    _last_schema: str         # which schema just went through QA
    _qa_target_node: str      # node to re-run on rejection


# --------------------------------------------------------------------------- #
# Node implementations                                                          #
# --------------------------------------------------------------------------- #

def _memory(state: PipelineState) -> ProjectMemory:
    base_dir = os.getenv("PROJECTS_DIR", "./projects")
    return ProjectMemory(state["project_id"], base_dir=base_dir)


def parse_input_node(state: PipelineState) -> dict:
    """Run InputParserAgent to extract site_data from the user prompt / file."""
    logger.info("[pipeline] Node: parse_input")
    mem = _memory(state)
    agent = InputParserAgent(memory=mem)

    # Accept either a file path or a plain text prompt
    prompt = state.get("user_prompt", "")
    site_file = None
    if os.path.isfile(prompt):
        site_file = prompt

    try:
        site_data = agent.run({"file_path": site_file, "prompt": prompt})
        mem.update_phase("brief")
        return {
            "site_data": site_data,
            "phase": "brief",
            "messages": _tail_messages(mem),
        }
    except Exception as exc:
        logger.error(f"[pipeline] parse_input failed: {exc}")
        return {"error": str(exc), "phase": "error"}


def generate_brief_node(state: PipelineState) -> dict:
    """Run BriefAgent to generate the room program."""
    logger.info("[pipeline] Node: generate_brief")
    mem = _memory(state)
    agent = BriefAgent(memory=mem)

    # TOKEN-OPT: Pass QA feedback (if any) so BriefAgent can use compact delta-prompt.
    qa_results = state.get("qa_results") or {}
    last_qa = qa_results.get("room_program", {})
    qa_feedback = None
    if last_qa.get("verdict") in ("REJECTED", "CONDITIONAL"):
        qa_feedback = {
            "issues": last_qa.get("issues", []),
            "fix_instructions": last_qa.get("fix_instructions", ""),
        }

    try:
        room_program = agent.run({
            "prompt": state.get("user_prompt", ""),
            "site_data": state.get("site_data", {}),
            "jurisdiction": state.get("jurisdiction", "SE"),
            "qa_feedback": qa_feedback,  # TOKEN-OPT: structured feedback for delta-prompt
        })
        mem.update_phase("components")
        return {
            "room_program": room_program,
            "phase": "components",
            "_last_schema": "room_program",
            "_qa_target_node": "generate_brief",
            "messages": _tail_messages(mem),
        }
    except Exception as exc:
        logger.error(f"[pipeline] generate_brief failed: {exc}")
        return {"error": str(exc), "phase": "error"}


def fetch_components_node(state: PipelineState) -> dict:
    """Run ComponentLibraryAgent to fetch/generate room templates."""
    logger.info("[pipeline] Node: fetch_components")
    mem = _memory(state)
    agent = ComponentLibraryAgent(memory=mem)

    try:
        templates = agent.run({
            "room_program": state.get("room_program", {}),
            "jurisdiction": state.get("jurisdiction", "SE"),
        })
        mem.update_phase("compliance_check")
        return {
            "component_templates": templates,
            "phase": "compliance_check",
            "messages": _tail_messages(mem),
        }
    except Exception as exc:
        logger.error(f"[pipeline] fetch_components failed: {exc}")
        return {"error": str(exc), "phase": "error"}


def compliance_check_node(state: PipelineState) -> dict:
    """Run ComplianceAgent to validate the room program."""
    logger.info("[pipeline] Node: compliance_check")
    mem = _memory(state)
    agent = ComplianceAgent(memory=mem)

    try:
        result = agent.run({
            "room_program": state.get("room_program", {}),
            "jurisdiction": state.get("jurisdiction", "SE"),
        })
        mem.update_phase("architect")
        return {
            "phase": "architect",
            "messages": _tail_messages(mem),
        }
    except Exception as exc:
        logger.error(f"[pipeline] compliance_check failed: {exc}")
        return {"error": str(exc), "phase": "error"}


def architect_node(state: PipelineState) -> dict:
    """Run ArchitectAgent to create the spatial layout."""
    logger.info("[pipeline] Node: architect")
    mem = _memory(state)
    agent = ArchitectAgent(memory=mem)

    try:
        spatial_layout = agent.run({
            "room_program": state.get("room_program", {}),
            "site_data": state.get("site_data", {}),
            "component_templates": state.get("component_templates", {}),
        })
        mem.update_phase("qa_spatial_layout")
        return {
            "spatial_layout": spatial_layout,
            "phase": "qa_spatial_layout",
            "_last_schema": "spatial_layout",
            "_qa_target_node": "architect",
            "messages": _tail_messages(mem),
        }
    except Exception as exc:
        logger.error(f"[pipeline] architect failed: {exc}")
        return {"error": str(exc), "phase": "error"}


def structural_node(state: PipelineState) -> dict:
    """Run StructuralAgent to propose the structural grid."""
    logger.info("[pipeline] Node: structural")
    mem = _memory(state)
    agent = StructuralAgent(memory=mem)

    try:
        structural_schema = agent.run({
            "spatial_layout": state.get("spatial_layout", {}),
        })
        mem.update_phase("qa_structural_schema")
        return {
            "structural_schema": structural_schema,
            "phase": "qa_structural_schema",
            "_last_schema": "structural_schema",
            "_qa_target_node": "structural",
            "messages": _tail_messages(mem),
        }
    except Exception as exc:
        logger.error(f"[pipeline] structural failed: {exc}")
        return {"error": str(exc), "phase": "error"}


def mep_node(state: PipelineState) -> dict:
    """Run MEPAgent to generate the MEP schema."""
    logger.info("[pipeline] Node: mep")
    mem = _memory(state)
    agent = MEPAgent(memory=mem)

    try:
        mep_schema = agent.run({
            "spatial_layout": state.get("spatial_layout", {}),
            "structural_schema": state.get("structural_schema", {}),
        })
        mem.update_phase("qa_mep_schema")
        return {
            "mep_schema": mep_schema,
            "phase": "qa_mep_schema",
            "_last_schema": "mep_schema",
            "_qa_target_node": "mep",
            "messages": _tail_messages(mem),
        }
    except Exception as exc:
        logger.error(f"[pipeline] mep failed: {exc}")
        return {"error": str(exc), "phase": "error"}


def ifc_build_node(state: PipelineState) -> dict:
    """Run IFCBuilderAgent to generate the IFC4 file."""
    logger.info("[pipeline] Node: ifc_build")
    mem = _memory(state)
    agent = IFCBuilderAgent(memory=mem)

    project_id = state["project_id"]
    projects_dir = os.getenv("PROJECTS_DIR", "./projects")
    output_path = os.path.join(projects_dir, project_id, "outputs", "model_M1.ifc")

    try:
        result = agent.run({
            "spatial_layout": state.get("spatial_layout", {}),
            "structural_schema": state.get("structural_schema", {}),
            "mep_schema": state.get("mep_schema", {}),
            "component_templates": state.get("component_templates", {}),
            "output_path": output_path,
        })
        mem.update_phase("complete")
        mem.approve_milestone("M1", notes=f"IFC saved: {result['ifc_path']}")
        return {
            "phase": "complete",
            "messages": _tail_messages(mem),
        }
    except Exception as exc:
        logger.error(f"[pipeline] ifc_build failed: {exc}")
        return {"error": str(exc), "phase": "error"}


def qa_node(state: PipelineState) -> dict:
    """Run QAAgent on the most recently produced schema."""
    schema_type = state.get("_last_schema", "unknown")
    logger.info(f"[pipeline] Node: qa ({schema_type})")
    mem = _memory(state)
    agent = QAAgent(memory=mem)

    # Determine the schema data
    schema_map = {
        "room_program": state.get("room_program", {}),
        "spatial_layout": state.get("spatial_layout", {}),
        "structural_schema": state.get("structural_schema", {}),
        "mep_schema": state.get("mep_schema", {}),
    }
    schema_data = schema_map.get(schema_type, {})
    version = schema_data.get("_version", "v1")
    rejection_counts = dict(state.get("rejection_counts") or {})
    prior_rejections = rejection_counts.get(schema_type, 0)

    try:
        verdict = agent.run({
            "schema_type": schema_type,
            "schema_data": schema_data,
            "version": version,
            "prior_rejections": prior_rejections,
            "context": {
                k: v for k, v in schema_map.items()
                if k != schema_type and v
            },
        })

        qa_results = dict(state.get("qa_results") or {})
        qa_results[schema_type] = {
            "verdict": verdict["verdict"],
            "version": version,
            "issues": verdict.get("issues", []),
        }

        if verdict["verdict"] != "APPROVED":
            rejection_counts[schema_type] = prior_rejections + 1

        return {
            "qa_results": qa_results,
            "rejection_counts": rejection_counts,
            "messages": _tail_messages(mem),
        }
    except Exception as exc:
        logger.error(f"[pipeline] qa failed: {exc}")
        return {"error": str(exc), "phase": "error"}


def pm_decision_node(state: PipelineState) -> dict:
    """PM decides next action after repeated rejections or escalations."""
    logger.info("[pipeline] Node: pm_decision")
    mem = _memory(state)

    if not _PM_AVAILABLE:
        logger.warning("[pipeline] PMAgent unavailable — defaulting to user_approval")
        return {"awaiting_user_approval": True, "phase": "awaiting_approval"}

    agent = PMAgent(memory=mem)  # type: ignore[name-defined]
    schema_type = state.get("_last_schema", "unknown")
    rejection_counts = state.get("rejection_counts") or {}

    try:
        decision = agent.run({
            "event": "qa_verdict",
            "schema_type": schema_type,
            "rejection_count": rejection_counts.get(schema_type, 0),
            "qa_results": state.get("qa_results", {}),
            "phase": state.get("phase"),
        })

        action = decision.get("action", "escalate")
        if action == "escalate":
            return {"awaiting_user_approval": True, "phase": "awaiting_approval"}
        else:
            # PM assigns a target node — store in state for routing
            return {
                "phase": decision.get("next_phase", state.get("phase")),
                "_qa_target_node": decision.get("target_node", state.get("_qa_target_node")),
                "messages": _tail_messages(mem),
            }
    except Exception as exc:
        logger.error(f"[pipeline] pm_decision failed: {exc}")
        return {"awaiting_user_approval": True, "phase": "awaiting_approval"}


def user_approval_node(state: PipelineState) -> dict:
    """
    Pause for human review. Sets awaiting_user_approval=True.
    The LangGraph interrupt mechanism (or external trigger) resumes the graph
    once user_approval_response is set.
    """
    logger.info("[pipeline] Node: user_approval — WAITING for human response")
    mem = _memory(state)
    mem.update_phase("awaiting_approval")

    approval_response = state.get("user_approval_response")
    if approval_response:
        logger.info(f"[pipeline] User responded: {approval_response[:80]}")
        return {
            "awaiting_user_approval": False,
            "phase": "pm_review",
            "messages": _tail_messages(mem),
        }

    return {
        "awaiting_user_approval": True,
        "phase": "awaiting_approval",
    }


# --------------------------------------------------------------------------- #
# Routing functions                                                             #
# --------------------------------------------------------------------------- #

def _route_after_qa(state: PipelineState) -> str:
    """Decide where to go after QA."""
    schema_type = state.get("_last_schema", "unknown")
    qa_results = state.get("qa_results") or {}
    rejection_counts = state.get("rejection_counts") or {}

    result = qa_results.get(schema_type, {})
    verdict = result.get("verdict", "REJECTED")
    rejections = rejection_counts.get(schema_type, 0)

    if verdict == "APPROVED":
        # Advance to the next phase
        phase = state.get("phase", "")
        logger.info(f"[pipeline] QA APPROVED {schema_type} → routing to next phase ({phase})")
        return _next_node_after_approval(schema_type)
    elif rejections >= QAAgent.MAX_REJECTIONS:
        logger.warning(f"[pipeline] {schema_type} hit max rejections ({rejections}) → pm_decision")
        return "pm_decision"
    else:
        target = state.get("_qa_target_node", "architect")
        # TOKEN-OPT: Log iteration depth so we can spot runaway loops in production
        logger.info(f"[pipeline] QA REJECTED {schema_type} (attempt {rejections}/{QAAgent.MAX_REJECTIONS}) → {target}")
        return target


def _next_node_after_approval(schema_type: str) -> str:
    """Map a just-approved schema to the next pipeline node."""
    return {
        "room_program": "fetch_components",
        "spatial_layout": "structural",
        "structural_schema": "mep",
        "mep_schema": "ifc_build",
    }.get(schema_type, END)


def _route_after_pm(state: PipelineState) -> str:
    """After pm_decision, go to user_approval or the target node."""
    if state.get("awaiting_user_approval"):
        return "user_approval"
    return state.get("_qa_target_node", "architect")


def _route_after_user_approval(state: PipelineState) -> str:
    """After user responds, go back to pm_decision for re-routing."""
    if state.get("awaiting_user_approval"):
        return "user_approval"  # Still waiting
    return "pm_decision"


# --------------------------------------------------------------------------- #
# Graph assembly                                                                #
# --------------------------------------------------------------------------- #

def build_pipeline() -> Any:
    """
    Assemble and compile the LangGraph state machine.

    Returns:
        Compiled LangGraph app with MemorySaver checkpointer.

    Raises:
        ImportError: if langgraph is not installed.
    """
    if not _LANGGRAPH_AVAILABLE:
        raise ImportError(
            "langgraph is required. Install with: pip install langgraph"
        )

    graph = StateGraph(PipelineState)

    # Register nodes
    graph.add_node("parse_input", parse_input_node)
    graph.add_node("generate_brief", generate_brief_node)
    graph.add_node("fetch_components", fetch_components_node)
    graph.add_node("compliance_check", compliance_check_node)
    graph.add_node("architect", architect_node)
    graph.add_node("structural", structural_node)
    graph.add_node("mep", mep_node)
    graph.add_node("ifc_build", ifc_build_node)
    graph.add_node("qa", qa_node)
    graph.add_node("pm_decision", pm_decision_node)
    graph.add_node("user_approval", user_approval_node)

    # Entry point
    graph.set_entry_point("parse_input")

    # Linear edges (no branching)
    graph.add_edge("parse_input", "generate_brief")
    graph.add_edge("generate_brief", "qa")         # QA the room_program
    graph.add_edge("fetch_components", "compliance_check")
    graph.add_edge("compliance_check", "architect")
    graph.add_edge("architect", "qa")              # QA spatial_layout
    graph.add_edge("structural", "qa")             # QA structural_schema
    graph.add_edge("mep", "qa")                    # QA mep_schema
    graph.add_edge("ifc_build", END)

    # Branching from qa
    graph.add_conditional_edges(
        "qa",
        _route_after_qa,
        {
            "fetch_components": "fetch_components",
            "structural": "structural",
            "mep": "mep",
            "ifc_build": "ifc_build",
            "generate_brief": "generate_brief",   # rejection loop
            "architect": "architect",             # rejection loop
            "pm_decision": "pm_decision",
            END: END,
        },
    )

    # Branching from pm_decision
    graph.add_conditional_edges(
        "pm_decision",
        _route_after_pm,
        {
            "user_approval": "user_approval",
            "generate_brief": "generate_brief",
            "architect": "architect",
            "structural": "structural",
            "mep": "mep",
        },
    )

    # user_approval → pm_decision (or loops on itself while waiting)
    graph.add_conditional_edges(
        "user_approval",
        _route_after_user_approval,
        {
            "pm_decision": "pm_decision",
            "user_approval": "user_approval",
        },
    )

    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)
    logger.info("[pipeline] LangGraph pipeline compiled successfully")
    return app


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _tail_messages(mem: ProjectMemory, n: int = 20) -> list:
    return mem.get_recent_messages(n)


def run_pipeline(project_id: str, prompt: str, jurisdiction: str = "SE") -> PipelineState:
    """
    Convenience function: build and run the full pipeline for a project.

    Args:
        project_id: unique project identifier
        prompt: user's building brief (text or file path)
        jurisdiction: regulatory jurisdiction code (e.g. "SE")

    Returns:
        Final pipeline state
    """
    app = build_pipeline()
    initial_state: PipelineState = {
        "project_id": project_id,
        "phase": "init",
        "user_prompt": prompt,
        "jurisdiction": jurisdiction,
        "qa_results": {},
        "rejection_counts": {},
        "awaiting_user_approval": False,
        "user_approval_response": None,
        "messages": [],
        "error": None,
    }
    config = {"configurable": {"thread_id": project_id}}
    final = app.invoke(initial_state, config=config)
    return final

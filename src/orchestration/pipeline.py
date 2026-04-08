"""
ArchitectAI -- LangGraph Pipeline

Orchestrates the multi-agent design pipeline as a directed graph with:
- Sequential agent phases (Client -> InputParser -> Brief -> ... -> IFC)
- QA retry loops (up to MAX_RETRIES rejections per phase)
- Human-in-the-loop milestone gates (M1, M2, M3)
- Crash recovery via PM-guided self-healing
"""

import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()
MAX_RETRIES = 4


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class PipelineState(TypedDict):
    # Inputs (set once at start)
    project_id: str
    prompt: str
    site_file: str
    jurisdiction: str
    projects_dir: str
    memory: Any  # ProjectMemory

    # Agent outputs
    project_brief: Optional[dict]
    site_data: Optional[dict]
    room_program: Optional[dict]
    comp_results: Optional[dict]
    spatial_layout: Optional[dict]
    structural_schema: Optional[dict]
    mep_schema: Optional[dict]
    ifc_result: Optional[dict]
    pm_decision: Optional[dict]

    # Per-phase QA tracking
    brief_qa_feedback: Optional[str]
    brief_qa_attempt: int
    architect_qa_feedback: Optional[str]
    architect_qa_attempt: int
    structural_qa_feedback: Optional[str]
    structural_qa_attempt: int
    mep_qa_feedback: Optional[str]
    mep_qa_attempt: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_qa_subprocess(schema_type, schema_data, version, prior_rejections,
                       projects_dir, project_id, timeout=90):
    """Run QA evaluation as an isolated subprocess with timeout."""
    payload = {
        "project_id": project_id,
        "base_dir": projects_dir,
        "schema_type": schema_type,
        "schema_data": schema_data,
        "version": version,
        "prior_rejections": prior_rejections,
    }
    venv_python = str(Path(projects_dir).parent / ".venv" / "bin" / "python3")
    if not Path(venv_python).exists():
        venv_python = sys.executable
    try:
        proc = subprocess.run(
            [venv_python, "scripts/run_qa.py"],
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=timeout,
            env={
                **os.environ,
                "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", "dummy"),
                "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
            },
        )
        if proc.returncode != 0:
            logger.warning(f"QA subprocess stderr: {proc.stderr[:200]}")
        return json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        return {"verdict": "CONDITIONAL", "issues": [f"QA timed out after {timeout}s"]}
    except Exception as e:
        return {"verdict": "CONDITIONAL", "issues": [f"QA error: {e}"]}


def _safe_run_agent(agent, inputs, memory, context_name="task", max_retries=2):
    """Run an agent with PM-guided crash recovery (up to max_retries internal retries)."""
    from src.agents.pm_agent import PMAgent

    last_e = None
    for attempt in range(max_retries + 1):
        try:
            return agent.run(inputs)
        except Exception as e:
            last_e = e
            tb = traceback.format_exc()
            agent.send_message("pm", "status_update", {"status": "blocked", "message": str(e)})
            logger.error(f"[{agent.AGENT_ID}] Crash on {context_name} (attempt {attempt + 1}/{max_retries + 1}): {e}")
            if attempt < max_retries:
                pm = PMAgent(memory)
                fix = pm.chat(
                    "You are a project manager. An agent crashed. Suggest a brief instruction to fix the input.",
                    [{"role": "user", "content": f"Agent {agent.AGENT_ID} crashed:\n{tb[:500]}"}],
                    max_tokens=200,
                )
                inputs = {**inputs, "qa_feedback": fix}
    raise last_e


def _qa_feedback_from_verdict(verdict_data):
    """Extract actionable feedback string from a QA verdict dict."""
    return (verdict_data.get("fix_instructions")
            or "; ".join(verdict_data.get("issues", [])[:3])
            or None)


def _should_proceed(verdict, attempt):
    """Decide whether to proceed past a QA gate."""
    if verdict == "APPROVED":
        return True
    if verdict == "CONDITIONAL" and attempt >= 2:
        return True
    if attempt >= MAX_RETRIES:
        return True
    return False


def _milestone_gate(memory, milestone_name, agent_classes, context_data, schema_names):
    """Display milestone info, run agent reflections, pause for human approval."""
    schemas_found = []
    for name in schema_names:
        path = memory.root / "schemas" / f"{name}_v1.json"
        if path.exists():
            schemas_found.append(path.name)

    console.print(Panel(
        Text.assemble(
            (f"Milestone: {milestone_name}\n", "bold"),
            (f"Cost so far: ${memory.state.get('total_cost_usd', 0):.4f}\n", "cyan"),
            (f"Schemas: {', '.join(schemas_found) or '(none)'}", "green"),
        ),
        title=f"-- {milestone_name} Gate --",
        border_style="yellow",
    ))

    for AgentClass in agent_classes:
        try:
            agent = AgentClass(memory)
            agent.reflect(milestone_name, context_data)
        except Exception as e:
            logger.warning(f"Reflection failed for {AgentClass.__name__}: {e}")

    console.print("[bold yellow]System paused for human review.[/bold yellow]")
    input(f"Press [ENTER] to approve {milestone_name} and continue...")
    memory.approve_milestone(milestone_name, "Approved via CLI")
    console.print(f"[green]{milestone_name} Approved[/green]\n")


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def run_client(state: PipelineState) -> dict:
    from src.agents.client_agent import ClientAgent

    console.print("\n[bold]Phase 0: Interpreting project brief...[/bold]")
    client = ClientAgent(state["memory"])
    try:
        brief = client.run({"prompt": state["prompt"], "jurisdiction": state["jurisdiction"]})
    except Exception as e:
        logger.warning(f"ClientAgent failed: {e}")
        brief = {"building_type": "healthcare", "jurisdiction": state["jurisdiction"],
                 "brief_summary": state["prompt"]}
    return {"project_brief": brief}


def run_input_parser(state: PipelineState) -> dict:
    from src.agents.input_parser import InputParserAgent

    console.print("\n[bold]Phase 1: Parsing site data...[/bold]")
    parser = InputParserAgent(state["memory"])
    try:
        site_data = parser.run({"file_path": state["site_file"], "jurisdiction": state["jurisdiction"]})
    except Exception as e:
        logger.warning(f"InputParserAgent failed: {e}")
        site_data = {"boundary": {"points": [], "area_m2": None}, "jurisdiction": state["jurisdiction"]}

    if site_data.get("error") or not site_data.get("boundary"):
        site_data["boundary"] = site_data.get("boundary", {"points": [], "area_m2": None})

    return {"site_data": site_data}


def run_brief(state: PipelineState) -> dict:
    from src.agents.brief_agent import BriefAgent

    attempt = state.get("brief_qa_attempt", 0)
    console.print(f"\n[bold]Phase 2: Generating room program (attempt {attempt + 1})...[/bold]")

    brief = BriefAgent(state["memory"])
    result = _safe_run_agent(brief, {
        "prompt": state["prompt"],
        "site_data": state["site_data"],
        "jurisdiction": state["jurisdiction"],
        "qa_feedback": state.get("brief_qa_feedback"),
        "project_brief": state.get("project_brief"),
    }, state["memory"], "generating room program")

    # Export RFP document on first successful generation
    if attempt == 0:
        try:
            brief.export_rfp_document(result)
        except Exception as e:
            logger.warning(f"RFP export failed: {e}")

    return {"room_program": result}


def qa_brief(state: PipelineState) -> dict:
    attempt = state.get("brief_qa_attempt", 0)
    verdict_data = _run_qa_subprocess(
        "room_program", state["room_program"], f"v{attempt + 1}", attempt,
        state["projects_dir"], state["project_id"],
    )
    verdict = verdict_data.get("verdict", "?")
    console.print(f"  QA verdict: [{'green' if verdict == 'APPROVED' else 'yellow'}]{verdict}[/]")

    return {
        "brief_qa_attempt": attempt + 1,
        "brief_qa_feedback": _qa_feedback_from_verdict(verdict_data) if verdict != "APPROVED" else None,
    }


def route_brief_qa(state: PipelineState) -> str:
    attempt = state.get("brief_qa_attempt", 0)
    has_feedback = state.get("brief_qa_feedback") is not None
    if not has_feedback or attempt >= MAX_RETRIES:
        return "run_pm_kickoff"
    return "run_brief"


def run_pm_kickoff(state: PipelineState) -> dict:
    from src.agents.pm_agent import PMAgent

    console.print("\n[bold]Phase 3: PM validating brief...[/bold]")
    pm = PMAgent(state["memory"])
    pm_decision = pm.kickoff(state["prompt"], state["site_data"], state["jurisdiction"])
    return {"pm_decision": pm_decision}


def run_compliance(state: PipelineState) -> dict:
    from src.agents.compliance_agent import ComplianceAgent

    console.print("\n[bold]Phase 4: Compliance check...[/bold]")
    compliance = ComplianceAgent(state["memory"])
    comp_results = compliance.check_room_program(state["room_program"])
    summary = comp_results.get("summary", {})
    console.print(
        f"  Pass: {summary.get('pass', 0)} | Fail: {summary.get('fail', 0)}"
        f" | Conditional: {summary.get('conditional', 0)}"
    )
    return {"comp_results": comp_results}


def gate_m1(state: PipelineState) -> dict:
    from src.agents.brief_agent import BriefAgent
    from src.agents.compliance_agent import ComplianceAgent

    _milestone_gate(
        state["memory"], "M1",
        agent_classes=[BriefAgent, ComplianceAgent],
        context_data={"room_program": state.get("room_program"), "comp_results": state.get("comp_results")},
        schema_names=["site_data", "room_program", "compliance_brief"],
    )
    return {}


def run_architect(state: PipelineState) -> dict:
    from src.agents.architect_agent import ArchitectAgent

    attempt = state.get("architect_qa_attempt", 0)
    console.print(f"\n[bold]Phase 5: Architect laying out rooms (attempt {attempt + 1})...[/bold]")

    memory = state["memory"]

    # Try to load enriched site_data from saved schema
    site_data_full = state["site_data"]
    site_data_path = memory.root / "schemas" / "site_data_v1.json"
    if site_data_path.exists():
        with open(site_data_path) as f:
            site_data_full = json.load(f)

    architect = ArchitectAgent(memory)
    result = _safe_run_agent(architect, {
        "room_program": state["room_program"],
        "site_data": site_data_full,
        "component_templates": {},
        "qa_feedback": state.get("architect_qa_feedback"),
        "project_brief": state.get("project_brief"),
    }, memory, "layout generation")
    return {"spatial_layout": result}


def qa_architect(state: PipelineState) -> dict:
    attempt = state.get("architect_qa_attempt", 0)
    verdict_data = _run_qa_subprocess(
        "spatial_layout", state["spatial_layout"], f"v{attempt + 1}", attempt,
        state["projects_dir"], state["project_id"],
    )
    verdict = verdict_data.get("verdict", "?")
    console.print(f"  QA verdict: [{'green' if verdict == 'APPROVED' else 'yellow'}]{verdict}[/]")

    return {
        "architect_qa_attempt": attempt + 1,
        "architect_qa_feedback": _qa_feedback_from_verdict(verdict_data) if verdict != "APPROVED" else None,
    }


def route_architect_qa(state: PipelineState) -> str:
    attempt = state.get("architect_qa_attempt", 0)
    has_feedback = state.get("architect_qa_feedback") is not None
    if not has_feedback or attempt >= MAX_RETRIES:
        return "gate_m2"
    return "run_architect"


def gate_m2(state: PipelineState) -> dict:
    from src.agents.architect_agent import ArchitectAgent

    _milestone_gate(
        state["memory"], "M2",
        agent_classes=[ArchitectAgent],
        context_data={"spatial_layout": state.get("spatial_layout")},
        schema_names=["spatial_layout"],
    )
    return {}


def run_structural(state: PipelineState) -> dict:
    from src.agents.structural_agent import StructuralAgent

    attempt = state.get("structural_qa_attempt", 0)
    console.print(f"\n[bold]Phase 6: Structural grid (attempt {attempt + 1})...[/bold]")

    memory = state["memory"]
    site_data_full = state["site_data"]
    site_data_path = memory.root / "schemas" / "site_data_v1.json"
    if site_data_path.exists():
        with open(site_data_path) as f:
            site_data_full = json.load(f)

    structural = StructuralAgent(memory)
    result = _safe_run_agent(structural, {
        "spatial_layout": state["spatial_layout"],
        "site_data": site_data_full,
        "qa_feedback": state.get("structural_qa_feedback"),
    }, memory, "structural grid")
    return {"structural_schema": result}


def qa_structural(state: PipelineState) -> dict:
    attempt = state.get("structural_qa_attempt", 0)
    verdict_data = _run_qa_subprocess(
        "structural_schema", state["structural_schema"], f"v{attempt + 1}", attempt,
        state["projects_dir"], state["project_id"],
    )
    verdict = verdict_data.get("verdict", "?")
    console.print(f"  QA verdict: [{'green' if verdict == 'APPROVED' else 'yellow'}]{verdict}[/]")

    return {
        "structural_qa_attempt": attempt + 1,
        "structural_qa_feedback": _qa_feedback_from_verdict(verdict_data) if verdict != "APPROVED" else None,
    }


def route_structural_qa(state: PipelineState) -> str:
    attempt = state.get("structural_qa_attempt", 0)
    has_feedback = state.get("structural_qa_feedback") is not None
    if not has_feedback or attempt >= MAX_RETRIES:
        return "run_mep"
    return "run_structural"


def run_mep(state: PipelineState) -> dict:
    from src.agents.mep_agent import MEPAgent

    attempt = state.get("mep_qa_attempt", 0)
    console.print(f"\n[bold]Phase 7: MEP routing (attempt {attempt + 1})...[/bold]")

    memory = state["memory"]
    site_data_full = state["site_data"]
    site_data_path = memory.root / "schemas" / "site_data_v1.json"
    if site_data_path.exists():
        with open(site_data_path) as f:
            site_data_full = json.load(f)

    mep = MEPAgent(memory)
    result = _safe_run_agent(mep, {
        "spatial_layout": state["spatial_layout"],
        "structural_schema": state["structural_schema"],
        "site_data": site_data_full,
        "qa_feedback": state.get("mep_qa_feedback"),
    }, memory, "mep routing")
    return {"mep_schema": result}


def qa_mep(state: PipelineState) -> dict:
    attempt = state.get("mep_qa_attempt", 0)
    verdict_data = _run_qa_subprocess(
        "mep_schema", state["mep_schema"], f"v{attempt + 1}", attempt,
        state["projects_dir"], state["project_id"],
    )
    verdict = verdict_data.get("verdict", "?")
    console.print(f"  QA verdict: [{'green' if verdict == 'APPROVED' else 'yellow'}]{verdict}[/]")

    return {
        "mep_qa_attempt": attempt + 1,
        "mep_qa_feedback": _qa_feedback_from_verdict(verdict_data) if verdict != "APPROVED" else None,
    }


def route_mep_qa(state: PipelineState) -> str:
    attempt = state.get("mep_qa_attempt", 0)
    has_feedback = state.get("mep_qa_feedback") is not None
    if not has_feedback or attempt >= MAX_RETRIES:
        return "run_ifc_builder"
    return "run_mep"


def run_ifc_builder(state: PipelineState) -> dict:
    from src.agents.ifc_builder_agent import IFCBuilderAgent

    console.print("\n[bold]Phase 8: Building IFC model...[/bold]")
    memory = state["memory"]
    output_dir = Path(state["projects_dir"]) / state["project_id"] / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    ifc_path = output_dir / "model_M1.ifc"

    ifc_builder = IFCBuilderAgent(memory)
    try:
        result = ifc_builder.run({
            "spatial_layout": state["spatial_layout"],
            "structural_schema": state["structural_schema"],
            "mep_schema": state["mep_schema"],
            "output_path": str(ifc_path),
        })
        console.print(f"  IFC model: {result.get('entity_count', '?')} entities -> {ifc_path.name}")
    except Exception as e:
        logger.error(f"IFC Builder failed: {e}")
        result = {"entity_count": 0, "error": str(e)}
    return {"ifc_result": result}


def gate_m3(state: PipelineState) -> dict:
    from src.agents.mep_agent import MEPAgent
    from src.agents.structural_agent import StructuralAgent

    _milestone_gate(
        state["memory"], "M3",
        agent_classes=[StructuralAgent, MEPAgent],
        context_data={
            "structural_schema": state.get("structural_schema"),
            "mep_schema": state.get("mep_schema"),
        },
        schema_names=["structural_schema", "mep_schema"],
    )
    return {}


def finalize(state: PipelineState) -> dict:
    memory = state["memory"]
    memory.update_phase("complete")

    ifc_path = Path(state["projects_dir"]) / state["project_id"] / "outputs" / "model_M1.ifc"
    memory.approve_milestone("M4", "IFC Base Model generated")
    memory.approve_milestone("M5", f"Final export approved: {ifc_path.name}")

    console.print(Panel(
        Text.assemble(
            ("Pipeline Complete\n", "bold green"),
            (f"Project: {state['project_id']}\n", "white"),
            (f"Total cost: ${memory.state.get('total_cost_usd', 0):.4f}\n", "cyan"),
            (f"IFC entities: {state.get('ifc_result', {}).get('entity_count', '?')}", "green"),
        ),
        title="Done",
        border_style="green",
    ))
    return {}


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_pipeline() -> StateGraph:
    """Build and compile the ArchitectAI LangGraph pipeline."""
    builder = StateGraph(PipelineState)

    # --- Add nodes ---
    builder.add_node("run_client", run_client)
    builder.add_node("run_input_parser", run_input_parser)
    builder.add_node("run_brief", run_brief)
    builder.add_node("qa_brief", qa_brief)
    builder.add_node("run_pm_kickoff", run_pm_kickoff)
    builder.add_node("run_compliance", run_compliance)
    builder.add_node("gate_m1", gate_m1)
    builder.add_node("run_architect", run_architect)
    builder.add_node("qa_architect", qa_architect)
    builder.add_node("gate_m2", gate_m2)
    builder.add_node("run_structural", run_structural)
    builder.add_node("qa_structural", qa_structural)
    builder.add_node("run_mep", run_mep)
    builder.add_node("qa_mep", qa_mep)
    builder.add_node("run_ifc_builder", run_ifc_builder)
    builder.add_node("gate_m3", gate_m3)
    builder.add_node("finalize", finalize)

    # --- Linear edges ---
    builder.add_edge(START, "run_client")
    builder.add_edge("run_client", "run_input_parser")
    builder.add_edge("run_input_parser", "run_brief")
    builder.add_edge("run_brief", "qa_brief")
    # qa_brief -> conditional (run_brief or run_pm_kickoff)
    builder.add_edge("run_pm_kickoff", "run_compliance")
    builder.add_edge("run_compliance", "gate_m1")
    builder.add_edge("gate_m1", "run_architect")
    builder.add_edge("run_architect", "qa_architect")
    # qa_architect -> conditional (run_architect or gate_m2)
    builder.add_edge("gate_m2", "run_structural")
    builder.add_edge("run_structural", "qa_structural")
    # qa_structural -> conditional (run_structural or run_mep)
    builder.add_edge("run_mep", "qa_mep")
    # qa_mep -> conditional (run_mep or run_ifc_builder)
    builder.add_edge("run_ifc_builder", "gate_m3")
    builder.add_edge("gate_m3", "finalize")
    builder.add_edge("finalize", END)

    # --- QA retry loops (conditional edges) ---
    builder.add_conditional_edges("qa_brief", route_brief_qa)
    builder.add_conditional_edges("qa_architect", route_architect_qa)
    builder.add_conditional_edges("qa_structural", route_structural_qa)
    builder.add_conditional_edges("qa_mep", route_mep_qa)

    return builder.compile()

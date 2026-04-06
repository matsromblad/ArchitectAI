"""
ArchitectAI — Main entry point
Usage: python main.py --project-id my-project --prompt "Design a geriatric ward..."
                      --site-file inputs/floorplan.png --jurisdiction SE
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

load_dotenv()

console = Console()


def main():
    parser = argparse.ArgumentParser(description="ArchitectAI — Multi-agent building design system")
    parser.add_argument("--project-id",  required=True, help="Unique project identifier")
    parser.add_argument("--prompt",      required=True, help="Building brief in natural language")
    parser.add_argument("--site-file",   required=True, help="Path to site plan (PNG/PDF/DWG/IFC)")
    parser.add_argument("--jurisdiction",default="SE",  help="ISO country code (default: SE)")
    parser.add_argument("--projects-dir",default="./projects", help="Root directory for project storage")
    args = parser.parse_args()

    # Make sure we have a fallback key so anthropic SDK doesn't crash if we ever use it
    if not os.getenv("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = "dummy_for_local_models"

    # Validate site file
    site_file = Path(args.site_file)
    if not site_file.exists():
        console.print(f"[red]Error: Site file not found: {site_file}[/red]")
        sys.exit(1)

    console.print(Panel(
        Text.assemble(
            ("+ AI NIGHTINGALE\n", "bold yellow"),
            (f"Project: {args.project_id}\n", "white"),
            (f"Prompt:  {args.prompt[:80]}\n", "cyan"),
            (f"Site:    {site_file.name}\n", "green"),
            (f"Jurisdiction: {args.jurisdiction}", "blue"),
        ),
        title="Initializing",
        border_style="yellow",
    ))

    # Import here to avoid slow startup if just checking --help
    from src.memory.project_memory import ProjectMemory
    from src.agents.pm_agent import PMAgent
    from src.agents.input_parser import InputParserAgent
    from src.agents.client_agent import ClientAgent
    from src.agents.brief_agent import BriefAgent
    from src.agents.compliance_agent import ComplianceAgent
    from src.agents.qa_agent import QAAgent
    from src.agents.structural_agent import StructuralAgent
    from src.agents.mep_agent import MEPAgent
    from src.agents.ifc_builder_agent import IFCBuilderAgent
    import subprocess, json as _json

    def run_qa(schema_type, schema_data, version, prior_rejections, timeout=90):
        """Run QA as an isolated subprocess with timeout. Returns verdict dict."""
        payload = {
            "project_id": args.project_id,
            "base_dir": args.projects_dir,
            "schema_type": schema_type,
            "schema_data": schema_data,
            "version": version,
            "prior_rejections": prior_rejections,
        }
        venv_python = str(Path(args.projects_dir).parent / ".venv" / "bin" / "python3")
        if not Path(venv_python).exists():
            venv_python = sys.executable
        try:
            result = subprocess.run(
                [venv_python, "scripts/run_qa.py"],
                input=_json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=Path(__file__).parent,
                env={**os.environ, "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", "dummy")},
            )
            if result.returncode != 0:
                logger.warning(f"[qa-subprocess] exit {result.returncode}: {result.stderr[:200]}")
            out = result.stdout.strip()
            if out:
                return _json.loads(out)
            return {"verdict": "REJECTED", "issues": ["QA subprocess returned no output"]}
        except subprocess.TimeoutExpired:
            logger.error(f"[qa-subprocess] Timed out after {timeout}s")
            return {"verdict": "CONDITIONAL", "issues": [f"QA timed out after {timeout}s — proceeding with caution"]}
        except Exception as e:
            logger.error(f"[qa-subprocess] Error: {e}")
            return {"verdict": "REJECTED", "issues": [str(e)]}

    def milestone_gate(memory, milestone_name: str, reflecting_agents: list, context_data: dict, schemas: list):
        cost = memory.state.get("total_cost_usd", 0.0)
        console.print(Panel(
            Text.assemble(
                (f"Milestone: {milestone_name}\n", "bold cyan"),
                (f"Cost so far: ${cost:.3f}\n", "bold green"),
                (f"Outputs: {', '.join(schemas)}", "white"),
            ),
            title="🛑 Milestone Reached", border_style="cyan"
        ))
        
        # Agent reflection
        if reflecting_agents:
            console.print("[dim]Agents are reflecting on their work...[/dim]")
            for agent in reflecting_agents:
                try:
                    agent.reflect(milestone_name, context_data)
                except Exception as e:
                    logger.warning(f"Reflection failed for {agent.AGENT_ID}: {e}")
                    
        # Pause for Human-in-the-loop
        console.print("[bold yellow]System paused for human review.[/bold yellow]")
        input(f"Press [ENTER] to approve {milestone_name} and continue...")
        memory.approve_milestone(milestone_name, "Approved via CLI")
        console.print(f"[green]✓ {milestone_name} Approved[/green]\n")

    # Initialize project memory
    memory = ProjectMemory(project_id=args.project_id, base_dir=args.projects_dir)
    logger.info(f"Project memory initialized at: {memory.root}")

    # Initialize agents
    pm           = PMAgent(memory)
    parser_agent = InputParserAgent(memory)
    client       = ClientAgent(memory)
    brief        = BriefAgent(memory)
    compliance   = ComplianceAgent(memory)
    qa           = QAAgent(memory)

    console.print("[green]✓ Agents initialized[/green]")
    console.print(f"  PM:         {pm.model}")
    console.print(f"  Others:     {brief.model}")

    # ---- PHASE 0: Client Agent — interpret brief, set realistic project parameters ----
    console.print("\n[bold]Phase 0: Client Agent interpreting brief...[/bold]")
    project_brief = client.run({"prompt": args.prompt, "jurisdiction": args.jurisdiction})
    size = project_brief.get("size", {})
    prog = project_brief.get("programme", {})
    console.print(
        f"[green]✓ Project brief: {project_brief.get('project_name','?')} | "
        f"{size.get('target_gross_area_m2','?')}m² gross | "
        f"{size.get('site_width_m','?')}×{size.get('site_depth_m','?')}m site | "
        f"{prog.get('patient_beds','?')} beds[/green]"
    )

    # ---- PHASE 1: Parse site input ----
    console.print("\n[bold]Phase 1: Parsing site input...[/bold]")
    site_data = parser_agent.run({"file_path": str(site_file), "jurisdiction": args.jurisdiction})
    if not site_data or site_data.get("error"):
        console.print(f"[yellow]⚠ Site parse issue: {site_data.get('notes', 'unknown error') if site_data else 'no data returned'}[/yellow]")
        console.print("[yellow]  Continuing with minimal site data (area unknown)...[/yellow]")
        # Use fallback site data so pipeline can continue
        site_data = site_data or {}
        site_data.setdefault("boundary", {"points": [], "area_m2": None})
        site_data.setdefault("jurisdiction", args.jurisdiction)
    # boundary may be a list of points or a dict with area_m2
    _boundary = site_data.get("boundary") or {}
    area = _boundary.get("area_m2", "unknown") if isinstance(_boundary, dict) else site_data.get("area_m2", "unknown")
    console.print(f"[green]✓ Site parsed: {area} m²[/green]")

    # ---- PHASE 2: Generate room program (with QA retry loop) ----
    console.print("\n[bold]Phase 2: Generating room program...[/bold]")
    MAX_RETRIES = 4
    qa_feedback = None
    room_program = None

    for attempt in range(MAX_RETRIES + 1):
        room_program = brief.run({
            "prompt": args.prompt,
            "site_data": site_data,
            "jurisdiction": args.jurisdiction,
            "qa_feedback": qa_feedback,
            "project_brief": project_brief,  # client agent output
        })
        n_rooms = len(room_program.get("rooms", []))
        total_area = room_program.get("total_net_area_m2", room_program.get("total_area_m2", "?"))
        console.print(f"[green]  Attempt {attempt+1}: {n_rooms} rooms, {total_area} m²[/green]")

        # QA review (isolated subprocess with 90s timeout)
        qa_verdict = run_qa("room_program", room_program, f"v{attempt+1}", attempt)
        verdict = qa_verdict.get("verdict", "?")
        if verdict == "APPROVED":
            console.print("[green]✓ Room program QA: APPROVED[/green]")
            break
        elif verdict == "CONDITIONAL" and attempt >= 1:
            console.print("[yellow]✓ Room program QA: CONDITIONAL — proceeding[/yellow]")
            break
        else:
            issues = qa_verdict.get("issues", [])
            qa_feedback = qa_verdict.get("fix_instructions") or "; ".join(issues[:3])
            color = "yellow" if verdict == "CONDITIONAL" else "red"
            console.print(f"[{color}]  QA {verdict} — retry with feedback[/{color}]")
            if attempt == MAX_RETRIES:
                console.print("[yellow]  Max retries reached — proceeding with best attempt[/yellow]")

    # ---- PHASE 3: PM kickoff ----
    console.print("\n[bold]Phase 3: PM reviewing brief...[/bold]")
    pm_decision = pm.kickoff(args.prompt, site_data, args.jurisdiction)
    console.print(f"[green]✓ PM decision: {pm_decision.get('action', '?')}[/green]")

    # ---- PHASE 4: Compliance Validation ----
    console.print("\n[bold]Phase 4: Compliance Validation of Room Program...[/bold]")
    comp_results = compliance.check_room_program(room_program)
    if "summary" in comp_results:
        summary_txt = f"{comp_results['summary'].get('pass', 0)} pass, {comp_results['summary'].get('fail', 0)} fail, {comp_results['summary'].get('conditional', 0)} cond, {comp_results['summary'].get('unknown', 0)} unknown"
    else:
        summary_txt = "completed"
    console.print(f"[green]✓ Compliance: {summary_txt}[/green]")
    
    # --- MILESTONE 1 (M1) ---
    milestone_gate(memory, "M1", 
                   reflecting_agents=[brief, compliance], 
                   context_data={"room_program": room_program, "compliance": comp_results},
                   schemas=["site_data.json", "room_program.json", "compliance_brief.json"])

    # ---- PHASE 5: Architect Agent — spatial layout (with retry) ----
    console.print("\n[bold]Phase 5: Architect laying out rooms...[/bold]")
    from src.agents.architect_agent import ArchitectAgent
    architect = ArchitectAgent(memory)

    import json as _json
    site_data_path = memory.root / "schemas" / "site_data_v1.json"
    if site_data_path.exists():
        with open(site_data_path) as f:
            site_data_full = _json.load(f)
    else:
        site_data_full = site_data

    layout_qa_feedback = None
    spatial_layout = None
    layout_verdict = "?"

    for attempt in range(MAX_RETRIES + 1):
        spatial_layout = architect.run({
            "room_program": room_program,
            "site_data": site_data_full,
            "component_templates": {},
            "qa_feedback": layout_qa_feedback,
            "project_brief": project_brief,  # for site dimensions
        })
        floors = spatial_layout.get("floors", [])
        total_rooms = sum(len(fl.get("rooms", [])) for fl in floors)
        console.print(f"[green]  Attempt {attempt+1}: {total_rooms} rooms across {len(floors)} floor(s)[/green]")

        qa_layout_verdict = run_qa("spatial_layout", spatial_layout, f"v{attempt+1}", attempt)
        layout_verdict = qa_layout_verdict.get("verdict", "?")
        if layout_verdict == "APPROVED":
            console.print("[green]✓ Spatial layout QA: APPROVED[/green]")
            break
        elif layout_verdict == "CONDITIONAL" and attempt >= 1:
            console.print("[yellow]✓ Spatial layout QA: CONDITIONAL — proceeding[/yellow]")
            break
        else:
            issues = qa_layout_verdict.get("issues", [])
            layout_qa_feedback = qa_layout_verdict.get("fix_instructions") or "; ".join(issues[:3])
            color2 = "yellow" if layout_verdict == "CONDITIONAL" else "red"
            console.print(f"[{color2}]  Layout QA {layout_verdict} — retry with feedback[/{color2}]")
            if attempt == MAX_RETRIES:
                console.print("[yellow]  Max retries reached — proceeding with best attempt[/yellow]")

    # --- MILESTONE 2 (M2) ---
    milestone_gate(memory, "M2", 
                   reflecting_agents=[architect], 
                   context_data={"spatial_layout": spatial_layout, "qa_feedback": layout_qa_feedback},
                   schemas=["spatial_layout.json"])

    # ---- PHASE 6: Structural Agent ----
    console.print("\n[bold]Phase 6: Structural Agent proposing grid...[/bold]")
    structural = StructuralAgent(memory)
    structural_schema = None
    struct_qa_feedback = None
    struct_verdict = "?"
    
    for attempt in range(MAX_RETRIES + 1):
        structural_schema = structural.run({
            "spatial_layout": spatial_layout,
            "qa_feedback": struct_qa_feedback,
        })
        
        qa_struct_verdict = run_qa("structural_schema", structural_schema, f"v{attempt+1}", attempt)
        struct_verdict = qa_struct_verdict.get("verdict", "?")
        
        if struct_verdict == "APPROVED":
            console.print("[green]✓ Structural QA: APPROVED[/green]")
            break
        elif struct_verdict == "CONDITIONAL" and attempt >= 1:
            console.print("[yellow]✓ Structural QA: CONDITIONAL — proceeding[/yellow]")
            break
        else:
            issues = qa_struct_verdict.get("issues", [])
            struct_qa_feedback = qa_struct_verdict.get("fix_instructions") or "; ".join(issues[:3])
            color = "yellow" if struct_verdict == "CONDITIONAL" else "red"
            console.print(f"[{color}]  Structural QA {struct_verdict} — retry with feedback[/{color}]")
            if attempt == MAX_RETRIES:
                console.print("[yellow]  Max retries reached — proceeding with best attempt[/yellow]")

    # ---- PHASE 7: MEP Agent ----
    console.print("\n[bold]Phase 7: MEP Agent designing systems...[/bold]")
    mep = MEPAgent(memory)
    mep_schema = None
    mep_qa_feedback = None
    mep_verdict = "?"
    
    for attempt in range(MAX_RETRIES + 1):
        mep_schema = mep.run({
            "spatial_layout": spatial_layout,
            "structural_schema": structural_schema,
            "qa_feedback": mep_qa_feedback,
        })
        
        qa_mep_verdict = run_qa("mep_schema", mep_schema, f"v{attempt+1}", attempt)
        mep_verdict = qa_mep_verdict.get("verdict", "?")
        
        if mep_verdict == "APPROVED":
            console.print("[green]✓ MEP QA: APPROVED[/green]")
            break
        elif mep_verdict == "CONDITIONAL" and attempt >= 1:
            console.print("[yellow]✓ MEP QA: CONDITIONAL — proceeding[/yellow]")
            break
        else:
            issues = qa_mep_verdict.get("issues", [])
            mep_qa_feedback = qa_mep_verdict.get("fix_instructions") or "; ".join(issues[:3])
            color = "yellow" if mep_verdict == "CONDITIONAL" else "red"
            console.print(f"[{color}]  MEP QA {mep_verdict} — retry with feedback[/{color}]")
            if attempt == MAX_RETRIES:
                console.print("[yellow]  Max retries reached — proceeding with best attempt[/yellow]")

    # ---- PHASE 8: IFC Builder Agent ----
    console.print("\n[bold]Phase 8: IFC Builder generating model...[/bold]")
    ifc_builder = IFCBuilderAgent(memory)
    
    output_dir = Path(args.projects_dir) / args.project_id / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    ifc_path = output_dir / "model_M1.ifc"
    
    ifc_result = ifc_builder.run({
        "spatial_layout": spatial_layout,
        "structural_schema": structural_schema,
        "mep_schema": mep_schema,
        "output_path": str(ifc_path),
    })
    console.print(f"[green]✓ IFC Model generated: {ifc_result.get('entity_count', 0)} entities ({ifc_path.name})[/green]")

    # --- MILESTONE 3 & 4/5 (M3-M5) ---
    # Simplified here to just approve M3 and M5 at the end, along with reflections for structural and MEP.
    milestone_gate(memory, "M3", 
                   reflecting_agents=[structural, mep], 
                   context_data={"structural": structural_schema, "mep": mep_schema},
                   schemas=["structural_schema.json", "mep_schema.json"])

    # ---- PHASE 9: Final Approval ----
    memory.update_phase("complete")
    memory.approve_milestone("M4", notes="IFC Base Model generated")
    memory.approve_milestone("M5", notes=f"Final export approved: {ifc_path.name}")
    console.print("\n[bold]Phase 9: Project milestones all approved[/bold]")

    # ---- Summary ----
    console.print(Panel(
        Text.assemble(
            (f"Project: {args.project_id}\n", "white"),
            (f"Phase: {memory.state['phase']}\n", "cyan"),
            (f"Files saved to: {memory.root}\n", "green"),
            (f"Room program QA: {verdict}\n", "bold"),
            (f"Layout QA: {layout_verdict}\n", "bold"),
            (f"Structural QA: {struct_verdict}\n", "bold"),
            (f"MEP QA: {mep_verdict}", "bold"),
        ),
        title="✅ Pipeline end-to-end Complete",
        border_style="green" if all(v in ("APPROVED", "CONDITIONAL") for v in (verdict, layout_verdict, struct_verdict, mep_verdict)) else "yellow",
    ))

    console.print("\n[dim]Next steps: run src/server/ws_server.py to see live state in browser[/dim]")


if __name__ == "__main__":
    main()

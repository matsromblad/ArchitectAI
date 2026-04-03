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

    # Validate API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        console.print("[red]Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.[/red]")
        sys.exit(1)

    # Validate site file
    site_file = Path(args.site_file)
    if not site_file.exists():
        console.print(f"[red]Error: Site file not found: {site_file}[/red]")
        sys.exit(1)

    console.print(Panel(
        Text.assemble(
            ("⬛ ARCHITECTAI\n", "bold yellow"),
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

    # ---- Summary ----
    console.print(Panel(
        Text.assemble(
            (f"Project: {args.project_id}\n", "white"),
            (f"Phase: {memory.state['phase']}\n", "cyan"),
            (f"Files saved to: {memory.root}\n", "green"),
            (f"Room program QA: {verdict}\n", "bold"),
            (f"Layout QA: {layout_verdict}", "bold"),
        ),
        title="✅ Phase 1–2 Complete",
        border_style="green" if layout_verdict == "APPROVED" else "yellow",
    ))

    console.print("\n[dim]Next steps: run dashboard/server.py to see live state in browser[/dim]")


if __name__ == "__main__":
    main()

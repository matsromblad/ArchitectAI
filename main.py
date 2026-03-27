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
    from src.agents.brief_agent import BriefAgent
    from src.agents.compliance_agent import ComplianceAgent
    from src.agents.qa_agent import QAAgent

    # Initialize project memory
    memory = ProjectMemory(project_id=args.project_id, base_dir=args.projects_dir)
    logger.info(f"Project memory initialized at: {memory.root}")

    # Initialize agents
    pm         = PMAgent(memory)
    parser_agent = InputParserAgent(memory)
    brief      = BriefAgent(memory)
    compliance = ComplianceAgent(memory)
    qa         = QAAgent(memory)

    console.print("[green]✓ Agents initialized[/green]")
    console.print(f"  PM:         {pm.model}")
    console.print(f"  Others:     {brief.model}")

    # ---- PHASE 1: Parse site input ----
    console.print("\n[bold]Phase 1: Parsing site input...[/bold]")
    site_data = parser_agent.run({"file_path": str(site_file), "jurisdiction": args.jurisdiction})
    console.print(f"[green]✓ Site parsed: {site_data.get('boundary', {}).get('area_m2', '?')} m²[/green]")

    # ---- PHASE 2: Generate room program ----
    console.print("\n[bold]Phase 2: Generating room program...[/bold]")
    room_program = brief.run({
        "prompt": args.prompt,
        "site_data": site_data,
        "jurisdiction": args.jurisdiction,
    })
    console.print(f"[green]✓ Room program: {len(room_program.get('rooms', []))} rooms, {room_program.get('total_area_m2', '?')} m²[/green]")

    # ---- PHASE 3: PM kickoff ----
    console.print("\n[bold]Phase 3: PM reviewing brief...[/bold]")
    pm_decision = pm.kickoff(args.prompt, site_data, args.jurisdiction)
    console.print(f"[green]✓ PM decision: {pm_decision.get('action', '?')}[/green]")

    # ---- PHASE 4: QA review of room program ----
    console.print("\n[bold]Phase 4: QA reviewing room program...[/bold]")
    qa_verdict = qa.run({
        "schema_type": "room_program",
        "schema_data": room_program,
        "version": "v1",
        "prior_rejections": 0,
    })

    verdict = qa_verdict.get("verdict", "?")
    color = "green" if verdict == "APPROVED" else "red" if verdict == "REJECTED" else "yellow"
    console.print(f"[{color}]✓ QA verdict: {verdict}[/{color}]")

    if qa_verdict.get("issues"):
        for issue in qa_verdict["issues"]:
            console.print(f"  [yellow]⚠ {issue}[/yellow]")

    # ---- Summary ----
    console.print(Panel(
        Text.assemble(
            (f"Project: {args.project_id}\n", "white"),
            (f"Phase: {memory.state['phase']}\n", "cyan"),
            (f"Files saved to: {memory.root}\n", "green"),
            (f"QA Status: {verdict}", "bold"),
        ),
        title="✅ Phase 1 Complete",
        border_style="green" if verdict == "APPROVED" else "yellow",
    ))

    console.print("\n[dim]Next steps: run dashboard/server.py to see live state in browser[/dim]")


if __name__ == "__main__":
    main()

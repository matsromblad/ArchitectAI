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

# Reconfigure loguru to write to stdout so the dashboard terminal captures it
# Use utf-8 wrapper to avoid cp1252 encoding errors on Windows
import sys as _sys
import io as _io
logger.remove()
_utf8_stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
logger.add(_utf8_stdout, format="<level>[{level}]</level> {message}", level="INFO", colorize=False)

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
    from src.orchestration.pipeline import build_pipeline

    # Initialize project memory
    memory = ProjectMemory(project_id=args.project_id, base_dir=args.projects_dir)
    logger.info(f"Project memory initialized at: {memory.root}")

    # Build and run the LangGraph pipeline
    graph = build_pipeline()
    initial_state = {
        "project_id": args.project_id,
        "prompt": args.prompt,
        "site_file": str(site_file),
        "jurisdiction": args.jurisdiction,
        "projects_dir": args.projects_dir,
        "memory": memory,
        # QA counters start at 0
        "brief_qa_attempt": 0,
        "architect_qa_attempt": 0,
        "structural_qa_attempt": 0,
        "mep_qa_attempt": 0,
    }

    console.print("[green]Pipeline graph compiled — starting execution[/green]\n")
    graph.invoke(initial_state)

    console.print("\n[dim]Next steps: run src/server/ws_server.py to see live state in browser[/dim]")


if __name__ == "__main__":
    main()

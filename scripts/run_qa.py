"""
QA Runner — standalone subprocess for QA reviews.
Called by the pipeline with schema data via stdin (JSON).
Writes result to stdout as JSON.

Usage:
  echo '{"schema_type":"room_program","schema_data":{...},"version":"v1","prior_rejections":0}' \
    | python3 scripts/run_qa.py

Exit codes: 0=ok, 1=error
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")

from src.memory.project_memory import ProjectMemory
from src.agents.qa_agent import QAAgent

def main():
    try:
        inputs = json.load(sys.stdin)
    except Exception as e:
        print(json.dumps({"error": f"Bad stdin JSON: {e}", "verdict": "REJECTED", "issues": [str(e)]}))
        sys.exit(1)

    project_id = inputs.pop("project_id", "qa-runner-tmp")
    base_dir   = inputs.pop("base_dir", "./projects")

    memory = ProjectMemory(project_id=project_id, base_dir=base_dir)
    qa = QAAgent(memory)

    try:
        result = qa.run(inputs)
        print(json.dumps(result))
        sys.exit(0)
    except Exception as e:
        print(json.dumps({"error": str(e), "verdict": "REJECTED", "issues": [str(e)]}))
        sys.exit(1)

if __name__ == "__main__":
    main()

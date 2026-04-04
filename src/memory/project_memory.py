"""
Project Memory — manages all persistent state for a single project.
Handles versioned schema files, message log, and state.json.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class ProjectMemory:
    """
    Manages the filesystem-based memory for a single project.

    Directory structure:
        /projects/<project_id>/
            state.json              — project phase, milestones, decisions
            inputs/                 — original uploaded files
            schemas/                — versioned JSON schemas
            outputs/                — IFC files, QA reports
            messages/message_log.jsonl — full audit trail
    """

    def __init__(self, project_id: str, base_dir: str = "./projects"):
        self.project_id = project_id
        self.root = Path(base_dir) / project_id
        self._init_dirs()
        self._load_state()

    def _init_dirs(self):
        for d in ["inputs", "schemas", "outputs/qa_reports", "messages"]:
            (self.root / d).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # State                                                                #
    # ------------------------------------------------------------------ #

    def _load_state(self):
        state_file = self.root / "state.json"
        if state_file.exists():
            self.state = json.loads(state_file.read_text())
        else:
            self.state = {
                "project_id": self.project_id,
                "created_at": self._now(),
                "phase": "init",
                "current_milestone": 0,
                "milestones": {
                    "M1": {"status": "pending", "approved_at": None},
                    "M2": {"status": "pending", "approved_at": None},
                    "M3": {"status": "pending", "approved_at": None},
                    "M4": {"status": "pending", "approved_at": None},
                    "M5": {"status": "pending", "approved_at": None},
                },
                "current_schemas": {},   # schema_type → latest approved version
                "decisions": [],         # log of PM decisions
                "reflections": [],       # log of agent learnings
                "jurisdiction": None,
                "building_type": None,
                "total_cost_usd": 0.0,
            }
            self._save_state()

    def _save_state(self):
        (self.root / "state.json").write_text(
            json.dumps(self.state, indent=2, ensure_ascii=False)
        )

    def update_phase(self, phase: str):
        self.state["phase"] = phase
        self.state["updated_at"] = self._now()
        self._save_state()

    def approve_milestone(self, milestone: str, notes: str = ""):
        self.state["milestones"][milestone] = {
            "status": "approved",
            "approved_at": self._now(),
            "notes": notes,
        }
        self.state["current_milestone"] += 1
        self._save_state()

    def log_decision(self, agent: str, decision: str, context: str = ""):
        self.state["decisions"].append({
            "timestamp": self._now(),
            "agent": agent,
            "decision": decision,
            "context": context,
        })
        self._save_state()

    def log_cost(self, amount: float):
        self.state["total_cost_usd"] = self.state.get("total_cost_usd", 0.0) + amount
        self._save_state()

    def log_reflection(self, agent: str, milestone: str, content: str):
        self.state.setdefault("reflections", []).append({
            "timestamp": self._now(),
            "agent": agent,
            "milestone": milestone,
            "content": content
        })
        self._save_state()

    # ------------------------------------------------------------------ #
    # Schema versioning                                                    #
    # ------------------------------------------------------------------ #

    def save_schema(self, schema_type: str, data: dict, version: str = None) -> str:
        """Save a versioned schema file. Returns the version string."""
        if version is None:
            existing = list((self.root / "schemas").glob(f"{schema_type}_v*.json"))
            version = f"v{len(existing) + 1}"

        filename = f"{schema_type}_{version}.json"
        data["_version"] = version
        data["_saved_at"] = self._now()
        (self.root / "schemas" / filename).write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )
        return version

    def get_schema(self, schema_type: str, version: str = None) -> Optional[dict]:
        """Load a schema. If version is None, returns the latest."""
        if version:
            path = self.root / "schemas" / f"{schema_type}_{version}.json"
            return json.loads(path.read_text()) if path.exists() else None

        # Latest = highest version number
        files = sorted(
            (self.root / "schemas").glob(f"{schema_type}_v*.json"),
            key=lambda p: int(p.stem.split("_v")[-1])
        )
        return json.loads(files[-1].read_text()) if files else None

    def mark_schema_approved(self, schema_type: str, version: str):
        self.state["current_schemas"][schema_type] = version
        self._save_state()

    def list_schema_versions(self, schema_type: str) -> list[str]:
        return sorted(
            [p.stem.split("_")[-1] for p in (self.root / "schemas").glob(f"{schema_type}_v*.json")]
        )

    # ------------------------------------------------------------------ #
    # Message log                                                          #
    # ------------------------------------------------------------------ #

    def log_message(self, from_agent: str, to_agent: str, msg_type: str, payload: dict, reply_to: str = None) -> str:
        """Append a message to the JSONL audit log. Returns msg_id."""
        msg = {
            "msg_id": str(uuid.uuid4()),
            "timestamp": self._now(),
            "from": from_agent,
            "to": to_agent,
            "type": msg_type,
            "project_id": self.project_id,
            "reply_to": reply_to,
            "payload": payload,
        }
        with open(self.root / "messages" / "message_log.jsonl", "a") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return msg["msg_id"]

    def get_recent_messages(self, n: int = 20) -> list[dict]:
        log_path = self.root / "messages" / "message_log.jsonl"
        if not log_path.exists():
            return []
        lines = log_path.read_text().strip().splitlines()
        return [json.loads(l) for l in lines[-n:]]

    # ------------------------------------------------------------------ #
    # Outputs                                                              #
    # ------------------------------------------------------------------ #

    def save_output(self, filename: str, content: bytes | str):
        path = self.root / "outputs" / filename
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_bytes(content)
        return str(path)

    def save_qa_report(self, milestone: str, report: dict):
        path = self.root / "outputs" / "qa_reports" / f"qa_{milestone}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_project_summary(self) -> dict:
        """Returns a compact summary for dashboard/PM context."""
        return {
            "project_id": self.project_id,
            "phase": self.state["phase"],
            "milestone": self.state["current_milestone"],
            "milestones": self.state["milestones"],
            "approved_schemas": self.state["current_schemas"],
            "jurisdiction": self.state.get("jurisdiction"),
            "building_type": self.state.get("building_type"),
            "total_cost_usd": self.state.get("total_cost_usd", 0.0),
            "reflections": self.state.get("reflections", []),
        }

import tempfile
import pytest
from pathlib import Path

from src.memory.project_memory import ProjectMemory

def test_project_memory_init():
    with tempfile.TemporaryDirectory() as tmpdir:
        pm = ProjectMemory("test-proj", base_dir=tmpdir)
        assert pm.project_id == "test-proj"
        assert pm.root.exists()
        assert (pm.root / "state.json").exists()
        assert (pm.root / "schemas").exists()
        assert (pm.root / "outputs").exists()
        assert (pm.root / "messages.jsonl").exists()

def test_schema_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        pm = ProjectMemory("test-proj", base_dir=tmpdir)
        
        # Save new schema
        version = pm.save_schema("room_program", {"rooms": []})
        assert version == "v1"
        
        # Load it back
        data = pm.load_schema("room_program", "v1")
        assert data is not None
        assert data["rooms"] == []
        
        # Save update
        version2 = pm.save_schema("room_program", {"rooms": [{"id": 1}]})
        assert version2 == "v2"
        
        assert pm.get_latest_schema_version("room_program") == "v2"

def test_message_log():
    with tempfile.TemporaryDirectory() as tmpdir:
        pm = ProjectMemory("test-proj", base_dir=tmpdir)
        pm.log_message("agent_a", "status_update", {"status": "working", "task": "test"})
        
        msgs = pm.get_recent_messages(5)
        assert len(msgs) == 1
        assert msgs[0]["from"] == "agent_a"
        assert msgs[0]["message_type"] == "status_update"
        assert msgs[0]["payload"]["status"] == "working"

def test_milestone_approve():
    with tempfile.TemporaryDirectory() as tmpdir:
        pm = ProjectMemory("test-proj", base_dir=tmpdir)
        pm.approve_milestone("M1", "Notes here")
        
        summary = pm.get_project_summary()
        assert summary["milestones"]["M1"]["status"] == "approved"
        assert summary["milestones"]["M1"]["notes"] == "Notes here"

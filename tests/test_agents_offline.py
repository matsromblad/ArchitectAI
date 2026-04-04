import tempfile
import pytest
from unittest.mock import MagicMock

from src.memory.project_memory import ProjectMemory
from src.agents.base_agent import BaseAgent
from src.agents.pm_agent import PMAgent

class DummyAgent(BaseAgent):
    AGENT_ID = "dummy"
    def run(self, inputs):
        pass

def test_extract_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = ProjectMemory("test-proj", base_dir=tmpdir)
        agent = DummyAgent(memory)
        
        # Test clean json
        clean = agent._extract_json('{"key": "value"}')
        assert clean == {"key": "value"}
        
        # Test markdown wrapper
        wrapped = agent._extract_json("```json\n{\"key\": \"value\"}\n```")
        assert wrapped == {"key": "value"}
        
        # Test invalid
        with pytest.raises(ValueError):
            agent._extract_json("invalid json")

def test_pm_kickoff(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = ProjectMemory("test-proj", base_dir=tmpdir)
        pm = PMAgent(memory)
        
        # Mock chat to return a dummy response
        monkeypatch.setattr(pm, "chat", lambda **kwargs: '{"action": "proceed", "reason": "Looks good"}')
        
        res = pm.kickoff("prompt", {}, "SE")
        assert res["action"] == "proceed"
        assert memory.state["phase"] == "briefing"

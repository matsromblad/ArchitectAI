import tempfile

from src.memory.project_memory import ProjectMemory
from src.orchestration.pipeline import build_pipeline

def test_pipeline_graph_structure():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = ProjectMemory("test-proj", base_dir=tmpdir)
        graph = build_pipeline(memory)
        
        app = graph.compile()
        nodes = app.get_graph().nodes
        
        assert "pm_node" in nodes
        assert "brief_node" in nodes
        assert "architect_node" in nodes
        assert "structural_node" in nodes
        assert "mep_node" in nodes
        assert "ifc_builder_node" in nodes
        assert "qa_node" in nodes

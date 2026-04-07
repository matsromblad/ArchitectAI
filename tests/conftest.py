"""
conftest.py — shared pytest fixtures for ArchitectAI test suite.

Ensures test isolation for global singletons (KB loader, etc.)
so that one test's state cannot bleed into another.
"""

import pytest
from src.memory import kb_loader as _kb_loader_module


@pytest.fixture(autouse=True)
def isolate_kb_singleton():
    """
    Reset the KnowledgeBaseLoader singleton before and after every test.

    Without this, the first test that imports any agent (BriefAgent,
    ComplianceAgent, MEPAgent) locks in a KnowledgeBaseLoader that may
    point to the wrong kb_dir — causing intermittent failures in tests
    that need a clean or mocked KB.
    """
    _kb_loader_module.reset_loader()
    yield
    _kb_loader_module.reset_loader()

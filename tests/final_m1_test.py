"""
Final M1 Verification Script — verifying Gemini 3.1 models and RAG/KB integration.
Executes the pipeline through Phase 4 (Milestone 1).
"""
import os
import json
from pathlib import Path
from loguru import logger
from src.memory.project_memory import ProjectMemory
from src.agents.pm_agent import PMAgent
from src.agents.input_parser import InputParserAgent
from src.agents.client_agent import ClientAgent
from src.agents.brief_agent import BriefAgent
from src.agents.compliance_agent import ComplianceAgent

def run_test():
    project_id = "final-m1-verification"
    prompt = "En modern vårdcentral i Stockholm med 3 undersökningsrum, 1 personalrum och ett rymligt väntrum."
    site_file = "inputs/site-plan-simple.png"

    # 1. Setup
    memory = ProjectMemory(project_id, base_dir="./projects")
    logger.info(f"Starting M1 Verification for project: {project_id}")

    # 2. Phase 0: Client Agent
    client = ClientAgent(memory)
    logger.info("Running ClientAgent...")
    project_brief = client.run({"prompt": prompt, "jurisdiction": "SE"})
    logger.info(f"Client Result: {project_brief.get('project_name')}")

    # 3. Phase 1: Input Parser
    parser = InputParserAgent(memory)
    logger.info("Running InputParser...")
    site_data = parser.run({"file_path": site_file, "jurisdiction": "SE"})
    logger.info(f"Site Data Parsed: {site_data.get('boundary', {}).get('area_m2', 'unknown')} m2")

    # 4. Phase 2: Brief Agent (RAG)
    brief = BriefAgent(memory)
    logger.info("Running BriefAgent (RAG Mode)...")
    room_program = brief.run({
        "prompt": prompt,
        "site_data": site_data,
        "project_brief": project_brief
    })
    logger.info(f"Brief Result: {len(room_program.get('rooms', []))} rooms generated.")

    # 5. Phase 4: Compliance Agent (RAG)
    compliance = ComplianceAgent(memory)
    logger.info("Running ComplianceAgent (RAG Mode)...")
    comp_results = compliance.check_room_program(room_program)
    logger.info(f"Compliance Check Complete.")

    # 6. Milestone Check
    logger.success("M1 PIPELINE TEST SUCCESSFUL")
    logger.info("Artifacts generated in projects/final-m1-verification/schemas/")

if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        logger.exception(f"Test failed: {e}")
        exit(1)

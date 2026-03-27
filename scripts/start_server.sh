#!/bin/bash
PROJECT=${1:-test-01}
cd "$(dirname "$0")/.."
source .venv/bin/activate
echo "Starting ArchitectAI WebSocket server for project: $PROJECT"
PROJECTS_DIR=./projects python -m uvicorn src.server.ws_server:app --host 0.0.0.0 --port 8765 --reload

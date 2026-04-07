"""
WebSocket server — live dashboard bridge for ArchitectAI.

Watches project state.json for changes and broadcasts updates to all
connected dashboard clients. Also accepts user approvals from the dashboard.

Endpoints:
    GET  /                         → serve dashboard/index.html
    GET  /static/{path}            → serve dashboard/ files
    WS   /ws/{project_id}          → live state updates
    POST /approve/{project_id}     → accept user approval
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in PYTHONPATH so 'src' imports work when run as script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from loguru import logger

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    import uvicorn
    import subprocess
    import sys
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False
    logger.warning(
        "[ws_server] fastapi/uvicorn not installed — "
        "run: pip install fastapi uvicorn  to enable the dashboard server."
    )

try:
    from watchfiles import awatch
    _WATCHFILES_AVAILABLE = True
except ImportError:
    _WATCHFILES_AVAILABLE = False
    logger.warning(
        "[ws_server] watchfiles not installed — falling back to polling. "
        "Install with: pip install watchfiles"
    )

from src.memory.project_memory import ProjectMemory


PROJECTS_DIR = os.getenv("PROJECTS_DIR", "./projects")
DASHBOARD_DIR = os.getenv("DASHBOARD_DIR", "./dashboard")
POLL_INTERVAL_S = float(os.getenv("WS_POLL_INTERVAL", "2.0"))

# Known agent IDs — used to build the agents status map
ALL_AGENTS = [
    "pm", "brief", "input_parser", "compliance",
    "architect", "structural", "mep",
    "component_library", "ifc_builder", "qa",
]

# Schema types that appear in the Outputs tab
OUTPUT_SCHEMAS = [
    "room_program", "spatial_layout", "structural_schema",
    "mep_schema", "ifc_model",
]


# Module-level process tracking (must be before FastAPI app block)
_active_processes: dict = {}
_process_logs: dict = {}


if not _FASTAPI_AVAILABLE:
    # Provide a stub so the module is importable
    app = None  # type: ignore
else:
    app = FastAPI(title="ArchitectAI Dashboard Server", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ #
    # Connection manager                                                   #
    # ------------------------------------------------------------------ #

    class ConnectionManager:
        """Manages active WebSocket connections per project."""

        def __init__(self):
            # project_id → list of WebSocket connections
            self._connections: dict[str, list[WebSocket]] = {}

        async def connect(self, project_id: str, ws: WebSocket):
            await ws.accept()
            self._connections.setdefault(project_id, []).append(ws)
            logger.info(f"[ws_server] Client connected: project={project_id}, total={self.count(project_id)}")

        def disconnect(self, project_id: str, ws: WebSocket):
            connections = self._connections.get(project_id, [])
            if ws in connections:
                connections.remove(ws)
            logger.info(f"[ws_server] Client disconnected: project={project_id}")

        async def broadcast(self, project_id: str, message: dict):
            connections = self._connections.get(project_id, [])
            dead: list[WebSocket] = []
            payload = json.dumps(message, ensure_ascii=False)
            for ws in connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.disconnect(project_id, ws)

        def count(self, project_id: str) -> int:
            return len(self._connections.get(project_id, []))

    manager = ConnectionManager()

    # ------------------------------------------------------------------ #
    # State snapshot builder                                               #
    # ------------------------------------------------------------------ #

    def _build_state_broadcast(project_id: str) -> dict:
        """
        Build the full state broadcast payload for a project.

        Reads state.json + schema versions + recent messages.
        """
        try:
            mem = ProjectMemory(project_id, base_dir=PROJECTS_DIR)
            summary = mem.get_project_summary()
            recent_messages = mem.get_recent_messages(20)

            # Build per-agent status from recent messages
            agents: dict[str, str] = {agent_id: "waiting" for agent_id in ALL_AGENTS}
            for msg in recent_messages:
                from_agent = msg.get("from", "")
                if from_agent in agents:
                    payload = msg.get("payload", {})
                    status = payload.get("status", "")
                    if status in ("working", "done"):
                        agents[from_agent] = status

            # Build outputs map
            outputs: dict[str, dict] = {}
            for schema_type in OUTPUT_SCHEMAS:
                versions = mem.list_schema_versions(schema_type)
                if versions:
                    latest = versions[-1]
                    approved = summary.get("approved_schemas", {}).get(schema_type)
                    outputs[schema_type] = {
                        "version": latest,
                        "status": "approved" if approved else "draft",
                        "versions": versions,
                    }

            return {
                "type": "state_update",
                "project_id": project_id,
                "phase": summary.get("phase", "init"),
                "milestone": summary.get("milestone", 0),
                "agents": agents,
                "outputs": outputs,
                "recent_messages": recent_messages,
                "milestones": summary.get("milestones", {}),
                "jurisdiction": summary.get("jurisdiction"),
                "building_type": summary.get("building_type"),
                "total_cost_usd": summary.get("total_cost_usd", 0.0),
                "console_output": _process_logs.get(project_id, []),
                "timestamp": _now_iso(),
            }
        except Exception as exc:
            logger.error(f"[ws_server] Failed to build state for {project_id}: {exc}")
            return {
                "type": "error",
                "project_id": project_id,
                "error": str(exc),
            }

    # ------------------------------------------------------------------ #
    # Background watchers                                                  #
    # ------------------------------------------------------------------ #

    async def _watch_project_watchfiles(project_id: str):
        """Watch project directory for changes using watchfiles (inotify-based)."""
        project_dir = Path(PROJECTS_DIR) / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[ws_server] Watching (watchfiles): {project_dir}")
        async for changes in awatch(str(project_dir)):
            if manager.count(project_id) > 0:
                payload = _build_state_broadcast(project_id)
                await manager.broadcast(project_id, payload)

    async def _watch_project_poll(project_id: str):
        """Watch project directory by polling state.json mtime."""
        state_path = Path(PROJECTS_DIR) / project_id / "state.json"
        last_mtime: float = 0.0
        logger.info(f"[ws_server] Polling (interval={POLL_INTERVAL_S}s): {state_path}")
        while True:
            await asyncio.sleep(POLL_INTERVAL_S)
            try:
                if state_path.exists():
                    mtime = state_path.stat().st_mtime
                    if mtime != last_mtime:
                        last_mtime = mtime
                        if manager.count(project_id) > 0:
                            payload = _build_state_broadcast(project_id)
                            await manager.broadcast(project_id, payload)
            except Exception as exc:
                logger.warning(f"[ws_server] Poll error for {project_id}: {exc}")

    # Track per-project background tasks
    _watcher_tasks: dict[str, asyncio.Task] = {}

    def _ensure_watcher(project_id: str):
        """Start a background watcher task for a project if not already running."""
        if project_id in _watcher_tasks and not _watcher_tasks[project_id].done():
            return
        if _WATCHFILES_AVAILABLE:
            coro = _watch_project_watchfiles(project_id)
        else:
            coro = _watch_project_poll(project_id)
        task = asyncio.create_task(coro)
        _watcher_tasks[project_id] = task
        logger.info(f"[ws_server] Started watcher for project: {project_id}")

    # ------------------------------------------------------------------ #
    # Routes                                                               #
    # ------------------------------------------------------------------ #

    @app.get("/")
    async def serve_dashboard():
        """Serve the main dashboard HTML file."""
        index = Path(DASHBOARD_DIR) / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse(
            {"message": "ArchitectAI Dashboard Server — no dashboard/index.html found"},
            status_code=200,
        )

    # Mount static files if directory exists — available at both /static and /dashboard
    _dashboard_path = Path(DASHBOARD_DIR)
    if _dashboard_path.exists():
        app.mount("/static",    StaticFiles(directory=str(_dashboard_path)), name="static")
        app.mount("/dashboard", StaticFiles(directory=str(_dashboard_path)), name="dashboard")
        
    _website_path = Path(__file__).parent.parent.parent / "website"
    if _website_path.exists():
        app.mount("/website", StaticFiles(directory=str(_website_path)), name="website")

    @app.websocket("/ws/{project_id}")
    async def websocket_endpoint(websocket: WebSocket, project_id: str):
        """Live state updates for a project."""
        await manager.connect(project_id, websocket)
        _ensure_watcher(project_id)

        # Send current state immediately on connect
        try:
            initial = _build_state_broadcast(project_id)
            await websocket.send_text(json.dumps(initial, ensure_ascii=False))
        except Exception as exc:
            logger.warning(f"[ws_server] Failed to send initial state: {exc}")

        try:
            while True:
                # Listen for incoming messages from dashboard (e.g., approvals, pings)
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                    await _handle_client_message(project_id, msg)
                except json.JSONDecodeError:
                    logger.warning(f"[ws_server] Non-JSON message from client: {raw[:100]}")
        except WebSocketDisconnect:
            manager.disconnect(project_id, websocket)

    async def _handle_client_message(project_id: str, msg: dict):
        """Handle messages sent from the dashboard over WebSocket."""
        msg_type = msg.get("type", "")
        if msg_type == "approval":
            _write_approval(project_id, msg.get("response", "approved"))
            logger.info(f"[ws_server] Approval via WS for {project_id}: {msg.get('response')}")
        elif msg_type == "ping":
            pass  # silently ignore pings
        else:
            logger.debug(f"[ws_server] Unknown client message type: {msg_type}")

    class ApprovalRequest(BaseModel):
        response: str = "approved"
        notes: str = ""

    @app.post("/approve/{project_id}")
    async def approve_project(project_id: str, body: ApprovalRequest):
        """
        Accept a user approval decision from the dashboard (REST endpoint).

        Writes the response to a file that the pipeline reads.
        Also broadcasts an immediate state update.
        """
        _write_approval(project_id, body.response, body.notes)
        logger.info(f"[ws_server] Approval received for {project_id}: {body.response}")

        # Broadcast updated state
        payload = _build_state_broadcast(project_id)
        await manager.broadcast(project_id, payload)

        return {"status": "ok", "project_id": project_id, "response": body.response}

    @app.get("/state/{project_id}")
    async def get_state(project_id: str):
        """Return the current project state as JSON (for polling clients)."""
        return _build_state_broadcast(project_id)

    @app.get("/projects")
    async def list_projects():
        """List available project directories that have passed Phase 0 (client)."""
        import json
        projects_dir = Path(PROJECTS_DIR)
        projects = []
        if projects_dir.exists():
            for d in projects_dir.iterdir():
                state_file = d / "state.json"
                if d.is_dir() and state_file.exists():
                    try:
                        with open(state_file, 'r', encoding='utf-8') as f:
                            st = json.load(f)
                            # Only show projects that passed milestone 1 (client)
                            client_status = st.get("milestones", {}).get("client", {}).get("status")
                            if client_status in ("approved", "completed"):
                                projects.append(d.name)
                    except Exception:
                        pass
        return {"projects": projects}

    @app.get("/files/{project_id}")
    async def list_files(project_id: str):
        """List files in the project directory."""
        from fastapi.responses import JSONResponse
        import os, datetime
        p_dir = Path(PROJECTS_DIR) / project_id
        if not p_dir.exists():
            return JSONResponse({"files": []})
            
        files = []
        for file_path in p_dir.rglob("*"):
            if file_path.is_file() and file_path.name != "state.json":
                stat = file_path.stat()
                rel_path = file_path.relative_to(p_dir).as_posix()
                files.append({
                    "name": file_path.name,
                    "path": rel_path,
                    "size": stat.st_size,
                    "updated": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        return {"files": sorted(files, key=lambda f: f["updated"], reverse=True)}

    @app.get("/download/{project_id}/{file_path:path}")
    async def download_file(project_id: str, file_path: str):
        """Serve a file from the project directory."""
        from fastapi.responses import FileResponse, JSONResponse
        p_dir = Path(PROJECTS_DIR) / project_id
        target = p_dir / file_path
        if not target.exists() or not target.is_relative_to(p_dir):
            return JSONResponse({"error": "File not found"}, status_code=404)
        return FileResponse(str(target), filename=target.name)

    async def _read_stream(stream, project_id):
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode('utf-8', errors='replace').rstrip()
            if project_id not in _process_logs:
                _process_logs[project_id] = []
            _process_logs[project_id].append(text)
            if len(_process_logs[project_id]) > 200:
                _process_logs[project_id].pop(0)
                
            # Stream directly to dashboard without waiting for watchfiles
            if manager.count(project_id) > 0:
                try:
                    payload = _build_state_broadcast(project_id)
                    await manager.broadcast(project_id, payload)
                except Exception as e:
                    logger.debug(f"[_read_stream] broadcast failed: {e}")

    class LaunchPayload(BaseModel):
        projectName: str
        jurisdiction: str
        buildingType: str
        prompt: str
        siteDrawings: list
        governingDocs: list

    @app.post("/launch")
    async def launch_project(payload: LaunchPayload):
        """Stub for launching a project from the Web UI."""
        project_id = payload.projectName.lower().replace(" ", "-")
        
        # We need a fallback site file since the web ui currently simulates uploads
        site_file = "inputs/site-plan-simple.png"
        cwd = Path(__file__).parent.parent.parent
        
        if payload.siteDrawings and len(payload.siteDrawings) > 0:
            requested = f"inputs/{payload.siteDrawings[0].get('name', '')}"
            if (cwd / requested).exists():
                site_file = requested
            
        cmd = [
            sys.executable, "main.py",
            "--project-id", project_id,
            "--prompt", payload.prompt,
            "--site-file", site_file,
            "--jurisdiction", payload.jurisdiction
        ]
        
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["NO_COLOR"] = "1"
        env["FORCE_COLOR"] = "0"
        env["PYTHONIOENCODING"] = "utf-8"
            
        try:
            cwd = Path(__file__).parent.parent.parent
            logger.info(f"[ws_server] Launching: {' '.join(cmd)} in {cwd}")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.PIPE
            )
            _active_processes[project_id] = proc
            _process_logs[project_id] = [f"[launcher] Process started (pid={proc.pid})"]
            asyncio.create_task(_read_stream(proc.stdout, project_id))
            logger.info(f"[ws_server] main.py process started, pid={proc.pid}")
            
            return {"status": "ok", "project_id": project_id}
        except Exception as e:
            logger.error(f"Failed to launch main.py: {e}")
            raise HTTPException(status_code=500, detail=str(e))
            
    @app.post("/approve/{project_id}")
    async def approve_milestone(project_id: str):
        proc = _active_processes.get(project_id)
        if not proc or proc.returncode is not None:
            raise HTTPException(status_code=400, detail="No active process or process already exited.")
        
        try:
            proc.stdin.write(b'\n')
            await proc.stdin.drain()
            return {"status": "approved"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------ #
    # Approval file helper                                                 #
    # ------------------------------------------------------------------ #

    def _write_approval(project_id: str, response: str, notes: str = ""):
        """
        Write the user approval response to a file so the pipeline can read it.

        The pipeline's user_approval_node checks for this file.
        """
        project_dir = Path(PROJECTS_DIR) / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        approval_path = project_dir / "user_approval.json"
        approval_path.write_text(
            json.dumps({
                "response": response,
                "notes": notes,
                "timestamp": _now_iso(),
            }, indent=2),
            encoding="utf-8",
        )

    def _now_iso() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Entry point                                                                   #
# --------------------------------------------------------------------------- #

def serve(host: str = "0.0.0.0", port: int = 8765, reload: bool = False):
    """Start the WebSocket/HTTP server."""
    if not _FASTAPI_AVAILABLE:
        raise ImportError(
            "fastapi and uvicorn are required. "
            "Install with: pip install fastapi uvicorn"
        )
    logger.info(f"[ws_server] Starting ArchitectAI server on {host}:{port}")
    uvicorn.run(
        "src.server.ws_server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8765"))
    serve(host=host, port=port)

"""
Brief Agent — generates room_program.json from user prompt + site data
"""

import json
from datetime import datetime, timezone

from loguru import logger

from src.agents.base_agent import BaseAgent


SYSTEM_PROMPT = """You are the Brief Agent for ArchitectAI. Output ONLY valid JSON, no prose.

Schema:
{"building_type":"healthcare","jurisdiction":"SE","rooms":[{"room_id":"R01a","room_name":"Patient Bedroom A","quantity":1,"zone":"clean","access_type":"restricted","min_area_m2":18.0,"width_hint_m":4.5,"depth_hint_m":4.0,"adjacencies":["R02a"],"compliance_flag":false,"notes":"SS 91 42 21"}],"total_net_area_m2":0,"clean_dirty_separation":"<100 chars>"}

Rules:
- JSON only. No corridors (code adds them). No markdown.
- zone: clean|dirty|staff|public|service
- Each bedroom=separate entry R01a..R01j, quantity=1
- Each ensuite=separate entry R02a..R02j — zone=dirty, adjacency to its bedroom only
- Isolation room: zone=clean, access only via anteroom
- Anteroom: zone=clean, connects corridor↔isolation room
- Isolation ensuite: zone=dirty, connects to isolation room only
- notes: max 40 chars
- Keep adjacencies minimal — code enforces corridor links automatically
"""


class BriefAgent(BaseAgent):
    AGENT_ID = "brief"
    DEFAULT_MODEL = "claude-sonnet-4-6"

    def run(self, inputs: dict) -> dict:
        """
        Generate a room program from user prompt and site data.

        Args:
            inputs: {
                "prompt": str,          # User's building brief
                "site_data": dict,      # From InputParserAgent
                "jurisdiction": str,    # e.g. "SE"
            }

        Returns:
            room_program dict
        """
        prompt         = inputs["prompt"]
        site_data      = inputs.get("site_data", {})
        jurisdiction   = inputs.get("jurisdiction", site_data.get("jurisdiction", "SE"))
        qa_feedback    = inputs.get("qa_feedback")
        project_brief  = inputs.get("project_brief", {})

        attempt_label = "REVISION" if qa_feedback else "INITIAL"
        logger.info(f"[{self.AGENT_ID}] [{attempt_label}] Generating room program for: {prompt[:80]}...")
        self.send_message("pm", "status_update", {"status": "working", "task": f"Room program ({attempt_label})"})

        feedback_section = ""
        if qa_feedback:
            # TOKEN-OPT: Compact delta-feedback on revision — only include what changed.
            # Full QA JSON can be 500+ chars; we extract only the actionable issues.
            if isinstance(qa_feedback, dict):
                issues = qa_feedback.get("issues", [])
                fix_instr = qa_feedback.get("fix_instructions", "")
                issues_text = "\n".join(f"- {i}" for i in issues[:6]) if issues else str(qa_feedback)[:150]
                fix_text = fix_instr[:150] if fix_instr else ""
            else:
                issues_text = str(qa_feedback)[:200]
                fix_text = ""
            feedback_section = f"""
REVISION — fix ONLY these QA issues:
{issues_text}
{("Fix: " + fix_text) if fix_text else ""}
Keep all rooms from previous version. Minimal changes only."""

        # Extract client brief parameters
        prog = project_brief.get("programme", {})
        size = project_brief.get("size", {})
        standards = project_brief.get("applicable_standards", ["SS 91 42 21", "BBR 2023"])
        constraints = project_brief.get("constraints", {})

        # TOKEN-OPT: On revision, send a compact delta-prompt instead of full brief.
        # The LLM already has the schema shape from the system prompt — no need to repeat it.
        if qa_feedback:
            # Revision prompt: just the project ID + what to fix
            user_message = f"""Project: {self.memory.project_id} ({jurisdiction})
{feedback_section}
Output corrected room_program JSON. Same rooms, fix only the listed issues."""
        else:
            # Initial prompt: full context needed
            user_message = f"""User request: "{prompt}"

Project parameters (from Client Agent):
- Building type: {project_brief.get('building_type', 'healthcare')}
- Jurisdiction: {jurisdiction} ({project_brief.get('jurisdiction_name', 'Sweden')})
- Target net area: {size.get('target_net_area_m2', 280)} m²
- Target gross area: {size.get('target_gross_area_m2', 420)} m²
- Patient beds: {prog.get('patient_beds', 4)}
- Key rooms required: {', '.join(prog.get('key_rooms', [])[:6])}
- Isolation rooms: {constraints.get('isolation_rooms_required', 1)}
- Standards: {', '.join(standards[:3])}
- Min corridor width: {constraints.get('min_corridor_width_m', 2.4)} m

Generate compact room program JSON. Max 25 rooms. Short strings. No corridors."""

        response = self.chat(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=4000,
        )

        room_program = self._extract_json(response)
        # Unwrap nested structure if Claude returned {"room_program": {...}}
        if "room_program" in room_program and isinstance(room_program["room_program"], dict):
            room_program = room_program["room_program"]

        # ── Code-level sanitisation (fixes common LLM inconsistencies) ──────
        rooms = room_program.get("rooms", [])
        for r in rooms:
            # Ensure min_area >= width_hint * depth_hint
            w = float(r.get("width_hint_m") or 0)
            d = float(r.get("depth_hint_m") or 0)
            if w > 0 and d > 0:
                hint_area = round(w * d, 2)
                if hint_area < float(r.get("min_area_m2", 0)):
                    # Fix dims to match area
                    target = float(r["min_area_m2"])
                    r["depth_hint_m"] = round(target / w, 2)
            # Remove duplicate area fields — keep only min_area_m2
            r.pop("area_m2", None)
            # Ensure zone is valid
            valid_zones = {"clean", "dirty", "staff", "public", "service", "restricted"}
            if r.get("zone") not in valid_zones:
                r["zone"] = "staff"
            # Make adjacency lists bidirectional
            # (we do a second pass below)
        
        # Second pass: enforce bidirectional adjacencies
        room_by_id = {r.get("room_id"): r for r in rooms if r.get("room_id")}
        for r in rooms:
            rid = r.get("room_id")
            if not rid:
                continue
            for adj_id in list(r.get("adjacencies", [])):
                adj = room_by_id.get(adj_id)
                if adj is not None:
                    adj_list = adj.setdefault("adjacencies", [])
                    if rid not in adj_list:
                        adj_list.append(rid)

        # Authoritative area calculation (single field, no duplicates)
        total = round(sum(
            float(r.get("min_area_m2", 0)) * int(r.get("quantity", 1))
            for r in rooms
        ), 1)

        # ── Auto-inject mandatory infrastructure rooms if not already present ──
        INFRA_KW = {
            "stair": {"kw": ["stair","trappa","egress stair"], "id": "R_ST01",
                      "name": "Primary Stair + Core", "zone": "staff",
                      "min_area_m2": 14.0, "width_hint_m": 2.8, "depth_hint_m": 5.0},
            "lift":  {"kw": ["lift","elevator","hiss","bed lift"], "id": "R_LF01",
                      "name": "Bed Lift", "zone": "staff",
                      "min_area_m2": 5.5, "width_hint_m": 2.2, "depth_hint_m": 2.5},
            "entry": {"kw": ["entry","entrance","reception","lobby","entré","mottagning"],
                      "id": "R_ENT", "name": "Ward Entrance / Reception",
                      "zone": "public", "min_area_m2": 12.0, "width_hint_m": 4.0, "depth_hint_m": 3.0},
            "corridor": {"kw": ["corridor","korridor","hallway","circulation","gang"],
                         "id": "R_COR", "name": "Ward Corridor Spine",
                         "zone": "staff",
                         "min_area_m2": 60.0, "width_hint_m": 2.4, "depth_hint_m": 25.0},
        }
        existing_names = " ".join((r.get("room_name") or r.get("name") or "").lower() for r in rooms)
        for infra_type, cfg in INFRA_KW.items():
            if not any(kw in existing_names for kw in cfg["kw"]):
                rooms.append({
                    "room_id": cfg["id"],
                    "room_name": cfg["name"],
                    "quantity": 1,
                    "zone": cfg["zone"],
                    "access_type": cfg["zone"],
                    "min_area_m2": cfg["min_area_m2"],
                    "width_hint_m": cfg["width_hint_m"],
                    "depth_hint_m": cfg["depth_hint_m"],
                    "adjacencies": [],
                    "compliance_flag": False,
                    "notes": "Auto-added by Brief Agent — mandatory for SE healthcare",
                })
                logger.info(f"[{self.AGENT_ID}] Auto-injected {cfg['name']}")

        # ── Fix zone for ensuites: bathrooms/WCs are "clean" not "dirty" ──
        # SE vårdhygien: ensuiter/toaletter/duschar = "dirty" (oren zon).
        # Ensure ensuites are correctly marked dirty, and remove their corridor adjacency
        # (they are only accessed from the bedroom, never directly from corridor).
        room_by_id = {r["room_id"]: r for r in rooms if r.get("room_id")}
        for r in rooms:
            name_lower = (r.get("room_name") or "").lower()
            if any(kw in name_lower for kw in ["ensuite", "bathroom", "wc", "toalett", "badrum", "shower", "dusch"]):
                # Force dirty zone
                if r.get("zone") != "dirty":
                    r["zone"] = "dirty"
                    logger.info(f"[{self.AGENT_ID}] Zoned {r['room_id']} ({r['room_name']}) → dirty (SE hygiene)")
                # Remove any corridor adjacency — ensuites accessed via bedroom only
                r["adjacencies"] = [a for a in r.get("adjacencies", []) if a != "R_COR"]

        # ── Identify isolation cluster: anteroom + isolation room + isolation ensuite ──
        # Rules:
        #   - Isolation room (R03) connects ONLY to its anteroom (R04) — no direct corridor
        #   - Anteroom (R04) connects to corridor and isolation room
        #   - Isolation ensuite (R05) connects ONLY to isolation room — no direct corridor
        iso_room   = next((r for r in rooms if "isolation" in (r.get("room_name") or "").lower()
                           and "anteroom" not in (r.get("room_name") or "").lower()
                           and "ensuite"  not in (r.get("room_name") or "").lower()), None)
        anteroom   = next((r for r in rooms if "anteroom" in (r.get("room_name") or "").lower()
                           or "förrum"    in (r.get("room_name") or "").lower()), None)
        iso_ensuite = next((r for r in rooms if "ensuite" in (r.get("room_name") or "").lower()
                            and "isolation" in (r.get("room_name") or "").lower()), None)

        # IDs of rooms that must NOT get a direct corridor link
        no_corridor_direct = set()
        if iso_room:
            no_corridor_direct.add(iso_room["room_id"])
        if iso_ensuite:
            no_corridor_direct.add(iso_ensuite["room_id"])

        # Wire isolation cluster correctly
        if iso_room and anteroom:
            # Anteroom ↔ iso_room (bidirectional, no corridor for iso_room)
            ar_id = anteroom["room_id"]
            ir_id = iso_room["room_id"]
            anteroom.setdefault("adjacencies", [])
            iso_room.setdefault("adjacencies", [])
            if ir_id not in anteroom["adjacencies"]:
                anteroom["adjacencies"].append(ir_id)
            iso_room["adjacencies"] = [ar_id]   # ONLY anteroom
            logger.info(f"[{self.AGENT_ID}] Isolation cluster: {ir_id} wired exclusively to anteroom {ar_id}")

        if iso_ensuite and iso_room:
            ie_id  = iso_ensuite["room_id"]
            ir_id  = iso_room["room_id"]
            iso_ensuite["adjacencies"] = [ir_id]  # ONLY iso room
            if ie_id not in iso_room["adjacencies"]:
                iso_room["adjacencies"].append(ie_id)
            logger.info(f"[{self.AGENT_ID}] Isolation ensuite {ie_id} wired exclusively to {ir_id}")

        # ── Wire bedroom ↔ ensuite pairs ──
        # Ensuites (R02a, R02b…) must be adjacent to their bedroom (R01a, R01b…).
        # The LLM sometimes orphans them after zone corrections.
        for r in rooms:
            rid = r.get("room_id", "")
            name_lower = (r.get("room_name") or "").lower()
            # Patient ensuite pattern: R02a, R02b, etc.
            if rid.startswith("R02") and len(rid) == 4:
                suffix = rid[-1]   # a, b, c…
                bed_id = f"R01{suffix}"
                bed_room = room_by_id.get(bed_id)
                if bed_room:
                    r.setdefault("adjacencies", [])
                    bed_room.setdefault("adjacencies", [])
                    if bed_id not in r["adjacencies"]:
                        r["adjacencies"].append(bed_id)
                    if rid not in bed_room["adjacencies"]:
                        bed_room["adjacencies"].append(rid)

        # ── Post-inject: wire corridor to rooms (skip isolation cluster internals) ──
        cor_room = next((r for r in rooms if r.get("room_id") == "R_COR"), None)
        if cor_room:
            cor_id = cor_room["room_id"]
            cor_adjs = cor_room.setdefault("adjacencies", [])
            for r in rooms:
                rid = r.get("room_id")
                if not rid or rid == cor_id:
                    continue
                # Skip rooms that must not have direct corridor access
                if rid in no_corridor_direct:
                    continue
                # Skip ALL ensuites/bathrooms — accessed via bedroom only, not corridor
                r_name_lower = (r.get("room_name") or "").lower()
                if any(kw in r_name_lower for kw in ["ensuite", "bathroom", "wc", "toalett", "badrum", "shower", "dusch"]):
                    continue
                if iso_ensuite and rid == iso_ensuite.get("room_id"):
                    continue
                r_adjs = r.setdefault("adjacencies", [])
                if cor_id not in r_adjs:
                    r_adjs.append(cor_id)
                if rid not in cor_adjs:
                    cor_adjs.append(rid)
            logger.info(f"[{self.AGENT_ID}] Corridor R_COR wired to {len(cor_adjs)} rooms")

        # ── Remove illegal clean↔dirty adjacencies EXCEPT bedroom↔ensuite ──
        # Legal: bedroom (clean) ↔ ensuite (dirty) — ensuite is a private wet room of the bed
        # Illegal: clean utility ↔ dirty utility (shared service wall with door)
        for r in rooms:
            fixed_adjs = []
            r_name = (r.get("room_name") or "").lower()
            r_zone = r.get("zone")
            for adj_id in r.get("adjacencies", []):
                adj_room = room_by_id.get(adj_id)
                adj_zone = adj_room.get("zone") if adj_room else None
                adj_name = (adj_room.get("room_name") or "").lower() if adj_room else ""
                is_illegal = (r_zone == "clean" and adj_zone == "dirty") or (r_zone == "dirty" and adj_zone == "clean")
                if is_illegal:
                    # Allow bedroom↔ensuite (private connection)
                    is_bedroom = any(k in r_name for k in ["bedroom", "patient room", "patientrum"])
                    is_ensuite = any(k in adj_name for k in ["ensuite", "wc", "bathroom", "toalett", "badrum", "shower"])
                    is_ensuite_to_bed = any(k in r_name for k in ["ensuite", "wc", "bathroom", "toalett", "badrum", "shower"]) and \
                                        any(k in adj_name for k in ["bedroom", "patient room", "patientrum", "isolation"])
                    if is_bedroom and is_ensuite:
                        fixed_adjs.append(adj_id)
                        continue
                    if is_ensuite_to_bed:
                        fixed_adjs.append(adj_id)
                        continue
                    logger.info(f"[{self.AGENT_ID}] Removed illegal clean↔dirty adjacency: {r['room_id']} ↔ {adj_id}")
                    continue
                fixed_adjs.append(adj_id)
            r["adjacencies"] = fixed_adjs

        # Remove conflicting area fields — leave only total_net_area_m2
        total = round(sum(
            float(r.get("min_area_m2", 0)) * int(r.get("quantity", 1))
            for r in rooms
        ), 1)

        for key in ("total_area_m2", "total_gross_area_m2", "total_net_area_m2"):
            room_program.pop(key, None)
        room_program["total_net_area_m2"] = total
        room_program["gross_area_m2"] = round(total * 1.5, 1)   # healthcare = 1.5
        room_program["gross_factor"] = 1.5
        room_program["rooms"] = rooms

        room_program["project_id"] = self.memory.project_id
        room_program["jurisdiction"] = jurisdiction
        room_program["created_at"] = datetime.now(timezone.utc).isoformat()
        room_program["created_by"] = self.AGENT_ID
        room_program.pop("compliance_queries", None)

        version = self.memory.save_schema("room_program", room_program)
        logger.success(f"[{self.AGENT_ID}] room_program saved as {version} — {len(room_program.get('rooms', []))} rooms, {total:.0f} m² total")

        self.send_message("pm", "status_update", {
            "status": "done",
            "schema": "room_program",
            "version": version,
            "summary": f"{len(room_program.get('rooms', []))} rooms, {total:.0f} m²",
        })

        return room_program

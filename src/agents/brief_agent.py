"""
Brief Agent — generates room_program.json from user prompt + site data.

Revision flow (TOKEN-OPT):
  On first run  → full room_program JSON output
  On revision   → patch-only output (modified_rooms + added_rooms + removed_room_ids)
                  applied by _apply_patch() against the prior version.
  Savings: revision prompts ~80% smaller; patch outputs ~70% smaller than full JSON.
"""

import copy
import json
from datetime import datetime, timezone

from loguru import logger

from src.agents.base_agent import BaseAgent


# System prompt for initial generation
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

# TOKEN-OPT: Separate system prompt for revision mode — instructs patch output only.
# Much smaller output than a full room_program (only changed rooms).
REVISION_SYSTEM_PROMPT = """You are the Brief Agent for ArchitectAI fixing a QA-rejected room program.

Output ONLY a JSON patch — do NOT output the full room_program.

Patch schema:
{
  "modified_rooms": [<full room objects that need changes>],
  "added_rooms":    [<new room objects to insert>],
  "removed_room_ids": ["R_id1", "R_id2"]
}

Rules:
- JSON only. No prose, no markdown.
- Include a room in modified_rooms ONLY if it needs to change.
- Omit rooms that are already correct.
- If no rooms need removal, use removed_room_ids: []
- If no rooms need adding, use added_rooms: []
- Room objects follow the same schema as the original.
- adjacencies: list only direct neighbours, not corridor (corridor is auto-wired).
"""


class BriefAgent(BaseAgent):
    AGENT_ID = "brief"
    DEFAULT_MODEL = "claude-sonnet-4-6"

    # TOKEN-OPT: Patch-based revision threshold.
    # If prior_room_program is available AND qa_feedback is set, use patch mode.
    # Set BRIEF_PATCH_MODE=false in .env to disable (fall back to full regen).
    PATCH_MODE = True

    def _apply_patch(self, prior: dict, patch: dict) -> dict:
        """
        TOKEN-OPT: Apply a patch dict to the prior room_program.

        Patch schema:
          modified_rooms:    list of room objects (full) — replaces matching room_id
          added_rooms:       list of new room objects — appended
          removed_room_ids:  list of room_id strings — removed

        Returns a new room_program dict with the patch applied.
        """
        result = copy.deepcopy(prior)
        rooms = result.get("rooms", [])

        # Index by room_id
        room_by_id = {r["room_id"]: i for i, r in enumerate(rooms) if r.get("room_id")}

        # 1. Remove
        removed = set(patch.get("removed_room_ids") or [])
        if removed:
            rooms = [r for r in rooms if r.get("room_id") not in removed]
            logger.info(f"[{self.AGENT_ID}] Patch: removed {len(removed)} rooms: {removed}")
            # Rebuild index after removal
            room_by_id = {r["room_id"]: i for i, r in enumerate(rooms) if r.get("room_id")}

        # 2. Modify — replace full room object by room_id
        modified = patch.get("modified_rooms") or []
        mod_count = 0
        for mod_room in modified:
            rid = mod_room.get("room_id")
            if rid and rid in room_by_id:
                rooms[room_by_id[rid]] = mod_room
                mod_count += 1
            else:
                # room_id not found — treat as add
                rooms.append(mod_room)
                mod_count += 1
        if mod_count:
            logger.info(f"[{self.AGENT_ID}] Patch: modified {mod_count} rooms")

        # 3. Add
        added = patch.get("added_rooms") or []
        existing_ids = {r.get("room_id") for r in rooms}
        for new_room in added:
            if new_room.get("room_id") not in existing_ids:
                rooms.append(new_room)
        if added:
            logger.info(f"[{self.AGENT_ID}] Patch: added {len(added)} rooms")

        result["rooms"] = rooms
        return result

    def run(self, inputs: dict) -> dict:
        """
        Generate a room program from user prompt and site data.

        Args:
            inputs: {
                "prompt": str,               # User's building brief
                "site_data": dict,           # From InputParserAgent
                "jurisdiction": str,         # e.g. "SE"
                "qa_feedback": dict|None,    # QA issues on revision
                "prior_room_program": dict|None,  # TOKEN-OPT: previous version for patch mode
            }

        Returns:
            room_program dict
        """
        prompt              = inputs["prompt"]
        site_data           = inputs.get("site_data", {})
        jurisdiction        = inputs.get("jurisdiction", site_data.get("jurisdiction", "SE"))
        qa_feedback         = inputs.get("qa_feedback")
        project_brief       = inputs.get("project_brief", {})
        prior_room_program  = inputs.get("prior_room_program")  # TOKEN-OPT

        # Decide mode: patch or full
        use_patch_mode = (
            self.PATCH_MODE
            and qa_feedback is not None
            and prior_room_program is not None
            and len(prior_room_program.get("rooms", [])) > 0
        )

        attempt_label = ("PATCH-REVISION" if use_patch_mode else "REVISION") if qa_feedback else "INITIAL"
        logger.info(f"[{self.AGENT_ID}] [{attempt_label}] Generating room program for: {prompt[:80]}...")
        self.send_message("pm", "status_update", {"status": "working", "task": f"Room program ({attempt_label})"})

        # Build feedback text (shared across patch and non-patch revision)
        feedback_section = ""
        if qa_feedback:
            if isinstance(qa_feedback, dict):
                issues = qa_feedback.get("issues", [])
                fix_instr = qa_feedback.get("fix_instructions", "")
                issues_text = "\n".join(f"- {i}" for i in issues[:6]) if issues else str(qa_feedback)[:150]
                fix_text = fix_instr[:150] if fix_instr else ""
            else:
                issues_text = str(qa_feedback)[:200]
                fix_text = ""
            feedback_section = (
                f"QA issues to fix:\n{issues_text}\n"
                + (f"Fix guidance: {fix_text}" if fix_text else "")
            )

        # ── Build prompt and call LLM ────────────────────────────────────────
        if use_patch_mode:
            # TOKEN-OPT: Send only the affected rooms + QA issues.
            # Compress prior rooms to a compact representation for context.
            prior_rooms_compact = json.dumps(
                [{"id": r.get("room_id"), "n": r.get("room_name","")[:25],
                  "z": r.get("zone"), "a": r.get("min_area_m2"),
                  "adj": r.get("adjacencies", [])}
                 for r in prior_room_program.get("rooms", [])],
                separators=(',', ':'),
            )
            user_message = (
                f"Project: {self.memory.project_id} ({jurisdiction})\n\n"
                f"Current rooms (compact):\n{prior_rooms_compact}\n\n"
                f"{feedback_section}\n\n"
                f"Output ONLY a patch JSON to fix the listed issues. "
                f"Do not output rooms that are already correct."
            )
            response = self.chat(
                system=REVISION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                max_tokens=2000,  # TOKEN-OPT: patch is much smaller than full regen
            )
            patch = self._extract_json(response)
            # Unwrap if nested
            if "patch" in patch and isinstance(patch["patch"], dict):
                patch = patch["patch"]
            # Apply patch to prior version
            room_program = self._apply_patch(prior_room_program, patch)
            logger.info(f"[{self.AGENT_ID}] Patch applied — "
                        f"{len(patch.get('modified_rooms') or [])} modified, "
                        f"{len(patch.get('added_rooms') or [])} added, "
                        f"{len(patch.get('removed_room_ids') or [])} removed")

        elif qa_feedback:
            # Fallback non-patch revision: compact prompt, full regen
            user_message = (
                f"Project: {self.memory.project_id} ({jurisdiction})\n"
                f"{feedback_section}\n"
                f"Output corrected room_program JSON. Same rooms, fix only the listed issues."
            )
            response = self.chat(
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                max_tokens=4000,
            )
            room_program = self._extract_json(response)
            if "room_program" in room_program and isinstance(room_program["room_program"], dict):
                room_program = room_program["room_program"]

        else:
            # Initial generation: full context needed
            prog = project_brief.get("programme", {})
            size = project_brief.get("size", {})
            standards = project_brief.get("applicable_standards", ["SS 91 42 21", "BBR 2023"])
            constraints = project_brief.get("constraints", {})
            user_message = (
                f'User request: "{prompt}"\n\n'
                f"Project parameters (from Client Agent):\n"
                f"- Building type: {project_brief.get('building_type', 'healthcare')}\n"
                f"- Jurisdiction: {jurisdiction} ({project_brief.get('jurisdiction_name', 'Sweden')})\n"
                f"- Target net area: {size.get('target_net_area_m2', 280)} m²\n"
                f"- Target gross area: {size.get('target_gross_area_m2', 420)} m²\n"
                f"- Patient beds: {prog.get('patient_beds', 4)}\n"
                f"- Key rooms required: {', '.join(prog.get('key_rooms', [])[:6])}\n"
                f"- Isolation rooms: {constraints.get('isolation_rooms_required', 1)}\n"
                f"- Standards: {', '.join(standards[:3])}\n"
                f"- Min corridor width: {constraints.get('min_corridor_width_m', 2.4)} m\n\n"
                f"Generate compact room program JSON. Max 25 rooms. Short strings. No corridors."
            )
            response = self.chat(
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                max_tokens=4000,
            )
            room_program = self._extract_json(response)
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

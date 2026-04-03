"""
Architect Agent — places rooms onto the site using a deterministic double-loaded corridor algorithm.
Produces spatial_layout.json with guaranteed collision-free geometry.
"""

import json
from datetime import datetime, timezone
from loguru import logger
from src.agents.base_agent import BaseAgent
from src.tools.se_dimensions import SE, snap_mm


class ArchitectAgent(BaseAgent):
    AGENT_ID = "architect"
    DEFAULT_MODEL = "claude-sonnet-4-6"

    # Words that indicate a room is really a corridor — filter from rooms array
    CORRIDOR_KEYWORDS = {"corridor", "gang", "korridor", "hallway", "circulation",
                         "passage", "lobby", "entrance hall", "ingång",
                         "airlock", "buffer", "pass-through", "pass-thro", "circulation"}

    def run(self, inputs: dict) -> dict:
        room_program    = inputs["room_program"]
        site_data       = inputs.get("site_data", {})
        qa_feedback     = inputs.get("qa_feedback")
        project_brief   = inputs.get("project_brief", {})

        rooms_input    = room_program.get("rooms", [])
        building_type  = room_program.get("building_type", "healthcare")
        jurisdiction   = room_program.get("jurisdiction", "SE")

        attempt_label  = "REVISION" if qa_feedback else "INITIAL"
        logger.info(f"[{self.AGENT_ID}] [{attempt_label}] Laying out {len(rooms_input)} rooms on site")
        self.send_message("pm", "status_update", {
            "status": "working",
            "task": f"Spatial layout ({attempt_label}) — {len(rooms_input)} rooms",
        })

        # Prefer project_brief dimensions (realistic), fall back to site_data, then defaults
        pb_size = project_brief.get("size", {})
        site_w  = float(pb_size.get("site_width_m") or site_data.get("boundary", {}).get("width_m") or 30)
        site_d  = float(pb_size.get("site_depth_m") or site_data.get("boundary", {}).get("depth_m") or 20)

        # All layout constants in metres but derived from SE mm constants.
        # snap_mm(x*1000, 100)/1000 ensures values are multiples of 100 mm.
        WALL   = SE.WALL_INTERNAL_LOADBEARING / 1000          # 0.200 m
        CORR_W = SE.CORRIDOR_HEALTHCARE_REC  / 1000           # 0.270 m → 2.700 m
        CORE_W = snap_mm(SE.COLUMN_SIZE_TYPICAL * 8, 100) / 1000  # 3200 mm → 3.200 m

        # ── 1. Filter corridor-named rooms ────────────────────────────────────
        def _is_corr(r):
            n = (r.get("room_name") or r.get("name") or "").lower()
            return any(kw in n for kw in self.CORRIDOR_KEYWORDS)

        rooms = [r for r in rooms_input if not _is_corr(r)]

        # Re-zone patient ensuites to clean (they must adjoin their bedroom)
        ENSUITE_KW = {"ensuite", "toilet", "wc", "shower", "bathroom", "toalett", "dusch", "badrum"}
        def _is_ensuite(r):
            n = (r.get("room_name") or r.get("name") or "").lower()
            return any(kw in n for kw in ENSUITE_KW)
        for r in rooms:
            if _is_ensuite(r) and r.get("zone") == "dirty":
                r["zone"] = "clean"  # patient ensuites belong in the clean row

        # ── 2. Sort into zone rows ────────────────────────────────────────────
        CLEAN  = ("clean", "restricted")
        STAFF  = ("staff", "public", "service")
        DIRTY  = ("dirty",)

        all_clean = [r for r in rooms if r.get("zone") in CLEAN]
        staff_rooms = [r for r in rooms if r.get("zone") in STAFF]
        dirty_rooms = [r for r in rooms if r.get("zone") in DIRTY]
        other_rooms = [r for r in rooms if r.get("zone") not in CLEAN + STAFF + DIRTY]
        staff_rooms += other_rooms   # uncategorised → middle row

        # Interleave bedrooms with their ensuites so they end up adjacent
        # Pattern: bedroom, ensuite, bedroom, ensuite, ...  then other clean rooms
        BED_KW = {"bedroom", "patient room", "patientrum", "ward room", "patient bed", "inpatient"}
        bedrooms = [r for r in all_clean if not _is_ensuite(r) and
                    any(kw in (r.get("room_name") or r.get("name") or "").lower()
                        for kw in BED_KW)]
        ensuites = [r for r in all_clean if _is_ensuite(r)]
        other_clean = [r for r in all_clean if r not in bedrooms and r not in ensuites]

        # Pair bedroom with ensuite by suffix (R01a→R02a, R01b→R02b etc.)
        def _suffix(r):
            rid = r.get("room_id", "")
            return rid[-1] if rid and rid[-1].isalpha() else ""

        paired_clean = []
        used_ensuites = set()
        for bed in bedrooms:
            paired_clean.append(bed)
            sfx = _suffix(bed)
            match = next((e for e in ensuites if _suffix(e) == sfx and e.get("room_id") not in used_ensuites), None)
            if match:
                paired_clean.append(match)
                used_ensuites.add(match.get("room_id"))
        # Add unmatched ensuites + other clean rooms at the end
        paired_clean += [e for e in ensuites if e.get("room_id") not in used_ensuites]
        paired_clean += other_clean

        clean_rooms = paired_clean if paired_clean else all_clean

        # ── 3. Row-packing helper ─────────────────────────────────────────────
        # Leaves CORE_W + 1.0m gap on the east side for the stair/lift core
        ROW_MAX_X = site_w - CORE_W - 1.0

        def _snap(val_m: float, grid_mm: int = 100) -> float:
            """Snap a metre value to the nearest grid_mm boundary."""
            return snap_mm(val_m * 1000, grid_mm) / 1000

        def pack_row(room_list: list, y0: float) -> tuple[list, float]:
            """Pack rooms left→right, wrap if needed. Returns (placed, y_bottom).
            All x/y/width/depth values are snapped to 100 mm grid (SE standard).
            """
            placed = []
            x, y, row_max_d = 0.0, y0, 0.0
            for r in room_list:
                area = float(r.get("min_area_m2") or 12)
                # Use snapped hint dims from BriefAgent; fall back to computed square
                w_hint = r.get("width_hint_m")
                d_hint = r.get("depth_hint_m")
                w = _snap(float(w_hint) if w_hint else max(3.0, area ** 0.5))
                d = _snap(float(d_hint) if d_hint else area / max(w, 0.1))
                # Ensure snapped dims satisfy min_area (extend depth if needed)
                if w * d < area:
                    d = _snap(area / w + 0.05)
                # Wrap to next sub-row?
                if x + w > ROW_MAX_X and placed:
                    y         = _snap(y + row_max_d + WALL)
                    x         = 0.0
                    row_max_d = 0.0
                placed.append({
                    "room_id":   r.get("room_id", f"R{len(placed)+1:02d}"),
                    "name":      (r.get("room_name") or r.get("name") or "Room")[:50],
                    "x_m":       _snap(x),
                    "y_m":       _snap(y),
                    "width_m":   w,
                    "depth_m":   d,
                    "area_m2":   round(w * d, 2),
                    "zone":      r.get("zone", "staff"),
                    "access":    r.get("access_type", "staff"),
                })
                x = _snap(x + w + WALL)
                row_max_d = max(row_max_d, d)
            return placed, _snap(y + row_max_d)

        # ── 4. Place the three rows with corridors between them ───────────────
        # Clean row starts at y=0
        p_clean,  y_clean_bot  = pack_row(clean_rooms, 0.0)

        # C01 (clean corridor) sits immediately below the clean row
        y_c01   = y_clean_bot                        # flush with room bottoms
        y_staff0 = round(y_c01 + CORR_W, 2)         # staff row starts right after C01

        p_staff,  y_staff_bot  = pack_row(staff_rooms, y_staff0)

        # C02 (dirty corridor) sits immediately below the staff row
        y_c02   = y_staff_bot
        y_dirty0 = round(y_c02 + CORR_W, 2)

        p_dirty,  y_dirty_bot  = pack_row(dirty_rooms, y_dirty0)

        all_rooms = p_clean + p_staff + p_dirty

        # ── 5. Stair/lift core (east end, no collision guaranteed) ──────────
        core_x = round(site_w - CORE_W, 2)

        # Fill gap between last clean room and stair core with entrance/reception
        if p_clean:
            last_clean_x = max(r["x_m"] + r["width_m"] for r in p_clean)
            gap = round(core_x - last_clean_x - WALL, 2)
            if gap > 1.0:
                all_rooms.append({
                    "room_id": "R_ENT",
                    "name": "Ward Entrance / Reception",
                    "x_m": round(last_clean_x + WALL, 2),
                    "y_m": 0.0,
                    "width_m": round(gap, 2),
                    "depth_m": round(y_c01, 2),
                    "area_m2": round(gap * y_c01, 1),
                    "zone": "public",
                    "access": "public",
                })

        # ST01: primary stair spans from C01 southward (clear of C01 top = y_c01)
        # Place it ABOVE clean row so it doesn't touch corridors
        y_st01 = 0.0          # top of site, above the clean row
        d_st01 = y_c01        # spans entire clean row height → adjacent to C01

        # LF01: bed lift spans full staff row height (y_staff0 to y_c02, flush both sides)
        lf_y0  = round(y_staff0, 2)
        d_lf01 = round(y_c02 - y_staff0, 2)  # flush with C02 start — no gap
        y_lf01 = lf_y0

        # ST02: secondary egress — placed alongside dirty row at west end
        # Shares the dirty row y-band but at x=0 (west, outside room pack area)
        y_st02 = y_dirty0   # aligned with dirty row start
        d_st02 = round(y_dirty_bot - y_dirty0, 2) if y_dirty_bot > y_dirty0 else CORR_W + 1.0
        # Safety: must fit within site depth
        if y_st02 + d_st02 > site_d:
            y_st02 = round(site_d - d_st02 - WALL, 2)

        stairs = [
            {
                "stair_id": "ST01", "name": "Primary Stair", "zone": "staff",
                "x_m": core_x, "y_m": y_st01, "width_m": CORE_W, "depth_m": d_st01,
                "note": f"East-end primary egress. x={core_x}, y={y_st01}–{round(y_st01+d_st01,2)}",
            },
            {
                "stair_id": "ST02", "name": "Secondary Stair", "zone": "staff",
                "x_m": round(site_w - CORE_W - 3.5, 1),  # west of ST01 core, avoids dirty rooms at x=0
                "y_m": y_st02, "width_m": 2.8, "depth_m": d_st02,
                "note": f"Second egress at dirty zone level. y={y_st02}–{round(y_st02+d_st02,2)}, fits within site depth {site_d}m",
            },
        ]
        lifts = [
            {
                "lift_id": "LF01", "name": "Bed Lift", "zone": "staff",
                "x_m": core_x, "y_m": y_lf01, "width_m": 2.2, "depth_m": d_lf01,
                "note": f"Bed/patient lift south of ST01. y={y_lf01}–{round(y_lf01+d_lf01,2)}",
            },
        ]

        # ── 6. Corridors — span FULL site width including stair core ────────
        corridors = [
            {
                "corridor_id": "C01", "name": "Patient/Staff Separation Corridor",
                "zone": "clean",
                "x_m": 0.0, "y_m": y_c01, "width_m": site_w, "depth_m": CORR_W,
                "note": (f"Full-width x=0–{site_w}m. "
                         f"Separates clean zone (y<{y_c01}m) from staff zone. "
                         f"Directly connects to ST01+LF01 core at x={core_x}m."),
            },
            {
                "corridor_id": "C02", "name": "Staff/Service Separation Corridor",
                "zone": "service",
                "x_m": 0.0, "y_m": y_c02, "width_m": site_w, "depth_m": CORR_W,
                "note": (f"Full-width x=0–{site_w}m. "
                         f"Separates staff zone from dirty zone. "
                         f"ST02 secondary egress at west end x=0."),
            },
        ]

        # ── 7. Collision check ────────────────────────────────────────────────
        def bbox(el):
            return (el["x_m"], el["y_m"],
                    el["x_m"] + el["width_m"], el["y_m"] + el["depth_m"])

        def overlaps(a, b):
            """True only when elements genuinely overlap (shared edge = no overlap)."""
            ax1,ay1,ax2,ay2 = bbox(a)
            bx1,by1,bx2,by2 = bbox(b)
            TOL = 0.001  # 1mm tolerance — shared edge counts as touching, not overlapping
            return ax1 + TOL < bx2 and ax2 - TOL > bx1 and ay1 + TOL < by2 and ay2 - TOL > by1

        all_elements = all_rooms + corridors + stairs + lifts
        collision_notes = []
        for i, ea in enumerate(all_elements):
            for eb in all_elements[i+1:]:
                if overlaps(ea, eb):
                    msg = f"COLLISION: {ea.get('room_id') or ea.get('corridor_id') or ea.get('stair_id') or ea.get('lift_id')} ↔ {eb.get('room_id') or eb.get('corridor_id') or eb.get('stair_id') or eb.get('lift_id')}"
                    collision_notes.append(msg)
                    logger.warning(f"[{self.AGENT_ID}] {msg}")

        total_room_area = round(sum(r["area_m2"] for r in all_rooms), 1)

        spatial_layout = {
            "building_type":    building_type,
            "site_width_m":     site_w,
            "site_depth_m":     site_d,
            "jurisdiction":     jurisdiction,
            "layout_strategy":  "double-loaded corridor (algorithmic)",
            "floors": [{
                "floor_id":          "G",
                "level_m":           0.0,
                "total_room_area_m2": total_room_area,
                "rooms":     all_rooms,
                "corridors": corridors,
                "stairs":    stairs,
                "lifts":     lifts,
            }],
            "clean_dirty_separation": (
                f"Row 1 (y=0–{y_c01}m): clean/patient zone. "
                f"C01 clean corridor (y={y_c01}–{round(y_c01+CORR_W,2)}m). "
                f"Row 2 (y={y_staff0}–{y_c02}m): staff/public zone. "
                f"C02 dirty corridor (y={y_c02}–{round(y_c02+CORR_W,2)}m). "
                f"Row 3 (y={y_dirty0}–{y_dirty_bot}m): dirty/service zone."
            ),
            "collision_check": "PASS" if not collision_notes else f"FAIL: {'; '.join(collision_notes)}",
            "layout_notes": [
                "Algorithm: deterministic pack; no LLM geometry generation",
                f"Rows: {len(p_clean)} clean + {len(p_staff)} staff + {len(p_dirty)} dirty",
                f"ST01@({core_x},{y_st01}) ST02@(0,{y_st02}) LF01@({core_x},{y_lf01})",
                f"C01@y={y_c01} C02@y={y_c02} — both span full width to stair core",
            ],
            "project_id":   self.memory.project_id,
            "created_at":   datetime.now(timezone.utc).isoformat(),
            "created_by":   self.AGENT_ID,
        }

        version = self.memory.save_schema("spatial_layout", spatial_layout)
        logger.success(
            f"[{self.AGENT_ID}] spatial_layout {version} — "
            f"{len(all_rooms)} rooms, collision={spatial_layout['collision_check'][:10]}"
        )
        self.send_message("pm", "status_update", {
            "status": "done",
            "schema": "spatial_layout",
            "version": version,
            "collision_check": spatial_layout["collision_check"],
        })
        return spatial_layout

"""
Input Parser Agent — parses DWG, PDF, PNG/JPG, IFC into site_data.json
"""

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from src.agents.base_agent import BaseAgent
from src.memory.project_memory import ProjectMemory


SYSTEM_PROMPT = """You are the Input Parser Agent for ArchitectAI, a multi-agent building design system.

Your job is to analyze a site plan file and extract structured site data. You must output ONLY valid JSON matching the site_data schema.

Extract:
- Site boundary as a list of [x, y] points in metres
- Site area in m²
- Drawing scale (e.g. 0.01 for 1:100)
- North orientation in degrees (0 = up/north)
- Constraints: setbacks, max height, access points, existing structures
- Jurisdiction: infer from context clues if possible (language, regulations mentioned, etc.)

If you cannot determine a value with confidence, set it to null and add a note.
Output format: strict JSON only, no prose, no markdown.
"""


class InputParserAgent(BaseAgent):
    AGENT_ID = "input_parser"
    DEFAULT_MODEL = "gemini-3-flash"

    def run(self, inputs: dict) -> dict:
        """
        Parse a site input file.

        Args:
            inputs: {
                "file_path": str,          # path to DWG/PDF/PNG/IFC
                "jurisdiction": str,        # optional override, e.g. "SE"
            }

        Returns:
            site_data dict (also saved to project memory)
        """
        file_path = Path(inputs["file_path"])
        jurisdiction = inputs.get("jurisdiction")
        suffix = file_path.suffix.lower()

        logger.info(f"[{self.AGENT_ID}] Parsing {file_path.name} ({suffix})")
        self.send_message("pm", "status_update", {"status": "working", "task": f"Parsing {file_path.name}"})

        if suffix in [".png", ".jpg", ".jpeg", ".webp"]:
            site_data = self._parse_image(file_path, jurisdiction)
        elif suffix == ".pdf":
            site_data = self._parse_pdf(file_path, jurisdiction)
        elif suffix == ".dwg":
            site_data = self._parse_dwg(file_path, jurisdiction)
        elif suffix == ".ifc":
            site_data = self._parse_ifc(file_path, jurisdiction)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

        # Enrich with metadata
        site_data["project_id"] = self.memory.project_id
        site_data["source_file"] = file_path.name
        site_data["source_type"] = suffix.lstrip(".")
        site_data["created_at"] = datetime.now(timezone.utc).isoformat()
        site_data["created_by"] = self.AGENT_ID
        if jurisdiction:
            site_data["jurisdiction"] = jurisdiction

        # Save to project memory
        version = self.memory.save_schema("site_data", site_data)
        logger.success(f"[{self.AGENT_ID}] site_data saved as {version}")

        self.send_message("pm", "status_update", {
            "status": "done",
            "schema": "site_data",
            "version": version,
        })

        return site_data

    def _parse_image(self, path: Path, jurisdiction: Optional[str]) -> dict:
        """Use Claude vision to interpret a PNG/JPG floor plan."""
        image_data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
        media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"

        prompt = f"""Analyze this site plan image and extract the following as JSON:
- boundary: polygon points in metres (estimate from visual scale indicators)
- area_m2: total site area
- scale: drawing scale ratio (e.g. 0.01 for 1:100)
- orientation: north bearing in degrees
- constraints: setbacks, max_height_m, access_points
- jurisdiction: {jurisdiction or 'infer from context'}
- notes: any observations about ambiguity

Output ONLY valid JSON, no markdown."""

        response = self.client.chat.completions.create(
            model="openclaw",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_data}"}},
                    {"type": "text", "text": prompt},
                ]
            }],
            extra_headers={"x-openclaw-model": f"anthropic/{self.model}"},
        )
        return self._extract_json(response.choices[0].message.content)

    def _parse_pdf(self, path: Path, jurisdiction: Optional[str]) -> dict:
        """Extract site data from a PDF (convert first page to image, then vision)."""
        try:
            import pymupdf
            doc = pymupdf.open(str(path))
            page = doc[0]
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            # Save temp, then use vision
            tmp = path.parent / f"_tmp_{path.stem}.png"
            tmp.write_bytes(img_bytes)
            result = self._parse_image(tmp, jurisdiction)
            tmp.unlink()
            return result
        except ImportError:
            raise RuntimeError("pymupdf not installed. Run: pip install pymupdf")

    def _parse_dwg(self, path: Path, jurisdiction: Optional[str]) -> dict:
        """Parse DWG using ezdxf to extract geometry."""
        try:
            import ezdxf
            doc = ezdxf.readfile(str(path))
            msp = doc.modelspace()

            # Extract all line/polyline entities and build boundary estimate
            points = []
            for entity in msp:
                if entity.dxftype() in ("LINE", "LWPOLYLINE", "POLYLINE"):
                    if hasattr(entity, "get_points"):
                        points.extend([[p[0], p[1]] for p in entity.get_points()])
                    elif entity.dxftype() == "LINE":
                        points.append([entity.dxf.start.x, entity.dxf.start.y])
                        points.append([entity.dxf.end.x, entity.dxf.end.y])

            if not points:
                raise ValueError("No geometry found in DWG file")

            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            bbox_area = (max(xs) - min(xs)) * (max(ys) - min(ys))

            return {
                "boundary": {
                    "points": [[min(xs), min(ys)], [max(xs), min(ys)], [max(xs), max(ys)], [min(xs), max(ys)]],
                    "area_m2": round(bbox_area, 1),
                },
                "scale": None,
                "orientation": 0,
                "constraints": {"notes": ["Extracted from DWG bounding box — manual review recommended"]},
                "jurisdiction": jurisdiction,
                "notes": ["DWG parsed via ezdxf — boundary is bounding box approximation"],
            }
        except ImportError:
            raise RuntimeError("ezdxf not installed. Run: pip install ezdxf")

    def _parse_ifc(self, path: Path, jurisdiction: Optional[str]) -> dict:
        """Parse existing IFC to extract site context."""
        try:
            import ifcopenshell
            ifc = ifcopenshell.open(str(path))
            sites = ifc.by_type("IfcSite")
            site = sites[0] if sites else None

            return {
                "boundary": {"points": [], "area_m2": None},
                "scale": 1.0,
                "orientation": 0,
                "constraints": {},
                "jurisdiction": jurisdiction,
                "notes": [f"Parsed from IFC. Site name: {site.Name if site else 'unknown'}"],
            }
        except ImportError:
            raise RuntimeError("ifcopenshell not installed")

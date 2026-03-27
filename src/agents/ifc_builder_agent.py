"""
IFC Builder Agent — generates a valid IFC4 file from approved schemas.
Uses ifcopenshell to build real IFC geometry.
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from src.agents.base_agent import BaseAgent

try:
    import ifcopenshell
    import ifcopenshell.api
    import ifcopenshell.api.root
    import ifcopenshell.api.unit
    import ifcopenshell.api.context
    import ifcopenshell.api.project
    import ifcopenshell.api.spatial
    import ifcopenshell.api.geometry
    import ifcopenshell.api.aggregate
    import ifcopenshell.util.element
    _IFC_AVAILABLE = True
except ImportError:
    _IFC_AVAILABLE = False
    logger.warning(
        "[ifc_builder] ifcopenshell not installed. "
        "Run: pip install ifcopenshell  — IFC export will be unavailable."
    )


class IFCBuilderAgent(BaseAgent):
    """
    Generates a valid IFC4 file from approved spatial, structural, and MEP schemas.

    Produces:
    - IfcProject / IfcSite / IfcBuilding / IfcBuildingStorey per floor
    - IfcSpace per room (with Name and GrossFloorArea)
    - IfcWall boundary walls around each room (box approximation)
    - IfcDoor placeholder for each room entry
    - IfcZone for MEP fire compartments and ventilation zones
    - Correct spatial relationships (IfcRelContainedInSpatialStructure, IfcRelAggregates)
    - IfcOwnerHistory with project metadata
    """

    AGENT_ID = "ifc_builder"
    DEFAULT_MODEL = "claude-sonnet-4-5"

    def run(self, inputs: dict) -> dict:
        """
        Build an IFC4 file from approved schemas.

        Args:
            inputs: {
                "spatial_layout": dict,
                "structural_schema": dict,
                "mep_schema": dict,
                "component_templates": dict,
                "output_path": str,       # e.g. "projects/xxx/outputs/model.ifc"
            }

        Returns:
            {"ifc_path": str, "entity_count": int, "floors": int}
        """
        if not _IFC_AVAILABLE:
            raise ImportError(
                "ifcopenshell is required for IFC export. "
                "Install with: pip install ifcopenshell"
            )

        spatial_layout = inputs["spatial_layout"]
        structural_schema = inputs.get("structural_schema", {})
        mep_schema = inputs.get("mep_schema", {})
        component_templates = inputs.get("component_templates", {})
        output_path = inputs["output_path"]

        project_id = self.memory.project_id
        floors = spatial_layout.get("floors", [])
        building_type = spatial_layout.get("building_type", "Building")

        logger.info(
            f"[{self.AGENT_ID}] Building IFC4 model — "
            f"{len(floors)} floor(s), project={project_id}"
        )
        self.send_message("pm", "status_update", {
            "status": "working",
            "task": f"IFC4 export — {len(floors)} floors",
        })

        # ---------------------------------------------------------------- #
        # Create IFC model                                                   #
        # ---------------------------------------------------------------- #
        ifc = ifcopenshell.file(schema="IFC4")

        # Owner history
        person = ifc.createIfcPerson(
            Identification="ArchitectAI",
            FamilyName="ArchitectAI",
            GivenName="System",
        )
        org = ifc.createIfcOrganization(
            Identification="AIAI",
            Name="ArchitectAI",
        )
        person_and_org = ifc.createIfcPersonAndOrganization(
            ThePerson=person,
            TheOrganization=org,
        )
        app = ifc.createIfcApplication(
            ApplicationDeveloper=org,
            Version="1.0",
            ApplicationFullName="ArchitectAI",
            ApplicationIdentifier="ArchitectAI",
        )
        now_ts = int(datetime.now(timezone.utc).timestamp())
        owner_history = ifc.createIfcOwnerHistory(
            OwningUser=person_and_org,
            OwningApplication=app,
            ChangeAction="ADDED",
            CreationDate=now_ts,
        )

        # Units
        unit_assignment = ifc.createIfcUnitAssignment(
            Units=[
                ifc.createIfcSIUnit(
                    UnitType="LENGTHUNIT",
                    Name="METRE",
                ),
                ifc.createIfcSIUnit(
                    UnitType="AREAUNIT",
                    Name="SQUARE_METRE",
                ),
                ifc.createIfcSIUnit(
                    UnitType="VOLUMEUNIT",
                    Name="CUBIC_METRE",
                ),
            ]
        )

        # Geometric representation context (3D)
        geom_context = ifc.createIfcGeometricRepresentationContext(
            ContextIdentifier="Model",
            ContextType="Model",
            CoordinateSpaceDimension=3,
            Precision=1e-5,
            WorldCoordinateSystem=ifc.createIfcAxis2Placement3D(
                Location=ifc.createIfcCartesianPoint([0.0, 0.0, 0.0])
            ),
        )

        # Project
        project = ifc.createIfcProject(
            GlobalId=self._guid(),
            OwnerHistory=owner_history,
            Name=project_id,
            Description=f"{building_type} — generated by ArchitectAI",
            UnitsInContext=unit_assignment,
            RepresentationContexts=[geom_context],
        )

        # Site
        site_placement = ifc.createIfcLocalPlacement(
            RelativePlacement=ifc.createIfcAxis2Placement3D(
                Location=ifc.createIfcCartesianPoint([0.0, 0.0, 0.0])
            )
        )
        site = ifc.createIfcSite(
            GlobalId=self._guid(),
            OwnerHistory=owner_history,
            Name="Site",
            ObjectPlacement=site_placement,
            CompositionType="ELEMENT",
        )

        # Building
        building_placement = ifc.createIfcLocalPlacement(
            PlacementRelTo=site_placement,
            RelativePlacement=ifc.createIfcAxis2Placement3D(
                Location=ifc.createIfcCartesianPoint([0.0, 0.0, 0.0])
            ),
        )
        building = ifc.createIfcBuilding(
            GlobalId=self._guid(),
            OwnerHistory=owner_history,
            Name=building_type,
            ObjectPlacement=building_placement,
            CompositionType="ELEMENT",
        )

        # Aggregate: project → site → building
        ifc.createIfcRelAggregates(
            GlobalId=self._guid(),
            OwnerHistory=owner_history,
            RelatingObject=project,
            RelatedObjects=[site],
        )
        ifc.createIfcRelAggregates(
            GlobalId=self._guid(),
            OwnerHistory=owner_history,
            RelatingObject=site,
            RelatedObjects=[building],
        )

        # ---------------------------------------------------------------- #
        # Floors                                                             #
        # ---------------------------------------------------------------- #
        storey_objects: list = []
        total_spaces = 0
        total_walls = 0
        total_doors = 0

        for floor in floors:
            floor_id = floor.get("floor_id", "G")
            level_m = float(floor.get("level_m", 0.0))
            rooms_on_floor = floor.get("rooms", [])

            storey_placement = ifc.createIfcLocalPlacement(
                PlacementRelTo=building_placement,
                RelativePlacement=ifc.createIfcAxis2Placement3D(
                    Location=ifc.createIfcCartesianPoint([0.0, 0.0, level_m])
                ),
            )
            storey = ifc.createIfcBuildingStorey(
                GlobalId=self._guid(),
                OwnerHistory=owner_history,
                Name=f"Floor {floor_id}",
                ObjectPlacement=storey_placement,
                CompositionType="ELEMENT",
                Elevation=level_m,
            )
            storey_objects.append(storey)

            # Collect elements for this storey
            floor_elements: list = []
            floor_spaces: list = []

            for room in rooms_on_floor:
                space, walls, door = self._create_room(
                    ifc=ifc,
                    room=room,
                    owner_history=owner_history,
                    storey_placement=storey_placement,
                    geom_context=geom_context,
                )
                floor_spaces.append(space)
                floor_elements.extend(walls)
                if door:
                    floor_elements.append(door)
                total_spaces += 1
                total_walls += len(walls)
                if door:
                    total_doors += 1

            # IfcRelAggregates: building storey → spaces
            if floor_spaces:
                ifc.createIfcRelAggregates(
                    GlobalId=self._guid(),
                    OwnerHistory=owner_history,
                    RelatingObject=storey,
                    RelatedObjects=floor_spaces,
                )

            # IfcRelContainedInSpatialStructure: storey → walls/doors
            if floor_elements:
                ifc.createIfcRelContainedInSpatialStructure(
                    GlobalId=self._guid(),
                    OwnerHistory=owner_history,
                    RelatingStructure=storey,
                    RelatedElements=floor_elements,
                )

        # Aggregate: building → storeys
        if storey_objects:
            ifc.createIfcRelAggregates(
                GlobalId=self._guid(),
                OwnerHistory=owner_history,
                RelatingObject=building,
                RelatedObjects=storey_objects,
            )

        # ---------------------------------------------------------------- #
        # MEP Zones                                                          #
        # ---------------------------------------------------------------- #
        self._add_mep_zones(ifc, mep_schema, owner_history)

        # ---------------------------------------------------------------- #
        # Save                                                               #
        # ---------------------------------------------------------------- #
        output_path = str(output_path)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        ifc.write(output_path)

        entity_count = len(list(ifc))
        logger.success(
            f"[{self.AGENT_ID}] IFC4 saved → {output_path} "
            f"({entity_count} entities, {len(floors)} floors, "
            f"{total_spaces} spaces, {total_walls} walls, {total_doors} doors)"
        )

        self.send_message("pm", "status_update", {
            "status": "done",
            "schema": "ifc_model",
            "summary": (
                f"{entity_count} entities, {len(floors)} floors, "
                f"{total_spaces} spaces"
            ),
        })

        return {
            "ifc_path": output_path,
            "entity_count": entity_count,
            "floors": len(floors),
            "spaces": total_spaces,
            "walls": total_walls,
            "doors": total_doors,
        }

    # ------------------------------------------------------------------ #
    # Private builders                                                     #
    # ------------------------------------------------------------------ #

    def _create_room(
        self,
        ifc,
        room: dict,
        owner_history,
        storey_placement,
        geom_context,
    ):
        """Create IfcSpace + boundary walls + door for a single room."""
        name = room.get("name", room.get("room_type", "Room"))
        x = float(room.get("x_m", 0.0))
        y = float(room.get("y_m", 0.0))
        w = float(room.get("width_m", 4.0))
        d = float(room.get("depth_m", 3.0))
        area = float(room.get("area_m2", w * d))
        height = float(room.get("height_m", 3.0))

        room_placement = ifc.createIfcLocalPlacement(
            PlacementRelTo=storey_placement,
            RelativePlacement=ifc.createIfcAxis2Placement3D(
                Location=ifc.createIfcCartesianPoint([x, y, 0.0])
            ),
        )

        # Space boundary shape (extruded rectangle)
        polyline = ifc.createIfcPolyline(Points=[
            ifc.createIfcCartesianPoint([0.0, 0.0]),
            ifc.createIfcCartesianPoint([w, 0.0]),
            ifc.createIfcCartesianPoint([w, d]),
            ifc.createIfcCartesianPoint([0.0, d]),
            ifc.createIfcCartesianPoint([0.0, 0.0]),
        ])
        profile = ifc.createIfcArbitraryClosedProfileDef(
            ProfileType="AREA",
            OuterCurve=polyline,
        )
        extrusion = ifc.createIfcExtrudedAreaSolid(
            SweptArea=profile,
            Position=ifc.createIfcAxis2Placement3D(
                Location=ifc.createIfcCartesianPoint([0.0, 0.0, 0.0])
            ),
            ExtrudedDirection=ifc.createIfcDirection([0.0, 0.0, 1.0]),
            Depth=height,
        )
        shape_rep = ifc.createIfcShapeRepresentation(
            ContextOfItems=geom_context,
            RepresentationIdentifier="Body",
            RepresentationType="SweptSolid",
            Items=[extrusion],
        )
        product_rep = ifc.createIfcProductDefinitionShape(
            Representations=[shape_rep]
        )

        space = ifc.createIfcSpace(
            GlobalId=self._guid(),
            OwnerHistory=owner_history,
            Name=name,
            Description=room.get("room_type", ""),
            ObjectPlacement=room_placement,
            Representation=product_rep,
            LongName=name,
        )

        # Property set: area
        area_prop = ifc.createIfcPropertySingleValue(
            Name="GrossFloorArea",
            NominalValue=ifc.createIfcAreaMeasure(area),
        )
        ifc.createIfcPropertySet(
            GlobalId=self._guid(),
            OwnerHistory=owner_history,
            Name="Pset_SpaceCommon",
            HasProperties=[area_prop],
        )

        # Boundary walls (4 sides, simplified thin walls)
        wall_thickness = 0.2
        walls = []
        wall_configs = [
            # (x_start, y_start, x_end, y_end, label)
            (x, y, x + w, y, "S"),          # South
            (x + w, y, x + w, y + d, "E"),  # East
            (x + w, y + d, x, y + d, "N"),  # North
            (x, y + d, x, y, "W"),           # West
        ]
        for wx0, wy0, wx1, wy1, label in wall_configs:
            wall = self._create_wall(
                ifc=ifc,
                owner_history=owner_history,
                storey_placement=storey_placement,
                x0=wx0, y0=wy0, x1=wx1, y1=wy1,
                height=height,
                thickness=wall_thickness,
                name=f"Wall-{room.get('room_id', 'R')}-{label}",
                geom_context=geom_context,
            )
            walls.append(wall)

        # Door placeholder on south wall
        door_placement = ifc.createIfcLocalPlacement(
            PlacementRelTo=storey_placement,
            RelativePlacement=ifc.createIfcAxis2Placement3D(
                Location=ifc.createIfcCartesianPoint([x + w / 2, y, 0.0])
            ),
        )
        door = ifc.createIfcDoor(
            GlobalId=self._guid(),
            OwnerHistory=owner_history,
            Name=f"Door-{room.get('room_id', 'R')}",
            ObjectPlacement=door_placement,
            OverallHeight=2.1,
            OverallWidth=0.9,
        )

        return space, walls, door

    def _create_wall(
        self,
        ifc,
        owner_history,
        storey_placement,
        x0: float, y0: float,
        x1: float, y1: float,
        height: float,
        thickness: float,
        name: str,
        geom_context,
    ):
        """Create a simplified IfcWall as a box between two points."""
        import math

        dx = x1 - x0
        dy = y1 - y0
        length = math.sqrt(dx * dx + dy * dy)
        if length < 0.01:
            length = 0.01

        # Axis direction
        angle = math.atan2(dy, dx)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        wall_placement = ifc.createIfcLocalPlacement(
            PlacementRelTo=storey_placement,
            RelativePlacement=ifc.createIfcAxis2Placement3D(
                Location=ifc.createIfcCartesianPoint([x0, y0, 0.0]),
                Axis=ifc.createIfcDirection([0.0, 0.0, 1.0]),
                RefDirection=ifc.createIfcDirection([cos_a, sin_a, 0.0]),
            ),
        )

        # Simple rectangle profile for the wall cross-section
        profile = ifc.createIfcRectangleProfileDef(
            ProfileType="AREA",
            XDim=length,
            YDim=thickness,
        )
        extrusion = ifc.createIfcExtrudedAreaSolid(
            SweptArea=profile,
            Position=ifc.createIfcAxis2Placement3D(
                Location=ifc.createIfcCartesianPoint([length / 2, 0.0, 0.0])
            ),
            ExtrudedDirection=ifc.createIfcDirection([0.0, 0.0, 1.0]),
            Depth=height,
        )
        shape_rep = ifc.createIfcShapeRepresentation(
            ContextOfItems=geom_context,
            RepresentationIdentifier="Body",
            RepresentationType="SweptSolid",
            Items=[extrusion],
        )
        wall = ifc.createIfcWall(
            GlobalId=self._guid(),
            OwnerHistory=owner_history,
            Name=name,
            ObjectPlacement=wall_placement,
            Representation=ifc.createIfcProductDefinitionShape(
                Representations=[shape_rep]
            ),
        )
        return wall

    def _add_mep_zones(self, ifc, mep_schema: dict, owner_history):
        """Add IfcZone entities for fire compartments and ventilation zones."""
        for comp in mep_schema.get("fire_compartments", []):
            ifc.createIfcZone(
                GlobalId=self._guid(),
                OwnerHistory=owner_history,
                Name=comp.get("compartment_id", "FC"),
                Description=f"Fire compartment — {comp.get('area_m2', 0)} m²",
                LongName=comp.get("compartment_id", ""),
            )
        for zone in mep_schema.get("ventilation_zones", []):
            ifc.createIfcZone(
                GlobalId=self._guid(),
                OwnerHistory=owner_history,
                Name=zone.get("zone_id", "VZ"),
                Description=f"Ventilation zone — {zone.get('type', '')}",
                LongName=zone.get("ahu_ref", ""),
            )

    @staticmethod
    def _guid() -> str:
        """Generate a valid IFC GlobalId (22-char base64-like string)."""
        try:
            return ifcopenshell.guid.new()
        except Exception:
            # Fallback: truncated UUID
            return str(uuid.uuid4()).replace("-", "")[:22]

"""OpenCascade STEP loading and face-feature extraction."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, tan
from pathlib import Path
from typing import Any

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import (
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Plane,
    GeomAbs_Sphere,
)
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

from .matching import FaceFeature, SurfaceKind


@dataclass(frozen=True, slots=True)
class FaceMesh:
    component_id: str
    face_id: int
    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]


@dataclass(slots=True)
class Component:
    component_id: str
    component_name: str
    instance_name: str
    features: list[FaceFeature]
    meshes: list[FaceMesh]


@dataclass(slots=True)
class StepModel:
    components: list[Component]
    non_analytic_faces: list[tuple[str, int, str]]

    @property
    def features(self) -> list[FaceFeature]:
        return [feature for component in self.components for feature in component.features]


def _xyz(point: Any) -> tuple[float, float, float]:
    return (float(point.X()), float(point.Y()), float(point.Z()))


def _direction(axis: Any) -> tuple[float, float, float]:
    direction = axis.Direction()
    return (float(direction.X()), float(direction.Y()), float(direction.Z()))


def _surface_data(
    face: Any, center: tuple[float, float, float]
) -> tuple[
    SurfaceKind,
    str | None,
    tuple[float, float, float] | None,
    float | None,
    float | None,
]:
    surface = BRepAdaptor_Surface(face, True)
    kind = surface.GetType()
    if kind == GeomAbs_Plane:
        return "plane", None, _direction(surface.Plane().Axis()), None, None
    if kind == GeomAbs_Cylinder:
        cylinder = surface.Cylinder()
        return (
            "cylinder",
            None,
            _direction(cylinder.Axis()),
            float(cylinder.Radius()),
            None,
        )
    if kind == GeomAbs_Cone:
        cone = surface.Cone()
        axis = _direction(cone.Axis())
        reference = _xyz(cone.Position().Location())
        offset = tuple(value - origin for value, origin in zip(center, reference))
        axial_distance = sum(value * direction for value, direction in zip(offset, axis))
        semi_angle = float(cone.SemiAngle())
        local_radius = float(abs(float(cone.RefRadius()) + axial_distance * tan(semi_angle)))
        return "cone", None, axis, local_radius, semi_angle
    if kind == GeomAbs_Sphere:
        sphere = surface.Sphere()
        return "sphere", None, None, float(sphere.Radius()), None
    return "other", getattr(kind, "name", str(kind)), None, None, None


def _principal_spans(mesh: FaceMesh | None) -> tuple[float, float] | None:
    if mesh is None or len(mesh.vertices) < 3:
        return None
    points = np.asarray(mesh.vertices, dtype=float)
    centered = points - points.mean(axis=0)
    _, eigenvectors = np.linalg.eigh(np.cov(points, rowvar=False))
    projected = centered @ eigenvectors
    spans = sorted(
        (float(value) for value in np.ptp(projected, axis=0)),
        reverse=True,
    )
    return (spans[0], spans[1])


def _face_mesh(face: Any, component_id: str, face_id: int) -> FaceMesh | None:
    mesh_location = TopLoc_Location()
    location = BRep_Tool.Triangulation_s(face, mesh_location)
    if location is None or location.NbNodes() == 0:
        return None
    transform = mesh_location.Transformation()
    vertices = tuple(
        _xyz(location.Node(index).Transformed(transform))
        for index in range(1, location.NbNodes() + 1)
    )
    triangles: list[tuple[int, int, int]] = []
    for index in range(1, location.NbTriangles() + 1):
        triangle = location.Triangle(index)
        a, b, c = triangle.Get()
        if face.Orientation() == TopAbs_REVERSED:
            triangles.append((int(a) - 1, int(c) - 1, int(b) - 1))
        else:
            triangles.append((int(a) - 1, int(b) - 1, int(c) - 1))
    return FaceMesh(component_id, face_id, vertices, tuple(triangles))


def _extract_component(
    component_shape: Any,
    component_id: str,
    component_name: str,
    instance_name: str,
) -> tuple[Component, list[tuple[str, int, str]]]:
    explorer = TopExp_Explorer(component_shape, TopAbs_FACE)
    features: list[FaceFeature] = []
    meshes: list[FaceMesh] = []
    unsupported: list[tuple[str, int, str]] = []
    face_id = 0
    while explorer.More():
        face_id += 1
        face = TopoDS.Face_s(explorer.Current())
        properties = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, properties)
        area = float(properties.Mass())
        center = _xyz(properties.CentreOfMass())
        linear_properties = GProp_GProps()
        BRepGProp.LinearProperties_s(face, linear_properties)
        perimeter = float(linear_properties.Mass())
        mesh = _face_mesh(face, component_id, face_id)
        surface_type, surface_subtype, axis, radius, semi_angle = _surface_data(face, center)
        feature = FaceFeature(
            face_id=face_id,
            component_id=component_id,
            surface_type=surface_type,
            area=area,
            perimeter=perimeter,
            center=center,
            axis=axis,
            radius=radius,
            semi_angle=semi_angle,
            reversed=face.Orientation() == TopAbs_REVERSED,
            principal_spans=_principal_spans(mesh),
            surface_subtype=surface_subtype,
            component_name=component_name,
            instance_name=instance_name,
        )
        features.append(feature)
        if surface_type == "other":
            unsupported.append(
                (component_id, face_id, "non-analytic surface uses tessellated signature")
            )
        if mesh is not None:
            meshes.append(mesh)
        explorer.Next()
    return Component(component_id, component_name, instance_name, features, meshes), unsupported


def _label_name(label: TDF_Label) -> str | None:
    attribute = TDataStd_Name()
    if not label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        return None
    name = attribute.Get().ToExtString().strip()
    return name or None


def _component_shapes(label: TDF_Label) -> list[tuple[Any, str | None, str | None]]:
    root_name = _label_name(label)
    if not XCAFDoc_ShapeTool.IsAssembly_s(label):
        shape = XCAFDoc_ShapeTool.GetShape_s(label)
        return [] if shape.IsNull() else [(shape, root_name, None)]

    children = TDF_LabelSequence()
    if not XCAFDoc_ShapeTool.GetComponents_s(label, children, False):
        return []
    shapes: list[tuple[Any, str | None, str | None]] = []
    for index in range(1, children.Length() + 1):
        child = children.Value(index)
        referred = TDF_Label()
        has_reference = XCAFDoc_ShapeTool.GetReferredShape_s(child, referred)
        instance_name = _label_name(child)
        component_name = _label_name(referred) if has_reference else None
        if not component_name or component_name.upper() in {"SOLID", "ASSEMBLY", "COMPOUND"}:
            component_name = instance_name or component_name
        shape = XCAFDoc_ShapeTool.GetShape_s(child)
        if not shape.IsNull():
            shapes.append((shape, component_name or root_name, instance_name))
    return shapes


def _solids(shape: Any) -> list[Any]:
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    solids: list[Any] = []
    while explorer.More():
        solids.append(TopoDS.Solid_s(explorer.Current()))
        explorer.Next()
    return solids or [shape]


def _extract_model(
    document: TDocStd_Document,
    source_name: str,
    linear_deflection: float,
) -> StepModel:
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    free_shapes = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_shapes)
    if free_shapes.Length() == 0:
        raise ValueError(f"STEP file contains no geometry: {source_name}")

    named_shapes: list[tuple[Any, str | None, str | None]] = []
    for index in range(1, free_shapes.Length() + 1):
        named_shapes.extend(_component_shapes(free_shapes.Value(index)))
    if not named_shapes:
        raise ValueError(f"No component geometry was found in STEP file: {source_name}")

    flattened_shapes: list[tuple[Any, str | None, str | None]] = []
    for shape, component_name, instance_name in named_shapes:
        component_solids = _solids(shape)
        for solid_index, solid in enumerate(component_solids, start=1):
            solid_instance_name = instance_name
            if len(component_solids) > 1:
                solid_instance_name = (
                    f"{instance_name or component_name or 'Instance'} / Solid {solid_index}"
                )
            flattened_shapes.append((solid, component_name, solid_instance_name))

    components: list[Component] = []
    non_analytic: list[tuple[str, int, str]] = []
    for index, (component_shape, component_name, instance_name) in enumerate(
        flattened_shapes, start=1
    ):
        component_id = f"Part {index:03d}"
        component_name = component_name or component_id
        instance_name = instance_name or f"Instance {index:03d}"
        BRepMesh_IncrementalMesh(component_shape, linear_deflection)
        component, component_non_analytic = _extract_component(
            component_shape, component_id, component_name, instance_name
        )
        if component.features:
            components.append(component)
            non_analytic.extend(component_non_analytic)
    if not components:
        raise ValueError(f"No faces were found in STEP file: {source_name}")
    return StepModel(components, non_analytic)


def load_step(path: str | Path, *, linear_deflection: float = 0.5) -> StepModel:
    """Load a STEP file, assigning stable one-based IDs to faces within each solid."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"STEP file does not exist: {source}")
    if not isfinite(linear_deflection) or linear_deflection <= 0:
        raise ValueError("linear_deflection must be positive.")

    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    status = reader.ReadFile(str(source))
    if status != IFSelect_RetDone:
        raise ValueError(f"OpenCascade could not read STEP file: {source.name}")
    application = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    application.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), document)
    document.Open(application)
    try:
        if not reader.Transfer(document):
            raise ValueError(f"STEP file contains no transferable roots: {source.name}")
        return _extract_model(document, source.name, linear_deflection)
    finally:
        application.Close(document)

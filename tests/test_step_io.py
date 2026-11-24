from __future__ import annotations

from pathlib import Path

import pytest
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeCone,
    BRepPrimAPI_MakeCylinder,
    BRepPrimAPI_MakeSphere,
    BRepPrimAPI_MakeTorus,
)
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopoDS import TopoDS_Compound
from OCP.gp import gp_Trsf, gp_Vec
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

from auto_mating.matching import find_matches
from auto_mating.step_io import load_step


def _write_step(shape: object, path: Path) -> None:
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    assert writer.Write(str(path)) == IFSelect_RetDone


def _write_named_assembly(path: Path) -> None:
    application = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    application.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), document)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(25.0, 0.0, 0.0))
    translated_box = BRepBuilderAPI_Transform(box, transform, True).Shape()
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, box)
    builder.Add(compound, translated_box)
    assembly = shape_tool.AddShape(compound, True, True)
    TDataStd_Name.Set_s(assembly, TCollection_ExtendedString("Synthetic Assembly"))
    children = TDF_LabelSequence()
    assert XCAFDoc_ShapeTool.GetComponents_s(assembly, children, False)
    for index in range(1, children.Length() + 1):
        TDataStd_Name.Set_s(
            children.Value(index),
            TCollection_ExtendedString(f"Synthetic Instance {index}"),
        )
    writer = STEPCAFControl_Writer()
    assert writer.Transfer(document, STEPControl_AsIs)
    assert writer.Write(str(path)) == IFSelect_RetDone


def test_load_step_extracts_face_ids_features_and_render_meshes(tmp_path: Path) -> None:
    path = tmp_path / "box.step"
    _write_step(BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape(), path)

    model = load_step(path)

    assert len(model.components) == 1
    component = model.components[0]
    assert component.component_id == "Part 001"
    assert len(component.features) == 6
    assert {feature.surface_type for feature in component.features} == {"plane"}
    assert len(component.meshes) == 6
    assert all(feature.principal_spans is not None for feature in component.features)
    assert {feature.face_id for feature in component.features} == set(range(1, 7))
    assert sorted(feature.area for feature in component.features) == pytest.approx(
        [200.0, 200.0, 300.0, 300.0, 600.0, 600.0]
    )


def test_load_step_recognizes_cylindrical_faces(tmp_path: Path) -> None:
    path = tmp_path / "cylinder.step"
    _write_step(BRepPrimAPI_MakeCylinder(2.0, 5.0).Shape(), path)

    model = load_step(path)
    cylinders = [feature for feature in model.features if feature.surface_type == "cylinder"]

    assert len(cylinders) == 1
    assert cylinders[0].radius == pytest.approx(2.0)
    assert cylinders[0].area == pytest.approx(20.0 * 3.141592653589793)


def test_load_step_recognizes_conical_and_spherical_faces(tmp_path: Path) -> None:
    cone_path = tmp_path / "cone.step"
    sphere_path = tmp_path / "sphere.step"
    _write_step(BRepPrimAPI_MakeCone(1.0, 2.0, 5.0).Shape(), cone_path)
    _write_step(BRepPrimAPI_MakeSphere(2.0).Shape(), sphere_path)

    cone_model = load_step(cone_path)
    sphere_model = load_step(sphere_path)
    cone = next(feature for feature in cone_model.features if feature.surface_type == "cone")
    sphere = next(feature for feature in sphere_model.features if feature.surface_type == "sphere")

    assert cone.radius is not None
    assert 1.0 < cone.radius < 2.0
    assert cone.semi_angle == pytest.approx(0.19739556)
    assert sphere.radius == pytest.approx(2.0)


def test_load_step_supports_other_analytic_surfaces_by_subtype(tmp_path: Path) -> None:
    path = tmp_path / "torus.step"
    _write_step(BRepPrimAPI_MakeTorus(5.0, 1.0).Shape(), path)

    model = load_step(path)

    assert len(model.features) == 1
    feature = model.features[0]
    assert feature.surface_type == "other"
    assert feature.surface_subtype == "GeomAbs_Torus"
    assert feature.principal_spans is not None
    assert model.non_analytic_faces == [
        ("Part 001", 1, "non-analytic surface uses tessellated signature")
    ]


def test_load_step_preserves_assembly_instance_names_and_transforms(tmp_path: Path) -> None:
    path = tmp_path / "named_assembly.step"
    _write_named_assembly(path)

    model = load_step(path)

    assert len(model.components) == 2
    assert [component.instance_name for component in model.components] == [
        "Synthetic Instance 1",
        "Synthetic Instance 2",
    ]
    assert all(len(component.features) == 6 for component in model.components)
    assert model.components[0].features[0].center != model.components[1].features[0].center


def test_group_search_returns_each_named_instance_and_honors_exclusion(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.step"
    assembly_path = tmp_path / "assembly.step"
    _write_step(BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape(), source_path)
    _write_named_assembly(assembly_path)
    source = load_step(source_path)
    assembly = load_step(assembly_path)
    selected = source.components[0].features[:2]

    all_matches, _ = find_matches(selected, assembly.features)
    remaining_matches, _ = find_matches(
        selected,
        assembly.features,
        excluded_component_ids={"Part 001"},
    )

    assert {match.instance_name for match in all_matches} == {
        "Synthetic Instance 1",
        "Synthetic Instance 2",
    }
    assert {match.component_name for match in all_matches} == {
        "Synthetic Instance 1",
        "Synthetic Instance 2",
    }
    assert {match.instance_name for match in remaining_matches} == {"Synthetic Instance 2"}
    assert all(len(match.matched_faces) == 2 for match in all_matches)


def test_load_step_reports_invalid_files(tmp_path: Path) -> None:
    path = tmp_path / "invalid.step"
    path.write_text("not a STEP document", encoding="utf-8")

    with pytest.raises(ValueError, match="could not read STEP"):
        load_step(path)

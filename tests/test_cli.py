from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from io import StringIO

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

from auto_mating.cli import main


def test_cli_writes_structured_json_for_synthetic_step(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "source.step"
    assembly_path = tmp_path / "assembly.step"
    output_path = tmp_path / "matches.json"
    writer = STEPControl_Writer()
    assert writer.Transfer(BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape(), STEPControl_AsIs)
    assert writer.Write(str(source_path)) == IFSelect_RetDone
    assembly_path.write_bytes(source_path.read_bytes())

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "auto-mating",
            "--source",
            str(source_path),
            "--assembly",
            str(assembly_path),
            "--faces",
            "1,2",
            "--output",
            str(output_path),
        ],
    )
    stdout = StringIO()
    with redirect_stdout(stdout):
        main()

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert json.loads(stdout.getvalue()) == result
    assert result["selected_face_ids"] == [1, 2]
    assert result["matches"]
    assert len(result["matches"][0]["matched_faces"]) == 2

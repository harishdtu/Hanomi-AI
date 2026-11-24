"""Command-line entry point for repeatable STEP mating searches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .matching import find_matches
from .step_io import load_step


def _face_ids(value: str) -> list[int]:
    tokens = value.split(",")
    if any(not token.strip() for token in tokens):
        raise argparse.ArgumentTypeError("face IDs must be comma-separated integers")
    try:
        face_ids = [int(token.strip()) for token in tokens]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("face IDs must be comma-separated integers") from exc
    if not face_ids or any(face_id < 1 for face_id in face_ids):
        raise argparse.ArgumentTypeError("provide one or more positive, one-based face IDs")
    if len(set(face_ids)) != len(face_ids):
        raise argparse.ArgumentTypeError("face IDs must be unique")
    return face_ids


def _positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("tolerance must be a number") from exc
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("tolerance must be finite and positive")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description="Find mating-face groups in a STEP assembly.")
    parser.add_argument("--source", required=True, type=Path, help="STEP file of the source part")
    parser.add_argument("--assembly", required=True, type=Path, help="STEP file of the target assembly")
    parser.add_argument("--faces", required=True, type=_face_ids, help="one-based source face IDs, e.g. 3,4,8")
    parser.add_argument(
        "--exclude-component",
        action="append",
        default=[],
        metavar="ID",
        help="assembly component ID to omit (repeat for multiple IDs)",
    )
    parser.add_argument(
        "--linear-tolerance",
        type=_positive_float,
        default=0.05,
        help="tolerance in the STEP model's units",
    )
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    args = parser.parse_args()

    source = load_step(args.source)
    if len(source.components) != 1:
        parser.error("the source STEP must contain exactly one solid part")
    source_faces_by_id = {feature.face_id: feature for feature in source.components[0].features}
    missing = [face_id for face_id in args.faces if face_id not in source_faces_by_id]
    if missing:
        parser.error(f"source face IDs not found: {', '.join(map(str, missing))}")

    assembly = load_step(args.assembly)
    if len(set(args.exclude_component)) != len(args.exclude_component):
        parser.error("--exclude-component cannot be repeated with the same component ID")
    known_component_ids = {component.component_id for component in assembly.components}
    unknown_components = sorted(set(args.exclude_component) - known_component_ids)
    if unknown_components:
        parser.error(
            "unknown assembly component ID(s): " + ", ".join(unknown_components)
        )
    selected = [source_faces_by_id[face_id] for face_id in args.faces]
    matches, truncated = find_matches(
        selected,
        assembly.features,
        linear_tolerance=args.linear_tolerance,
        excluded_component_ids=set(args.exclude_component),
    )
    result = {
        "source": str(args.source),
        "assembly": str(args.assembly),
        "selected_face_ids": args.faces,
        "linear_tolerance": args.linear_tolerance,
        "excluded_component_ids": args.exclude_component,
        "search_truncated": truncated,
        "non_analytic_source_faces": [
            {"component_id": component_id, "face_id": face_id, "reason": reason}
            for component_id, face_id, reason in source.non_analytic_faces
        ],
        "non_analytic_assembly_faces": [
            {"component_id": component_id, "face_id": face_id, "reason": reason}
            for component_id, face_id, reason in assembly.non_analytic_faces
        ],
        "matches": [
            {
                "component_id": match.component_id,
                "component_name": match.component_name,
                "instance_name": match.instance_name,
                "face_ids": list(match.face_ids),
                "score": round(match.score, 6),
                "surface_error": round(match.surface_error, 6),
                "group_error": round(match.group_error, 6),
                "fit_behavior": match.fit_behavior,
                "fit_confidence": round(match.fit_confidence, 4),
                "fit_gap": match.fit_gap,
                "matched_faces": [
                    {
                        "face_id": face.face_id,
                        "surface_type": face.surface_type,
                        "surface_subtype": face.surface_subtype,
                        "area": face.area,
                        "perimeter": face.perimeter,
                        "center": list(face.center),
                        "axis": list(face.axis) if face.axis else None,
                        "radius": face.radius,
                        "semi_angle": face.semi_angle,
                        "reversed": face.reversed,
                        "principal_spans": list(face.principal_spans)
                        if face.principal_spans
                        else None,
                    }
                    for face in match.matched_faces
                ],
            }
            for match in matches
        ],
    }
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()

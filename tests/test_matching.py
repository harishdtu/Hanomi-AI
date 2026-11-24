from __future__ import annotations

import pytest

from auto_mating.matching import FaceFeature, SurfaceKind, find_matches


def face(
    face_id: int,
    component_id: str,
    center: tuple[float, float, float],
    *,
    surface_type: SurfaceKind = "plane",
    area: float = 1.0,
    perimeter: float = 4.0,
    axis: tuple[float, float, float] | None = (0.0, 0.0, 1.0),
    radius: float | None = None,
    semi_angle: float | None = None,
    reversed: bool = False,
    principal_spans: tuple[float, float] | None = None,
    surface_subtype: str | None = None,
) -> FaceFeature:
    return FaceFeature(
        face_id=face_id,
        component_id=component_id,
        surface_type=surface_type,
        area=area,
        perimeter=perimeter,
        center=center,
        axis=axis,
        radius=radius,
        semi_angle=semi_angle,
        reversed=reversed,
        principal_spans=principal_spans,
        surface_subtype=surface_subtype,
    )


def test_finds_every_single_face_instance() -> None:
    query = [face(1, "source", (0, 0, 0))]
    assembly = [
        face(2, "chuck-a", (50, 0, 0)),
        face(3, "chuck-b", (-50, 0, 0)),
        face(4, "unrelated", (0, 0, 0), area=8, perimeter=18),
    ]

    matches, truncated = find_matches(query, assembly)

    assert not truncated
    assert {(match.component_id, match.face_ids) for match in matches} == {
        ("chuck-a", (2,)),
        ("chuck-b", (3,)),
    }


def test_group_context_rejects_individually_similar_faces_with_wrong_spacing() -> None:
    query = [
        face(1, "source", (0, 0, 0)),
        face(2, "source", (10, 0, 0)),
    ]
    assembly = [
        face(1, "correct", (20, 0, 0)),
        face(2, "correct", (30, 0, 0)),
        face(3, "false-positive", (20, 0, 0)),
        face(4, "false-positive", (35, 0, 0)),
    ]

    matches, _ = find_matches(query, assembly)

    assert [(match.component_id, match.face_ids) for match in matches] == [
        ("correct", (1, 2))
    ]


def test_finds_multiple_fit_locations_on_one_solid() -> None:
    query = [
        face(1, "source", (0, 0, 0)),
        face(2, "source", (10, 0, 0)),
    ]
    assembly = [
        face(1, "chuck", (100, 0, 0)),
        face(2, "chuck", (110, 0, 0)),
        face(3, "chuck", (200, 0, 0)),
        face(4, "chuck", (210, 0, 0)),
    ]

    matches, _ = find_matches(query, assembly)

    assert {match.face_ids for match in matches} == {(1, 2), (3, 4)}


def test_group_match_is_invariant_to_rigid_rotation_and_translation() -> None:
    query = [
        face(1, "source", (0, 0, 0), axis=(0, 0, 1)),
        face(2, "source", (10, 0, 0), axis=(0, 0, 1)),
    ]
    assembly = [
        face(8, "rotated-instance", (100, 25, 4), axis=(1, 0, 0)),
        face(9, "rotated-instance", (100, 35, 4), axis=(1, 0, 0)),
    ]

    matches, _ = find_matches(query, assembly)

    assert [(match.component_id, match.face_ids) for match in matches] == [
        ("rotated-instance", (8, 9))
    ]


def test_reflected_group_is_rejected_when_face_mapping_encodes_chirality() -> None:
    source_centers = [(0, 0, 0), (1, 0, 0), (0, 2, 0), (0, 0, 3)]
    mirrored_centers = [(100, 0, 0), (99, 0, 0), (100, 2, 0), (100, 0, 3)]
    query = [
        face(index, "source", center, area=float(index), perimeter=4.0)
        for index, center in enumerate(source_centers, start=1)
    ]
    assembly = [
        face(index + 10, "mirror", center, area=float(index), perimeter=4.0)
        for index, center in enumerate(mirrored_centers, start=1)
    ]

    matches, _ = find_matches(query, assembly)

    assert matches == []


def test_cylindrical_bore_pair_estimates_clearance_and_interference() -> None:
    male = face(
        1, "source", (0, 0, 0), surface_type="cylinder", area=12.56,
        perimeter=12.56, axis=(0, 0, 1), radius=2.0,
    )
    bore = face(
        2, "assembly", (30, 0, 0), surface_type="cylinder", area=13.82,
        perimeter=13.82, axis=(0, 0, 1), radius=2.2, reversed=True,
    )
    undersized_bore = face(
        3, "interference", (60, 0, 0), surface_type="cylinder", area=11.30,
        perimeter=11.30, axis=(0, 0, 1), radius=1.8, reversed=True,
    )
    exact_bore = face(
        4, "near-coincident", (90, 0, 0), surface_type="cylinder", area=12.56,
        perimeter=12.56, axis=(0, 0, 1), radius=2.0, reversed=True,
    )

    matches, _ = find_matches([male], [bore, undersized_bore, exact_bore])

    assert {match.component_id: match.fit_behavior for match in matches} == {
        "assembly": "clearance",
        "interference": "interference",
        "near-coincident": "near_coincident",
    }


@pytest.mark.parametrize(
    ("candidate_spacing", "expected_behavior"),
    [(2.2, "clearance"), (1.8, "interference"), (2.02, "near_coincident")],
)
def test_opposing_planar_pairs_classify_spacing(
    candidate_spacing: float,
    expected_behavior: str,
) -> None:
    query = [
        face(1, "source", (0, 0, 0)),
        face(2, "source", (0, 0, 2), reversed=True),
    ]
    assembly = [
        face(3, "target", (20, 0, 0)),
        face(4, "target", (20, 0, candidate_spacing), reversed=True),
    ]

    matches, _ = find_matches(query, assembly)

    assert len(matches) == 1
    assert matches[0].fit_behavior == expected_behavior


def test_matches_conical_and_spherical_surfaces_as_a_group() -> None:
    query = [
        face(
            1, "source", (0, 0, 0), surface_type="cone", area=12.0, perimeter=12.0,
            radius=2.0, semi_angle=0.25,
        ),
        face(
            2, "source", (5, 0, 0), surface_type="sphere", area=12.57,
            radius=1.0, axis=None,
        ),
    ]
    assembly = [
        face(
            4, "target", (20, 0, 0), surface_type="cone", area=12.1,
            perimeter=12.1, radius=2.01, semi_angle=0.25,
        ),
        face(
            5, "target", (25, 0, 0), surface_type="sphere", area=12.82,
            radius=1.01, axis=None,
        ),
    ]

    matches, _ = find_matches(query, assembly)

    assert [(match.component_id, match.face_ids) for match in matches] == [
        ("target", (4, 5))
    ]


def test_matches_other_tessellated_surface_types_only_with_same_subtype() -> None:
    query = [
        face(
            1, "source", (0, 0, 0), surface_type="other", surface_subtype="GeomAbs_Torus",
            area=60.0, perimeter=30.0, principal_spans=(12.0, 10.0),
        )
    ]
    assembly = [
        face(
            2, "torus", (20, 0, 0), surface_type="other", surface_subtype="GeomAbs_Torus",
            area=60.1, perimeter=30.1, principal_spans=(12.05, 10.02),
        ),
        face(
            3, "different-surface", (20, 0, 0), surface_type="other",
            surface_subtype="GeomAbs_BSplineSurface", area=60.0, perimeter=30.0,
            principal_spans=(12.0, 10.0),
        ),
        face(
            4, "missing-signature", (20, 0, 0), surface_type="other",
            surface_subtype="GeomAbs_Torus", area=60.0, perimeter=30.0,
        ),
    ]

    matches, _ = find_matches(query, assembly)

    assert [(match.component_id, match.face_ids) for match in matches] == [
        ("torus", (2,))
    ]
    assert matches[0].fit_behavior == "near_coincident"


def test_rejects_duplicate_source_ids_and_empty_selection() -> None:
    with pytest.raises(ValueError, match="at least one"):
        find_matches([], [])
    with pytest.raises(ValueError, match="unique"):
        find_matches(
            [face(1, "source", (0, 0, 0)), face(1, "source", (1, 0, 0))],
            [],
        )


def test_does_not_claim_a_planar_fit_class_without_gap_evidence() -> None:
    query = [face(1, "source", (0, 0, 0))]
    candidate = face(2, "target", (20, 0, 0), area=1.2, perimeter=4.4)

    matches, _ = find_matches(query, [candidate])

    assert len(matches) == 1
    assert matches[0].fit_behavior == "undetermined"
    assert matches[0].fit_confidence == 0.0


def test_exact_single_plane_is_not_mislabeled_near_coincident() -> None:
    query = [face(1, "source", (0, 0, 0))]
    candidate = face(2, "target", (20, 0, 0))

    matches, _ = find_matches(query, [candidate])

    assert len(matches) == 1
    assert matches[0].fit_behavior == "undetermined"
    assert matches[0].fit_gap is None


def test_excluded_source_instance_is_not_returned_as_a_match() -> None:
    query = [face(1, "source", (0, 0, 0))]
    assembly = [
        face(2, "source-instance", (100, 0, 0)),
        face(3, "other-instance", (200, 0, 0)),
    ]

    matches, _ = find_matches(query, assembly, excluded_component_ids={"source-instance"})

    assert [(match.component_id, match.face_ids) for match in matches] == [
        ("other-instance", (3,))
    ]


def test_does_not_match_unsupported_surface_types() -> None:
    query = [face(1, "source", (0, 0, 0), surface_type="other")]
    candidate = face(1, "target", (10, 0, 0), surface_type="other")

    matches, _ = find_matches(query, [candidate])

    assert matches == []


def test_reports_when_search_state_limit_is_reached() -> None:
    query = [face(1, "source", (0, 0, 0))]
    assembly = [face(index, "target", (index, 0, 0)) for index in range(1, 5)]

    matches, truncated = find_matches(query, assembly, max_search_states=2)

    assert truncated
    assert matches

"""Placement-invariant, group-aware face matching."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import isfinite, pi, sqrt
from typing import Literal

SurfaceKind = Literal["plane", "cylinder", "cone", "sphere", "other"]
FitBehavior = Literal["near_coincident", "clearance", "interference", "undetermined"]
Vector3 = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class FaceFeature:
    face_id: int
    component_id: str
    surface_type: SurfaceKind
    area: float
    perimeter: float
    center: Vector3
    axis: Vector3 | None = None
    radius: float | None = None
    semi_angle: float | None = None
    reversed: bool = False
    principal_spans: tuple[float, float] | None = None
    surface_subtype: str | None = None
    component_name: str | None = None
    instance_name: str | None = None


@dataclass(frozen=True, slots=True)
class Match:
    component_id: str
    component_name: str
    instance_name: str
    face_ids: tuple[int, ...]
    matched_faces: tuple[FaceFeature, ...]
    score: float
    surface_error: float
    group_error: float
    fit_behavior: FitBehavior
    fit_confidence: float
    fit_gap: float | None


def _dot(a: Vector3, b: Vector3) -> float:
    return sum(x * y for x, y in zip(a, b))


def _distance(a: Vector3, b: Vector3) -> float:
    return sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _subtract(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _axis_similarity(a: Vector3 | None, b: Vector3 | None) -> float | None:
    if a is None or b is None:
        return None
    # Surface axes are unoriented: reversing an axis does not change the surface.
    return min(1.0, abs(_dot(a, b)))


def _oriented_axis(face: FaceFeature) -> Vector3 | None:
    if face.axis is None:
        return None
    sign = -1.0 if face.reversed else 1.0
    return (
        sign * face.axis[0],
        sign * face.axis[1],
        sign * face.axis[2],
    )


def _relative_error(a: float, b: float, floor: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), floor)


def _surface_error(query: FaceFeature, candidate: FaceFeature) -> float | None:
    if query.surface_type != candidate.surface_type:
        return None
    if (
        query.surface_type == "other"
        and query.surface_subtype != candidate.surface_subtype
    ):
        return None
    if query.area <= 0 or candidate.area <= 0:
        return None
    if query.surface_type == "other" and (
        query.principal_spans is None or candidate.principal_spans is None
    ):
        return None

    terms: list[tuple[float, float]] = [
        (_relative_error(query.area, candidate.area, 1e-12), 0.25)
    ]
    if query.principal_spans and candidate.principal_spans:
        span_errors = [
            _relative_error(query_span, candidate_span, 1e-9)
            for query_span, candidate_span in zip(query.principal_spans, candidate.principal_spans)
        ]
        terms.append((sum(span_errors) / len(span_errors), 0.20))
    q_compactness = query.perimeter**2 / (4 * pi * query.area) if query.perimeter > 0 else 0
    c_compactness = candidate.perimeter**2 / (4 * pi * candidate.area) if candidate.perimeter > 0 else 0
    if q_compactness > 0 and c_compactness > 0:
        terms.append((_relative_error(q_compactness, c_compactness, 1e-12), 0.10))
    if query.radius is not None and candidate.radius is not None:
        terms.append((_relative_error(query.radius, candidate.radius, 1e-9), 0.40))
    if query.semi_angle is not None and candidate.semi_angle is not None:
        terms.append((abs(query.semi_angle - candidate.semi_angle) / (pi / 2), 0.15))

    weight = sum(w for _, w in terms)
    return min(1.0, sum(min(error, 1.0) * w for error, w in terms) / weight)


def _pair_error(
    query_a: FaceFeature,
    query_b: FaceFeature,
    candidate_a: FaceFeature,
    candidate_b: FaceFeature,
    linear_tolerance: float,
) -> float:
    query_distance = _distance(query_a.center, query_b.center)
    candidate_distance = _distance(candidate_a.center, candidate_b.center)
    characteristic_length = max(sqrt(query_a.area), sqrt(query_b.area), 1e-9)
    distance_delta = max(0.0, abs(query_distance - candidate_distance) - linear_tolerance)
    distance_error = distance_delta / max(
        query_distance, candidate_distance, characteristic_length * 0.02, linear_tolerance
    )
    distance_error = min(distance_error / 0.30, 1.0)

    plane_pair = (
        query_a.surface_type == query_b.surface_type == "plane"
        and candidate_a.surface_type == candidate_b.surface_type == "plane"
    )
    if plane_pair:
        q_axis = _oriented_axis(query_a)
        q_other_axis = _oriented_axis(query_b)
        c_axis = _oriented_axis(candidate_a)
        c_other_axis = _oriented_axis(candidate_b)
        if q_axis is None or q_other_axis is None or c_axis is None or c_other_axis is None:
            return distance_error
        q_relationship = _dot(q_axis, q_other_axis)
        c_relationship = _dot(c_axis, c_other_axis)
        angle_error = min(abs(q_relationship - c_relationship) / 0.15, 1.0)
        return 0.7 * distance_error + 0.3 * angle_error

    q_axis = _axis_similarity(query_a.axis, query_b.axis)
    c_axis = _axis_similarity(candidate_a.axis, candidate_b.axis)
    if q_axis is None or c_axis is None:
        return distance_error
    angle_error = min(abs(q_axis - c_axis) / 0.15, 1.0)
    return 0.7 * distance_error + 0.3 * angle_error


def _normalized_tetra_volume(points: tuple[Vector3, Vector3, Vector3, Vector3]) -> float:
    origin, point_a, point_b, point_c = points
    vector_a: Vector3 = (
        point_a[0] - origin[0],
        point_a[1] - origin[1],
        point_a[2] - origin[2],
    )
    vector_b: Vector3 = (
        point_b[0] - origin[0],
        point_b[1] - origin[1],
        point_b[2] - origin[2],
    )
    vector_c: Vector3 = (
        point_c[0] - origin[0],
        point_c[1] - origin[1],
        point_c[2] - origin[2],
    )
    determinant = _dot(_cross(vector_a, vector_b), vector_c)
    scale = max(
        _distance(origin, point_a) * _distance(origin, point_b) * _distance(origin, point_c),
        1e-12,
    )
    return determinant / scale


def _group_orientation_error(
    pairs: list[tuple[FaceFeature, FaceFeature, float]],
) -> float | None:
    if len(pairs) < 4:
        return 0.0
    ordered_pairs = sorted(pairs, key=lambda pair: pair[0].face_id)
    errors: list[float] = []
    for indices in combinations(range(len(ordered_pairs)), 4):
        query_point_0, query_point_1, query_point_2, query_point_3 = (
            ordered_pairs[index][0].center for index in indices
        )
        candidate_point_0, candidate_point_1, candidate_point_2, candidate_point_3 = (
            ordered_pairs[index][1].center for index in indices
        )
        query_volume = _normalized_tetra_volume(
            (query_point_0, query_point_1, query_point_2, query_point_3)
        )
        candidate_volume = _normalized_tetra_volume(
            (candidate_point_0, candidate_point_1, candidate_point_2, candidate_point_3)
        )
        query_is_degenerate = abs(query_volume) < 0.01
        candidate_is_degenerate = abs(candidate_volume) < 0.01
        if query_is_degenerate != candidate_is_degenerate:
            return 1.0
        if query_is_degenerate:
            continue
        if query_volume * candidate_volume < 0:
            return None
        errors.append(
            abs(abs(query_volume) - abs(candidate_volume))
            / max(abs(query_volume), abs(candidate_volume), 1e-9)
        )
    return sum(errors) / len(errors) if errors else 0.0


def _fit_behavior(
    pairs: list[tuple[FaceFeature, FaceFeature]],
    score: float,
    linear_tolerance: float,
) -> tuple[FitBehavior, float, float | None]:
    signed_gaps: list[float] = []
    for query, candidate in pairs:
        if (
            query.surface_type == "cylinder"
            and candidate.surface_type == "cylinder"
            and query.reversed != candidate.reversed
            and query.radius is not None
            and candidate.radius is not None
        ):
            # A reversed cylindrical face usually bounds a bore; a forward face
            # usually bounds an external shaft.
            signed_gaps.append(
                (query.radius - candidate.radius)
                if query.reversed
                else (candidate.radius - query.radius)
            )
    planar_gaps: list[float] = []
    for index, (query_a, candidate_a) in enumerate(pairs):
        if query_a.surface_type != "plane" or candidate_a.surface_type != "plane":
            continue
        query_axis_a = _oriented_axis(query_a)
        candidate_axis_a = _oriented_axis(candidate_a)
        if query_axis_a is None or candidate_axis_a is None:
            continue
        for query_b, candidate_b in pairs[index + 1 :]:
            if query_b.surface_type != "plane" or candidate_b.surface_type != "plane":
                continue
            query_axis_b = _oriented_axis(query_b)
            candidate_axis_b = _oriented_axis(candidate_b)
            if query_axis_b is None or candidate_axis_b is None:
                continue
            if _dot(query_axis_a, query_axis_b) > -0.95:
                continue
            if _dot(candidate_axis_a, candidate_axis_b) > -0.95:
                continue
            query_separation = abs(
                _dot(_subtract(query_b.center, query_a.center), query_axis_a)
            )
            candidate_separation = abs(
                _dot(
                    _subtract(candidate_b.center, candidate_a.center),
                    candidate_axis_a,
                )
            )
            planar_gaps.append(candidate_separation - query_separation)

    if signed_gaps and all(gap > linear_tolerance for gap in signed_gaps):
        gap = sum(signed_gaps) / len(signed_gaps)
        return "clearance", min(0.95, 0.55 + gap / max(linear_tolerance * 10, gap) * 0.4), gap
    if signed_gaps and all(gap < -linear_tolerance for gap in signed_gaps):
        gap = sum(signed_gaps) / len(signed_gaps)
        return (
            "interference",
            min(0.95, 0.55 + abs(gap) / max(linear_tolerance * 10, abs(gap)) * 0.4),
            gap,
        )
    if signed_gaps and all(abs(gap) <= linear_tolerance for gap in signed_gaps) and score <= 0.05:
        return "near_coincident", max(0.5, 1.0 - score / 0.1), 0.0
    if not signed_gaps and planar_gaps:
        if all(gap > linear_tolerance for gap in planar_gaps):
            gap = sum(planar_gaps) / len(planar_gaps)
            return (
                "clearance",
                min(0.95, 0.55 + gap / max(linear_tolerance * 10, gap) * 0.4),
                gap,
            )
        if all(gap < -linear_tolerance for gap in planar_gaps):
            gap = sum(planar_gaps) / len(planar_gaps)
            return (
                "interference",
                min(0.95, 0.55 + abs(gap) / max(linear_tolerance * 10, abs(gap)) * 0.4),
                gap,
            )
        if all(abs(gap) <= linear_tolerance for gap in planar_gaps) and score <= 0.05:
            return "near_coincident", max(0.5, 1.0 - score / 0.1), 0.0
    elif not signed_gaps and not planar_gaps and pairs:
        if all(
            query.surface_type == "other"
            and query.surface_subtype == candidate.surface_subtype
            and query.principal_spans is not None
            and candidate.principal_spans is not None
            and all(
                abs(query_span - candidate_span) <= linear_tolerance + 1e-9
                for query_span, candidate_span in zip(
                    query.principal_spans, candidate.principal_spans
                )
            )
            for query, candidate in pairs
        ):
            return "near_coincident", 0.4, 0.0
    return "undetermined", 0.0, None


def find_matches(
    query_faces: list[FaceFeature],
    assembly_faces: list[FaceFeature],
    *,
    linear_tolerance: float = 0.05,
    max_face_error: float = 0.35,
    max_group_error: float = 0.20,
    max_search_states: int = 250_000,
    excluded_component_ids: set[str] | None = None,
) -> tuple[list[Match], bool]:
    """Find all distinct candidate face groups, returning matches and truncation status.

    Candidate faces must be on the same solid. Assignments are one-to-one, and
    pairwise center/axis relationships are checked before a group is accepted.
    The state limit applies independently to each component, preventing a
    pathological solid from monopolizing the UI; `truncated` tells callers
    when at least one component search stopped early.
    """
    if not query_faces:
        raise ValueError("Select at least one source face.")
    if not isfinite(linear_tolerance) or linear_tolerance <= 0:
        raise ValueError("linear_tolerance must be positive.")
    if not isfinite(max_face_error) or max_face_error < 0:
        raise ValueError("max_face_error must be finite and non-negative.")
    if not isfinite(max_group_error) or max_group_error < 0:
        raise ValueError("max_group_error must be finite and non-negative.")
    if max_search_states < 1:
        raise ValueError("max_search_states must be positive.")
    if len({face.face_id for face in query_faces}) != len(query_faces):
        raise ValueError("Source face IDs must be unique.")
    if len({face.component_id for face in query_faces}) != 1:
        raise ValueError("Selected source faces must belong to one component.")

    by_component: dict[str, list[FaceFeature]] = {}
    for face in assembly_faces:
        by_component.setdefault(face.component_id, []).append(face)

    matches: list[Match] = []
    truncated = False

    for component_id, component_faces in by_component.items():
        if excluded_component_ids and component_id in excluded_component_ids:
            continue
        states = 0
        options: dict[int, list[tuple[FaceFeature, float]]] = {}
        for query in query_faces:
            candidates = [
                (candidate, error)
                for candidate in component_faces
                if (error := _surface_error(query, candidate)) is not None
                and error <= max_face_error
            ]
            options[query.face_id] = sorted(candidates, key=lambda item: (item[1], item[0].face_id))

        if any(not options[q.face_id] for q in query_faces):
            continue

        search_order = sorted(query_faces, key=lambda q: (len(options[q.face_id]), q.face_id))
        chosen: list[tuple[FaceFeature, FaceFeature, float]] = []
        used_ids: set[int] = set()
        component_truncated = False

        def visit(index: int, accumulated_pair_error: float) -> None:
            nonlocal states, component_truncated
            if states >= max_search_states:
                component_truncated = True
                return
            states += 1
            if index == len(search_order):
                local_error = sum(item[2] for item in chosen) / len(chosen)
                pair_count = len(chosen) * (len(chosen) - 1) // 2
                pair_error = accumulated_pair_error / pair_count if pair_count else 0.0
                orientation_error = _group_orientation_error(chosen)
                if orientation_error is None:
                    return
                group_error = 0.85 * pair_error + 0.15 * orientation_error
                score = 0.65 * local_error + 0.35 * group_error
                if group_error <= max_group_error:
                    query_candidate_pairs = [(q, c) for q, c, _ in chosen]
                    behavior, confidence, fit_gap = _fit_behavior(
                        query_candidate_pairs, score, linear_tolerance
                    )
                    ordered_candidates = tuple(
                        candidate
                        for _, candidate, _ in sorted(chosen, key=lambda item: item[1].face_id)
                    )
                    candidate_ids = tuple(candidate.face_id for candidate in ordered_candidates)
                    component_name = next(
                        (
                            candidate.component_name
                            for candidate in ordered_candidates
                            if candidate.component_name
                        ),
                        component_id,
                    )
                    matches.append(
                        Match(
                            component_id=component_id,
                            component_name=component_name,
                            instance_name=next(
                                (
                                    candidate.instance_name
                                    for candidate in ordered_candidates
                                    if candidate.instance_name
                                ),
                                component_id,
                            ),
                            face_ids=candidate_ids,
                            matched_faces=ordered_candidates,
                            score=score,
                            surface_error=local_error,
                            group_error=group_error,
                            fit_behavior=behavior,
                            fit_confidence=confidence,
                            fit_gap=fit_gap,
                        )
                    )
                return

            query = search_order[index]
            for candidate, face_error in options[query.face_id]:
                if candidate.face_id in used_ids:
                    continue
                new_pair_error = accumulated_pair_error
                compatible = True
                for previous_query, previous_candidate, _ in chosen:
                    pair_error = _pair_error(
                        query, previous_query, candidate, previous_candidate, linear_tolerance
                    )
                    if pair_error > max_group_error:
                        compatible = False
                        break
                    new_pair_error += pair_error
                if not compatible:
                    continue
                chosen.append((query, candidate, face_error))
                used_ids.add(candidate.face_id)
                visit(index + 1, new_pair_error)
                used_ids.remove(candidate.face_id)
                chosen.pop()
                if component_truncated:
                    return

        visit(0, 0.0)
        truncated = truncated or component_truncated

    deduplicated: dict[tuple[str, tuple[int, ...]], Match] = {}
    for match in matches:
        key = (match.component_id, match.face_ids)
        if key not in deduplicated or match.score < deduplicated[key].score:
            deduplicated[key] = match
    return sorted(deduplicated.values(), key=lambda match: (match.score, match.component_id, match.face_ids)), truncated

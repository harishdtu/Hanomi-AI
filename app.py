"""Local interactive UI for STEP mating search."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from auto_mating.matching import FaceFeature, Match, find_matches
from auto_mating.step_io import Component, FaceMesh, StepModel, load_step


def _upload_key(source_bytes: bytes, assembly_bytes: bytes) -> str:
    return hashlib.sha256(source_bytes + assembly_bytes).hexdigest()


def _load_uploads(source_bytes: bytes, assembly_bytes: bytes) -> tuple[StepModel, StepModel]:
    with tempfile.TemporaryDirectory(prefix="auto-mating-") as directory:
        source_path = Path(directory) / "source.step"
        assembly_path = Path(directory) / "assembly.step"
        source_path.write_bytes(source_bytes)
        assembly_path.write_bytes(assembly_bytes)
        return load_step(source_path), load_step(assembly_path)


def _mesh_trace(
    meshes: list[FaceMesh],
    *,
    name: str,
    color: str,
    opacity: float,
) -> go.Mesh3d | None:
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for mesh in meshes:
        offset = len(vertices)
        vertices.extend(mesh.vertices)
        triangles.extend((a + offset, b + offset, c + offset) for a, b, c in mesh.triangles)
    if not vertices or not triangles:
        return None
    return go.Mesh3d(
        x=[vertex[0] for vertex in vertices],
        y=[vertex[1] for vertex in vertices],
        z=[vertex[2] for vertex in vertices],
        i=[triangle[0] for triangle in triangles],
        j=[triangle[1] for triangle in triangles],
        k=[triangle[2] for triangle in triangles],
        name=name,
        color=color,
        opacity=opacity,
        flatshading=True,
        hoverinfo="skip",
    )


def _draw_assembly(
    assembly: StepModel,
    matches: list[Match],
    selected_index: int | None = None,
) -> None:
    figure = go.Figure()
    all_meshes = [mesh for component in assembly.components for mesh in component.meshes]
    base = _mesh_trace(all_meshes, name="Assembly", color="#64748b", opacity=0.14)
    if base is not None:
        figure.add_trace(base)
    palette = ["#38bdf8", "#f59e0b", "#c084fc", "#fb7185", "#a3e635"]
    for index, match in enumerate(matches):
        matched_ids = set(match.face_ids)
        matched_meshes = [
            mesh
            for component in assembly.components
            if component.component_id == match.component_id
            for mesh in component.meshes
            if mesh.face_id in matched_ids
        ]
        highlight = _mesh_trace(
            matched_meshes,
            name=(
                f"{match.component_name} | {match.instance_name} | "
                f"faces {', '.join(map(str, match.face_ids))}"
            ),
            color="#22c55e" if index == selected_index else palette[index % len(palette)],
            opacity=0.98 if index == selected_index else 0.82,
        )
        if highlight is not None:
            figure.add_trace(highlight)
    figure.update_layout(
        height=650,
        margin=dict(l=0, r=0, t=10, b=0),
        scene=dict(
            aspectmode="data",
            xaxis_title="X",
            yaxis_title="Y",
            zaxis_title="Z",
            bgcolor="#0b1220",
        ),
        paper_bgcolor="#0b1220",
        font_color="#e2e8f0",
        legend=dict(orientation="h"),
    )
    st.plotly_chart(figure, width="stretch")


def _draw_source(component: Component, selected_ids: set[int]) -> None:
    figure = go.Figure()
    base = _mesh_trace(component.meshes, name=component.component_id, color="#64748b", opacity=0.28)
    if base is not None:
        figure.add_trace(base)
    selected_meshes = [mesh for mesh in component.meshes if mesh.face_id in selected_ids]
    highlight = _mesh_trace(
        selected_meshes,
        name="Selected source faces",
        color="#22c55e",
        opacity=0.98,
    )
    if highlight is not None:
        figure.add_trace(highlight)
    figure.update_layout(
        height=500,
        margin=dict(l=0, r=0, t=10, b=0),
        scene=dict(aspectmode="data", xaxis_title="X", yaxis_title="Y", zaxis_title="Z"),
        showlegend=True,
    )
    st.plotly_chart(figure, width="stretch")


def _face_table(features: list[FaceFeature]) -> list[dict[str, object]]:
    return [
        {
            "Face ID": feature.face_id,
            "Surface": feature.surface_subtype or feature.surface_type,
            "Area": round(feature.area, 5),
            "Perimeter": round(feature.perimeter, 5),
            "Radius": round(feature.radius, 5) if feature.radius is not None else "-",
            "Semi-angle": round(feature.semi_angle, 5)
            if feature.semi_angle is not None
            else "-",
            "Axis": ", ".join(f"{value:.3f}" for value in feature.axis) if feature.axis else "-",
            "Principal spans": ", ".join(f"{value:.3f}" for value in feature.principal_spans)
            if feature.principal_spans
            else "-",
        }
        for feature in features
    ]


def _render_results(assembly: StepModel, matches: list[Match], truncated: bool) -> None:
    if truncated:
        st.warning("The search hit its safety limit. Results may be incomplete; split the assembly and retry.")
    if not matches:
        st.info("No candidate groups met the current tolerances. Adjust the tolerance or inspect the selected faces.")
        _draw_assembly(assembly, [])
        return

    st.success(f"Found {len(matches)} candidate face group(s).")
    if len(matches) > 1:
        selected_index = st.selectbox(
            "Highlight a candidate",
            options=range(len(matches)),
            format_func=lambda index: (
                f"#{index + 1} | {matches[index].component_id} | "
                f"{matches[index].component_name} | "
                f"faces {', '.join(map(str, matches[index].face_ids))} | "
                f"score {matches[index].score:.3f}"
            ),
        )
    else:
        selected_index = 0
    _draw_assembly(assembly, matches, selected_index)

    st.subheader("All candidate matches")
    st.dataframe(
        [
            {
                "Rank": index + 1,
                "Component": match.component_id,
                "Component name": match.component_name,
                "Instance": match.instance_name,
                "Face IDs": ", ".join(map(str, match.face_ids)),
                "Surface types": ", ".join(
                    face.surface_subtype or face.surface_type for face in match.matched_faces
                ),
                "Score (lower is better)": round(match.score, 4),
                "Surface error": round(match.surface_error, 4),
                "Group error": round(match.group_error, 4),
                "Fit behavior": match.fit_behavior,
                "Fit gap (model units)": round(match.fit_gap, 5)
                if match.fit_gap is not None
                else "-",
                "Fit confidence": round(match.fit_confidence, 3),
            }
            for index, match in enumerate(matches)
        ],
        hide_index=True,
        width="stretch",
    )


def main() -> None:
    st.set_page_config(page_title="Auto-mating in an assembly", layout="wide")
    st.title("Auto-mating in an assembly")
    st.caption(
        "Search a STEP assembly for every placement-independent group of faces "
        "that matches a selected source-face group."
    )
    st.info(
        "Candidate search uses surface signatures and group geometry. "
        "It is not a Boolean interference/contact proof; planar fit behavior may be "
        "undetermined unless the selection contains opposing faces."
    )

    left, right = st.columns(2)
    with left:
        source_upload = st.file_uploader("Source part STEP", type=["step", "stp"], key="source")
    with right:
        assembly_upload = st.file_uploader("Assembly STEP", type=["step", "stp"], key="assembly")

    if source_upload is None or assembly_upload is None:
        st.markdown("Upload the source part and target assembly to begin.")
        return

    source_bytes = source_upload.getvalue()
    assembly_bytes = assembly_upload.getvalue()
    upload_key = _upload_key(source_bytes, assembly_bytes)
    if st.session_state.get("upload_key") != upload_key:
        st.session_state.pop("source_model", None)
        st.session_state.pop("assembly_model", None)
        st.session_state.pop("matches", None)
        st.session_state["upload_key"] = upload_key

    if st.button("Inspect STEP files", type="primary"):
        try:
            with st.spinner("Reading STEP geometry and tessellating faces…"):
                source_model, assembly_model = _load_uploads(source_bytes, assembly_bytes)
            st.session_state["source_model"] = source_model
            st.session_state["assembly_model"] = assembly_model
            st.session_state.pop("matches", None)
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            st.error(f"Could not inspect STEP files: {exc}")

    source_model = st.session_state.get("source_model")
    assembly_model = st.session_state.get("assembly_model")
    if source_model is None or assembly_model is None:
        return
    if len(source_model.components) != 1:
        st.error(
            "The source file must contain one solid part, as specified by the assignment. "
            f"Found {len(source_model.components)} solids."
        )
        return

    source_component: Component = source_model.components[0]
    st.subheader("Source faces")
    st.caption("Face IDs are one-based and local to the source solid.")
    st.dataframe(_face_table(source_component.features), hide_index=True, width="stretch")
    feature_by_id = {feature.face_id: feature for feature in source_component.features}
    face_ids = st.multiselect(
        "Selected source faces",
        options=list(feature_by_id),
        format_func=lambda face_id: (
            f"{face_id} | {feature_by_id[face_id].surface_type} | "
            f"area {feature_by_id[face_id].area:.4g}"
        ),
    )
    _draw_source(source_component, set(face_ids))
    if any(feature_by_id[face_id].surface_type == "other" for face_id in face_ids):
        st.warning(
            "The selection includes non-analytic surfaces. These are compared by "
            "tessellated shape signatures and may have lower confidence."
        )
    st.caption(
        f"Assembly contains {len(assembly_model.components)} solid(s) and "
        f"{len(assembly_model.features)} face(s)."
    )
    if assembly_model.non_analytic_faces:
        st.warning(
            f"{len(assembly_model.non_analytic_faces)} assembly face(s) use tessellated "
            "non-analytic matching; review their candidates carefully."
        )
    component_labels = {
        component.component_id: (
            f"{component.component_id} | {component.component_name} | {component.instance_name}"
        )
        for component in assembly_model.components
    }
    excluded_component = st.selectbox(
        "Source component to exclude (if it is included in the assembly)",
        options=[None, *component_labels],
        format_func=lambda component_id: (
            "Do not exclude a component"
            if component_id is None
            else component_labels[component_id]
        ),
    )
    tolerance = st.number_input(
        "Linear tolerance (in STEP model units)",
        min_value=0.0001,
        max_value=10.0,
        value=0.05,
        step=0.01,
    )
    if st.button("Find mating candidates"):
        try:
            selected = [feature_by_id[face_id] for face_id in face_ids]
            matches, truncated = find_matches(
                selected,
                assembly_model.features,
                linear_tolerance=float(tolerance),
                excluded_component_ids={excluded_component}
                if excluded_component is not None
                else None,
            )
            st.session_state["matches"] = matches
            st.session_state["search_truncated"] = truncated
            st.session_state["search_key"] = (
                tuple(face_ids),
                float(tolerance),
                excluded_component,
            )
        except (ValueError, RuntimeError) as exc:
            st.error(f"Search failed: {exc}")

    current_search_key = (tuple(face_ids), float(tolerance), excluded_component)
    if (
        "matches" in st.session_state
        and st.session_state.get("search_key") == current_search_key
    ):
        _render_results(
            assembly_model,
            st.session_state["matches"],
            st.session_state.get("search_truncated", False),
        )


if __name__ == "__main__":
    main()

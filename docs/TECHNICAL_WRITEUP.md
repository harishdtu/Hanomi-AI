# Technical write-up: automatic mating detection

## Problem framing

Given a source part, a selected subset of its faces, and a STEP assembly, return
every component-local group of assembly faces whose surface signatures and
relative arrangement are compatible with the selection. This is a geometric
candidate search. It is not a full constraint solver: it does not place the
source part into the assembly, prove surface overlap, or run a solid Boolean
contact/interference computation.

## STEP ingestion and identity

The loader uses OpenCascade's XCAF-aware STEP reader so assembly component
placements and product/occurrence names survive when the STEP exporter wrote
them. Each solid is analyzed in its placed assembly coordinates. If product
names or instance names are absent, deterministic `Part NNN` and `Instance
NNN` labels are supplied. Face IDs are one-based within each extracted solid;
they are traversal IDs and are not portable CAD-persistent identifiers.

For each B-rep face, the loader records:

- analytic surface family: plane, cylinder, cone, or sphere;
- OpenCascade surface subtype for non-analytic surfaces;
- area, total boundary length, and area centroid;
- canonical axis for planes/cylinders/cones;
- radius for cylinders/spheres and local radius plus semi-angle for cones;
- face orientation, used cautiously to infer bore/shaft roles;
- two largest principal-coordinate extents from the tessellated face.

The mesh is also retained for display. Principal extents are obtained by
centering mesh vertices, finding principal directions by covariance
eigendecomposition, projecting onto those directions, and measuring the
projected ranges. Area, perimeter, and these extents are invariant to rigid
translation and rotation (up to tessellation and degenerate-axis effects).

## Candidate scoring

### Per-face signature

Candidates must have the same analytic family. For non-analytic faces, the
OpenCascade subtype must also match and both faces must have mesh-derived
principal extents. A weighted error combines scale-normalized differences in
area, principal extents, compactness `perimeter² / (4π area)`, radius, and cone
semi-angle where available. Errors are bounded to avoid a single dimension
dominating the score. Faces above `max_face_error` (default `0.35`) are pruned.

These are signatures, not complete boundary descriptions. Faces can have
similar area and extents but different trimmed regions, holes, or curvature;
non-analytic signatures are especially approximate.

### Group consistency

Matching is solved per solid, never across component boundaries. The matcher
uses the source face with the fewest candidates first, assigns distinct
assembly faces one-to-one, and checks every new assignment against the already
chosen group:

1. area-centroid pair distances are compared with the source group; the
   configured linear tolerance is removed from the distance delta before
   normalization;
2. pairwise angles between canonical surface axes are compared, and oriented
   planar normals retain the distinction between parallel and opposing faces;
3. for four or more non-coplanar face centroids, signed normalized tetrahedral
   volumes detect reflected arrangements that pair distances alone cannot
   distinguish.

The group error is the pair-error mean (85%) plus chirality-error mean (15%).
Assignments with error above `max_group_error` (default `0.20`) are rejected.
The reported ranking score is `0.65 * mean_face_error + 0.35 * group_error`,
with lower scores ranked first. The search returns all accepted assignments,
not only the top result. A state cap is applied independently to each solid;
the output carries a truncation flag whenever a component hits that cap.

The signature search is intentionally designed to be invariant to where each
solid sits in the assembly and to its rigid rotation. It is not invariant to
reflection when the selected centroid group has a non-degenerate tetrahedron.

## Fit classification

Fit class and match score answer different questions: the score measures
signature/group similarity; fit class describes only a gap that can be
estimated from the available surfaces.

- **Cylindrical pair:** when the source and candidate face orientations imply
  opposite bore/shaft roles, `source_radius` and `candidate_radius` produce a
  signed radial gap. Consistently positive gaps are `clearance`; consistently
  negative gaps are `interference`; gaps within the linear tolerance and a
  low match score are `near_coincident`.
- **Opposing planar pair:** opposing face-normal pairs provide source and
  candidate centroid separations. Increased separation is reported as
  `clearance`, decreased separation as `interference`, and near-equal
  separation with a low score as `near_coincident`.
- **Non-analytic tessellated faces:** matching subtypes with principal extents
  within linear tolerance can be labeled `near_coincident`, but the confidence
  is deliberately low. No Boolean claim is made.
- **Insufficient or contradictory evidence:** reported as `undetermined`;
  a numeric confidence of zero means no fit-class evidence, not that the
  candidate match score is zero.

Fit confidence is a heuristic based on the observed gap relative to the
configured tolerance. It is not a calibrated probability. Face orientation
may be exporter-dependent, so cylindrical fit labels should be reviewed
against the source CAD model.

## UI and CLI behavior

The Streamlit app lists source face IDs and measured properties, draws the
source with selected faces highlighted, provides an optional selector for
excluding the source's assembly instance, and highlights every returned match
in the assembly viewer. The candidate selector emphasizes one result without
hiding the other highlights. Invalid STEP reads, empty selections, and
unsupported/approximate surfaces produce explicit messages.

The CLI accepts `--source`, `--assembly`, and comma-separated `--faces`, with
an optional `--exclude-component` repeated for each component to omit.
`--output` writes machine-readable JSON including component/instance labels,
candidate face IDs and properties, scores, fit class/gap/confidence, and
approximate-surface records.

## Limitations and future work

1. Use persistent XCAF label/face references rather than traversal-based face
   IDs where the source workflow provides stable identifiers.
2. Compare trimmed surface boundaries and overlap/contact regions, not only
   area, perimeter, and principal extents.
3. Compute a robust best-fit rigid transform (with symmetric/partial
   correspondence handling), then verify the transformed B-reps with
   tolerance-aware surface distance and Boolean interference checks.
4. Calibrate fit thresholds and confidence against labeled real assemblies,
   including press, running-clearance, sliding, and non-mating controls.
5. Preserve nested assembly paths, occurrence names, colors, and units across
   more STEP exporters.
6. Add spatial indexing/candidate pruning for large assemblies and a
   user-visible resume/split strategy for capped searches.

The bundled tests use generated synthetic STEP fixtures. They establish the
tested behaviors listed in `VALIDATION.md`; they do not establish accuracy on
the assignment's lathe assembly or an unseen CAD dataset.

# Automatic mating detection in a CAD assembly

This project searches a STEP assembly for every component face group that is
geometrically compatible with a selected group of faces on a source part. It
includes a Streamlit 3D viewer, a JSON-producing CLI, and synthetic regression
tests built with OpenCascade.

The matcher is candidate detection, not a full CAD assembly solver or a
Boolean-contact proof. Read [the technical write-up](docs/TECHNICAL_WRITEUP.md)
and [validation record](docs/VALIDATION.md) for the method, evidence, and
limitations.

## Architecture

- `src/auto_mating/step_io.py` reads STEP with OpenCascade's XCAF reader,
  preserves available product/instance names, extracts per-face properties,
  and triangulates faces for display and generic-surface signatures.
- `src/auto_mating/matching.py` compares analytic surface descriptors and
  selected-face-group geometry, searches all one-to-one assignments per solid,
  rejects reflected tetrahedral groups, ranks candidates, and classifies fit
  behavior where geometry supports the distinction.
- `app.py` provides source-face selection, optional source-instance exclusion,
  all-match results, and a 3D viewer that highlights every returned candidate.
- `src/auto_mating/cli.py` exposes the same engine and writes structured JSON.
- `tests/` contains matcher regressions and STEP files generated in temporary
  directories. They are synthetic fixtures, not the assignment's lathe data.

## Prerequisites and installation

- Python 3.10 or newer (tested here with Python 3.12).
- Windows, macOS, or Linux with wheels available for `cadquery-ocp`.
- The OpenCascade dependency includes large native libraries; first install
  downloads can take several minutes.

From the project root on Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If PowerShell blocks activation, use the venv interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Streamlit application

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

1. Upload the source-part STEP and complete assembly STEP.
2. Select one or more source faces from the ID-indexed table. IDs are one-based
   and local to the source solid loaded by this version of OpenCascade.
3. If the source part is also present in the assembly, choose that component in
   **Source component to exclude** to avoid reporting the source as its own
   match.
4. Set the linear tolerance in the STEP model's units and run the search.
5. Inspect all candidate rows and the viewer. Every returned match is
   highlighted; use the candidate selector to emphasize one result.

The result table includes component/instance names where STEP product metadata
provides them (otherwise stable `Part NNN` fallbacks), face IDs, surface
subtypes, surface/group errors, fit class, fit gap, and confidence.

## Command-line interface

```powershell
.\.venv\Scripts\auto-mating.exe `
  --source .\key.step `
  --assembly .\lathe-assembly.step `
  --faces 1,2,3,4 `
  --exclude-component "Part 001" `
  --linear-tolerance 0.05 `
  --output .\matches.json
```

`--exclude-component` may be repeated. Component IDs are shown in the UI and
included in each JSON match. Omit `--output` to print the same JSON to stdout.
The output includes per-face geometric properties, match scores, truncation
status, and non-analytic faces that used tessellated signatures.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests create small box, cylinder, cone, sphere, torus, and named multi-instance
STEP fixtures in temporary directories, then discard them. They cover grouped
matching, false positives, rigid translation/rotation, reflection rejection,
multiple instances, source-instance exclusion, fit classification, invalid
files, and STEP name/geometry extraction. See
[docs/VALIDATION.md](docs/VALIDATION.md) for results and the explicit distinction
between synthetic and real assignment validation.

## Screenshots

These genuine UI captures use synthetic box STEP files and demonstrate the
workflow only; they are not results on the assignment assembly.

- [Source-face selection and 3D highlight](screenshots/synthetic-match.png)
- [Synthetic candidate-match results](screenshots/synthetic-match-results.png)

## Known limitations

- Exact/confidence-bearing fit classification is possible only for limited
  geometries: opposite planar pairs estimate signed separation, and
  coaxial cylindrical faces estimate radial clearance when B-rep orientation
  identifies bore versus shaft. Contradictory or insufficient evidence is
  reported as `undetermined`.
- Non-analytic surfaces (including toroidal or spline surfaces) are compared
  using mesh-derived principal extents, area, and perimeter. This is a
  lower-confidence candidate signature, not exact surface comparison.
- This version compares face area-centroid distances and relative axis
  angles; it does not calculate surface-overlap regions, solve the rigid
  transform between parts, or perform a Boolean interference/contact test.
- STEP files without assembly metadata are split into solids and assigned
  fallback component names. Nested subassemblies may be flattened, and
  product/instance labels vary by exporter.
- A per-component search-state cap prevents pathological combinatorial
  searches; a truncated result is explicitly flagged and must not be treated
  as exhaustive.
- Face numbering follows OpenCascade's traversal order and is not guaranteed
  to match another CAD application's face IDs.

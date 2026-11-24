# Validation record

## Environment and test data

- Python: 3.12.4 on Windows.
- Clean environment: project `.venv` with dependencies installed from
  `pyproject.toml`.
- Test data: synthetic STEP fixtures generated at test runtime with
  OpenCascade. Fixture files are temporary and are not included in the repo.
- Real assignment data: **not validated**. The Notion assignment lists the
  `WM290V_RedrawStart.stp` assembly, but it could not be retrieved into the
  workspace; no source-part STEP was available. Synthetic results must not be
  interpreted as evidence that the WM290 lathe assembly or source key part has
  been matched correctly.

## Automated cases

`tests/test_matching.py` covers:

- one-face lookups return every component match;
- group spacing rejects independent-face false positives;
- multiple candidate locations on one solid;
- translation and rotation invariance;
- reflection rejection for a face mapping with distinct signatures;
- cylindrical clearance, interference, and near-coincident classification;
- opposing planar clearance, interference, and near-coincident classification;
- cone/sphere group matching;
- same-subtype tessellated non-analytic matching and missing-signature
  rejection;
- single planar faces remain `undetermined` without gap evidence;
- source-component exclusion;
- empty/duplicate selections, unsupported/incomplete signatures, and search
  truncation.

`tests/test_step_io.py` writes synthetic STEP files at runtime and covers:

- face IDs, area, mesh generation, and principal extents on a box;
- cylinder, cone, sphere, and torus surface extraction;
- XCAF assembly instance names, placements, and multiple instance search;
- invalid STEP rejection.

## Actual run results

| Validation | Result | Data |
|---|---:|---|
| Baseline test suite before corrections | 17 passed | Synthetic/unit tests |
| Expanded suite during implementation | 23 passed, 1 failed | Synthetic; a torus confidence-boundary assertion was corrected |
| Final project virtual-environment test suite (`python -m pytest -q`) | 25 passed | Synthetic STEP and unit tests |
| `python -m compileall -q src app.py tests` | Passed | Project source and tests |
| `python -m pip check` | No broken requirements | Installed dependency metadata |
| CLI help (`python -m auto_mating.cli --help`) | Passed | CLI argument parser |
| CLI end-to-end JSON output | Passed in automated test | Synthetic STEP files |
| Streamlit upload, inspect, select faces, match, and highlight | Passed | Synthetic STEP files; screenshots in `screenshots/` |
| WM290 assignment assembly/source-part matching | Not run | Assembly unavailable locally; source-part STEP unavailable |

## Interpretation

Passing synthetic tests verifies only the listed generated cases. The suite
does not quantify false-positive rates, establish calibrated confidence, or
prove compatibility with the actual assignment files. The final validation
rows will be updated only with commands actually run against the final code.

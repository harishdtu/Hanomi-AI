# Validation record

## Environment and test data

- Python: 3.12.4 on Windows.
- Clean environment: project `.venv` with dependencies installed from
  `pyproject.toml`.
- Test data: synthetic STEP fixtures generated at test runtime with
  OpenCascade. Fixture files are temporary and are not included in the repo.
- Real assignment data: the assembly
  `C:\Users\pavan\Downloads\WM290V_RedrawStart.stp` and an extracted key source
  solid were available for a real-input CLI and Streamlit run. The extracted
  source is the actual `Key.1` solid in the assembly, written to a separate
  STEP file for the source input. This is a real-geometry integration check,
  not an independent ground-truth evaluation.

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
| Complete project test suite after real-data run | 25 passed | Synthetic/unit tests; `python -m pytest -q` |
| Real assignment CLI run | 3 candidate groups; `search_truncated=false` | Actual WM290 assembly and actual extracted `Key.1` solid; source faces 2, 4, 16, 18; excluded `Part 040`; tolerance 0.05 |
| Real assignment Streamlit run | 3 candidate groups; matches agree with CLI | Same actual source and assembly; uploaded, inspected, selected faces, excluded source, ran search, and inspected the results table/viewer |

## Real assignment run

The source was identified in the XCAF assembly as:

`01. Test00 / TOS Svitavy 125.1 / Assem1.1 / Key.1`

Its selected face IDs **2, 4, 16, 18** are the four planar square-drive sides,
identified from the extracted model using this project's one-based OpenCascade
face traversal. They were not inferred from the illustration.

The CLI and Streamlit each returned the following three candidate groups:

| Component | Instance | Matched face IDs | Score | Fit behavior | Fit gap | Fit confidence |
|---|---|---|---:|---|---:|---:|
| Part 029 | TOS Svitavy 125.1 / Solid 22 (Pinion M1.8 10T.3) | 4, 6, 8, 12 | 0.117528 | clearance | 0.4 | 0.87 |
| Part 027 | TOS Svitavy 125.1 / Solid 20 (Pinion M1.8 10T.1) | 4, 6, 8, 12 | 0.117528 | clearance | 0.4 | 0.87 |
| Part 028 | TOS Svitavy 125.1 / Solid 21 (Pinion M1.8 10T.2) | 4, 6, 8, 12 | 0.117528 | clearance | 0.4 | 0.87 |

The reported 0.4 gap is the matcher estimate in STEP model units; it is not a
Boolean contact or interference measurement. The assignment illustration shows
three highlighted locations, consistent with the number of candidate groups,
but is not a machine-readable list of expected matches. Therefore this run
confirms that the real files were processed and documents the returned
candidates; it does not establish a complete precision/recall score or prove
that there are no false positives or missed matches. The UI also reported that
4,699 assembly faces use tessellated non-analytic matching, which warrants
manual review.

Genuine screenshots from the real-input Streamlit session:

- [Real assignment run and selected candidate](../screenshots/real-assignment-results.png)
- [All three real candidate groups](../screenshots/real-assignment-candidates.png)

The STEP inputs and CLI JSON output were kept outside the repository. The
assembly is at the local path above; the extracted source and CLI result JSON
were saved in the temporary `hanomi-assembly-inventory` directory.

## Interpretation

Passing synthetic tests verifies only the listed generated cases. The real
assignment run confirms actual-file processing and the recorded three
candidates, but does not quantify false-positive rates, establish calibrated
confidence, or prove that every expected mating instance was found.

# Metadata Bundler (`metadata_bundler`)

Metadata Bundler reads a directory of VICARIUS `.meta.json` sidecar files and renders, for each one, a human-readable plain-text summary and an EML 2.2.0 XML document, for an operator preparing a readable handoff or an archival metadata package.

- Tags: META | Version: 1.0.0 | Type: process | Owner: Lauren K Olinger
- Repo: `vicarius/modules/metadata_bundler/github_repo` | Related studies: none
- Status: `module.yaml` declares no status field. It sets `hidden: false`, so the module is visible. It sets version 1.0.0 and records creation on 2026-04-22.

## What it does and why it exists

A sidecar is the `.meta.json` file a VICARIUS module writes next to each data artifact it produces. Each sidecar carries a frozen copy of the dataset descriptor (the `descriptor_snapshot`) plus run provenance: the job id, the producing module and step, the generation timestamp, the data file path, the SHA-256 hash, the byte count, and the row count. Sidecars are machine-oriented JSON. A person reads them only with effort, and they use no standard archival format.

Metadata Bundler turns each sidecar into two documents that people and archives can use. The plain-text file (`<basename>.txt`) is the primary deliverable: a monospace quick reference that states the dataset name, provenance, description, per-column summaries, coverage, license, and contact. The EML file (`<basename>.eml.xml`) is EML 2.2.0, the Ecological Metadata Language, which the bundler regenerates from the descriptor snapshot for archival and for interoperability with repositories that consume EML.

An operator runs the bundler after another module has produced artifacts and the sidecars beside them, to hand off a readable summary or to assemble an archival package. The module produces derived metadata only. It does not mint a new dataset type, so `module.yaml` declares `outputs: []` on purpose. The comment in `module.yaml` records the decision (per Lauren, 2026-04-22): the bundler pins the artifacts it writes to the upstream descriptor of the sidecar and mints no separate descriptor for them.

## Where it sits in the pipeline

Upstream of the bundler is any VICARIUS module that emits `.meta.json` sidecars at artifact-generation time through the platform sidecar generator at `_METADATA/sidecar/generate.py`. The `reef_point_seg` module is one such producer: it writes a point dataset CSV alongside a sidecar, which the bundler then renders. The bundler reads whatever sidecars sit in the directory the operator points it at. It does not call the upstream modules and does not require them to be running.

Downstream, no VICARIUS module consumes the outputs of the bundler. The plain-text file is a human deliverable for field QA, a quick reference, or a handoff. The EML file targets external EML-consuming metadata archives. The bundler sits off the survey chain (`bag_metashape_export -> 3D_phase1 -> 3D_phase2 -> reef_point_seg`). It is a META-tagged utility that runs after artifact generation for any module. It stands outside any single survey chain.

## Inputs

| Input | Type | Formats | Required | What it is |
|-------|------|---------|----------|------------|
| `sidecar_dir` | directory | `.meta.json` | yes | A directory holding one or more VICARIUS `.meta.json` sidecar files emitted by upstream modules. The operator passes this directory on the command line with `--sidecar-dir`. |

The bundler globs the directory for `*.meta.json` files, sorts them by name, and processes each one. It does not recurse into subdirectories. When a directory holds no matching files, the bundler logs a warning and writes nothing.

Each sidecar is a JSON object. The renderer reads these keys when present:

- `descriptor_snapshot`: the frozen dataset descriptor. The renderer reads these keys from the descriptor snapshot: `name`, `title`, `description`, `schema.fields` (each field carries `name`, `type`, `description`), `temporalCoverage.start` and `temporalCoverage.end`, `spatialCoverage.bbox` and `spatialCoverage.label`, `license`, and `schema_version`.
- Provenance keys: `schema_version`, `module`, `step`, `job_id`, `generated_at`, `file_path`, `file_sha256`, `byte_count`, `row_count`.
- `extra`: an optional dict. The renderer looks for `extra.stats` (precomputed per-field statistics), `extra.job_start`, `extra.job_end`, and `extra.processing_time_s`.

With `--csv-inspect`, the bundler also opens the data file named by `file_path` when that file sits next to the sidecar and ends in `.csv`, and computes per-field statistics from the rows of that file.

### Where to get a sidecar directory to point at

VICARIUS modules write a `.meta.json` sidecar next to each data file they produce, through the platform generator at `_METADATA/sidecar/generate.py`. As of 2026-07-04 no such sidecar sits on this drive. The producers write the data files but do not call the generator yet, so `reef_point_seg` leaves an `all_points.csv` in each run folder with no sidecar beside it, and a search for `*.meta.json` across the drive returns nothing. Two verified routes give you a real sidecar directory to point `--sidecar-dir` at.

Route 1 stays inside this repo and needs no other module. The helper `tests/_render_sample.py` writes a real, spec-shaped sidecar (`points.csv.meta.json`) next to a small CSV in a temporary directory, runs the bundler over it with `--format both --csv-inspect`, prints the two output paths and the rendered text bundle, then removes the temporary directory. Run it from the repo root:

```
python tests/_render_sample.py
```

This route exercises the renderer end to end and prints the exact text layout, with no descriptor store and no other module. It removes the temporary directory it created, so the run demonstrates a bundle end to end and leaves no directory to point `--sidecar-dir` at a second time.

Route 2 mints a sidecar next to a real producer output and then bundles it, which is the end-to-end run this module exists for. Copy a real data file into a working directory you own, mint the sidecar with the platform generator, then point `--sidecar-dir` at that directory:

```
# 1. copy a real producer output into a working directory
mkdir -p /tmp/mb_example
cp /mnt/rip/vicarius_drive/vicarius/modules/reef_point_seg/github_repo/supporting_data/all_points.csv /tmp/mb_example/

# 2. mint a .meta.json sidecar next to the copied file
cd /mnt/rip/vicarius_drive
PYTHONPATH=/mnt/rip/vicarius_drive/vicarius_ui_os python -m vicarius._METADATA.sidecar.generate --file /tmp/mb_example/all_points.csv --descriptor reef_point_seg_all_points --job 20260704-000000-reef_point_seg-example

# 3. bundle the directory that now holds the sidecar
cd /mnt/rip/vicarius_drive/vicarius/modules/metadata_bundler/github_repo
python scripts/bundle.py --sidecar-dir /tmp/mb_example --output-dir /tmp/mb_example/bundle --format both
```

The generator requires a registered descriptor. `reef_point_seg_all_points` is one, defined at `_METADATA/dictionary/datasets/reef_point_seg_all_points.yaml`, and it matches the 9 columns of `all_points.csv`. Any `all_points.csv` from a `reef_point_seg` run works in step 1. The copy under `supporting_data` in the `reef_point_seg` repo is a durable location, while the copies under `inprocess` run folders are transient test-run outputs. The generator requires the `PYTHONPATH` entry because it resolves descriptors through a `dictionary_store` module that it looks for under `vicarius_ui` at the repo root. That directory is archived, and the live descriptor store is `vicarius_ui_os`, so placing `vicarius_ui_os` on `PYTHONPATH` lets the import resolve (verified 2026-07-04). Step 3 then writes `all_points.csv.txt` and `all_points.csv.eml.xml` into `/tmp/mb_example/bundle`.

## Parameters

| Parameter | Type | Default | What it controls |
|-----------|------|---------|------------------|
| `contact` | string | `LO` | Contact identifier that the bundler prints in the plain-text bundle. Defaults to `LO`, the initials of Lauren; pass your own value to override. The bundler never prints an email unless you supply one. |
| `notes` | string | `""` (empty) | Free-form user notes that the bundler appends beneath the Description section. When empty, the bundler omits the entire block from the plain-text output. |
| `format` | string | `both` | Which artifacts to emit per sidecar: `txt`, `eml`, or `both`. |
| `csv_inspect` | boolean | `false` | When true, the bundler opens the data file that each sidecar references on disk and computes categorical and numerical statistics. When false, the bundler uses `extra.stats` from the sidecar if present, otherwise it skips statistics. |

One required argument, `--output-dir`, does not appear in the parameter list above. The parameters above tune behavior, while `--output-dir` names the output destination. The command line requires it, and the runner supplies it as the output directory for a UI run.

## Outputs and data-dictionary entries

This module produces no catalogued datasets. It writes derived-metadata documents that describe existing artifacts, so no `_METADATA/dictionary/datasets/<name>.yaml` descriptor covers the outputs of the bundler, and the runner emits no EML sidecar for those outputs. `module.yaml` records this exception (`outputs: []`, per Lauren, 2026-04-22): the bundler pins the artifacts to the descriptor of the upstream sidecar and mints no separate descriptor for them.

For each input sidecar, and depending on `--format`, the bundler writes into `--output-dir`:

| Written artifact | Path template | Descriptor | What it is |
|------------------|---------------|------------|------------|
| Plain-text bundle | `<output_dir>/<basename>.txt` | none | The main deliverable. A monospace, tab-aligned quick reference of the dataset. |
| EML document | `<output_dir>/<basename>.eml.xml` | none | EML 2.2.0 XML that the bundler regenerates from the descriptor snapshot and validates as well-formed before writing it. |

The basename comes from the sidecar filename with the `.meta.json` suffix removed. A sidecar named `all_points.csv.meta.json` yields `all_points.csv.txt` and `all_points.csv.eml.xml`. Both files share the basename. The bundler writes them atomically: it writes each to a `.tmp` file, then moves it into place. The bundler prints the full path of each written file to standard output and exits with status 0.

The plain-text file has this layout:

```
═════════════════════════════════════════════════════════════════
  VICARIUS  ·  reef_point_seg_all_points
    Unified TCRMP CVR Point Dataset
═════════════════════════════════════════════════════════════════

Schema version  : 1.0.0
Produced by     : reef_point_seg (step 1)
Job             : 20260422-203015-reef_point_seg-a4c1d9
Generated       : 2026-04-22 20:30:15 AST
Processing time : 0:04:17  (257 s)
File            : all_points.csv
Size            : 48,291 bytes
Row count       : 412
SHA-256         : ff92a1e3...

Description
─────────────────────────────────────────────────────────────────
Unified per-image coral point-count annotations extracted from
TCRMP CVR (Caribbean Video Recorder) transects...

Columns
─────────────────────────────────────────────────────────────────
  site_code       string    TCRMP site identifier
                            Values (all 5):
                              Salt_Pond         (118)
                              Black_Point       (97)
                              ...
  x               number    Normalized x coord (0 to 1)
                            min 0.003, max 0.997, mean 0.512, median 0.508

Temporal coverage : 2008-01-01  to  2024-12-31
Spatial coverage  : bbox  [-65.1, 17.6]  ->  [-64.5, 18.5]  (USVI)
License           : CC-BY-4.0
Contact           : LO
```

The word VICARIUS appears exactly once, in the top banner. The bundler renders all timestamps in Atlantic Standard Time (UTC-04:00), 24-hour.

## How to run it

### From the CLI

This is the supported way to run the module. From the module repo, with the environment set up (see Resume from cold):

```
python scripts/bundle.py \
    --sidecar-dir <path> \
    --output-dir  <path> \
    [--contact LO] \
    [--notes "..."] \
    [--format both|txt|eml] \
    [--csv-inspect]
```

- `--sidecar-dir` (required, named): directory of `*.meta.json` sidecars.
- `--output-dir` (required, named): output directory; the bundler creates it if it does not exist.
- `--contact` (default `LO`): contact identifier that the bundler prints in the text bundle. The bundler never prints an email unless you supply it.
- `--notes` (default empty): free-form notes that the bundler appends beneath the Description section; the bundler omits the block entirely when empty.
- `--format` (default `both`): `txt`, `eml`, or `both`.
- `--csv-inspect` (flag, off by default): open the CSV that each sidecar references and compute statistics on the fly. When absent, the bundler uses `extra.stats` from the sidecar if present, otherwise it omits statistics.

Both `--sidecar-dir` and `--output-dir` are required NAMED arguments. The script accepts no positional arguments. The `--csv-inspect` flag uses a hyphen. Argparse rejects the underscore form `--csv_inspect`.

### From the UI

The team archived the classic VICARIUS UI. The current UI runs on port 5090. The module homepage sits at `/modules/metadata_bundler`, where the homepage renders the parameter fields (`contact`, `notes`, `format`, `csv_inspect`) as a form.

As shipped, a UI launch does not drive this module hands-free, and a plain UI run fails. Two mismatches between the runner and the script cause this, both verified against `vicarius_ui_os/runner.py` and `scripts/bundle.py`:

- For a non-interactive module (this module sets no `cli.interactive`), the runner passes the input and output directories POSITIONALLY. `bundle.py` accepts no positional arguments and requires the named `--sidecar-dir` and `--output-dir`, so argparse errors before any work starts.
- The runner expands each form parameter as `--<key>` using the raw parameter name. The runner would emit the `csv_inspect` parameter as `--csv_inspect` (underscore), which argparse rejects; the real flag is `--csv-inspect` (hyphen).

`module.yaml` declares no `cli.flag_map`. Until a maintainer reconciles the runner convention and the script interface, run `scripts/bundle.py` directly with the exact named flags shown above.

## How it works inside

The entry point is `scripts/bundle.py`. The `bundle_dir` function in `bundle.py` globs `--sidecar-dir` for `*.meta.json`, sorts the matches, and calls `bundle_sidecar` on each. One malformed sidecar aborts the whole batch: `bundle_dir` re-raises any error, so a sidecar that is not a JSON object stops the run.

`bundle_sidecar` produces the requested artifacts for one sidecar:

- Text path (`--format txt` or `both`): `resolve_stats` decides the per-field statistics, then `format_text.format_sidecar_as_text` renders the string, and `write_atomic` writes `<basename>.txt`. The `format_text` module is pure standard library and does no I/O, which keeps it directly testable.
- EML path (`--format eml` or `both`): `render_eml` prefers `regenerate_eml_from_sidecar` from `_METADATA/sidecar/generate.py`, which handles sidecar-level provenance augmentation. On any failure (the generator is missing, the import fails, or the call raises), it falls back to `generate_eml(descriptor_snapshot)` from `_METADATA/eml/generate.py` and splices in a manual `<additionalMetadata>` block carrying the schema version, job id, sidecar `generated_at`, file SHA-256, and byte count. Before it writes the file, `render_eml` parses the XML with `ElementTree.fromstring` to confirm well-formedness. A broken document fails here with a clear error and never lands on disk.

`resolve_stats` follows this rule. Without `--csv-inspect`, it uses `extra.stats` from the sidecar if present, otherwise it returns nothing and the renderer omits statistics. With `--csv-inspect`, it opens the data file named by `file_path` when that file sits next to the sidecar and ends in `.csv`, reads the rows, and computes statistics against the field list in `descriptor_snapshot.schema.fields`. If the file is missing or is not a CSV, it falls back to `extra.stats`, otherwise it omits statistics.

`compute_stats_from_rows` in `format_text.py` reads the declared type of each field and summarizes the field:

- Numeric fields (`number`, `integer`, `float`, and similar) show `min`, `max`, `mean`, and `median`.
- Date fields (`date`, `datetime`, `timestamp`) show the range from earliest to latest.
- The renderer handles categorical fields by cardinality. With 10 or fewer distinct values, the renderer shows all of them, frequency-descending, under `Values (all N):`. With more than 10 distinct values and a repeating top value, it shows the top 10 under `Values (top 10 of N):`. With more than 10 distinct values and a top value that appears only once (an ID-like column, roughly one row per value), it shows 10 values sampled with a per-column-name random seed, so the same sidecar renders the same sample when read twice.

The bundler reads CSVs with pandas when it is installed and falls back to the standard-library `csv` module otherwise. The bundler computes numeric statistics with the standard-library `statistics` module.

Runtime requirements from `module.yaml` and `setup_env.sh`: Python 3.10 or newer, no GPU, tested on Ubuntu 22.04 and Ubuntu 24.04, roughly one second per sidecar. `setup_env.sh` creates a virtual environment and installs `pyyaml`, then optionally installs `pandas`. The two bundler scripts (`bundle.py`, `format_text.py`) import only the standard library plus optional pandas; the platform EML generators that `render_eml` imports at runtime consume `pyyaml` (unverified inference from the dependency list, since the bundler scripts do not import `yaml` directly).

## Gotchas and troubleshooting

- A UI launch fails as shipped. Use the CLI. See the From the UI section for the two verified reasons.
- The `--csv-inspect` flag uses a hyphen. Passing `--csv_inspect` makes argparse reject the argument.
- EML generation depends on the location of the module inside the VICARIUS tree. `bundle.py` computes the paths to the generators relative to the location of `bundle.py` itself: it expects to sit at `vicarius/modules/metadata_bundler/github_repo/scripts/bundle.py` so that `_METADATA/sidecar/generate.py` and `_METADATA/eml/generate.py` resolve. Running a copy of the script from outside that tree breaks the EML step. Passing `--format txt` avoids the generators entirely and needs no `_METADATA`.
- `--csv-inspect` only computes statistics when the data file sits next to the sidecar. `resolve_data_file` joins the parent directory of the sidecar with the bare `file_path` value; the bundler does not find a `file_path` that points elsewhere, so it falls back to `extra.stats` or omits statistics.
- One malformed sidecar stops the batch. A sidecar with top-level JSON that is not an object raises, and `bundle_dir` re-raises, so `bundle_dir` processes no further sidecars.
- The EML fallback path needs a usable `descriptor_snapshot`. When the preferred generator is unavailable and the sidecar has no non-empty `descriptor_snapshot`, `render_eml` raises a `ValueError`.
- The directory scan is not recursive and matches only `*.meta.json`. The scan ignores other files. When a directory holds no sidecars, the bundler logs a warning and writes nothing.
- Contact email never appears unless you supply it through `--contact`. The default `LO` prints no email.

## Resume from cold

These steps let a person with no prior context set up, run, and verify the module.

Environment. The interpreter is Python 3.10 or newer with no GPU. From the module repo, create the virtual environment and install dependencies:

```
cd /mnt/rip/vicarius_drive/vicarius/modules/metadata_bundler/github_repo
bash setup_env.sh
source .venv/bin/activate
```

`setup_env.sh` creates `.venv` in the repo, installs `pyyaml`, and optionally installs `pandas`. The bundler uses `pandas` only under `--csv-inspect`.

Location. Keep the module at `/mnt/rip/vicarius_drive/vicarius/modules/metadata_bundler/github_repo`. The EML step resolves `_METADATA/sidecar/generate.py` and `_METADATA/eml/generate.py` relative to this location.

Platform. The supported CLI path does not need the VICARIUS platform or the UI running. To launch from the UI instead (port 5090), bring the VICARIUS platform up first; see `/mnt/rip/vicarius_drive/vicarius/_DOCS/START_HERE.md`.

Inputs and outputs. The input is a directory of `*.meta.json` sidecar files. No such directory sits on this drive yet, so build one first. The section "Where to get a sidecar directory to point at" under Inputs gives two verified recipes: `python tests/_render_sample.py` for a self-contained demonstration, or a three-step mint-then-bundle sequence that produces a real sidecar directory at `/tmp/mb_example` from a `reef_point_seg` output. The output directory is whatever you pass to `--output-dir`; the bundler creates it if it does not exist.

Run, against the `/tmp/mb_example` directory produced by Route 2 above, or against any directory of `*.meta.json` sidecars:

```
python scripts/bundle.py \
    --sidecar-dir /tmp/mb_example \
    --output-dir  /tmp/mb_example/bundle \
    --format both
```

Add `--csv-inspect` to compute per-field statistics from the referenced CSVs, `--contact <id>` to set the contact, and `--notes "..."` to append a notes block.

Success check. For each sidecar `foo.meta.json` in the input directory, the output directory contains `foo.txt` and `foo.eml.xml` (or only the one requested by `--format`). The command prints the full path of each written file and exits 0. Each `.eml.xml` parses as well-formed XML, since the script validates before writing. To confirm the renderer on a synthetic fixture, run the test suite from the repo:

```
python tests/test_bundle.py
```

The suite has 8 test methods that cover 10 acceptance checks (one file-placement test covers the first three). It builds a synthetic sidecar and a tiny CSV in a temporary directory, runs the bundler, and asserts these results: the bundler emits both formats with matching basenames; VICARIUS appears exactly once; the default contact is `LO` with no email; a five-valued categorical column renders all five values in frequency-descending order; a numeric column shows min, max, mean, and median; the EML is well-formed; no empty Notes section appears without `--notes`; and a supplied note appears after the Description. A clean run reports `OK`.

## Provenance and links

- Repo: `vicarius/modules/metadata_bundler/github_repo`
- Contract: `module.yaml` in the repo root
- Entry script: `scripts/bundle.py`; renderer: `scripts/format_text.py`; environment: `setup_env.sh`; tests: `tests/test_bundle.py`
- Platform EML generators: `_METADATA/sidecar/generate.py` (`regenerate_eml_from_sidecar`) and `_METADATA/eml/generate.py` (`generate_eml`)
- Related modules: any producer of `.meta.json` sidecars, for example `reef_point_seg`
- Data-dictionary descriptors: none. The module produces derived metadata only and declares `outputs: []`.
- Related studies: none
- Author: Lauren K Olinger

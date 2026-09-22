"""
Developer helper: render a synthetic sidecar as a sample .txt bundle.
Not part of the unit-test suite; kept here so reviewers can reproduce
the exact rendering shown in the module hand-off notes.

Usage:
    python tests/_render_sample.py
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS_DIR = HERE.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def main() -> None:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mbundler_render_"))
    in_dir = tmp / "in"
    out_dir = tmp / "out"
    in_dir.mkdir()
    csv_path = in_dir / "points.csv"

    rows = [
        ("Salt_Pond",   0.10, "IMG_001", "2024-01-01"),
        ("Salt_Pond",   0.15, "IMG_002", "2024-01-02"),
        ("Salt_Pond",   0.20, "IMG_003", "2024-01-03"),
        ("Salt_Pond",   0.25, "IMG_004", "2024-01-04"),
        ("Black_Point", 0.30, "IMG_005", "2024-02-01"),
        ("Black_Point", 0.35, "IMG_006", "2024-02-02"),
        ("Black_Point", 0.40, "IMG_007", "2024-02-03"),
        ("Flat_Cay",    0.50, "IMG_008", "2024-03-01"),
        ("Flat_Cay",    0.55, "IMG_009", "2024-03-02"),
        ("Cane_Bay",    0.70, "IMG_010", "2024-04-01"),
        ("Cane_Bay",    0.80, "IMG_011", "2024-04-02"),
        ("Botany_Bay",  0.90, "IMG_012", "2024-05-01"),
    ]
    with csv_path.open("w") as h:
        h.write("site_code,x,image_id,date\n")
        for r in rows:
            h.write(f"{r[0]},{r[1]},{r[2]},{r[3]}\n")

    sidecar = {
        "vicarius_sidecar_version": "1.0",
        "descriptor_name": "test_points",
        "schema_version": "1.0.0",
        "descriptor_snapshot": {
            "name": "test_points",
            "schema_version": "1.0.0",
            "title": "Synthetic Test Points",
            "description": (
                "Synthetic test dataset for metadata_bundler unit tests.\n"
                "Includes categorical, numeric, and date columns."
            ),
            "module": "test_module",
            "license": "CC-BY-4.0",
            "temporalCoverage": {"start": "2024-01-01", "end": "2024-12-31"},
            "spatialCoverage": {"bbox": [-65.1, 17.6, -64.5, 18.5], "label": "USVI"},
            "schema": {"fields": [
                {"name": "site_code", "type": "string",
                 "description": "Test site identifier"},
                {"name": "x", "type": "number",
                 "description": "Normalized x coord (0 to 1)"},
                {"name": "image_id", "type": "string",
                 "description": "Unique image identifier"},
                {"name": "date", "type": "date",
                 "description": "Survey date"},
            ]},
        },
        "module": "test_module",
        "step": 1,
        "job_id": "20260422-120000-test_module-abc123",
        "generated_at": "2026-04-22T12:00:00-04:00",
        "file_path": "points.csv",
        "file_sha256": "ff92a1e3deadbeefcafe0000000000000000000000000000000000000000",
        "byte_count": csv_path.stat().st_size,
        "row_count": 12,
        "extra": {
            "job_start": "2026-04-22T11:55:00-04:00",
            "job_end":   "2026-04-22T12:00:00-04:00",
        },
    }
    (in_dir / "points.csv.meta.json").write_text(json.dumps(sidecar, indent=2))

    import bundle  # type: ignore
    bundle.main([
        "--sidecar-dir", str(in_dir),
        "--output-dir", str(out_dir),
        "--format", "both",
        "--csv-inspect",
    ])

    print((out_dir / "points.csv.txt").read_text())
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()

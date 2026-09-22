"""
Unit tests for the metadata_bundler module.

Covers the 10 acceptance checks called out in the module brief:

  1. build a synthetic sidecar + tiny CSV in /tmp
  2. run bundle.py --format both
  3. assert .txt + .eml.xml exist with matching basenames
  4. .txt contains "VICARIUS" exactly once
  5. .txt contains "Contact ... : LO" by default
  6. a 5-valued categorical column shows all 5, sorted by frequency desc
  7. a numerical column shows min / max / mean / median
  8. .eml.xml is well-formed
  9. without --notes, no empty Notes section sneaks in
 10. with --notes "some note", the note appears after Description

Run with:
    python -m pytest scripts/../tests/test_bundle.py -v
or directly:
    python tests/test_bundle.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
MODULE_ROOT = HERE.parent
SCRIPTS_DIR = MODULE_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import bundle  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_tiny_csv(path: Path) -> None:
    """
    Write a 12-row CSV with:
      - site_code:  5 distinct values, unequal frequencies (categorical-all)
      - x:          numeric in [0, 1]
      - image_id:   12 distinct values, one per row (categorical-random)
      - date:       date type
    """
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
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("site_code,x,image_id,date\n")
        for row in rows:
            handle.write(f"{row[0]},{row[1]},{row[2]},{row[3]}\n")


def _make_sidecar(csv_path: Path, sidecar_path: Path) -> dict:
    descriptor = {
        "name": "test_points",
        "schema_version": "1.0.0",
        "title": "Synthetic Test Points",
        "description": (
            "Synthetic test dataset for metadata_bundler unit tests. "
            "Includes categorical, numeric, and date columns."
        ),
        "module": "test_module",
        "dataType": "table",
        "format": "csv",
        "license": "CC-BY-4.0",
        "keywords": ["test", "synthetic"],
        "contact": {"name": "Test User", "email": "", "orcid": None},
        "temporalCoverage": {"start": "2024-01-01", "end": "2024-12-31"},
        "spatialCoverage": {"bbox": [-65.1, 17.6, -64.5, 18.5], "label": "USVI"},
        "schema": {
            "fields": [
                {"name": "site_code", "type": "string",
                 "description": "Test site identifier"},
                {"name": "x", "type": "number",
                 "description": "Normalized x coord (0 to 1)"},
                {"name": "image_id", "type": "string",
                 "description": "Unique image identifier"},
                {"name": "date", "type": "date",
                 "description": "Survey date"},
            ]
        },
    }
    sidecar = {
        "vicarius_sidecar_version": "1.0",
        "descriptor_name": "test_points",
        "schema_version": "1.0.0",
        "descriptor_snapshot": descriptor,
        "module": "test_module",
        "step": 1,
        "job_id": "20260422-120000-test_module-abc123",
        "generated_at": "2026-04-22T12:00:00-04:00",
        "file_path": csv_path.name,
        "file_sha256": "0" * 64,
        "byte_count": csv_path.stat().st_size,
        "row_count": 12,
        "extra": {
            "job_start": "2026-04-22T11:55:00-04:00",
            "job_end":   "2026-04-22T12:00:00-04:00",
        },
    }
    sidecar_path.write_text(json.dumps(sidecar, indent=2))
    return sidecar


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class MetadataBundlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mbundler_"))
        self.in_dir = self.tmp / "test_in"
        self.out_dir = self.tmp / "test_out"
        self.in_dir.mkdir()
        self.csv_path = self.in_dir / "points.csv"
        self.sidecar_path = self.in_dir / "points.csv.meta.json"
        _make_tiny_csv(self.csv_path)
        _make_sidecar(self.csv_path, self.sidecar_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 1-3: files land in the right place ------------------------------
    def test_01_02_03_both_formats_emitted(self) -> None:
        bundle.main([
            "--sidecar-dir", str(self.in_dir),
            "--output-dir", str(self.out_dir),
            "--format", "both",
            "--csv-inspect",
        ])
        txt = self.out_dir / "points.csv.txt"
        eml = self.out_dir / "points.csv.eml.xml"
        self.assertTrue(txt.exists(), f"missing text output: {txt}")
        self.assertTrue(eml.exists(), f"missing EML output: {eml}")

    # ---- 4: "VICARIUS" appears exactly once -----------------------------
    def test_04_vicarius_word_appears_once(self) -> None:
        bundle.main([
            "--sidecar-dir", str(self.in_dir),
            "--output-dir", str(self.out_dir),
            "--format", "txt",
        ])
        text = (self.out_dir / "points.csv.txt").read_text()
        self.assertEqual(
            text.count("VICARIUS"),
            1,
            f"expected exactly 1 occurrence of VICARIUS, got "
            f"{text.count('VICARIUS')}\n---\n{text}",
        )

    # ---- 5: default contact is "LO" -------------------------------------
    def test_05_default_contact_is_LO(self) -> None:
        bundle.main([
            "--sidecar-dir", str(self.in_dir),
            "--output-dir", str(self.out_dir),
            "--format", "txt",
        ])
        text = (self.out_dir / "points.csv.txt").read_text()
        # Allow any amount of padding between label and colon + value.
        self.assertRegex(
            text, r"Contact\s+:\s+LO\b",
            f"expected 'Contact : LO' line in output\n---\n{text}",
        )
        # And email must NOT appear.
        self.assertNotIn("@", text, "email must not appear when not passed")

    # ---- 6: categorical with 5 distinct -> all 5, freq-desc -------------
    def test_06_categorical_all_values_sorted_desc(self) -> None:
        bundle.main([
            "--sidecar-dir", str(self.in_dir),
            "--output-dir", str(self.out_dir),
            "--format", "txt",
            "--csv-inspect",
        ])
        text = (self.out_dir / "points.csv.txt").read_text()
        self.assertIn("Values (all 5)", text,
                      f"expected 'Values (all 5)' for site_code\n---\n{text}")
        # Confirm frequency-descending order: Salt_Pond(4) > Black_Point(3)
        # > Flat_Cay(2)/Cane_Bay(2) > Botany_Bay(1).
        idx_salt = text.find("Salt_Pond")
        idx_black = text.find("Black_Point")
        idx_flat = text.find("Flat_Cay")
        idx_botany = text.find("Botany_Bay")
        self.assertLess(idx_salt, idx_black,
                        "Salt_Pond (4) should precede Black_Point (3)")
        self.assertLess(idx_black, idx_flat,
                        "Black_Point (3) should precede Flat_Cay (2)")
        self.assertLess(idx_flat, idx_botany,
                        "Flat_Cay (2) should precede Botany_Bay (1)")
        # And the (count) markers are present.
        self.assertIn("(4)", text)
        self.assertIn("(3)", text)
        self.assertIn("(1)", text)

    # ---- 7: numerical column shows min/max/mean/median ------------------
    def test_07_numeric_stats_complete(self) -> None:
        bundle.main([
            "--sidecar-dir", str(self.in_dir),
            "--output-dir", str(self.out_dir),
            "--format", "txt",
            "--csv-inspect",
        ])
        text = (self.out_dir / "points.csv.txt").read_text()
        # Find the block under `x` column. Easiest: check the one line that
        # carries the four stat tokens together.
        self.assertRegex(
            text,
            r"min\s+\S+,\s*max\s+\S+,\s*mean\s+\S+,\s*median\s+\S+",
            f"expected 'min X, max Y, mean Z, median W' for x column\n"
            f"---\n{text}",
        )

    # ---- 8: EML XML is well-formed --------------------------------------
    def test_08_eml_is_wellformed(self) -> None:
        bundle.main([
            "--sidecar-dir", str(self.in_dir),
            "--output-dir", str(self.out_dir),
            "--format", "eml",
        ])
        xml_path = self.out_dir / "points.csv.eml.xml"
        self.assertTrue(xml_path.exists(), f"missing EML: {xml_path}")
        # ET.fromstring raises if malformed.
        ET.fromstring(xml_path.read_text())

    # ---- 9: no empty Notes section when --notes omitted -----------------
    def test_09_no_empty_notes_section(self) -> None:
        bundle.main([
            "--sidecar-dir", str(self.in_dir),
            "--output-dir", str(self.out_dir),
            "--format", "txt",
        ])
        text = (self.out_dir / "points.csv.txt").read_text()
        # Our format does not emit a standalone "Notes" header; notes are
        # appended under Description. An empty block would manifest as a
        # bare "Notes" line, extra whitespace, or a rule-under-Description
        # with nothing after it. Check for all of those.
        self.assertNotIn("Notes\n", text, "empty Notes block must not appear")
        self.assertNotIn("\nNotes:\n", text,
                         "empty Notes: header must not appear")
        # There must not be two consecutive blank lines trailing the
        # Description rule (which would indicate an empty notes paragraph).
        self.assertNotRegex(
            text, r"Description\n─+\n\s*\n\s*\nColumns",
            f"empty paragraph between Description and Columns\n---\n{text}",
        )

    # ---- 10: with --notes, the note appears after Description ----------
    def test_10_notes_appear_after_description(self) -> None:
        note_text = "This is a one-off reference bundle for field QA."
        bundle.main([
            "--sidecar-dir", str(self.in_dir),
            "--output-dir", str(self.out_dir),
            "--format", "txt",
            "--notes", note_text,
        ])
        text = (self.out_dir / "points.csv.txt").read_text()
        self.assertIn(note_text, text,
                      f"notes text not found in output\n---\n{text}")
        idx_desc = text.find("Description")
        idx_note = text.find(note_text)
        idx_cols = text.find("Columns")
        self.assertNotEqual(idx_desc, -1, "Description section missing")
        self.assertNotEqual(idx_note, -1, "note text missing")
        self.assertLess(idx_desc, idx_note,
                        "note must come after the Description header")
        # If Columns is present, note must precede it.
        if idx_cols != -1:
            self.assertLess(idx_note, idx_cols,
                            "note must precede the Columns section")


if __name__ == "__main__":
    unittest.main(verbosity=2)

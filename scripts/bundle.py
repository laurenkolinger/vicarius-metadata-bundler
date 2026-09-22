"""
metadata_bundler.scripts.bundle
================================

Driver script for the ``metadata_bundler`` VICARIUS module.

For each ``*.meta.json`` sidecar in ``--sidecar-dir``, emits up to two
derived-metadata artifacts in ``--output-dir``:

    <basename>.eml.xml    EML 2.2.0 XML (regenerated from sidecar snapshot)
    <basename>.txt        Human-readable plain-text bundle (main deliverable)

The plain-text format is the Lauren-approved spec dated 2026-04-22; see
``format_text.format_sidecar_as_text`` for the renderer.

EML generation prefers ``_METADATA/sidecar/generate.regenerate_eml_from_sidecar``
(which handles sidecar-level provenance augmentation) and falls back to
``_METADATA/eml/generate.generate_eml(descriptor_snapshot)`` plus a manual
``<additionalMetadata>`` splice when Agent F's module is unavailable.

CLI:

    python bundle.py --sidecar-dir <path> --output-dir <path>
                     [--contact LO] [--notes "..."]
                     [--format both|txt|eml] [--csv-inspect]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as _xml_escape

logger = logging.getLogger("metadata_bundler")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
MODULE_ROOT = HERE.parent                              # .../github_repo
MODULES_DIR = MODULE_ROOT.parent.parent                # .../vicarius/modules
VICARIUS_ROOT = MODULES_DIR.parent                      # .../vicarius
METADATA_DIR = VICARIUS_ROOT / "_METADATA"
SIDECAR_GEN_PATH = METADATA_DIR / "sidecar" / "generate.py"
EML_GEN_PATH = METADATA_DIR / "eml" / "generate.py"

# Make the sibling ``format_text`` module importable whether this file is run
# directly (``python bundle.py``) or imported by tests (``from scripts import
# bundle``).
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from format_text import (  # noqa: E402  (import after sys.path mutation)
    compute_stats_from_rows,
    format_sidecar_as_text,
)

SIDECAR_SUFFIX = ".meta.json"


# ---------------------------------------------------------------------------
# Sidecar + CSV helpers
# ---------------------------------------------------------------------------

def load_sidecar(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"sidecar at {path} is not a JSON object")
    return payload


def resolve_data_file(sidecar_path: Path, sidecar: dict) -> Optional[Path]:
    """Locate the sidecar's data file on disk if it sits next to the sidecar."""
    file_name = sidecar.get("file_path")
    if not file_name:
        return None
    candidate = sidecar_path.parent / file_name
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def _read_csv_rows_pandas(path: Path) -> Optional[list[dict]]:
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        return None
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        logger.warning("pandas failed to read %s: %s", path, exc)
        return None
    return [
        {k: (None if _pd_isna(v) else v) for k, v in rec.items()}
        for rec in df.to_dict(orient="records")
    ]


def _pd_isna(value: Any) -> bool:
    try:
        import pandas as pd  # type: ignore
        return bool(pd.isna(value))
    except Exception:
        return value is None


def _read_csv_rows_stdlib(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def read_csv_rows(path: Path) -> list[dict]:
    """Read a CSV into a list of row-dicts. Prefers pandas if available."""
    rows = _read_csv_rows_pandas(path)
    if rows is not None:
        return rows
    return _read_csv_rows_stdlib(path)


# ---------------------------------------------------------------------------
# Stats resolution
# ---------------------------------------------------------------------------

def resolve_stats(
    sidecar_path: Path,
    sidecar: dict,
    *,
    csv_inspect: bool,
) -> Optional[dict[str, dict]]:
    """
    Determine per-field stats for the sidecar according to the spec:

    - ``--csv-inspect`` set:
        - Open the referenced data file if present next to the sidecar
          and compute stats. Fall back to ``extra.stats`` if the file is
          missing; otherwise None.
    - ``--csv-inspect`` not set:
        - Use ``extra.stats`` if present, else None (stats omitted).
    """
    extra = sidecar.get("extra") or {}
    precomputed = extra.get("stats") if isinstance(extra, dict) else None

    if not csv_inspect:
        return precomputed if isinstance(precomputed, dict) else None

    data_file = resolve_data_file(sidecar_path, sidecar)
    if data_file is None or data_file.suffix.lower() != ".csv":
        if isinstance(precomputed, dict):
            return precomputed
        return None

    try:
        rows = read_csv_rows(data_file)
    except Exception as exc:
        logger.warning("csv-inspect failed for %s: %s", data_file, exc)
        if isinstance(precomputed, dict):
            return precomputed
        return None

    descriptor = sidecar.get("descriptor_snapshot") or {}
    fields = (descriptor.get("schema") or {}).get("fields") or []
    if not isinstance(fields, list):
        return None
    return compute_stats_from_rows(rows, [f for f in fields if isinstance(f, dict)])


# ---------------------------------------------------------------------------
# EML generation (with fallback)
# ---------------------------------------------------------------------------

def _dynamic_import(module_name: str, file_path: Path):
    """Import a python file by absolute path. Returns the module or raises."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[arg-type]
    return mod


def render_eml(sidecar_path: Path, sidecar: dict) -> str:
    """
    Preferred path: call ``regenerate_eml_from_sidecar`` from Agent F's
    ``_METADATA/sidecar/generate.py``. On any failure (missing module,
    import error, runtime error) fall back to the raw EML generator plus
    a manual ``<additionalMetadata>`` splice.
    """
    # --- Preferred path ---------------------------------------------------
    if SIDECAR_GEN_PATH.exists():
        try:
            mod = _dynamic_import("metadata_bundler_sidecar_gen", SIDECAR_GEN_PATH)
            fn = getattr(mod, "regenerate_eml_from_sidecar", None)
            if callable(fn):
                return fn(str(sidecar_path))
        except Exception as exc:
            logger.warning(
                "sidecar regenerate_eml_from_sidecar failed (%s); "
                "falling back to raw EML generator",
                exc,
            )

    # --- Fallback ---------------------------------------------------------
    if not EML_GEN_PATH.exists():
        raise RuntimeError(
            f"no EML generator available at {EML_GEN_PATH} — cannot "
            f"produce EML for {sidecar_path}"
        )
    eml_mod = _dynamic_import("metadata_bundler_eml_gen", EML_GEN_PATH)
    generate_eml = getattr(eml_mod, "generate_eml", None)
    if not callable(generate_eml):
        raise RuntimeError("EML generator exposes no generate_eml()")

    descriptor = sidecar.get("descriptor_snapshot") or {}
    if not isinstance(descriptor, dict) or not descriptor:
        raise ValueError(
            f"sidecar at {sidecar_path} has no usable descriptor_snapshot"
        )
    xml_text = generate_eml(descriptor)
    extra_xml = _build_additional_metadata_block(sidecar)
    closing = "</dataset>"
    if closing in xml_text and extra_xml:
        xml_text = xml_text.replace(closing, closing + "\n  " + extra_xml, 1)
    return xml_text


def _build_additional_metadata_block(sidecar: dict) -> str:
    """Mirror the block Agent F's sidecar generator splices in. Stdlib only."""
    fields: list[tuple[str, Any]] = [
        ("schemaVersion", sidecar.get("schema_version")),
        ("jobId", sidecar.get("job_id")),
        ("sidecarGeneratedAt", sidecar.get("generated_at")),
        ("fileSha256", sidecar.get("file_sha256")),
        ("byteCount", sidecar.get("byte_count")),
    ]
    rendered = "".join(
        f"<{k}>{_xml_escape(str(v))}</{k}>"
        for k, v in fields
        if v is not None and v != ""
    )
    if not rendered:
        return ""
    return (
        "<additionalMetadata><metadata>"
        + rendered
        + "</metadata></additionalMetadata>"
    )


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def output_basename(sidecar_path: Path) -> str:
    """
    ``/x/y/all_points.csv.meta.json`` -> ``all_points.csv``.

    Non-``.meta.json`` filenames fall back to ``path.stem``.
    """
    name = sidecar_path.name
    if name.endswith(SIDECAR_SUFFIX):
        return name[: -len(SIDECAR_SUFFIX)]
    return sidecar_path.stem


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Main bundler
# ---------------------------------------------------------------------------

def bundle_sidecar(
    sidecar_path: Path,
    output_dir: Path,
    *,
    contact: str,
    notes: str,
    fmt: str,
    csv_inspect: bool,
) -> list[Path]:
    """Produce the requested artifacts for one sidecar; return written paths."""
    sidecar = load_sidecar(sidecar_path)
    basename = output_basename(sidecar_path)
    written: list[Path] = []

    if fmt in ("txt", "both"):
        stats = resolve_stats(sidecar_path, sidecar, csv_inspect=csv_inspect)
        text = format_sidecar_as_text(
            sidecar,
            stats=stats,
            contact=contact,
            notes=notes,
        )
        txt_path = output_dir / f"{basename}.txt"
        write_atomic(txt_path, text)
        written.append(txt_path)

    if fmt in ("eml", "both"):
        xml = render_eml(sidecar_path, sidecar)
        eml_path = output_dir / f"{basename}.eml.xml"
        # Validate well-formedness before we commit the file. A broken XML
        # document is a harder-to-debug failure than a clear error here.
        ET.fromstring(xml)
        write_atomic(eml_path, xml)
        written.append(eml_path)

    return written


def bundle_dir(
    sidecar_dir: Path,
    output_dir: Path,
    *,
    contact: str,
    notes: str,
    fmt: str,
    csv_inspect: bool,
) -> list[Path]:
    if not sidecar_dir.is_dir():
        raise NotADirectoryError(f"--sidecar-dir is not a directory: {sidecar_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    sidecars = sorted(sidecar_dir.glob(f"*{SIDECAR_SUFFIX}"))
    if not sidecars:
        logger.warning(
            "no %s files found under %s", SIDECAR_SUFFIX, sidecar_dir
        )
    written: list[Path] = []
    for sidecar_path in sidecars:
        try:
            written.extend(
                bundle_sidecar(
                    sidecar_path,
                    output_dir,
                    contact=contact,
                    notes=notes,
                    fmt=fmt,
                    csv_inspect=csv_inspect,
                )
            )
        except Exception as exc:
            logger.error("failed to bundle %s: %s", sidecar_path, exc)
            raise
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="metadata_bundler",
        description=(
            "Bundle a directory of VICARIUS .meta.json sidecars into EML XML "
            "and human-readable plain-text metadata files."
        ),
    )
    parser.add_argument("--sidecar-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--contact",
        default="LO",
        help="Contact identifier printed in the text bundle (default: LO).",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional user notes appended beneath Description; omitted if empty.",
    )
    parser.add_argument(
        "--format",
        dest="fmt",
        choices=("txt", "eml", "both"),
        default="both",
    )
    parser.add_argument(
        "--csv-inspect",
        action="store_true",
        help="Open each sidecar's referenced CSV to compute stats on the fly.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    written = bundle_dir(
        args.sidecar_dir,
        args.output_dir,
        contact=args.contact,
        notes=args.notes,
        fmt=args.fmt,
        csv_inspect=args.csv_inspect,
    )
    for path in written:
        print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

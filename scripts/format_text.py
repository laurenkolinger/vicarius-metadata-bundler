"""
metadata_bundler.scripts.format_text
====================================

Render a VICARIUS sidecar (``.meta.json``) into the plain-text bundle
format approved by Lauren Olinger on 2026-04-22.

Design principles
-----------------
- Pure / stdlib only. No I/O. Input: a sidecar dict + optional stats dict.
  Output: a string. This keeps the formatter trivially testable.
- One word "VICARIUS" in the whole document, in the top banner.
- Monospace / tab-aligned. 2-space indent. Unicode box-drawing (``═`` /
  ``─``) for section separators.
- Notes section is suppressed entirely when the user passes nothing.
- Processing-time row is suppressed cleanly when neither
  ``job_end`` - ``job_start`` nor ``extra.processing_time_s`` is available.

See ``bundle.py`` for the CLI driver.
"""
from __future__ import annotations

import random
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BANNER_WIDTH = 65
_SECTION_RULE = "─" * _BANNER_WIDTH
_BANNER_RULE = "═" * _BANNER_WIDTH

# Column indent widths. Chosen for legibility at ~80-col terminals.
_COL_NAME_WIDTH = 15          # width of the column-name cell
_COL_TYPE_WIDTH = 10          # width of the type cell
_COL_INDENT = "  "            # indent for the whole Columns block
_COL_INNER_INDENT = " " * (len(_COL_INDENT) + _COL_NAME_WIDTH + _COL_TYPE_WIDTH)

# Random-sample seed is fixed per-column-name so the same sidecar renders
# deterministically when read twice. We re-seed inside _format_column().
_RANDOM_ID_SAMPLE = 10
_TOP_N = 10

_AST = timezone(timedelta(hours=-4))

_NUMERIC_TYPES = {"number", "integer", "float", "int", "double", "decimal", "numeric"}
_DATE_TYPES = {"date", "datetime", "timestamp"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _fmt_int(value: Optional[int]) -> str:
    if value is None:
        return ""
    return f"{int(value):,}"


def _fmt_num(value: Any) -> str:
    """Render a numeric value with up to 3 decimals, trimmed trailing zeros."""
    if value is None:
        return ""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f == int(f):
        return str(int(f))
    return f"{f:.3f}".rstrip("0").rstrip(".")


def _coerce_generated_at(raw: Any) -> str:
    """Render ``generated_at`` as ``YYYY-MM-DD HH:MM:SS AST``."""
    if not raw:
        return ""
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return raw  # best-effort: pass through
    elif isinstance(raw, datetime):
        dt = raw
    else:
        return str(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_AST)
    dt = dt.astimezone(_AST)
    return dt.strftime("%Y-%m-%d %H:%M:%S AST")


def _coerce_isoformat(raw: Any) -> Optional[datetime]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _processing_time_rows(sidecar: dict) -> Optional[str]:
    """
    Return the pre-formatted ``Processing time`` row, or None to omit it.

    Priority:
      1. ``extra.job_end`` - ``extra.job_start`` if both parse.
      2. ``extra.processing_time_s`` if scalar.
    """
    extra = sidecar.get("extra") or {}
    start = _coerce_isoformat(extra.get("job_start"))
    end = _coerce_isoformat(extra.get("job_end"))
    if start is not None and end is not None and end >= start:
        seconds = int((end - start).total_seconds())
    else:
        pts = extra.get("processing_time_s")
        try:
            seconds = int(float(pts)) if pts is not None else None
        except (TypeError, ValueError):
            seconds = None
    if seconds is None:
        return None

    td = timedelta(seconds=seconds)
    # Render as H:MM:SS (drop days for readability; sidecars rarely exceed a day).
    total_seconds = int(td.total_seconds())
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}  ({total_seconds} s)"


def _first_nonblank(*values: Any) -> str:
    for v in values:
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        return str(v)
    return ""


def _step_label(sidecar: dict) -> str:
    module = sidecar.get("module") or "unknown"
    step = sidecar.get("step")
    if step is None or step == "":
        return str(module)
    return f"{module} (step {step})"


def _descriptor_schema_fields(descriptor: dict) -> list[dict]:
    schema = descriptor.get("schema") or {}
    fields = schema.get("fields") or []
    if not isinstance(fields, list):
        return []
    return [f for f in fields if isinstance(f, dict)]


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def _is_numeric_type(t: str) -> bool:
    return (t or "").lower() in _NUMERIC_TYPES


def _is_date_type(t: str) -> bool:
    return (t or "").lower() in _DATE_TYPES


def _coerce_numeric_list(values: Iterable[Any]) -> list[float]:
    out: list[float] = []
    for v in values:
        if v is None or v == "":
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _coerce_date_list(values: Iterable[Any]) -> list[datetime]:
    out: list[datetime] = []
    for v in values:
        dt = _coerce_isoformat(v) if isinstance(v, str) else (
            v if isinstance(v, datetime) else None
        )
        if dt is not None:
            out.append(dt)
    return out


def compute_stats_from_rows(
    rows: list[dict], fields: list[dict]
) -> dict[str, dict]:
    """
    Given a list of row-dicts and a field descriptor list, return
    ``{field_name: stats_dict}``.

    stats_dict schema:
      - categorical:  {"kind": "categorical", "counts": [(value, n), ...],
                       "distinct": int, "total_rows": int}
      - numeric:      {"kind": "numeric", "min": x, "max": y,
                       "mean": z, "median": w}
      - date:         {"kind": "date", "min": iso, "max": iso}
    """
    stats: dict[str, dict] = {}
    total = len(rows)
    for field in fields:
        name = field.get("name")
        if not name:
            continue
        ftype = (field.get("type") or "").lower()
        col_values = [r.get(name) for r in rows]

        if _is_numeric_type(ftype):
            nums = _coerce_numeric_list(col_values)
            if not nums:
                continue
            stats[name] = {
                "kind": "numeric",
                "min": min(nums),
                "max": max(nums),
                "mean": statistics.fmean(nums),
                "median": statistics.median(nums),
            }
        elif _is_date_type(ftype):
            dates = _coerce_date_list(col_values)
            if not dates:
                continue
            stats[name] = {
                "kind": "date",
                "min": min(dates).date().isoformat(),
                "max": max(dates).date().isoformat(),
            }
        else:
            non_null = [v for v in col_values if v is not None and v != ""]
            counter = Counter(str(v) for v in non_null)
            if not counter:
                continue
            stats[name] = {
                "kind": "categorical",
                "counts": counter.most_common(),
                "distinct": len(counter),
                "total_rows": total,
            }
    return stats


# ---------------------------------------------------------------------------
# Column rendering
# ---------------------------------------------------------------------------

def _format_column(field: dict, stats: Optional[dict]) -> str:
    """
    Render one column entry. Lines after the header are indented to align
    under the description column.
    """
    name = str(field.get("name") or "")
    ftype = str(field.get("type") or "")
    desc = str(field.get("description") or "").strip()

    head = (
        _COL_INDENT
        + name.ljust(_COL_NAME_WIDTH)
        + ftype.ljust(_COL_TYPE_WIDTH)
        + desc
    )
    lines = [head]

    if stats is None:
        return head

    kind = stats.get("kind")
    if kind == "numeric":
        mn = _fmt_num(stats.get("min"))
        mx = _fmt_num(stats.get("max"))
        mean = _fmt_num(stats.get("mean"))
        med = _fmt_num(stats.get("median"))
        lines.append(
            _COL_INNER_INDENT
            + f"min {mn}, max {mx}, mean {mean}, median {med}"
        )
    elif kind == "date":
        lines.append(
            _COL_INNER_INDENT
            + f"range  {stats.get('min')}  to  {stats.get('max')}"
        )
    elif kind == "categorical":
        counts: list[tuple[str, int]] = list(stats.get("counts") or [])
        distinct = int(stats.get("distinct") or len(counts))
        total_rows = int(stats.get("total_rows") or 0)

        if distinct <= _TOP_N:
            header = f"Values (all {distinct}):"
            shown = counts
            rendered = _render_counts(shown)
        else:
            # Heuristic: if the top value appears only once, this is
            # essentially an ID column (~1 row per distinct value).
            top_count = counts[0][1] if counts else 0
            if top_count <= 1:
                rng = random.Random(name)
                labels = [v for v, _ in counts]
                rng.shuffle(labels)
                sample = labels[:_RANDOM_ID_SAMPLE]
                header = (
                    f"Values (random {len(sample)} of {distinct} "
                    f"— 1 per row)"
                )
                rendered = [_COL_INNER_INDENT + "  " + ", ".join(sample)]
            else:
                header = f"Values (top {_TOP_N} of {distinct}):"
                shown = counts[:_TOP_N]
                rendered = _render_counts(shown)

        lines.append(_COL_INNER_INDENT + header)
        lines.extend(rendered)

    return "\n".join(lines)


def _render_counts(counts: list[tuple[str, int]]) -> list[str]:
    """Render a ``value   (count)`` column under _COL_INNER_INDENT+"  "."""
    if not counts:
        return []
    max_val_w = max(len(str(v)) for v, _ in counts)
    out = []
    for v, n in counts:
        out.append(
            _COL_INNER_INDENT
            + "  "
            + str(v).ljust(max_val_w + 2)
            + f"({n})"
        )
    return out


# ---------------------------------------------------------------------------
# Top-level renderer
# ---------------------------------------------------------------------------

def format_sidecar_as_text(
    sidecar: dict,
    *,
    stats: Optional[dict[str, dict]] = None,
    contact: str = "LO",
    notes: str = "",
) -> str:
    """
    Render a sidecar (+ optional precomputed per-field stats) as the
    Lauren-approved plain-text bundle.
    """
    descriptor = sidecar.get("descriptor_snapshot") or {}
    dataset_name = _first_nonblank(
        sidecar.get("descriptor_name"),
        descriptor.get("name"),
        "unknown_dataset",
    )
    title = _first_nonblank(descriptor.get("title"), dataset_name)

    # --- Banner ----------------------------------------------------------
    banner_lines = [
        _BANNER_RULE,
        f"  VICARIUS  ·  {dataset_name}",
        f"    {title}",
        _BANNER_RULE,
        "",
    ]

    # --- Provenance / header block --------------------------------------
    header_rows: list[tuple[str, str]] = []

    def _add(label: str, value: str) -> None:
        if value == "" or value is None:
            return
        header_rows.append((label, value))

    _add("Schema version", _first_nonblank(sidecar.get("schema_version"),
                                           descriptor.get("schema_version")))
    _add("Produced by", _step_label(sidecar))
    _add("Job", _first_nonblank(sidecar.get("job_id")))
    _add("Generated", _coerce_generated_at(sidecar.get("generated_at")))

    ptime = _processing_time_rows(sidecar)
    if ptime is not None:
        _add("Processing time", ptime)

    _add("File", _first_nonblank(sidecar.get("file_path")))
    byte_count = sidecar.get("byte_count")
    if isinstance(byte_count, (int, float)):
        _add("Size", f"{_fmt_int(int(byte_count))} bytes")
    row_count = sidecar.get("row_count")
    if isinstance(row_count, (int, float)):
        _add("Row count", _fmt_int(int(row_count)))
    sha = sidecar.get("file_sha256")
    if sha:
        _add("SHA-256", str(sha))

    label_width = max((len(k) for k, _ in header_rows), default=0)
    provenance_lines = [
        f"{k.ljust(label_width)} : {v}"
        for k, v in header_rows
    ]

    # --- Description ----------------------------------------------------
    description = (descriptor.get("description") or "").strip()
    description_block: list[str] = []
    if description:
        description_block.append("")
        description_block.append("Description")
        description_block.append(_SECTION_RULE)
        description_block.extend(description.splitlines())

    notes_block: list[str] = []
    if notes and notes.strip():
        # Render notes beneath the Description header ONLY when non-empty.
        # If there is no descriptor description, we still open the section
        # once so the header rule is present exactly once.
        if not description_block:
            notes_block.append("")
            notes_block.append("Description")
            notes_block.append(_SECTION_RULE)
        notes_block.append("")
        for line in notes.strip().splitlines():
            notes_block.append(line)

    # --- Columns --------------------------------------------------------
    fields = _descriptor_schema_fields(descriptor)
    column_block: list[str] = []
    if fields:
        column_block.append("")
        column_block.append("Columns")
        column_block.append(_SECTION_RULE)
        for field in fields:
            field_name = field.get("name")
            field_stats = None
            if stats and field_name in stats:
                field_stats = stats[field_name]
            column_block.append(_format_column(field, field_stats))

    # --- Trailer --------------------------------------------------------
    trailer_rows: list[tuple[str, str]] = []
    temporal = descriptor.get("temporalCoverage") or {}
    t_start = temporal.get("start")
    t_end = temporal.get("end")
    if t_start or t_end:
        tc = f"{t_start or '?'}  to  {t_end or '?'}"
        trailer_rows.append(("Temporal coverage", tc))

    spatial = descriptor.get("spatialCoverage")
    if spatial:
        if isinstance(spatial, dict):
            bbox = spatial.get("bbox") or spatial.get("boundingBox")
            label = spatial.get("label") or spatial.get("name") or ""
            if bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                sw_x, sw_y, ne_x, ne_y = bbox
                rendered = (
                    f"bbox  [{_fmt_num(sw_x)}, {_fmt_num(sw_y)}]  "
                    f"→  [{_fmt_num(ne_x)}, {_fmt_num(ne_y)}]"
                )
                if label:
                    rendered += f"  ({label})"
                trailer_rows.append(("Spatial coverage", rendered))
            elif label:
                trailer_rows.append(("Spatial coverage", str(label)))
        else:
            trailer_rows.append(("Spatial coverage", str(spatial)))

    license_val = descriptor.get("license")
    if license_val:
        trailer_rows.append(("License", str(license_val)))

    trailer_rows.append(("Contact", contact or "LO"))

    trailer_width = max((len(k) for k, _ in trailer_rows), default=0)
    trailer_lines: list[str] = []
    if trailer_rows:
        trailer_lines.append("")
        for k, v in trailer_rows:
            trailer_lines.append(f"{k.ljust(trailer_width)} : {v}")

    # --- Assemble -------------------------------------------------------
    out_lines: list[str] = []
    out_lines.extend(banner_lines)
    out_lines.extend(provenance_lines)
    out_lines.extend(description_block)
    out_lines.extend(notes_block)
    out_lines.extend(column_block)
    out_lines.extend(trailer_lines)
    out_lines.append("")
    return "\n".join(out_lines)

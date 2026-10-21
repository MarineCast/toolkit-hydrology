"""One typed Parquet with embedded recipe; no release directory or sidecar files."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .products import checksum
from .provenance import digest

METADATA_KEY = b"hydrology_influence"
FORMAT = "hydrology-influence-factors-1"
SCHEMA = pa.schema(
    [
        ("factor_type", pa.string()),
        ("river_id", pa.string()),
        ("h3_index", pa.string()),
        ("distance_profile", pa.string()),
        ("water_distance_m", pa.float64()),
        ("reachable_r8_children", pa.int64()),
        ("weight", pa.float64()),
        ("date", pa.date32()),
        ("lag_profile", pa.string()),
        ("discharge", pa.float64()),
        ("relative_flow", pa.float64()),
        ("interpolated_input_weight", pa.float64()),
    ]
)


def factor_table(spatial, signals, recipe):
    """Discriminated factors retain native grains without a cell × day expansion."""
    records = [{"factor_type": "spatial", **row} for row in spatial]
    records.extend(
        {"factor_type": "temporal", **row, "date": date.fromisoformat(row["date"])}
        for row in signals
    )
    table = pa.Table.from_pylist(records, schema=SCHEMA)
    metadata = {
        "format": FORMAT,
        "identity": digest(recipe),
        "recipe": recipe,
        "factors_sha256": factor_digest(table),
    }
    return table.replace_schema_metadata(
        {METADATA_KEY: json.dumps(metadata, sort_keys=True, allow_nan=False).encode()}
    )


def factor_digest(table):
    """Hash logical typed rows, independently of Parquet encoding and row groups."""
    result = hashlib.sha256()
    for batch in table.to_batches(max_chunksize=10000):
        for row in batch.to_pylist():
            result.update(
                json.dumps(
                    row,
                    sort_keys=True,
                    default=str,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode()
            )
            result.update(b"\n")
    return result.hexdigest()


def write_influence(path, table, check_sources):
    """Validate a sibling staging file before atomically replacing the owned file."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Influence output must be a regular Parquet file")
    if path.exists():
        metadata = pq.read_metadata(path).metadata or {}
        if json.loads(metadata.get(METADATA_KEY, b"{}")).get("format") != FORMAT:
            raise ValueError("Refusing to replace an unowned influence file")
        if pq.read_table(path).equals(table, check_metadata=True):
            check_sources()
            return checksum(path)
    fd, temporary = tempfile.mkstemp(
        prefix=".influence-", suffix=".tmp", dir=path.parent
    )
    os.close(fd)
    try:
        pq.write_table(table, temporary, compression="zstd")
        if Path(temporary).stat().st_size > 268435456:
            raise ValueError("Influence output byte budget exceeded")
        if not pq.read_table(temporary).equals(table, check_metadata=True):
            raise ValueError("Influence Parquet readback mismatch")
        check_sources()
        os.replace(temporary, path)
        return checksum(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def native_catalog_sha256(catalog):
    """Fingerprint native inputs without circular references to derived products."""
    native = {k: v for k, v in catalog.items() if k != "products"}
    return hashlib.sha256(
        json.dumps(
            native, indent=2, sort_keys=True, default=str, allow_nan=False
        ).encode()
    ).hexdigest()


def catalog_with_influence(catalog, root):
    """Inventory the flat companion; a changed native binding requires a rebuild."""
    path = Path(root) / "influence.parquet"
    if not path.exists():
        if "influence" in catalog.get("products", {}):
            raise ValueError("Cataloged influence file is missing")
        return catalog
    if path.is_symlink() or not path.is_file():
        raise ValueError("Unexpected influence companion")
    file = pq.ParquetFile(path)
    metadata = json.loads((file.schema_arrow.metadata or {}).get(METADATA_KEY, b"{}"))
    if metadata.get("format") != FORMAT:
        raise ValueError("Unsupported influence catalog companion")
    recipe = metadata["recipe"]
    if metadata.get("identity") != digest(recipe):
        raise ValueError("Influence recipe identity mismatch")
    entry = {
        "path": "influence.parquet",
        "format": FORMAT,
        "sha256": checksum(path),
        "bytes": path.stat().st_size,
        "rows": file.metadata.num_rows,
        "identity": metadata["identity"],
        "metrics": recipe["signals"],
        "temporal_basis": recipe["temporal_basis"],
        "model_eligible": recipe["model_eligible"],
        "retrospective": recipe["retrospective"],
        "native_catalog_sha256": recipe["hydrology_catalog_sha256"],
        "source_status": "current"
        if recipe["hydrology_catalog_sha256"] == native_catalog_sha256(catalog)
        else "requires_rebuild",
    }
    return {**catalog, "products": {**catalog.get("products", {}), "influence": entry}}

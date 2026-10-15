"""Final long-form products, durable provenance catalog, and owned-download cleanup."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .core import STATUSES, atomic_json, atomic_parquet, digest

DYNAMIC_SCHEMA = pa.schema(
    [
        ("h3_index", pa.string()),
        ("date", pa.date32()),
        ("metric", pa.string()),
        ("value", pa.float64()),
        ("unit", pa.string()),
        ("status", pa.string()),
        ("temporal_basis", pa.string()),
        ("contributor_river_id", pa.string()),
        ("contributor_station_id", pa.string()),
        ("contributor_series", pa.string()),
        ("mouth_id", pa.string()),
        ("mapping_id", pa.string()),
        ("method_version", pa.string()),
        ("climatology_id", pa.string()),
    ]
)


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def staging_config(config, make_h3):
    """H3 builds own a resumable download namespace; shared cache is never swept."""
    if not make_h3:
        return config, None
    identity = digest(config.as_dict())
    root = Path(config.cache).resolve() / "build-staging" / identity
    marker = root / "owner.json"
    root.mkdir(parents=True, exist_ok=True)
    expected = {"owner": "hydrology-final-products-v1", "identity": identity}
    if marker.exists():
        if json.loads(marker.read_text()) != expected:
            raise ValueError("Download staging ownership mismatch")
    elif any(root.iterdir()):
        raise ValueError("Refusing to claim nonempty unowned staging directory")
    else:
        atomic_json(marker, expected)
    return replace(config, cache=str(root)), root


def clean_downloads(root):
    """Remove only HTTP cache folders in an owned namespace, preserving spatial cache."""
    root = Path(root)
    marker = root / "owner.json"
    if (
        root.is_symlink()
        or not marker.is_file()
        or json.loads(marker.read_text()).get("owner") != "hydrology-final-products-v1"
    ):
        raise ValueError("Refusing cleanup without staging ownership")
    for folder in ("requests", "snapshots"):
        path = root / folder
        if path.is_symlink():
            raise ValueError("Refusing symlinked download directory")
        if path.exists():
            shutil.rmtree(path)


def write_final(root, static, parts):
    """One static file and one dynamic file, written a day/row group at a time."""
    root = Path(root) / "final"
    root.mkdir(parents=True, exist_ok=True)
    static = static.sort_values(["h3_index", "metric"]).reset_index(drop=True)
    atomic_parquet(root / "static.parquet", static)
    fd, temporary = tempfile.mkstemp(dir=root, suffix=".parquet.tmp")
    os.close(fd)
    rows = 0
    try:
        with pq.ParquetWriter(temporary, DYNAMIC_SCHEMA, compression="zstd") as writer:
            for day, frame in parts:
                if frame.empty:
                    continue
                frame = frame.copy()
                frame["date"] = pd.to_datetime(frame.date).dt.date
                frame = frame.reindex(columns=DYNAMIC_SCHEMA.names).sort_values(
                    ["date", "h3_index", "metric"]
                )
                table = pa.Table.from_pandas(
                    frame, schema=DYNAMIC_SCHEMA, preserve_index=False
                )
                writer.write_table(table, row_group_size=len(frame))
                rows += len(frame)
        os.replace(temporary, root / "dynamic.parquet")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    validate_final(root)
    return rows


def validate_final(root):
    root = Path(root)
    static = pd.read_parquet(root / "static.parquet")

    def check(frame, keys):
        if frame[keys].isna().any().any() or frame.duplicated(keys).any():
            raise ValueError("Invalid final product keys")
        if (
            not set(frame.status).issubset(STATUSES)
            or ((frame.status == "valid") & frame.value.isna()).any()
        ):
            raise ValueError("Invalid final product status/value")

    check(static, ["h3_index", "metric"])
    file = pq.ParquetFile(root / "dynamic.parquet")
    if not file.schema_arrow.equals(DYNAMIC_SCHEMA, check_metadata=False):
        raise ValueError("Unexpected final dynamic schema")
    previous = None
    for i in range(file.num_row_groups):
        frame = file.read_row_group(i).to_pandas()
        check(frame, ["h3_index", "date", "metric"])
        dates = frame.date.unique()
        if len(dates) != 1 or (previous is not None and dates[0] <= previous):
            raise ValueError("Final row groups must have unique ascending dates")
        previous = dates[0]
        if set(frame.temporal_basis) != {"utc_daily"}:
            raise ValueError("Final dynamic product requires UTC daily support")
    if static.empty or file.metadata.num_rows == 0:
        raise ValueError("No supported final H3 products; downloads retained")
    return {"static_rows": len(static), "dynamic_rows": file.metadata.num_rows}


def write_catalog(root, manifest, metadata, rivers, staging):
    root = Path(root)
    final = root / "final"
    products = []
    if manifest["complete"] and (final / "dynamic.parquet").exists():
        validate_final(final)
        for name, keys in [
            ("static", ["h3_index", "metric"]),
            ("dynamic", ["h3_index", "date", "metric"]),
        ]:
            path = final / (name + ".parquet")
            file = pq.ParquetFile(path)
            metric_units = set()
            for batch in file.iter_batches(columns=["metric", "unit"]):
                metric_units.update(
                    zip(batch.column(0).to_pylist(), batch.column(1).to_pylist())
                )
            products.append(
                {
                    "path": path.name,
                    "grain": keys,
                    "rows": file.metadata.num_rows,
                    "sha256": checksum(path),
                    "bytes": path.stat().st_size,
                    "schema": {f.name: str(f.type) for f in file.schema_arrow},
                    "metrics": [
                        {"metric": metric, "unit": unit}
                        for metric, unit in sorted(metric_units)
                    ],
                    "temporal_basis": "static" if name == "static" else "utc_daily",
                }
            )
    sources = []
    if staging:
        for pointer in sorted((staging / "requests").glob("*.json")):
            record = json.loads(pointer.read_text())
            sources.append(
                {k: record[k] for k in ["url", "retrieved_at", "source_release"]}
            )
    catalog = {
        "schema_version": "1",
        "release": manifest["release"],
        "complete": bool(products) and manifest["complete"],
        "products": products,
        "software_version": manifest["software_version"],
        "implementation_hash": manifest["implementation_hash"],
        "configuration": manifest["config"],
        "sources": sources,
        "station_metadata": metadata,
        "river_registry": rivers,
        "source_outcomes": manifest["outcomes"],
        "source_snapshot_hashes": sorted(
            set(
                pd.read_parquet(
                    root / "station_observations.parquet", columns=["source_release"]
                ).source_release
            )
        ),
        "supporting_artifacts": [
            {"path": "../" + name, "sha256": value}
            for name, value in manifest["files"].items()
            if not name.startswith("final/")
        ],
        "availability_limitation": manifest["historical_availability"],
        "cleanup_policy": "remove owned HTTP downloads after final products, catalog and release validate; retain on failure",
        "external_inputs": {
            str(p): checksum(p)
            for p in [
                manifest["config"].get(k)
                for k in ["water_mask", "receiving_regions", "climatology", "registry"]
            ]
            if p and Path(p).is_file()
        },
    }
    atomic_json(final / "catalog.json", catalog)
    validate_catalog(final)
    return catalog


def validate_catalog(root):
    root = Path(root)
    catalog = json.loads((root / "catalog.json").read_text())
    for product in catalog["products"]:
        path = root / product["path"]
        if path.parent != root or checksum(path) != product["sha256"]:
            raise ValueError("Catalog product checksum/path mismatch")
        if pq.ParquetFile(path).metadata.num_rows != product["rows"]:
            raise ValueError("Catalog row count mismatch")
    if catalog["complete"]:
        if {p["path"] for p in catalog["products"]} != {
            "static.parquet",
            "dynamic.parquet",
        }:
            raise ValueError("Incomplete final product catalog")
        validate_final(root)
    return catalog

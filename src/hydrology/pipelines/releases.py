"""Releases pipeline: explicit stages, qualified inputs and outputs."""

import json
import platform
import resource
import time
from pathlib import Path

import pandas as pd

from ..utils.contracts import (
    VERSION,
    validate_observations,
    validate_values,
)
from ..utils.io import atomic_json, atomic_parquet
from ..utils.products import checksum as file_checksum
from ..utils.products import (
    clean_downloads,
    staging_config,
    validate_catalog,
    write_catalog,
    write_final,
)
from ..utils.provenance import digest, runtime_fingerprint
from ..utils.registry import registry_products, select_registry
from ..utils.spatial import associations, dynamic_h3, map_rivers
from . import processing


def build(
    config,
    *,
    make_h3=False,
    metrics=("discharge_mean", "temperature_mean", "temperature_max"),
):
    started = time.perf_counter()
    rivers = select_registry(config)
    acquisition_config, staging = staging_config(config, make_h3)
    prepared = processing.prepare(acquisition_config, metrics, make_h3=make_h3)
    observations = prepared["observations"]
    metadata, outcomes, network = (
        prepared[k] for k in ("metadata", "outcomes", "network")
    )
    conditions, features, warmup_conditions = (
        prepared[k] for k in ("conditions", "features", "warmup_conditions")
    )
    coverage, failures = prepared["coverage"], prepared["failures"]
    source_hashes = prepared["source_hashes"]
    implementation, identity = prepared["implementation"], prepared["identity"]
    engineered = time.perf_counter()
    root = Path(config.output) / identity
    if (root / "manifest.json").exists():
        previous = json.loads((root / "manifest.json").read_text())
        validate_release(root, previous)
        if (
            staging
            and previous["complete"]
            and (root / "final" / "catalog.json").exists()
        ):
            catalog = validate_catalog(root / "final")
            if catalog["complete"]:
                clean_downloads(staging)
        return root, previous
    root.mkdir(parents=True, exist_ok=True)
    stations_table, rivers_table = registry_products(rivers, metadata)
    atomic_parquet(root / "station_registry.parquet", stations_table)
    atomic_parquet(root / "river_registry.parquet", rivers_table)
    atomic_json(root / "registry.json", {"rivers": rivers})
    atomic_json(root / "station_metadata.json", metadata)
    for name, frame in [
        ("station_observations", observations),
        ("river_conditions", conditions),
        ("river_features", features),
        ("coverage", coverage),
        ("feature_warmup", warmup_conditions),
    ]:
        atomic_parquet(root / (name + ".parquet"), frame)
    spatial_error = None
    h3_count = 0
    if make_h3:
        try:
            links = map_rivers(acquisition_config, rivers)
            atomic_parquet(root / "river_marine_links.parquet", links)
            chosen = associations(links)
            atomic_parquet(root / "associations.parquet", chosen)
            static = chosen[
                [
                    "h3_index",
                    "river_id",
                    "mouth_id",
                    "water_distance_m",
                    "mapping_id",
                    "status",
                ]
            ].rename(columns={"water_distance_m": "value"})
            static["metric"] = "water_connected_distance_to_associated_mouth"
            static["unit"] = "m"
            h3_count = write_final(root, static, dynamic_h3(features, links))
        except Exception as exc:
            spatial_error = f"{type(exc).__name__}: {exc}"
    finished = time.perf_counter()
    manifest = {
        "schema_version": "1",
        "software_version": VERSION,
        "implementation_hash": implementation,
        "release": identity,
        "config": config.as_dict(),
        "outcomes": outcomes,
        "failures": failures,
        "spatial_error": spatial_error,
        "complete": not failures and not spatial_error,
        "execution_complete": prepared["execution_complete"] and not spatial_error,
        "data_eligible": all(
            e["required_discharge_eligible"] for e in prepared["eligibility"].values()
        ),
        "eligibility": prepared["eligibility"],
        "block_ledger": network.get("block_ledger", []),
        "metadata_hash": digest(metadata),
        "runtime": runtime_fingerprint(),
        "native_rows": len(observations),
        "source_snapshot_hashes": source_hashes,
        "low_flow_definitions": features.attrs.get("low_flow_definitions", {}),
        "high_flow_definitions": features.attrs.get("high_flow_definitions", {}),
        "flow_pulse_definitions": features.attrs.get("flow_pulse_definitions", {}),
        "h3_rows": h3_count,
        "historical_availability": "unknown; not an exact operational backtest",
        "timing_seconds": {
            **prepared["timing"],
            "spatial_and_write": finished - engineered,
            "total": finished - started,
        },
        "network": network,
        "hardware": platform.platform() + " " + platform.machine(),
        "peak_rss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "bytes": sum(p.stat().st_size for p in root.rglob("*") if p.is_file()),
        "files": {
            str(p.relative_to(root)): file_checksum(p)
            for p in root.rglob("*")
            if p.is_file() and p.name != "manifest.json"
        },
    }
    write_catalog(root, manifest, metadata, rivers, staging)
    manifest["files"]["final/catalog.json"] = file_checksum(
        root / "final" / "catalog.json"
    )
    validate_release(root, manifest)
    atomic_json(root / "manifest.json", manifest)
    if staging and manifest["complete"]:
        clean_downloads(staging)
    return root, manifest


def validate_release(root, manifest=None):
    root = Path(root)
    manifest = manifest or json.loads((root / "manifest.json").read_text())
    for name, checksum in manifest["files"].items():
        if file_checksum(root / name) != checksum:
            raise ValueError(f"Checksum mismatch: {name}")
    if (root / "final" / "catalog.json").exists():
        validate_catalog(root / "final")
    frame = pd.read_parquet(root / "station_observations.parquet")
    validate_observations(frame)
    for name, key in [
        ("river_conditions", ["river_id", "date", "metric", "temporal_basis"]),
        ("river_features", ["river_id", "date", "metric", "temporal_basis"]),
    ]:
        f = pd.read_parquet(root / (name + ".parquet"))
        validate_values(f)
        if f.duplicated(key).any():
            raise ValueError(f"Duplicate {name} keys")
        if ((f.status == "valid") & f.value.isna()).any():
            raise ValueError("Valid null feature")
    for path in (root / "h3").glob("date=*/part.parquet"):
        f = pd.read_parquet(path)
        if (
            set(f.temporal_basis) != {"utc_daily"}
            or f.duplicated(["date", "h3_index", "metric"]).any()
        ):
            raise ValueError("Invalid H3 contract")
    return {
        "validated": str(root),
        "observations": len(frame),
        "complete": manifest["complete"],
    }

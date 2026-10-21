"""Bounded, offline influence-factor production from explicit retained public products."""

from __future__ import annotations

import json
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ..utils.flow_history import flow_histories
from ..utils.influence import (
    METHOD,
    SIGNALS,
    distance_weights,
    lagged,
    validate_outlet_bindings,
    validate_profiles,
)
from ..utils.influence_product import (
    catalog_with_influence,
    factor_table,
    native_catalog_sha256,
    write_influence,
)
from ..utils.io import atomic_json
from ..utils.products import checksum
from ..utils.provenance import implementation_fingerprint, runtime_fingerprint
from .publication import product_snapshot


def build_influence(config_path):
    """Write one influence Parquet beside native products; never acquire source data."""
    path = Path(config_path).resolve()
    config = json.loads(path.read_text())
    if config["version"] != 1:
        raise ValueError("Unknown influence configuration")
    validate_profiles(config)

    def resolve(name):
        return (path.parent / config[name]).absolute()

    study_path, hydrology, bindings_path, output = (
        resolve(k) for k in ["study", "hydrology", "outlet_bindings", "output"]
    )
    study = json.loads(study_path.read_text())
    if (
        study["grid_registry"]["status"] != "validated"
        or study["domain"]["status"] != "approved"
    ):
        raise ValueError("Approved validated study required")
    sources = {}

    def bound(p, expected=None):
        p = p.resolve()
        observed = checksum(p)
        if expected is not None and observed != expected:
            raise ValueError(f"Input binding mismatch: {p.name}")
        sources[str(p)] = observed
        return p

    bound(path)
    bound(study_path)
    bound(bindings_path, config.get("outlet_bindings_sha256"))
    manifest = json.loads(
        bound(
            study_path.parent / study["grid_registry"]["manifest_relative_path"],
            study["grid_registry"]["manifest_sha256"],
        ).read_text()
    )
    member = next(
        m
        for m in study["grid_registry"]["memberships"]
        if m["role"] == "water_reporting" and m["resolution"] == 6
    )
    cells = (
        bound(study_path.parent / member["relative_path"], member["sha256"])
        .read_text()
        .splitlines()
    )
    if (
        len(set(cells)) != len(cells)
        or len(cells) != member["count"]
        or any(not h3.is_valid_cell(c) or h3.get_resolution(c) != 6 for c in cells)
    ):
        raise ValueError("Invalid R6 reporting membership")
    binding_rows = json.loads(bindings_path.read_text())["locations"]
    outlets = validate_outlet_bindings(config["rivers"], binding_rows)
    record = manifest["research_artifacts"]["outlet-relationships-r8"]
    relationships = bound(study_path.parent / record["relative_path"], record["sha256"])
    links = pq.read_table(
        relationships,
        columns=[
            "H3_INDEX",
            "H3_RESOLUTION",
            "OUTLET_ID",
            "WATER_NETWORK_DISTANCE_M",
            "REACHABILITY_STATUS",
            "QC_REASON",
        ],
        filters=[("OUTLET_ID", "in", [r["outlet_id"] for r in outlets])],
    ).to_pandas()
    if (
        links.duplicated(["H3_INDEX", "OUTLET_ID"]).any()
        or set(links.H3_RESOLUTION) != {8}
        or any(
            not h3.is_valid_cell(c) or h3.get_resolution(c) != 8
            for c in links.H3_INDEX.unique()
        )
    ):
        raise ValueError("Invalid native R8 relationship identities")
    numeric = pd.to_numeric(links.WATER_NETWORK_DISTANCE_M, errors="raise")
    if (numeric.notna() & (~np.isfinite(numeric) | (numeric < 0))).any() or (
        (links.REACHABILITY_STATUS == "reachable") != numeric.notna()
    ).any():
        raise ValueError("Water distance/reachability mismatch")
    links["parent"] = links.H3_INDEX.map(lambda c: h3.cell_to_parent(c, 6))
    spatial = []
    for river in outlets:
        group = links.loc[links.OUTLET_ID == river["outlet_id"]]
        if group.empty:
            raise ValueError("Missing selected outlet relationships")
        minimum = group.groupby("parent").WATER_NETWORK_DISTANCE_M.min().reindex(cells)
        child_counts = (
            group.groupby("parent")
            .WATER_NETWORK_DISTANCE_M.count()
            .reindex(cells, fill_value=0)
        )
        for profile in config["distance_profiles"]:
            for cell, distance, count, weight in zip(
                cells,
                minimum,
                child_counts,
                distance_weights(minimum, profile, river["gain"]),
                strict=True,
            ):
                spatial.append(
                    dict(
                        h3_index=cell,
                        river_id=river["id"],
                        distance_profile=profile["id"],
                        water_distance_m=float(distance)
                        if pd.notna(distance)
                        else None,
                        reachable_r8_children=int(count),
                        weight=float(weight) if np.isfinite(weight) else None,
                    )
                )
    signals, definitions, dates = [], {}, None
    with product_snapshot(hydrology, exclusive=True) as snapshot:
        catalog_path = snapshot / "catalog.json"
        cat = json.loads(catalog_path.read_text())
        if set(config["rivers"]) - set(cat["rivers"]):
            raise ValueError("River absent from retained conditions")
        for river in outlets:
            rid = river["id"]
            binding = cat["rivers"][rid]
            m = json.loads(
                bound(snapshot / binding["manifest"], binding["sha256"]).read_text()
            )
            folder = snapshot / rid
            conditions_path = bound(
                folder / "conditions.parquet",
                m["files"]["conditions.parquet"]["sha256"],
            )
            frame = pd.read_parquet(conditions_path)
            histories = list(flow_histories(frame))
            if (
                len(histories) != 1
                or histories[0][0] != rid
                or histories[0][2] != "provider_daily"
            ):
                raise ValueError("One provider-daily gauge per river required")
            _, station, basis, index, observed, filled, estimated, _, interpolation = (
                histories[0]
            )
            calendar = [d.date().isoformat() for d in index]
            if dates is not None and dates != calendar:
                raise ValueError("River calendars differ")
            dates = calendar
            supported = filled.dropna()
            p90 = float(supported.quantile(0.9)) if len(supported) >= 2 else None
            relative = filled / p90 if p90 is not None and p90 > 0 else filled * np.nan
            values = {
                "discharge": filled.to_numpy(),
                "relative_flow": relative.to_numpy(),
            }
            definitions[rid] = {
                "station_id": station,
                "temporal_basis": basis,
                "threshold_p90_m3_s": p90,
                "reference_start": dates[0],
                "reference_end": dates[-1],
                "observed_days": int(observed.notna().sum()),
                "interpolated_days": int(estimated.sum()),
                "unfilled_days": int(filled.isna().sum()),
                "interpolation": interpolation,
            }
            for profile in config["lag_profiles"]:
                calculated = {k: lagged(v, profile) for k, v in values.items()}
                estimated_input = lagged(estimated.astype(float), profile)
                for i, day in enumerate(dates):
                    signals.append(
                        {
                            "river_id": rid,
                            "date": day,
                            "lag_profile": profile["id"],
                            **{
                                k: float(v[i]) if np.isfinite(v[i]) else None
                                for k, v in calculated.items()
                            },
                            "interpolated_input_weight": float(estimated_input[i])
                            if np.isfinite(estimated_input[i])
                            else None,
                        }
                    )
        source_catalog_sha = native_catalog_sha256(cat)
        recipe = {
            "version": 1,
            "method": METHOD,
            "retrospective": True,
            "model_eligible": False,
            "temporal_basis": "provider_daily",
            "distance_support": "minimum reachable R8 child-water representative distance per R6 cell",
            "qualification": "Exploratory supported influence index from explicit upstream gauge proxies and modeled main-basin outlets; no currents, physical plume, mouth flux or whale-response calibration. Columbia origin is the modeled estuarine outlet upstream of the physical mouth. Recorded source-registration limits remain explicit, including Queets' R8-qualified attachment despite its unavailable R6 attachment. Missing routes remain unknown. Full-history interpolation and P90 use future observations; provider dates are not simultaneous UTC intervals.",
            "config": config,
            "cells": cells,
            "dates": dates,
            "rivers": outlets,
            "definitions": definitions,
            "signals": {k: {"name": n, "unit": u} for k, (n, u) in SIGNALS.items()},
            "hydrology_catalog_sha256": source_catalog_sha,
            "hydrology_catalog_hash_scope": "native_catalog_without_products",
            "study_sha256": sources[str(study_path.resolve())],
            "sources": sources,
            "implementation": implementation_fingerprint(),
            "runtime": runtime_fingerprint(),
        }
        spatial_frame, signal_frame = pd.DataFrame(spatial), pd.DataFrame(signals)
        display_ranges = {}
        for distance_profile in config["distance_profiles"]:
            for lag_profile in config["lag_profiles"]:
                bounds = {metric: [0.0, 0.0] for metric in SIGNALS}
                for river in outlets:
                    rid = river["id"]
                    spatial_values = spatial_frame.loc[
                        (spatial_frame.river_id == rid)
                        & (spatial_frame.distance_profile == distance_profile["id"]),
                        "weight",
                    ]
                    maximum_weight = spatial_values.max()
                    if pd.isna(maximum_weight):
                        continue
                    series = signal_frame.loc[
                        (signal_frame.river_id == rid)
                        & (signal_frame.lag_profile == lag_profile["id"])
                    ]
                    for metric in SIGNALS:
                        available = series[metric].dropna()
                        if not available.empty:
                            bounds[metric][0] += maximum_weight * min(
                                0.0, available.min()
                            )
                            bounds[metric][1] += maximum_weight * max(
                                0.0, available.max()
                            )
                display_ranges[distance_profile["id"] + ":" + lag_profile["id"]] = (
                    bounds
                )
        recipe["display_ranges"] = display_ranges
        if output.name != "influence.parquet" or output.parent.resolve() != snapshot:
            raise ValueError("Influence output must be Hydrology/influence.parquet")

        def check_sources():
            if (
                any(checksum(Path(p)) != sha for p, sha in sources.items())
                or hydrology.resolve() != snapshot
                or native_catalog_sha256(json.loads(catalog_path.read_text()))
                != source_catalog_sha
            ):
                raise ValueError("Inputs changed during build")

        table = factor_table(spatial, signals, recipe)
        destination = snapshot / output.name
        sha = write_influence(destination, table, check_sources)
        metadata = json.loads(table.schema.metadata[b"hydrology_influence"])
        revised_catalog = catalog_with_influence(cat, snapshot)
        if revised_catalog != cat:
            atomic_json(catalog_path, revised_catalog)
        return {
            "output": str(output),
            "identity": metadata["identity"],
            "sha256": sha,
            "bytes": destination.stat().st_size,
            "cells": len(cells),
            "river_days": len(dates) * len(outlets),
            "spatial_rows": len(spatial),
            "signal_rows": len(signals),
        }

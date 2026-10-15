"""Bounded acquisition, deterministic source selection, immutable releases."""

from __future__ import annotations

import json
import platform
import resource
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from .core import (
    VERSION,
    atomic_json,
    atomic_parquet,
    digest,
    eligible,
    empty_observations,
    validate_observations,
)
from .features import build_features
from .http import Client, UnsupportedVariable
from .products import (
    checksum as file_checksum,
)
from .products import (
    clean_downloads,
    staging_config,
    validate_catalog,
    write_catalog,
    write_final,
)
from .providers import HYDAT, USGS, WSC
from .registry import audit, registry_products, select_registry
from .spatial import associations, dynamic_h3, map_rivers
from .temporal import aggregate_utc


def date_blocks(start, end):
    a = pd.Timestamp(start)
    stop = pd.Timestamp(end)
    while a <= stop:
        b = min(a + pd.offsets.MonthEnd(0), stop)
        yield a.date().isoformat(), b.date().isoformat()
        a = b + pd.Timedelta(days=1)


def plan(config):
    rivers = select_registry(config)
    warmup = (
        (pd.Timestamp(config.start_date) - pd.Timedelta(days=30)).date().isoformat()
    )
    return {
        "config": config.as_dict(),
        "rivers": rivers,
        "acquisition_start": warmup,
        "blocks": list(date_blocks(warmup, config.end_date)),
        "cache_policy": "page snapshots reused unless refresh=true; refresh creates new content snapshots",
        "writes": [config.cache, config.output],
        "download": False,
    }


def acquire(config, metrics=("discharge_mean", "temperature_mean", "temperature_max")):
    rivers = select_registry(config)
    client = Client(config)
    metadata = {}
    outcomes = {}
    all_frames = []
    begin = (pd.Timestamp(config.start_date) - pd.Timedelta(days=30)).date().isoformat()

    def one(river):
        station = river["stations"][0]
        sid = station["station_id"]
        provider = station["provider"]
        result = {}
        frames = []
        meta = {}
        try:
            if config.data_source not in ("auto", provider) and not (
                provider == "wsc" and config.data_source == "hydat"
            ):
                raise ValueError(
                    f"Explicit source {config.data_source} incompatible with {sid}"
                )
            if config.data_source == "hydat" and not config.hydat:
                raise ValueError("hydat source requires a local snapshot path")
            adapter = (
                USGS(client)
                if provider == "usgs"
                else (HYDAT(config.hydat) if config.hydat else WSC(client))
            )
            meta = adapter.discover(sid)
        except Exception as exc:
            return (
                river,
                frames,
                meta,
                {m: f"failure: {type(exc).__name__}: {exc}" for m in metrics},
            )
        for metric in metrics:
            chunks = []
            try:
                for a, b in date_blocks(begin, config.end_date):
                    a = max(a, station["valid_from"])
                    if station.get("valid_to"):
                        b = min(b, station["valid_to"])
                    if a > b:
                        continue
                    if config.temporal_requirement == "utc_daily":
                        if not hasattr(adapter, "continuous"):
                            raise UnsupportedVariable(
                                "Local HYDAT daily cannot reconstruct UTC"
                            )
                        if (
                            provider == "wsc"
                            and b
                            < (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30))
                            .date()
                            .isoformat()
                        ):
                            continue
                        samples = adapter.continuous(
                            sid,
                            metric,
                            (pd.Timestamp(a) - pd.Timedelta(days=1)).date().isoformat(),
                            b,
                        )
                        chunks.append(
                            aggregate_utc(
                                samples,
                                sid,
                                metric,
                                a,
                                b,
                                max_hold_seconds=config.max_hold_seconds,
                                minimum_coverage=config.minimum_coverage,
                                allow_provisional=config.allow_provisional,
                                provider=provider,
                            )
                        )
                    else:
                        chunks.append(adapter.observations(sid, metric, a, b))
                f = (
                    pd.concat(chunks, ignore_index=True)
                    if chunks
                    else empty_observations()
                )
                validate_observations(f)
                if len(f):
                    frames.append(f)
                result[metric] = (
                    "observed" if f.value.notna().any() else "no_observations"
                )
            except UnsupportedVariable as exc:
                result[metric] = f"unsupported: {exc}"
            except Exception as exc:
                result[metric] = f"failure: {type(exc).__name__}: {exc}"
        return river, frames, meta, result

    with ThreadPoolExecutor(max_workers=config.workers) as pool:
        for river, frames, meta, result in pool.map(one, rivers):
            all_frames.extend(frames)
            metadata[river["river_id"]] = meta
            outcomes[river["river_id"]] = result
    observations = (
        pd.concat(all_frames, ignore_index=True) if all_frames else empty_observations()
    )
    validate_observations(observations)
    return (
        observations,
        metadata,
        outcomes,
        {"http_requests": client.requests, "cache_hits": client.hits},
    )


def river_conditions(observations, rivers, metadata, config):
    selected = eligible(observations, config.as_of, config.allow_provisional)
    frames = []
    for river in rivers:
        sid = river["stations"][0]["station_id"]
        f = selected.loc[selected.station_id == sid].copy()
        # Primary daily series only. Multiple primary series on one day fail closed, not arbitrary fallback.
        for metric, g in f.groupby("metric"):
            if g.series_id.nunique() > 1:
                primary = {
                    s["id"]
                    for s in metadata.get(river["river_id"], {}).get("series", [])
                    if s["properties"].get("primary") == "Primary"
                }
                g = g.loc[g.series_id.isin(primary)]
                if g.date.duplicated().any() or g.empty:
                    raise ValueError(f"{sid}/{metric}: ambiguous primary source")
            g = g.copy()
            g["river_id"] = river["river_id"]
            g["representation"] = "representative_gauge_proxy"
            g = g.sort_values("date")
            g["source_changed"] = g.series_id.ne(g.series_id.shift())
            g.loc[g.index[0], "source_changed"] = False
            frames.append(g)
    return (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(
            columns=list(observations.columns)
            + ["river_id", "representation", "source_changed"]
        )
    )


def build(
    config,
    *,
    make_h3=False,
    metrics=("discharge_mean", "temperature_mean", "temperature_max"),
):
    started = time.perf_counter()
    rivers = select_registry(config)
    acquisition_config, staging = staging_config(config, make_h3)
    observations, metadata, outcomes, network = acquire(acquisition_config, metrics)
    fetched = time.perf_counter()
    conditions = river_conditions(observations, rivers, metadata, config)
    baseline = (
        json.loads(Path(config.climatology).read_text()) if config.climatology else None
    )
    features = build_features(
        conditions,
        climatology=baseline,
        low_threshold=config.low_flow_threshold,
        pulse_threshold=config.pulse_threshold,
    )
    for frame in [observations, conditions, features]:
        frame.drop(
            frame.index[~frame.date.between(config.start_date, config.end_date)],
            inplace=True,
        )
    engineered = time.perf_counter()
    coverage = audit(conditions, rivers, config.start_date, config.end_date, outcomes)
    failures = {
        r: o for r, o in outcomes.items() if o.get("discharge_mean") != "observed"
    }
    for river in rivers:
        if (
            conditions.loc[
                (conditions.river_id == river["river_id"])
                & (conditions.metric == "discharge_mean"),
                "value",
            ]
            .notna()
            .sum()
            == 0
        ):
            failures.setdefault(river["river_id"], {})["eligibility"] = (
                "no eligible discharge observations"
            )
    implementation = digest(
        {p.name: p.read_text() for p in Path(__file__).parent.glob("*.py")}
    )
    identity = digest(
        {
            "implementation": implementation,
            "config": config.as_dict(),
            "sources": sorted(set(observations.source_release)),
            "registry": rivers,
            "software": VERSION,
            "baseline": baseline,
            "outcomes": outcomes,
            "metrics": metrics,
            "make_h3": make_h3,
            "spatial_inputs": {
                p: digest(Path(p).read_text())
                for p in [config.water_mask, config.receiving_regions]
                if p and Path(p).is_file()
            },
        }
    )[:20]
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
        "native_rows": len(observations),
        "h3_rows": h3_count,
        "historical_availability": "unknown; not an exact operational backtest",
        "timing_seconds": {
            "acquisition": fetched - started,
            "features_and_selection": engineered - fetched,
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

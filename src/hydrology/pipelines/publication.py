"""One current per-river product in a regular directory.

Readers must pin a snapshot under product_snapshot's shared lock. Writers use an
exclusive lock; no existing unowned directory or unrelated file is replaced.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import tempfile
import warnings
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..utils.contracts import (
    OBS_COLUMNS,
    STATUSES,
    validate_observations,
    validate_values,
)
from ..utils.influence_product import catalog_with_influence
from ..utils.io import atomic_json
from ..utils.products import checksum
from ..utils.provenance import digest, merge_source_references, runtime_fingerprint
from ..utils.publication_guard import POLICY, check_observations, check_scope

OWNER = "hydrology-current-per-river-v1"
EXTRA = ["river_id", "representation", "source_changed", "reason"]
FLOATS = {"value", "coverage"}


def schema(columns):
    return pa.schema(
        [
            (
                c,
                pa.date32()
                if c == "date"
                else pa.float64()
                if c in FLOATS
                else pa.bool_()
                if c == "source_changed"
                else pa.string(),
            )
            for c in columns
        ]
    )


OBS_SCHEMA = schema(OBS_COLUMNS + ["source_references"])
CONDITIONS_SCHEMA = schema(OBS_COLUMNS + ["source_references"] + EXTRA)
FEATURE_SCHEMA = schema(
    [
        "river_id",
        "station_id",
        "date",
        "metric",
        "temporal_basis",
        "value",
        "unit",
        "status",
        "reason",
        "climatology_id",
        "method_version",
        "contributor_series",
    ]
)


def _paths(destination):
    target = Path(destination).expanduser().absolute()
    target = target.parent.resolve() / target.name
    if target.name in ("", ".", ".."):
        raise ValueError("Invalid canonical destination")
    store = (
        target.parent.parent
        / ".marinecast-work"
        / "hydrology"
        / digest(str(target))[:16]
    )
    return target, store, store / ".publication.lock"


def _owner(target):
    return {"owner": OWNER, "destination": str(target)}


def _download_root(config, store):
    """Explicit cache selects a work base; never delete its shared contents."""
    if config.cache == "data/cache":
        return store / "downloads"
    return Path(config.cache).expanduser().resolve() / ("hydrology-" + store.name)


def _pin(target, store):
    if (store / "station-temperature-transaction.json").exists():
        raise ValueError("Interrupted station-temperature transaction; inspect journal and restore prior catalog/product before reading")
    if target.is_symlink() or not target.is_dir():
        raise ValueError(
            "An existing owned current product directory is required; migrate legacy symlinks first"
        )
    marker = target / "owner.json"
    if (
        marker.is_symlink()
        or not marker.is_file()
        or json.loads(marker.read_text()) != _owner(target)
    ):
        raise ValueError("Refusing an unowned destination directory")
    return target


def _sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _journal(path, state):
    atomic_json(path, state)
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    _sync(path.parent)


def _recover(target, store):
    """Recover the bounded directory rename protocol while holding its writer lock."""
    journal, backup = store / "promotion.json", store / "previous"
    if not journal.exists():
        if backup.exists():
            raise ValueError("Unjournaled product backup; manual recovery required")
        return
    state = json.loads(journal.read_text())
    if state.get("owner") != _owner(target) or state.get("phase") not in {
        "promoting",
        "committed",
    }:
        raise ValueError("Invalid product recovery journal")
    if backup.exists():
        if backup.is_symlink() or json.loads(
            (backup / "owner.json").read_text()
        ) != _owner(target):
            raise ValueError("Product backup ownership mismatch")
        if state["phase"] == "committed":
            _validate_snapshot(_pin(target, store))
            shutil.rmtree(backup)
        else:
            if target.exists():
                _pin(target, store)
                shutil.rmtree(target)
            os.rename(backup, target)
    elif (
        state["phase"] == "promoting"
        and not state["had_destination"]
        and target.exists()
    ):
        _pin(target, store)
        shutil.rmtree(target)
    journal.unlink()
    _sync(target.parent)
    _sync(store)


def _commit_stage(target, stage, store):
    """Promote a validated directory, restoring the prior product on rename failure."""
    journal, backup = store / "promotion.json", store / "previous"
    if backup.exists() or journal.exists():
        raise ValueError("Unrecovered prior publication")
    had_destination = target.exists()
    state = {
        "owner": _owner(target),
        "phase": "promoting",
        "had_destination": had_destination,
    }
    _journal(journal, state)
    try:
        if had_destination:
            os.replace(target, backup)
            _sync(target.parent)
            _sync(store)
        os.replace(stage, target)
        _sync(target.parent)
        _sync(store)
        _journal(journal, {**state, "phase": "committed"})
    except BaseException:
        _recover(target, store)
        raise
    try:
        _recover(target, store)
    except OSError as exc:
        warnings.warn(
            f"Product promoted; backup cleanup pending: {exc}", RuntimeWarning
        )


@contextmanager
def product_snapshot(destination, *, exclusive=False):
    """Pin a coherent read snapshot; don't resolve individual paths repeatedly."""
    target, store, lock = _paths(destination)
    with lock.open("rb") as handle:
        try:
            fcntl.flock(
                handle, fcntl.LOCK_EX | fcntl.LOCK_NB if exclusive else fcntl.LOCK_SH
            )
        except BlockingIOError as exc:
            raise ValueError(
                "Another canonical reader/writer holds the product lock"
            ) from exc
        if json.loads((store / "owner.json").read_text()) != _owner(target):
            raise ValueError("Canonical store ownership mismatch")
        if (store / "promotion.json").exists():
            if not exclusive:
                raise ValueError("Product needs writer recovery before reading")
            _recover(target, store)
        yield _pin(target, store)


def _preserve_influence(old, stage):
    """Carry the flat companion forward; its source hash still requires a rebuild."""
    if old is not None and (old / "station_temperature.parquet").exists():
        source = old / "station_temperature.parquet"
        if source.is_symlink() or not source.is_file():
            raise ValueError("Unexpected station temperature companion")
        os.link(source, stage / source.name)
    if old is not None and (old / "causal.parquet").exists():
        source = old / "causal.parquet"
        if source.is_symlink() or not source.is_file():
            raise ValueError("Unexpected causal companion")
        os.link(source, stage / source.name)
    if old is not None and (old / "influence.parquet").exists():
        source = old / "influence.parquet"
        if source.is_symlink() or not source.is_file():
            raise ValueError("Unexpected influence companion")
        os.link(source, stage / source.name)


def _validate_snapshot(root):
    catalog = json.loads((root / "catalog.json").read_text())
    if catalog["schema_version"] != "hydrology-per-river-1":
        raise ValueError("Unknown canonical schema")
    if catalog_with_influence(catalog, root) != catalog:
        raise ValueError("Influence catalog binding mismatch")
    from ..utils.causal import catalog_with_causal

    if catalog_with_causal(catalog, root) != catalog:
        raise ValueError("Causal catalog binding mismatch")
    allowed = {
        "station_temperature.parquet",
        "causal.parquet",
        "catalog.json",
        "owner.json",
        "influence.parquet",
        ".DS_Store",
        *catalog["rivers"],
    }
    if {p.name for p in root.iterdir()} - allowed:
        raise ValueError("Unrelated files in canonical product; preserved")
    for rid, item in catalog["rivers"].items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", rid):
            raise ValueError("Unsafe river identifier")
        directory = root / rid
        if directory.is_symlink() or item["manifest"] != f"{rid}/manifest.json":
            raise ValueError("Invalid river manifest path")
        manifest_path = directory / "manifest.json"
        if manifest_path.is_symlink() or checksum(manifest_path) != item["sha256"]:
            raise ValueError("River manifest checksum mismatch")
        m = json.loads(manifest_path.read_text())
        if {p.name for p in directory.iterdir()} - {
            "manifest.json",
            ".DS_Store",
            *m["files"],
        }:
            raise ValueError("Unrelated files in canonical river; preserved")
        if m["river_id"] != rid:
            raise ValueError("River manifest identity mismatch")
        for name, details in m["files"].items():
            path = directory / name
            if (
                path.parent != directory
                or path.is_symlink()
                or checksum(path) != details["sha256"]
            ):
                raise ValueError("Canonical file checksum/path mismatch")
        for name, expected_schema in [
            ("conditions", CONDITIONS_SCHEMA),
            ("features", FEATURE_SCHEMA),
            ("observations", OBS_SCHEMA),
            ("warmup", CONDITIONS_SCHEMA),
        ]:
            file = pq.ParquetFile(directory / f"{name}.parquet")
            if not file.schema_arrow.equals(expected_schema, check_metadata=False):
                raise ValueError("Canonical schema mismatch")
            f = file.read().to_pandas()
            validate_values(f)
            if not set(f.status).issubset(STATUSES):
                raise ValueError("Invalid canonical status")
            if ((f.status == "valid") & f.value.isna()).any():
                raise ValueError("Valid null canonical value")
            if len(f) and set(f.station_id) != {m["station_id"]}:
                raise ValueError("Cross-station contamination")
            if "river_id" in f and len(f) and set(f.river_id) != {rid}:
                raise ValueError("Cross-river contamination")
            if f.duplicated(
                ["date", "metric", "temporal_basis"]
                + (["series_id"] if name == "observations" else [])
            ).any():
                raise ValueError("Duplicate canonical keys")
            if name == "observations":
                validate_observations(f)
            if name in ("conditions", "features"):
                dates = set(pd.date_range(m["start_date"], m["end_date"]).date)
                if set(f.temporal_basis) != {m["temporal_basis"]}:
                    raise ValueError("Canonical temporal basis mismatch")
                expected_metrics = set(m["metrics"][name])
                if set(f.metric) != expected_metrics or len(f) != len(dates) * len(
                    expected_metrics
                ):
                    raise ValueError("Incomplete canonical metric calendar")
                if any(set(g.date) != dates for _, g in f.groupby("metric")):
                    raise ValueError("Incomplete canonical date calendar")
    return catalog


def validate_product(destination):
    with product_snapshot(destination) as root:
        return _validate_snapshot(root)


def _parquet(path, frame, expected_schema):
    f = frame.reindex(columns=expected_schema.names).copy()
    if "source_references" in f:
        f["source_references"] = [
            merge_source_references([r]) if pd.notna(r.get("source_release")) else "[]"
            for r in f.to_dict("records")
        ]
    f["date"] = pd.to_datetime(f.date).dt.date
    if "source_changed" in f:
        f["source_changed"] = f.source_changed.fillna(False).astype(bool)
    order = [c for c in ("date", "metric", "series_id") if c in f]
    f = f.sort_values(order).reset_index(drop=True)
    pq.write_table(
        pa.Table.from_pandas(f, schema=expected_schema, preserve_index=False),
        path,
        compression="zstd",
    )


def _cleanup_snapshots(store, current, expected):
    for candidate in store.glob("snapshot-*"):
        if candidate != current and candidate.is_dir() and not candidate.is_symlink():
            marker = candidate / "owner.json"
            if marker.is_file() and json.loads(marker.read_text()) == expected:
                shutil.rmtree(candidate)


def interpretation_notes(
    config,
    *,
    climatology_supplied=False,
    low_flow_definition=None,
    flow_pulse_definition=None,
    high_flow_definition=None,
):
    """Document configured parameters without asserting ecological validation."""
    return {
        "configured_feature_thresholds": {
            "low_flow_threshold_m3_s": low_flow_definition["threshold_m3_s"]
            if low_flow_definition
            else config.low_flow_threshold,
            "pulse_threshold_m3_s": flow_pulse_definition["threshold_m3_s"]
            if flow_pulse_definition
            else config.pulse_threshold,
            "high_flow_threshold_m3_s": high_flow_definition["threshold_m3_s"]
            if high_flow_definition
            else None,
            "scientific_validation_established_by_toolkit": False,
            "qualification": "Configured parameters, not validated universal river or whale-effect thresholds; qualify per river before modeling.",
        },
        "temperature_missingness": "not_applicable/not_requested identifies this run's acquisition/source scope, not scientific inapplicability of river temperature.",
        "training_climatology": "Explicit artifact supplied; see its training cutoff."
        if climatology_supplied
        else "Deferred: no explicit training configuration or artifact supplied; seasonal features remain unavailable.",
        **(
            {"high_flow_definition": high_flow_definition}
            if high_flow_definition
            else {}
        ),
        **({"low_flow_definition": low_flow_definition} if low_flow_definition else {}),
        **(
            {"flow_pulse_definition": flow_pulse_definition}
            if flow_pulse_definition
            else {}
        ),
    }


def publish_rivers(config, *, metrics=("discharge_mean",)):
    """Publish a bounded window without discarding retained eligible observations.

    Existing rivers require their full retained window and observed metrics; weaker
    replacements fail closed. New partial products retain explicit missingness.
    """
    from .processing import prepare

    target, store, lock = _paths(config.product_output)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Refuse unowned destinations before acquisition or claiming any directory.
    if target.exists() or target.is_symlink():
        _pin(target, store)
    if store.is_symlink():
        raise ValueError("Refusing symlinked canonical store")
    store.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(
                "Another canonical reader/writer holds the product lock"
            ) from exc
        expected = _owner(target)
        if store.is_symlink():
            raise ValueError("Refusing symlinked canonical store")
        if (store / "owner.json").exists():
            if (
                not (store / "owner.json").is_file()
                or json.loads((store / "owner.json").read_text()) != expected
            ):
                raise ValueError("Canonical store ownership mismatch")
        elif set(p.name for p in store.iterdir()) <= {".publication.lock"}:
            atomic_json(store / "owner.json", expected)
        else:
            raise ValueError("Canonical store ownership mismatch")
        _recover(target, store)
        old = _pin(target, store) if target.exists() else None
        previous = _validate_snapshot(old) if old else {"rivers": {}}
        _cleanup_snapshots(store, old, expected)
        from ..utils.registry import select_registry

        planned_rivers = select_registry(config)
        prior_manifests = {}
        for river in planned_rivers:
            rid = river["river_id"]
            if rid in previous["rivers"]:
                prior_manifests[rid] = json.loads(
                    (old / rid / "manifest.json").read_text()
                )
                check_scope(prior_manifests[rid], config, metrics, river)
        expected_rows = (
            len(planned_rivers)
            * len(pd.date_range(config.start_date, config.end_date))
            * 15
        )
        if expected_rows > config.publication_max_rows:
            raise ValueError(
                "Canonical publication row budget exceeded before acquisition"
            )
        # Canonical publication owns this resumable download namespace. Never sweep
        # the caller's shared/legacy cache or supplied HYDAT/climatology inputs.
        downloads = _download_root(config, store)
        if downloads.is_symlink():
            raise ValueError("Refusing symlinked publication downloads")
        if (
            target == downloads
            or target in downloads.parents
            or downloads in target.parents
        ):
            raise ValueError(
                "Publication downloads must be separate from final products"
            )
        downloads.mkdir(parents=True, exist_ok=True)
        marker = downloads / "owner.json"
        if marker.exists():
            if marker.is_symlink() or json.loads(marker.read_text()) != expected:
                raise ValueError("Publication download ownership mismatch")
        elif any(downloads.iterdir()):
            raise ValueError("Refusing unowned publication downloads")
        else:
            atomic_json(marker, expected)
        prepared = prepare(replace(config, cache=str(downloads)), metrics)
        selected = {r["river_id"]: r for r in prepared["rivers"]}
        replacement_checks = {}
        for rid in selected:
            replacement_checks[rid] = {"policy": POLICY, "new_river": True}
            if rid in prior_manifests:
                retained = pq.read_table(old / rid / "conditions.parquet").to_pandas()
                proposed = prepared["conditions"].loc[
                    prepared["conditions"].river_id == rid
                ]
                replacement_checks[rid] = check_observations(retained, proposed, rid)
                replacement_checks[rid]["previous_conditions_sha256"] = prior_manifests[
                    rid
                ]["files"]["conditions.parquet"]["sha256"]
        for rid in selected:
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", rid):
                raise ValueError("Unsafe river identifier")
        if old and all(
            rid in previous["rivers"]
            and json.loads((old / rid / "manifest.json").read_text())["build_identity"]
            == prepared["identity"]
            for rid in selected
        ):
            if prepared["execution_complete"] and downloads.exists():
                shutil.rmtree(downloads)
            return target, previous
        total_rows = sum(
            len(prepared[k])
            for k in ("conditions", "features", "observations", "warmup_conditions")
        )
        if total_rows > config.publication_max_rows:
            raise ValueError("Canonical publication row budget exceeded")
        stage = Path(tempfile.mkdtemp(prefix="snapshot-", dir=store))
        promoted = False
        try:
            atomic_json(stage / "owner.json", expected)
            _preserve_influence(old, stage)
            river_items = {}

            def budget():
                if (
                    sum(p.stat().st_size for p in stage.rglob("*") if p.is_file())
                    > config.publication_max_bytes
                ):
                    raise ValueError("Canonical publication byte budget exceeded")
                rows = sum(
                    pq.ParquetFile(p).metadata.num_rows
                    for p in stage.rglob("*.parquet")
                )
                if rows > config.publication_max_rows:
                    raise ValueError("Canonical publication row budget exceeded")

            for rid, item in previous["rivers"].items():
                if rid not in selected:
                    shutil.copytree(old / rid, stage / rid, copy_function=shutil.copy2)
                    river_items[rid] = item
                    budget()
            for rid, river in selected.items():
                sid = river["stations"][0]["station_id"]
                directory = stage / rid
                directory.mkdir()
                frames = {}
                for name, key, expected_schema in [
                    ("conditions", "conditions", CONDITIONS_SCHEMA),
                    ("features", "features", FEATURE_SCHEMA),
                    ("observations", "observations", OBS_SCHEMA),
                    ("warmup", "warmup_conditions", CONDITIONS_SCHEMA),
                ]:
                    all_rows = prepared[key]
                    frame = (
                        all_rows.loc[all_rows.river_id == rid]
                        if "river_id" in all_rows
                        else all_rows.loc[all_rows.station_id == sid]
                    )
                    frames[name] = frame
                    _parquet(directory / f"{name}.parquet", frame, expected_schema)
                    budget()
                coverage = prepared["coverage"].loc[
                    prepared["coverage"].river_id == rid
                ]
                coverage.to_parquet(directory / "coverage.parquet", index=False)
                sources = (
                    prepared["network"].get("source_requests_by_river", {}).get(rid, [])
                )
                atomic_json(
                    directory / "metadata.json",
                    {
                        "river_registry": river,
                        "station_metadata": prepared["metadata"].get(rid, {}),
                        "metadata_hash": digest(prepared["metadata"].get(rid, {})),
                        "source_requests": sources,
                        "climatology": prepared["baseline"],
                        **interpretation_notes(
                            config,
                            climatology_supplied=prepared["baseline"] is not None,
                            high_flow_definition=prepared["features"]
                            .attrs.get("high_flow_definitions", {})
                            .get(rid),
                            low_flow_definition=prepared["features"]
                            .attrs.get("low_flow_definitions", {})
                            .get(rid),
                            flow_pulse_definition=prepared["features"]
                            .attrs.get("flow_pulse_definitions", {})
                            .get(rid),
                        ),
                        "availability": "revised retrospective extracts; not operational vintages",
                        "prediction_cutoff": "Relative flow indicators are retrospective (full-history thresholds and two-sided interpolation); not eligible for operational backtests. Other features require completed day t support and provider availability."
                        if (
                            prepared["features"]
                            .attrs.get("low_flow_definitions", {})
                            .get(rid)
                            or prepared["features"]
                            .attrs.get("high_flow_definitions", {})
                            .get(rid)
                            or prepared["features"]
                            .attrs.get("flow_pulse_definitions", {})
                            .get(rid)
                        )
                        else "features include day t; require completed support and provider availability before use",
                    },
                )
                ledger = [
                    e
                    for e in prepared["network"].get("block_ledger", [])
                    if e["river_id"] == rid
                ]
                atomic_json(directory / "acquisition-ledger.json", {"blocks": ledger})
                budget()
                outcomes = prepared["outcomes"].get(rid, {})
                execution_complete = not any(
                    v.startswith(("failure:", "deferred:")) for v in outcomes.values()
                )
                eligible = prepared["eligibility"][rid]
                manifest = {
                    "schema_version": "hydrology-per-river-1",
                    "river_id": rid,
                    "station_id": sid,
                    "build_identity": prepared["identity"],
                    "implementation_hash": prepared["implementation"],
                    "start_date": config.start_date,
                    "end_date": config.end_date,
                    "temporal_basis": config.temporal_requirement,
                    "requested_metrics": list(metrics),
                    "metrics": {
                        k: sorted(f.metric.unique())
                        for k, f in frames.items()
                        if k in ("conditions", "features")
                    },
                    "execution_complete": execution_complete,
                    "data_eligible": eligible["required_discharge_eligible"],
                    "complete": eligible["required_discharge_eligible"]
                    and outcomes.get("discharge_mean") == "observed",
                    "eligibility": eligible,
                    "coverage_regression_guard": replacement_checks[rid],
                    "minimum_daily_coverage": config.minimum_daily_coverage,
                    "source_outcomes": outcomes,
                    "source_snapshot_hashes": sorted(
                        {
                            ref["source_release"]
                            for f in (frames["observations"], frames["warmup"])
                            for record in f.to_dict("records")
                            for ref in json.loads(merge_source_references([record]))
                            if ref.get("source_release")
                        }
                        | {e["source_release"] for e in sources}
                    ),
                    "configuration": config.as_dict(),
                    "source_storage": {
                        "owned_work_directory": str(downloads),
                        "policy": "discard downloaded payloads after validated execution-complete publication",
                    },
                    "runtime": runtime_fingerprint(),
                    "representation": "representative_gauge_proxy; not measured mouth flux or validated whale effect",
                    "files": {
                        p.name: {"sha256": checksum(p), "bytes": p.stat().st_size}
                        for p in sorted(directory.iterdir())
                    },
                }
                atomic_json(directory / "manifest.json", manifest)
                river_items[rid] = {
                    "manifest": f"{rid}/manifest.json",
                    "sha256": checksum(directory / "manifest.json"),
                }
                budget()
            catalog = {
                "schema_version": "hydrology-per-river-1",
                "rivers": dict(sorted(river_items.items())),
                "identity": digest(river_items),
                "model_readiness_established": False,
                "coverage_policy": "per-river manifests report actual eligible days; execution success is separate",
            }
            catalog = catalog_with_influence(catalog, stage)
            atomic_json(stage / "catalog.json", catalog)
            budget()
            _validate_snapshot(stage)
            _commit_stage(target, stage, store)
            promoted = True
            # Promotion already succeeded; cleanup failure must not report rollback.
            try:
                _cleanup_snapshots(store, None, expected)
                if prepared["execution_complete"] and downloads.exists():
                    shutil.rmtree(downloads)
            except OSError as exc:
                warnings.warn(
                    f"Product promoted; old snapshot cleanup pending: {exc}",
                    RuntimeWarning,
                )
            return target, catalog
        finally:
            if not promoted and stage.exists():
                shutil.rmtree(stage)

"""Offline current-product flow-indicator revision with atomic promotion and retained inputs."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path

import pandas as pd

from ..utils.flow_pulse import METHOD as PULSE_METHOD
from ..utils.flow_pulse import replace_flow_pulse
from ..utils.high_flow import METHOD as HIGH_METHOD
from ..utils.high_flow import replace_high_flow
from ..utils.influence_product import catalog_with_influence
from ..utils.io import atomic_json
from ..utils.low_flow import METHOD, replace_low_flow
from ..utils.products import checksum
from ..utils.provenance import digest, runtime_fingerprint
from .publication import (
    FEATURE_SCHEMA,
    _cleanup_snapshots,
    _commit_stage,
    _owner,
    _parquet,
    _paths,
    _pin,
    _preserve_influence,
    _recover,
    _validate_snapshot,
)


def _recompute(
    destination, *, indicator="low_flow", verbosity=False, max_bytes=536870912
):
    """Recalculate one flow indicator from saved conditions without acquisition.

    Immutable source companions are hard-linked into a new owned snapshot. Old
    staging is removed after promotion. Failed staging stays available for diagnosis.
    """
    from ..utils.settings import log

    replace, method, metric, threshold_key = {
        "low_flow": (
            replace_low_flow,
            METHOD,
            "low_flow_duration",
            "low_flow_threshold_m3_s",
        ),
        "flow_pulse": (
            replace_flow_pulse,
            PULSE_METHOD,
            "days_since_flow_pulse",
            "pulse_threshold_m3_s",
        ),
        "high_flow": (
            replace_high_flow,
            HIGH_METHOD,
            "high_flow_duration",
            "high_flow_threshold_m3_s",
        ),
    }[indicator]
    field, attribute = indicator + "_definition", indicator + "_definitions"
    config_key, module = indicator + "_method", indicator + ".py"
    log(verbosity, f"Offline recomputation started: {metric}; no provider acquisition")
    target, store, lock = _paths(destination)
    if target.is_symlink() or not lock.is_file():
        raise ValueError("An existing owned current product is required")
    with lock.open("r+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(
                "Another canonical reader/writer holds the product lock"
            ) from exc
        if store.is_symlink() or json.loads(
            (store / "owner.json").read_text()
        ) != _owner(target):
            raise ValueError("Canonical store ownership mismatch")
        _recover(target, store)
        old = _pin(target, store)
        previous = _validate_snapshot(old)
        prepared = {}
        for rid, item in previous["rivers"].items():
            directory = old / rid
            features = pd.read_parquet(directory / "features.parquet")
            revised = replace(
                features, pd.read_parquet(directory / "conditions.parquet")
            )
            definition = revised.attrs[attribute][rid]
            metadata = json.loads((directory / "metadata.json").read_text())
            unchanged = metadata.get(field) == definition and features.equals(revised)
            prepared[rid] = (item, revised, definition, metadata, unchanged)
            log(
                verbosity,
                f"Validated river {rid}: {len(revised)} feature rows; {definition['interpolated_days']} interpolated days for {metric}",
            )
        if all(value[-1] for value in prepared.values()):
            log(verbosity, "Current product already matches; no changes")
            return target, previous
        stage = Path(tempfile.mkdtemp(prefix="snapshot-", dir=store))
        atomic_json(stage / "owner.json", _owner(target))
        _preserve_influence(old, stage)
        implementation = checksum(Path(__file__).parents[1] / "utils" / module)
        rivers = {}
        for rid, (item, revised, definition, metadata, _) in prepared.items():
            directory = stage / rid
            directory.mkdir()
            for source in (old / rid).iterdir():
                if source.name not in {
                    "features.parquet",
                    "metadata.json",
                    "manifest.json",
                }:
                    if not source.is_file() or source.is_symlink():
                        raise ValueError("Unexpected canonical companion")
                    os.link(source, directory / source.name)
            _parquet(directory / "features.parquet", revised, FEATURE_SCHEMA)
            metadata[field] = definition
            metadata["configured_feature_thresholds"][threshold_key] = definition[
                "threshold_m3_s"
            ]
            metadata["prediction_cutoff"] = (
                "Relative flow indicators use full-history percentiles and two-sided interpolation; retrospective only, not eligible for operational backtests. Other metrics retain their original availability requirements."
            )
            atomic_json(directory / "metadata.json", metadata)
            manifest = json.loads((old / rid / "manifest.json").read_text())
            manifest["feature_recomputation"] = {
                "method": method,
                "shared_history_sha256": checksum(
                    Path(__file__).parents[1] / "utils" / "flow_history.py"
                ),
                "implementation_sha256": implementation,
                "source_manifest_sha256": item["sha256"],
                "source_snapshot": old.name,
                "source_conditions_sha256": manifest["files"]["conditions.parquet"][
                    "sha256"
                ],
                "definition_identity": definition["identity"],
                "runtime": runtime_fingerprint(),
            }
            manifest["metrics"]["features"] = sorted(set(revised.metric))
            manifest["configuration"][config_key] = "historical_percentile"
            manifest["build_identity"] = digest(manifest["feature_recomputation"])
            manifest["files"] = {
                p.name: {"sha256": checksum(p), "bytes": p.stat().st_size}
                for p in sorted(directory.iterdir())
            }
            atomic_json(directory / "manifest.json", manifest)
            rivers[rid] = {
                "manifest": f"{rid}/manifest.json",
                "sha256": checksum(directory / "manifest.json"),
            }
            if (
                sum(p.stat().st_size for p in stage.rglob("*") if p.is_file())
                > max_bytes
            ):
                raise ValueError("Recomputation byte budget exceeded; staging retained")
        catalog = {
            **previous,
            "rivers": rivers,
            "identity": digest(rivers),
            "model_readiness_established": False,
        }
        catalog = catalog_with_influence(catalog, stage)
        atomic_json(stage / "catalog.json", catalog)
        _validate_snapshot(stage)
        _commit_stage(target, stage, store)
        _cleanup_snapshots(store, None, _owner(target))
        log(
            verbosity,
            "Validated and promoted current directory; temporary snapshots removed",
        )
        return target, catalog


def recompute_low_flow(
    destination=None, *, max_bytes=536870912, verbosity=None, env_file=None
):
    """Recompute only relative low flow from retained conditions, without acquisition."""
    destination, verbosity = _settings(destination, verbosity, env_file)
    return _recompute(destination, max_bytes=max_bytes, verbosity=verbosity)


def recompute_flow_pulse(
    destination=None, *, max_bytes=536870912, verbosity=None, env_file=None
):
    """Recompute only relative flow-pulse timing; preserve observations/other metrics."""
    destination, verbosity = _settings(destination, verbosity, env_file)
    return _recompute(
        destination, indicator="flow_pulse", max_bytes=max_bytes, verbosity=verbosity
    )


def recompute_high_flow(
    destination=None, *, max_bytes=536870912, verbosity=None, env_file=None
):
    """Add/recompute relative high-flow duration from retained discharge only."""
    destination, verbosity = _settings(destination, verbosity, env_file)
    return _recompute(
        destination, indicator="high_flow", max_bytes=max_bytes, verbosity=verbosity
    )


def _settings(destination, verbosity, env_file):
    if destination is None or env_file is not None:
        from ..utils.config import Config

        config = Config.load(
            env_file=env_file, product_output=destination, verbosity=verbosity
        )
        return config.product_output, config.verbosity
    return destination, False if verbosity is None else verbosity

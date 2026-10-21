"""Processing pipeline: explicit stages, qualified inputs and outputs."""

import json
import time
from pathlib import Path

import pandas as pd

from ..utils.contracts import (
    VERSION,
    eligible,
)
from ..utils.daily import calendar_conditions, eligibility
from ..utils.features import build_features
from ..utils.provenance import digest, implementation_fingerprint, runtime_fingerprint
from ..utils.registry import audit, select_registry
from ..utils.settings import log
from . import acquisition


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


def prepare(config, metrics, *, make_h3=False):
    """Acquire and qualify a bounded selection without writing a release tree."""
    started = time.perf_counter()
    rivers = select_registry(config)
    observations, metadata, outcomes, network = acquisition.acquire(config, metrics)
    fetched = time.perf_counter()
    source_hashes = set(observations.source_release.dropna())
    # Decode repeated block provenance once, without copying all observation rows.
    references = observations.get("source_references", pd.Series(dtype=str))
    for encoded in references.dropna().unique():
        source_hashes.update(
            ref["source_release"]
            for ref in json.loads(encoded)
            if ref.get("source_release")
        )
    source_hashes.update(
        e["source_release"] for e in network.get("source_requests", [])
    )
    source_hashes = sorted(source_hashes)
    selected = river_conditions(observations, rivers, metadata, config)
    warmup_conditions = selected.loc[selected.date < config.start_date].copy()
    conditions = calendar_conditions(
        selected,
        observations,
        rivers,
        config,
        metrics,
        outcomes,
        network.get("block_ledger", []),
    )
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
    if config.low_flow_method == "historical_percentile":
        from ..utils.low_flow import replace_low_flow

        features = replace_low_flow(features, conditions)
    if config.flow_pulse_method == "historical_percentile":
        from ..utils.flow_pulse import replace_flow_pulse

        features = replace_flow_pulse(features, conditions)
    from ..utils.high_flow import replace_high_flow

    features = replace_high_flow(features, conditions)
    log(
        config.verbosity,
        f"Prepared {len(conditions)} condition rows and {len(features)} feature rows",
    )
    engineered = time.perf_counter()
    coverage = audit(conditions, rivers, config.start_date, config.end_date, outcomes)
    failures = {
        r: dict(o) for r, o in outcomes.items() if o.get("discharge_mean") != "observed"
    }
    eligibility_summary = eligibility(conditions, rivers, config)
    for rid, entry in eligibility_summary.items():
        if not entry["required_discharge_eligible"]:
            failures.setdefault(rid, {})["eligibility"] = (
                "required discharge coverage below configured threshold"
            )
    execution_complete = not any(
        v.startswith(("failure:", "deferred:"))
        for o in outcomes.values()
        for v in o.values()
    )
    implementation = implementation_fingerprint()
    identity = digest(
        {
            "implementation": implementation,
            "runtime": runtime_fingerprint(),
            "config": {k: v for k, v in config.as_dict().items() if k != "verbosity"},
            "sources": source_hashes,
            "metadata": metadata,
            "source_requests": network.get("source_requests", []),
            "registry": rivers,
            "software": VERSION,
            "baseline": baseline,
            # Retry diagnostics contain elapsed wait budgets; they are run evidence,
            # not a scientific input revision. Preserve full details in the manifest.
            "outcomes": {
                river: {
                    metric: message.split(":", 1)[0]
                    for metric, message in values.items()
                }
                for river, values in outcomes.items()
            },
            "metrics": metrics,
            "make_h3": make_h3,
            "spatial_inputs": {
                p: digest(Path(p).read_text())
                for p in [config.water_mask, config.receiving_regions]
                if p and Path(p).is_file()
            },
        }
    )[:20]
    return {
        "rivers": rivers,
        "observations": observations,
        "metadata": metadata,
        "outcomes": outcomes,
        "network": network,
        "source_hashes": source_hashes,
        "conditions": conditions,
        "features": features,
        "warmup_conditions": warmup_conditions,
        "baseline": baseline,
        "coverage": coverage,
        "failures": failures,
        "eligibility": eligibility_summary,
        "execution_complete": execution_complete,
        "implementation": implementation,
        "identity": identity,
        "timing": {
            "acquisition": fetched - started,
            "features_and_selection": engineered - fetched,
        },
    }

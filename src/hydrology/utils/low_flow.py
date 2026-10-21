"""Retrospective, river-relative low-flow duration; source observations stay intact."""

from __future__ import annotations

import pandas as pd

from .flow_history import flow_histories, replace_metric
from .provenance import digest

METHOD = "historical-p10-linear-interior-v1"
KEY = ["river_id", "station_id", "date", "metric", "temporal_basis"]


def relative_low_flow(conditions):
    """Return daily durations and per-river definitions from the full supplied history.

    Only finite, valid daily mean discharge is used. Interior gaps are linearly
    interpolated before fitting the linear 0.1 quantile. No edge extrapolation;
    a low spell starting before known support remains censored until a non-low day.
    This uses future observations and is unsuitable for operational backtests.
    """
    rows, definitions = [], {}
    for (
        river,
        station,
        basis,
        index,
        observed,
        filled,
        estimated,
        sources,
        interpolation,
    ) in flow_histories(conditions):
        supported = filled.dropna()
        threshold = (
            float(supported.quantile(0.1, interpolation="linear"))
            if len(supported) >= 2
            else None
        )
        definition = {
            "method": METHOD,
            "quantile": 0.1,
            "quantile_method": "linear",
            "comparison": "strictly below",
            "threshold_m3_s": threshold,
            "reference_start": index[0].date().isoformat(),
            "reference_end": index[-1].date().isoformat(),
            "observed_days": int(observed.notna().sum()),
            "interpolated_days": int(estimated.sum()),
            "unfilled_days": int(filled.isna().sum()),
            "interpolation": interpolation,
            "edge_policy": "no extrapolation; unknown streak start remains null until a non-low day",
            "retrospective": True,
            "model_eligible": False,
            "qualification": "Full retained history, including interpolated interior days; uses future observations. Descriptive only, not a validated ecological threshold or operational forecast input.",
        }
        definition["identity"] = digest(definition)
        definitions[river] = definition
        duration, includes_estimate = None, False
        for i, day in enumerate(index):
            value = filled.iloc[i]
            reason = None
            if threshold is None or pd.isna(value):
                duration, includes_estimate = None, False
                reason = (
                    "insufficient_reference_support"
                    if threshold is None
                    else "flow_unavailable_no_extrapolation"
                )
            elif value >= threshold:
                duration, includes_estimate = 0, False
            elif duration is None:
                reason = "low_flow_start_unknown"
            else:
                duration += 1
                includes_estimate = includes_estimate or bool(estimated.iloc[i])
            if duration is not None:
                if estimated.iloc[i]:
                    reason = "interpolated_flow_input"
                elif includes_estimate:
                    reason = "streak_includes_interpolated_flow"
            rows.append(
                {
                    "river_id": river,
                    "station_id": station,
                    "date": day.date().isoformat(),
                    "metric": "low_flow_duration",
                    "temporal_basis": basis,
                    "value": float(duration) if duration is not None else None,
                    "unit": "day",
                    "status": "valid" if duration is not None else "unavailable",
                    "reason": reason,
                    "climatology_id": definition["identity"],
                    "method_version": METHOD,
                    "contributor_series": sources.iloc[i]
                    if pd.notna(sources.iloc[i])
                    else None,
                }
            )
    return pd.DataFrame(rows), definitions


def replace_low_flow(features, conditions):
    """Replace only this metric, preserving other feature values and row order."""
    low, definitions = relative_low_flow(conditions)
    result = replace_metric(features, low, "low_flow_duration")
    result.attrs["low_flow_definitions"] = definitions
    return result

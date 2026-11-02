"""Retrospective, river-relative high-flow duration; source observations stay intact."""

from __future__ import annotations

import pandas as pd

from .flow_history import KEY, flow_histories, replace_metric
from .provenance import digest

METHOD = "historical-p90-high-duration-linear-interior-v1"


def relative_high_flow(conditions):
    """Return daily durations and per-river definitions from the full supplied history.

    Only finite, valid daily mean discharge is used. Interior gaps are linearly
    interpolated before fitting the linear 0.9 quantile. No edge extrapolation;
    a high spell starting before known support remains censored until a non-high day.
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
            float(supported.quantile(0.9, interpolation="linear"))
            if len(supported) >= 2
            else None
        )
        definition = {
            "method": METHOD,
            "quantile": 0.9,
            "quantile_method": "linear",
            "comparison": "strictly above",
            "threshold_m3_s": threshold,
            "reference_start": index[0].date().isoformat(),
            "reference_end": index[-1].date().isoformat(),
            "observed_days": int(observed.notna().sum()),
            "interpolated_days": int(estimated.sum()),
            "unfilled_days": int(filled.isna().sum()),
            "interpolation": interpolation,
            "edge_policy": "no extrapolation; unknown streak start remains null until a non-high day",
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
            elif value <= threshold:
                duration, includes_estimate = 0, False
            elif duration is None:
                reason = "high_flow_start_unknown"
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
                    "metric": "high_flow_duration",
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


def replace_high_flow(features, conditions):
    """Add or replace high-flow duration; preserve every other feature row.

    New calendars must match the existing daily discharge feature exactly. Existing
    high-flow calendars use the same strict replacement check as other indicators.
    """
    high, definitions = relative_high_flow(conditions)
    if high.empty:
        raise ValueError("No discharge history for relative flow")
    if features.metric.eq("high_flow_duration").any():
        result = replace_metric(features, high, "high_flow_duration")
    else:
        anchor = features.loc[features.metric == "discharge_mean", KEY].copy()
        anchor["date"] = pd.to_datetime(anchor.date).dt.strftime("%Y-%m-%d")
        anchor["metric"] = "high_flow_duration"
        if anchor.duplicated(KEY).any() or set(map(tuple, anchor.to_numpy())) != set(
            map(tuple, high[KEY].to_numpy())
        ):
            raise ValueError("Relative flow calendar/identity mismatch")
        for column in high.columns:
            if isinstance(features[column].dtype, pd.StringDtype):
                high[column] = high[column].astype(features[column].dtype)
        result = pd.concat([features, high], ignore_index=True)
        result.attrs = features.attrs.copy()
    result.attrs["high_flow_definitions"] = definitions
    return result

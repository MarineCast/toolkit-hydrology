"""Retrospective days since upward crossing of each river's historical P90."""

import pandas as pd

from .flow_history import flow_histories, replace_metric
from .provenance import digest

METHOD = "historical-p90-linear-interior-v1"


def relative_flow_pulse(conditions):
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
            "comparison": "upward crossing from below to at or above",
            "threshold_m3_s": threshold,
            "reference_start": index[0].date().isoformat(),
            "reference_end": index[-1].date().isoformat(),
            "observed_days": int(observed.notna().sum()),
            "interpolated_days": int(estimated.sum()),
            "unfilled_days": int(filled.isna().sum()),
            "interpolation": interpolation,
            "edge_policy": "no extrapolation; unavailable before a known upward crossing or after an unfilled gap",
            "retrospective": True,
            "model_eligible": False,
            "qualification": "Full retained history, including interpolated interior days; uses future observations. Descriptive only, not a validated ecological threshold or operational forecast input.",
        }
        definition["identity"] = digest(definition)
        definitions[river] = definition
        previous, last_pulse = None, None
        previous_estimated, depends_on_estimate = False, False
        for i, day in enumerate(index):
            value = filled.iloc[i]
            reason, duration = None, None
            if threshold is None or pd.isna(value):
                previous, last_pulse = None, None
                previous_estimated, depends_on_estimate = False, False
                reason = (
                    "insufficient_reference_support"
                    if threshold is None
                    else "flow_unavailable_no_extrapolation"
                )
            else:
                if previous is not None and previous < threshold <= value:
                    last_pulse = day
                    depends_on_estimate = previous_estimated or bool(estimated.iloc[i])
                elif last_pulse is not None:
                    depends_on_estimate = depends_on_estimate or bool(estimated.iloc[i])
                previous, previous_estimated = value, bool(estimated.iloc[i])
                if last_pulse is None:
                    reason = "pulse_history_unknown"
                else:
                    duration = (day - last_pulse).days
                    reason = (
                        "interpolated_flow_input"
                        if estimated.iloc[i]
                        else "pulse_history_includes_interpolated_flow"
                        if depends_on_estimate
                        else None
                    )
            rows.append(
                {
                    "river_id": river,
                    "station_id": station,
                    "date": day.date().isoformat(),
                    "metric": "days_since_flow_pulse",
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


def replace_flow_pulse(features, conditions):
    rows, definitions = relative_flow_pulse(conditions)
    result = replace_metric(features, rows, "days_since_flow_pulse")
    result.attrs["flow_pulse_definitions"] = definitions
    return result

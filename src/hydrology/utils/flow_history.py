"""Shared provider-daily discharge preparation for retrospective flow indicators."""

import numpy as np
import pandas as pd

from .contracts import validate_values

KEY = ["river_id", "station_id", "date", "metric", "temporal_basis"]


def flow_histories(conditions):
    validate_values(conditions)
    seen = set()
    discharge = conditions.loc[conditions.metric == "discharge_mean"].copy()
    for (river, station, basis), group in discharge.groupby(
        ["river_id", "station_id", "temporal_basis"]
    ):
        if river in seen:
            raise ValueError("Relative flow requires one station/basis per river")
        seen.add(river)
        if set(group.unit) != {"m3/s"}:
            raise ValueError("Relative flow requires discharge in m3/s")
        group.index = pd.to_datetime(group.date)
        if (
            group.index.duplicated().any()
            or (group.index != group.index.normalize()).any()
        ):
            raise ValueError("Ambiguous relative flow daily keys")
        group = group.sort_index()
        index = pd.date_range(group.index.min(), group.index.max())
        observed = (
            pd.to_numeric(group.value.where(group.status == "valid"), errors="raise")
            .astype(float)
            .reindex(index)
        )
        filled = observed.interpolate(method="linear", limit_area="inside")
        estimated = observed.isna() & filled.notna()
        sources = group.get(
            "series_id", pd.Series(index=group.index, dtype=object)
        ).reindex(index)
        interpolation = []
        eligible = np.flatnonzero(observed.notna().to_numpy())
        for i in np.flatnonzero(estimated.to_numpy()):
            left = eligible[np.searchsorted(eligible, i) - 1]
            right = eligible[np.searchsorted(eligible, i)]
            interpolation.append(
                {
                    "date": index[i].date().isoformat(),
                    "value_m3_s": float(filled.iloc[i]),
                    "left_date": index[left].date().isoformat(),
                    "right_date": index[right].date().isoformat(),
                    "left_value_m3_s": float(observed.iloc[left]),
                    "right_value_m3_s": float(observed.iloc[right]),
                    "left_series": sources.iloc[left]
                    if pd.notna(sources.iloc[left])
                    else None,
                    "right_series": sources.iloc[right]
                    if pd.notna(sources.iloc[right])
                    else None,
                }
            )
        yield (
            river,
            station,
            basis,
            index,
            observed,
            filled,
            estimated,
            sources,
            interpolation,
        )


def replace_metric(features, rows, metric):
    """Replace one metric with identical keys; leave other feature rows intact."""
    if rows.empty:
        raise ValueError("No discharge history for relative flow")
    result = features.copy()
    mask = result.metric == metric
    original = result.loc[mask, KEY].copy()
    original["date"] = pd.to_datetime(original.date).dt.strftime("%Y-%m-%d")
    if original.duplicated(KEY).any() or set(map(tuple, original.to_numpy())) != set(
        map(tuple, rows[KEY].to_numpy())
    ):
        raise ValueError("Relative flow calendar/identity mismatch")
    ordered = original.merge(
        rows, on=KEY, how="left", validate="one_to_one", sort=False
    )
    for column in rows.columns.difference(KEY):
        if column != "value" and pd.api.types.is_numeric_dtype(result[column]):
            result[column] = result[column].astype(object)
        values = (
            pd.to_numeric(ordered[column], errors="raise").to_numpy(
                dtype=float, na_value=np.nan
            )
            if column == "value"
            else ordered[column].to_numpy()
        )
        result.loc[mask, column] = values
    validate_values(result)
    return result

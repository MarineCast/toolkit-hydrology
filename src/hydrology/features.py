"""Daily causal windows and training-only seasonal reference artifacts."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import digest


def season_day(d):
    """365-day calendar: February 29 pools with February 28."""
    d = pd.Timestamp(d)
    return pd.Timestamp(
        f"2001-{d.month:02d}-{min(d.day, 28) if d.month == 2 else d.day:02d}"
    ).dayofyear


def fit_climatology(
    frame, cutoff, *, reference_start=None, window=15, min_samples=60, min_years=3
):
    cutoff = pd.Timestamp(cutoff).normalize()
    if window < 0 or window > 182 or min_samples < 1 or min_years < 1:
        raise ValueError("Invalid climatology settings")
    f = frame.loc[
        (pd.to_datetime(frame.date) <= cutoff)
        & frame.value.notna()
        & (frame.status == "valid")
    ].copy()
    if reference_start:
        f = f.loc[pd.to_datetime(f.date) >= pd.Timestamp(reference_start)]
    artifact = {
        "version": "seasonal-1",
        "training_cutoff": cutoff.date().isoformat(),
        "reference_start": reference_start,
        "window": window,
        "min_samples": min_samples,
        "min_years": min_years,
        "leap_day": "pool with February 28",
        "source_releases": sorted(set(f.source_release)),
        "groups": {},
    }
    for keys, g in f.groupby(["river_id", "station_id", "metric", "temporal_basis"]):
        doy = np.array([season_day(d) for d in g.date])
        years = pd.to_datetime(g.date).dt.year.to_numpy()
        entries = {}
        for day in range(1, 366):
            delta = np.abs(doy - day)
            mask = np.minimum(delta, 365 - delta) <= window
            vals = g.value.to_numpy()[mask]
            if len(vals) >= min_samples and len(set(years[mask])) >= min_years:
                entries[str(day)] = {
                    "values": sorted(map(float, vals)),
                    "years": len(set(years[mask])),
                }
        artifact["groups"]["|".join(keys)] = entries
    artifact["identity"] = digest(artifact)
    return artifact


def build_features(
    frame, *, climatology=None, low_threshold=10.0, pulse_threshold=1000.0
):
    if climatology and digest(
        {k: v for k, v in climatology.items() if k != "identity"}
    ) != climatology.get("identity"):
        raise ValueError("Climatology artifact checksum mismatch")
    rows = []
    for keys, g in frame.groupby(
        ["river_id", "station_id", "metric", "temporal_basis"]
    ):
        river, station, metric, basis = keys
        if g.date.duplicated().any():
            raise ValueError("Ambiguous selected daily source")
        g = g.sort_values("date").set_index(pd.to_datetime(g.date))
        index = pd.date_range(g.index.min(), g.index.max())
        values = g.value.where(g.status == "valid").reindex(index)
        rolling7 = values.rolling(7, min_periods=7).mean()
        rolling30 = values.rolling(30, min_periods=30).mean()
        change = (values - values.shift(7)).where(
            values.rolling(8, min_periods=8).count() == 8
        )
        low = None
        last_pulse = None
        prev = None
        baseline = (
            climatology.get("groups", {}).get("|".join(keys), {}) if climatology else {}
        )
        for i, day in enumerate(index):
            v = values.iloc[i]
            percentile = None
            anomaly = None
            if pd.isna(v):
                low = None
                last_pulse = None
                prev = None
            else:
                low = (
                    0 if v >= low_threshold else (low + 1 if low is not None else None)
                )
                if prev is not None and prev < pulse_threshold <= v:
                    last_pulse = day
                prev = v
            entry = baseline.get(str(season_day(day)))
            if (
                entry
                and day > pd.Timestamp(climatology["training_cutoff"])
                and pd.notna(v)
            ):
                ref = np.array(entry["values"])
                percentile = 100 * (np.sum(ref < v) + 0.5 * np.sum(ref == v)) / len(ref)
                # Absolute departure preserves signed/zero flows and temperature units.
                anomaly = float(v - np.mean(ref))
            metrics = {metric: (v, "m3/s" if metric == "discharge_mean" else "degC")}
            if metric == "discharge_mean":
                metrics.update(
                    discharge_mean_7d=(rolling7.iloc[i], "m3/s"),
                    discharge_mean_30d=(rolling30.iloc[i], "m3/s"),
                    discharge_change_7d=(change.iloc[i], "m3/s"),
                    discharge_seasonal_percentile=(percentile, "percent"),
                    discharge_seasonal_anomaly=(anomaly, "m3/s"),
                    low_flow_duration=(low, "day"),
                    days_since_flow_pulse=(
                        (day - last_pulse).days if last_pulse is not None else None,
                        "day",
                    ),
                )
            elif metric == "temperature_max":
                metrics["temperature_7dadm"] = (rolling7.iloc[i], "degC")
            elif metric == "temperature_mean":
                metrics["temperature_seasonal_anomaly"] = (anomaly, "degC")
            for name, (value, unit) in metrics.items():
                valid = value is not None and pd.notna(value)
                rows.append(
                    dict(
                        river_id=river,
                        station_id=station,
                        date=day.date().isoformat(),
                        metric=name,
                        temporal_basis=basis,
                        value=float(value) if valid else None,
                        unit=unit,
                        status="valid" if valid else "unavailable",
                        climatology_id=climatology["identity"] if climatology else None,
                        method_version="features-1",
                        contributor_series=g.loc[day, "series_id"]
                        if day in g.index
                        else None,
                    )
                )
    return pd.DataFrame(
        rows,
        columns=[
            "river_id",
            "station_id",
            "date",
            "metric",
            "temporal_basis",
            "value",
            "unit",
            "status",
            "climatology_id",
            "method_version",
            "contributor_series",
        ],
    )

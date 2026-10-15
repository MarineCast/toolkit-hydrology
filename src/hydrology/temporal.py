"""Causal left-hold integration on explicitly UTC-aligned intervals."""

import json

import numpy as np
import pandas as pd

from .core import OBS_COLUMNS, digest


def aggregate_utc(
    samples,
    station,
    metric,
    start,
    end,
    *,
    max_hold_seconds=3600,
    minimum_coverage=0.9,
    allow_provisional=False,
    provider="usgs",
):
    if max_hold_seconds <= 0 or not 0 < minimum_coverage <= 1:
        raise ValueError("Invalid support thresholds")
    if samples.empty:
        return pd.DataFrame(columns=OBS_COLUMNS)
    if samples.series_id.nunique() != 1:
        raise ValueError("Select one continuous series before aggregation")
    samples = samples.copy()
    # Naive time is not UTC. Never guess timezone.
    if any(pd.Timestamp(t).tzinfo is None for t in samples.time):
        raise ValueError("Timestamp requires timezone")
    samples["time"] = pd.to_datetime(samples.time, utc=True)
    samples = samples.drop_duplicates().sort_values("time")
    if samples.time.duplicated().any():
        raise ValueError("Conflicting samples at duplicate timestamps")
    samples["value"] = pd.to_numeric(samples.value)
    if not allow_provisional:
        samples.loc[
            samples.raw_flags.fillna("").str.contains("Provisional", case=False),
            "value",
        ] = np.nan
    ts = samples.time.tolist()
    values = samples.value.tolist()
    segments = []
    for i, (t, v) in enumerate(zip(ts, values)):
        if pd.isna(v):
            continue
        stop = min(
            t + pd.Timedelta(seconds=max_hold_seconds),
            ts[i + 1]
            if i + 1 < len(ts)
            else t + pd.Timedelta(seconds=max_hold_seconds),
        )
        segments.append((t, stop, v))
    rows = []
    for day in pd.date_range(start, end, tz="UTC"):
        stop = day + pd.Timedelta(days=1)
        supported = 0.0
        weighted = 0.0
        maxima = []
        for a, b, v in segments:
            seconds = max(0, (min(b, stop) - max(a, day)).total_seconds())
            if seconds:
                supported += seconds
                weighted += seconds * v
                maxima.append(v)
        coverage = supported / 86400
        value = (
            (max(maxima) if metric == "temperature_max" else weighted / supported)
            if supported and coverage >= minimum_coverage
            else None
        )
        # Maximum is only eligible for dense continuous measurements under explicit hold/coverage rules.
        rows.append(
            dict(
                station_id=station,
                series_id=samples.series_id.iloc[0],
                metric=metric,
                date=day.date().isoformat(),
                temporal_basis="utc_daily",
                value=value,
                unit="m3/s" if metric == "discharge_mean" else "degC",
                status="valid"
                if value is not None
                else ("partial" if supported else "unavailable"),
                provider=provider,
                origin="observed",
                raw_flags=json.dumps(sorted(set(samples.raw_flags))),
                coverage=coverage,
                interval_start=day.isoformat(),
                interval_end=stop.isoformat(),
                day_definition=f"UTC left hold <= {max_hold_seconds}s; minimum coverage {minimum_coverage}",
                retrieved_at=max(samples.retrieved_at),
                available_at=None,
                source_modified_at=None,
                source_release=digest(sorted(set(samples.source_release))),
                record_id=digest([station, metric, str(day)]),
            )
        )
    return pd.DataFrame(rows, columns=OBS_COLUMNS)

"""Lagged event-date causal discharge features; no interpolation or acquisition."""
from __future__ import annotations

import json
from pathlib import Path
import pyarrow.parquet as pq
from .products import checksum

import numpy as np
import pandas as pd

from .contracts import validate_values
from .features import season_day
from .provenance import digest

METHOD = "causal-seasonal-lag1-v1"
UNITS = {
    "causal_discharge_seasonal_mean": "m3/s",
    "causal_discharge_seasonal_p90": "m3/s",
    "causal_discharge_seasonal_anomaly": "m3/s",
    "causal_discharge_seasonal_percentile": "percent",
    "causal_discharge_pulse": "1",
    "causal_days_since_discharge_pulse": "day",
    "causal_reference_samples": "day",
    "causal_reference_years": "year",
}


def causal_features(conditions, *, window=15, min_samples=60, min_years=3, history_years=10):
    """One output date per input discharge date; all values use dates < output date."""
    if not (0 <= window <= 182 and min_samples >= 1 and 1 <= min_years <= history_years <= 30):
        raise ValueError("Invalid causal reference parameters")
    validate_values(conditions)
    definition = dict(method=METHOD, window_days=window, min_samples=min_samples,
        min_years=min_years, history_years=history_years, lag_days=1,
        reference="completed calendar years before as-of day year; circular 365-day +/- window",
        leap_day="February 29 pools with February 28, retained as a separate sample",
        as_of="output date t uses observed day s=t-1; reference years < year(s)",
        percentile="100 * (count(reference < q_s) + 0.5 * count(reference == q_s)) / n",
        pulse="q_(s-1) < P90(s) <= q_s; both compared to the same seasonal threshold",
        gaps="no interpolation; missing s resets pulse age; missing s-1 makes pulse unavailable; age unknown until a witnessed crossing",
        quantile="numpy linear P90", units=UNITS,
        event_date_causal=True, operational_availability="unknown; lag is not proof of provider availability",
        model_eligible=False, temporal_support="native provider civil dates; exact boundaries/timezone remain as recorded in retained metadata; not UTC")
    definition["identity"] = digest(definition)
    rows=[]
    discharge=conditions.loc[conditions.metric == "discharge_mean"]
    if discharge.empty:
        raise ValueError("No discharge")
    for (river, station, basis), group in discharge.groupby(["river_id", "station_id", "temporal_basis"]):
        if set(group.unit) != {"m3/s"}:
            raise ValueError("Expected m3/s")
        dates=pd.DatetimeIndex(pd.to_datetime(group.date))
        if dates.tz is not None or dates.duplicated().any() or (dates != dates.normalize()).any():
            raise ValueError("Ambiguous civil-day keys")
        group=group.copy(); group.index=dates; group=group.sort_index()
        index=pd.date_range(group.index.min()-pd.Timedelta(days=2), group.index.max())
        q=group.value.where(group.status.eq("valid")).reindex(index).astype(float).to_numpy()
        days=np.array([season_day(d) for d in index]); years=index.year.to_numpy()
        last=None
        for i, day in enumerate(index):
            if day not in group.index:
                last=None
                continue
            s=i-1
            delta=np.abs(days-days[s])
            mask=(years < years[s]) & (years >= years[s]-history_years) & (np.minimum(delta,365-delta)<=window) & np.isfinite(q)
            ref=q[mask]; n=len(ref); ny=len(set(years[mask]))
            ready=n>=min_samples and ny>=min_years
            vals={name:None for name in UNITS}
            reasons={name:"insufficient_reference_support" for name in UNITS}
            vals["causal_reference_samples"]=n; vals["causal_reference_years"]=ny
            if ready:
                mean=float(ref.mean()); p90=float(np.quantile(ref,.9,method="linear"))
                vals["causal_discharge_seasonal_mean"]=mean
                vals["causal_discharge_seasonal_p90"]=p90
                if np.isfinite(q[s]):
                    vals["causal_discharge_seasonal_anomaly"]=q[s]-mean
                    vals["causal_discharge_seasonal_percentile"]=100*((ref<q[s]).sum()+.5*(ref==q[s]).sum())/n
                    if np.isfinite(q[s-1]):
                        pulse=float(q[s-1]<p90<=q[s])
                        vals["causal_discharge_pulse"]=pulse
                        if pulse: last=day
                    else:
                        last=None
                        reasons["causal_discharge_pulse"]="previous_day_unavailable"
                    if last is not None:
                        vals["causal_days_since_discharge_pulse"]=(day-last).days
                    else:
                        reasons["causal_days_since_discharge_pulse"]="pulse_history_unknown"
                else:
                    last=None
                    for name in ("causal_discharge_seasonal_anomaly", "causal_discharge_seasonal_percentile", "causal_discharge_pulse", "causal_days_since_discharge_pulse"):
                        reasons[name]="as_of_discharge_unavailable"
            else:
                last=None
            for name,value in vals.items():
                rows.append(dict(river_id=river,station_id=station,date=day.date(),as_of_date=index[s].date(),
                    temporal_basis=basis,metric=name,value=value,unit=UNITS[name],status="valid" if value is not None else "unavailable",
                    reason=None if value is not None else reasons[name],method_version=METHOD))
    result=pd.DataFrame(rows)
    validate_values(result)
    return result,definition


KEY = b"hydrology_causal"


def catalog_with_causal(catalog, root):
    path=Path(root)/"causal.parquet"
    if not path.exists():
        if "causal" in catalog.get("products", {}):
            raise ValueError("Missing causal companion")
        return catalog
    if path.is_symlink():
        raise ValueError("Causal symlink forbidden")
    table=pq.read_table(path)
    meta=json.loads(table.schema.metadata[KEY])
    sources={rid:checksum(Path(root)/rid/"conditions.parquet") for rid in catalog["rivers"]}
    entry=dict(path=path.name,sha256=checksum(path),bytes=path.stat().st_size,rows=len(table),
        definition=meta["definition"],source_conditions_sha256=meta["sources"],
        source_status="current" if sources==meta["sources"] else "requires_rebuild")
    return {**catalog,"products":{**catalog.get("products",{}),"causal":entry}}

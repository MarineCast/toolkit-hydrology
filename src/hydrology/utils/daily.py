"""Expected-calendar missingness and eligibility, independent of execution success."""

import pandas as pd

from .contracts import OBS_COLUMNS
from .providers import METRICS


def calendar_conditions(
    selected, observations, rivers, config, metrics, outcomes, ledger
):
    start = (pd.Timestamp(config.start_date) - pd.Timedelta(days=30)).date().isoformat()
    dates = pd.date_range(start, config.end_date).strftime("%Y-%m-%d")
    frames = []
    for river in rivers:
        rid = river["river_id"]
        station = river["stations"][0]
        for metric, (_, _, unit) in METRICS.items():
            found = selected.loc[
                (selected.river_id == rid) & (selected.metric == metric)
            ]
            if len(found) and set(found.temporal_basis) != {
                config.temporal_requirement
            }:
                raise ValueError(
                    "Selected temporal basis does not match requested calendar"
                )
            if len(found) and set(found.unit.dropna()) != {unit}:
                raise ValueError("Unexpected selected units")
            if found.date.duplicated().any():
                raise ValueError("Ambiguous selected daily calendar")
            f = found.set_index("date").reindex(dates).rename_axis("date").reset_index()
            f["river_id"] = rid
            f["station_id"] = station["station_id"]
            f["metric"] = metric
            f["unit"] = f.unit.fillna(unit)
            f["temporal_basis"] = config.temporal_requirement
            f["representation"] = "representative_gauge_proxy"
            f["status"] = f.status.fillna("unavailable")
            f["source_changed"] = f.source_changed.fillna(False).astype(bool)
            f["reason"] = None
            outcome = outcomes.get(rid, {}).get(metric, "not_requested")
            entries = [
                e for e in ledger if e["river_id"] == rid and e["metric"] == metric
            ]
            raw_dates = set(
                observations.loc[
                    (observations.station_id == station["station_id"])
                    & (observations.metric == metric),
                    "date",
                ]
            )
            for i in f.index[f.value.isna()]:
                day = f.at[i, "date"]
                reason = "no_observation"
                if metric not in metrics:
                    reason = "not_requested"
                    f.at[i, "status"] = "not_applicable"
                elif day < station["valid_from"] or (
                    station.get("valid_to") and day > station["valid_to"]
                ):
                    reason = "outside_station_relationship"
                elif (
                    config.as_of and day in raw_dates and pd.isna(f.at[i, "series_id"])
                ):
                    reason = "availability_not_proven_by_as_of"
                elif pd.notna(f.at[i, "series_id"]):
                    reason = (
                        "insufficient_interval_support"
                        if f.at[i, "status"] == "partial"
                        else "ineligible_or_missing_value"
                    )
                else:
                    entry = next(
                        (e for e in entries if e["start"] <= day <= e["end"]), None
                    )
                    if entry:
                        if entry["state"] not in ("completed", "empty"):
                            reason = entry["state"]
                    elif outcome.startswith(("failure:", "deferred:", "unsupported:")):
                        reason = outcome.split(":", 1)[0]
                f.at[i, "reason"] = reason
            # Unknown support remains unknown for native days and absent UTC days.
            f["day_definition"] = f.day_definition.fillna(
                "UTC calendar day; no eligible observations"
                if config.temporal_requirement == "utc_daily"
                else "provider day; exact boundaries unverified"
            )
            if config.temporal_requirement == "utc_daily":
                f["interval_start"] = pd.to_datetime(f.date, utc=True).astype(str)
                f["interval_end"] = (
                    pd.to_datetime(f.date, utc=True) + pd.Timedelta(days=1)
                ).astype(str)
            frames.append(f)
    result = pd.concat(frames, ignore_index=True)
    for column in OBS_COLUMNS:
        if column not in result:
            result[column] = None
    return result.sort_values(["river_id", "metric", "date"]).reset_index(drop=True)


def eligibility(conditions, rivers, config):
    result = {}
    expected = len(pd.date_range(config.start_date, config.end_date))
    for river in rivers:
        entries = {}
        for metric in METRICS:
            f = conditions.loc[
                (conditions.river_id == river["river_id"])
                & (conditions.metric == metric)
            ]
            valid = f.loc[f.value.notna() & (f.status == "valid")]
            entries[metric] = {
                "expected_days": expected,
                "eligible_days": len(valid),
                "coverage": len(valid) / expected,
                "latest_eligible_date": valid.date.max() if len(valid) else None,
                "unknown_days": int(f.value.isna().sum()),
                "missing_reasons": f.loc[f.value.isna(), "reason"]
                .value_counts()
                .to_dict(),
            }
        result[river["river_id"]] = {
            "metrics": entries,
            "required_discharge_eligible": entries["discharge_mean"]["coverage"]
            >= config.minimum_daily_coverage,
        }
    return result

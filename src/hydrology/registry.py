"""Explicit station-to-river relationships; no implicit gauge summation/scaling."""

import json
from importlib.resources import files
from pathlib import Path

import pandas as pd


def load_registry(path=None):
    payload = json.loads(
        Path(path).read_text()
        if path
        else files("hydrology").joinpath("data/registry.json").read_text()
    )
    rivers = payload["rivers"]
    if len({r["river_id"] for r in rivers}) != len(rivers):
        raise ValueError("Duplicate river identifiers")
    for r in rivers:
        if len(r["stations"]) != 1:
            raise ValueError(
                "v1 requires one explicit representative station per river; nested gauges cannot be summed"
            )
        if r["representation"] != "representative_gauge_proxy":
            raise ValueError("Unsupported mouth-discharge estimate")
        if r.get("allocation") is not None:
            raise ValueError("Distributary allocation not implemented")
    return payload


def select_registry(config):
    payload = load_registry(config.registry)
    wanted = set(config.rivers)
    if wanted - set(r["river_id"] for r in payload["rivers"]):
        raise ValueError("Unknown river selection")
    rivers = [r for r in payload["rivers"] if r["river_id"] in wanted]
    if config.stations:
        available = {s["station_id"] for r in rivers for s in r["stations"]}
        if set(config.stations) - available:
            raise ValueError("Station selection must match curated river registry")
        rivers = [
            r for r in rivers if r["stations"][0]["station_id"] in config.stations
        ]
    if config.bbox:
        w, s, e, n = config.bbox
        for r in rivers:
            if not r.get("mouths"):
                raise ValueError(
                    f"{r['river_id']}: bbox filtering requires source-backed mouth geometry; never use gauge position"
                )
        rivers = [
            r
            for r in rivers
            if any(
                w <= m["longitude"] <= e and s <= m["latitude"] <= n
                for m in r["mouths"]
            )
        ]
    if not rivers:
        raise ValueError("No selected river mouths in domain")
    return rivers


def audit(observations, rivers, start, end, summary=None):
    dates = pd.date_range(start, end)
    rows = []
    calendar = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "year": dates.year,
            "season": [(m % 12) // 3 for m in dates.month],
        }
    )
    season_names = {0: "DJF", 1: "MAM", 2: "JJA", 3: "SON"}
    for r in rivers:
        station = r["stations"][0]["station_id"]
        for metric in ["discharge_mean", "temperature_mean", "temperature_max"]:
            found = observations.loc[
                (observations.station_id == station) & (observations.metric == metric)
            ]
            for (year, season), c in calendar.groupby(["year", "season"]):
                f = found.loc[found.date.isin(c.date)]
                count = f.loc[f.value.notna() & (f.status == "valid"), "date"].nunique()
                rows.append(
                    dict(
                        river_id=r["river_id"],
                        station_id=station,
                        metric=metric,
                        year=int(year),
                        season=season_names[season],
                        expected_days=len(c),
                        observed_days=count,
                        coverage=count / len(c),
                        temporal_basis=",".join(sorted(set(f.temporal_basis)))
                        or "unavailable",
                        latest_observation=f.date.max() if len(f) else None,
                        freshness_days_at_audit=(
                            pd.Timestamp.now(tz="UTC").date()
                            - pd.Timestamp(f.date.max()).date()
                        ).days
                        if len(f)
                        else None,
                        aggregation_basis="provider mean/max; interval coverage unknown"
                        if set(f.temporal_basis) == {"provider_daily"}
                        else "supported UTC intervals"
                        if len(f)
                        else "unavailable",
                        raw_flags="|".join(sorted(set(f.raw_flags)))
                        if len(f)
                        else None,
                        status="valid"
                        if count == len(c)
                        else ("partial" if count else "unavailable"),
                        source_outcome=(summary or {})
                        .get(r["river_id"], {})
                        .get(metric, "not_requested"),
                    )
                )
    return pd.DataFrame(rows)


def registry_products(rivers, metadata):
    """Normalized registry tables, preserving source series support and provider metadata."""
    stations = []
    river_rows = []
    for river in rivers:
        relation = river["stations"][0]
        meta = metadata.get(river["river_id"], {})
        for series in meta.get("series", []) or [
            {
                "id": relation["station_id"]
                + (":HYDAT:discharge" if relation["provider"] == "wsc" else ":unknown"),
                "properties": {},
            }
        ]:
            p = series["properties"]
            stations.append(
                dict(
                    river_id=river["river_id"],
                    station_id=relation["station_id"],
                    provider=relation["provider"],
                    series_id=series["id"],
                    valid_from=relation["valid_from"],
                    valid_to=relation["valid_to"],
                    parameter_code=p.get("parameter_code"),
                    unit=p.get("unit_of_measure"),
                    statistic_id=p.get("statistic_id"),
                    record_begin=p.get("begin"),
                    record_end=p.get("end"),
                    computation_period=p.get("computation_period_identifier"),
                    rationale=relation["rationale"],
                    metadata_json=json.dumps(meta.get("station", {}), sort_keys=True),
                )
            )
        river_rows.append(
            dict(
                river_id=river["river_id"],
                name=river["name"],
                receiving_region=river["receiving_region"],
                representation=river["representation"],
                mouths_json=json.dumps(river["mouths"], sort_keys=True),
                catchment_area_km2=river["catchment_area_km2"],
                catchment_geometry=river["catchment_geometry"],
                regulation_json=json.dumps(river["regulation"]),
                allocation_json=json.dumps(river["allocation"]),
            )
        )
    return pd.DataFrame(stations), pd.DataFrame(river_rows)

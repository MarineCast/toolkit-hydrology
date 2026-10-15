"""Official USGS OGC v1, ECCC HYDAT OGC and local HYDAT adapters."""

from __future__ import annotations

import calendar
import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd

from .core import OBS_COLUMNS, empty_observations, validate_observations
from .http import ProviderError, UnsupportedVariable

USGS_ROOT = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/"
WSC_ROOT = "https://api.weather.gc.ca/collections/"
METRICS = {
    "discharge_mean": ("00060", "00003", "m3/s"),
    "temperature_mean": ("00010", "00003", "degC"),
    "temperature_max": ("00010", "00001", "degC"),
}


def convert(value, source, target):
    if value is None or value == "":
        return None
    value = float(value)
    if source == target:
        return value
    if (source, target) == ("ft^3/s", "m3/s"):
        return value * 0.028316846592
    if (source, target) == ("degF", "degC"):
        return (value - 32) * 5 / 9
    raise ValueError(f"Unsupported units {source} -> {target}")


def row(
    station,
    metric,
    date,
    value,
    unit,
    provider,
    series,
    flags,
    envelope,
    record_id,
    modified=None,
):
    return dict(
        station_id=station,
        series_id=series,
        metric=metric,
        date=str(date)[:10],
        temporal_basis="provider_daily",
        value=value,
        unit=unit,
        status="valid" if value is not None else "unavailable",
        provider=provider,
        origin="observed",
        raw_flags=json.dumps(flags, sort_keys=True),
        coverage=None,
        interval_start=None,
        interval_end=None,
        day_definition="provider day; exact boundaries unverified",
        retrieved_at=envelope["retrieved_at"],
        available_at=None,
        source_modified_at=modified,
        source_release=envelope["source_release"],
        record_id=str(record_id),
    )


def finalize(rows):
    if not rows:
        return empty_observations()
    frame = pd.DataFrame(rows, columns=OBS_COLUMNS)
    # Exact repeated records from page boundaries are harmless; conflicts are not.
    frame = frame.drop_duplicates()
    validate_observations(frame)
    return frame.sort_values(["station_id", "metric", "date", "series_id"]).reset_index(
        drop=True
    )


class USGS:
    name = "usgs"

    def __init__(self, client):
        self.client = client

    def discover(self, station):
        locations = []
        for e in self.client.pages(
            USGS_ROOT + "monitoring-locations/items",
            {"f": "json", "id": station, "limit": 100},
        ):
            locations.extend(e["body"]["features"])
        series = []
        for e in self.client.pages(
            USGS_ROOT + "time-series-metadata/items",
            {"f": "json", "monitoring_location_id": station, "limit": 1000},
        ):
            series.extend(e["body"]["features"])
        if len(locations) != 1:
            raise ProviderError(f"{station}: expected one official monitoring location")
        return {"station": locations[0], "series": series}

    def observations(self, station, metric, start, end):
        if metric not in METRICS:
            raise UnsupportedVariable(metric)
        code, stat, unit = METRICS[metric]
        rows = []
        params = {
            "f": "json",
            "monitoring_location_id": station,
            "parameter_code": code,
            "statistic_id": stat,
            "time": f"{start}/{end}",
            "limit": 10000,
        }
        for e in self.client.pages(USGS_ROOT + "daily/items", params):
            for f in e["body"]["features"]:
                p = f["properties"]
                if p["parameter_code"] != code or p["statistic_id"] != stat:
                    raise ProviderError("Unexpected parameter/statistic")
                rows.append(
                    row(
                        station,
                        metric,
                        p["time"],
                        convert(p["value"], p["unit_of_measure"], unit),
                        unit,
                        self.name,
                        p["time_series_id"],
                        {
                            "approval": p.get("approval_status"),
                            "qualifier": p.get("qualifier"),
                        },
                        e,
                        f["id"],
                        p.get("last_modified"),
                    )
                )
        return finalize(rows)

    def continuous(self, station, metric, start, end):
        if metric not in METRICS:
            raise UnsupportedVariable(metric)
        code, _, unit = METRICS[metric]
        rows = []
        params = {
            "f": "json",
            "monitoring_location_id": station,
            "parameter_code": code,
            "time": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "limit": 10000,
        }
        for e in self.client.pages(USGS_ROOT + "continuous/items", params):
            for f in e["body"]["features"]:
                p = f["properties"]
                rows.append(
                    {
                        "time": p["time"],
                        "value": convert(p["value"], p["unit_of_measure"], unit),
                        "series_id": p["time_series_id"],
                        "raw_flags": json.dumps(
                            {
                                "approval": p.get("approval_status"),
                                "qualifier": p.get("qualifier"),
                            }
                        ),
                        "retrieved_at": e["retrieved_at"],
                        "source_release": e["source_release"],
                        "available_at": None,
                    }
                )
        return pd.DataFrame(rows)


class WSC:
    name = "wsc"

    def __init__(self, client):
        self.client = client

    def discover(self, station):
        features = []
        for e in self.client.pages(
            WSC_ROOT + "hydrometric-stations/items",
            {"f": "json", "STATION_NUMBER": station, "limit": 100},
        ):
            features.extend(e["body"]["features"])
        if len(features) != 1:
            raise ProviderError(f"{station}: expected one official station")
        return {
            "station": features[0],
            "series": [],
            "series_limitation": "OGC station response does not report historical period of record; audit requested dates",
        }

    def observations(self, station, metric, start, end):
        if metric != "discharge_mean":
            raise UnsupportedVariable("WSC HYDAT does not provide water temperature")
        rows = []
        params = {
            "f": "json",
            "STATION_NUMBER": station,
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "limit": 10000,
        }
        for e in self.client.pages(WSC_ROOT + "hydrometric-daily-mean/items", params):
            for f in e["body"]["features"]:
                p = f["properties"]
                rows.append(
                    row(
                        station,
                        metric,
                        p["DATE"],
                        convert(p.get("DISCHARGE"), "m3/s", "m3/s"),
                        "m3/s",
                        self.name,
                        station + ":HYDAT:discharge",
                        {"discharge_symbol": p.get("DISCHARGE_SYMBOL_EN")},
                        e,
                        f["id"],
                    )
                )
        return finalize(rows)

    def continuous(self, station, metric, start, end):
        if metric != "discharge_mean":
            raise UnsupportedVariable("WSC real-time temperature unsupported")
        oldest = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)).date().isoformat()
        if end < oldest:
            raise UnsupportedVariable(
                "WSC real-time retention is 30 days; historical native daily cannot reconstruct UTC"
            )
        start = max(start, oldest)
        rows = []
        params = {
            "f": "json",
            "STATION_NUMBER": station,
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "limit": 10000,
        }
        for e in self.client.pages(WSC_ROOT + "hydrometric-realtime/items", params):
            for f in e["body"]["features"]:
                p = f["properties"]
                rows.append(
                    {
                        "time": p["DATETIME"],
                        "value": convert(p.get("DISCHARGE"), "m3/s", "m3/s"),
                        "series_id": station + ":realtime:discharge",
                        "raw_flags": json.dumps(
                            {
                                "approval": "Provisional",
                                "symbol": p.get("DISCHARGE_SYMBOL_EN"),
                            }
                        ),
                        "retrieved_at": e["retrieved_at"],
                        "source_release": e["source_release"],
                        "available_at": None,
                    }
                )
        return pd.DataFrame(rows)


class HYDAT:
    """Read-only local official SQLite snapshot; never downloads the database."""

    name = "hydat"

    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        h = hashlib.sha256()
        with self.path.open("rb") as f:
            for b in iter(lambda: f.read(1024 * 1024), b""):
                h.update(b)
        self.release = h.hexdigest()

    def connection(self):
        return sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)

    def discover(self, station):
        with self.connection() as con:
            records = pd.read_sql_query(
                "SELECT * FROM STATIONS WHERE STATION_NUMBER=?", con, params=[station]
            ).to_dict("records")
        if len(records) != 1:
            raise ProviderError(f"{station}: missing HYDAT station")
        return {
            "station": {"properties": records[0]},
            "series": [],
            "source_release": self.release,
        }

    def observations(self, station, metric, start, end):
        if metric != "discharge_mean":
            raise UnsupportedVariable("HYDAT temperature unsupported")
        with self.connection() as con:
            data = pd.read_sql_query(
                "SELECT * FROM DLY_FLOWS WHERE STATION_NUMBER=? AND YEAR BETWEEN ? AND ?",
                con,
                params=[station, int(start[:4]), int(end[:4])],
            )
        envelope = {
            "retrieved_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "source_release": self.release,
        }
        rows = []
        for p in data.to_dict("records"):
            for day in range(1, calendar.monthrange(p["YEAR"], p["MONTH"])[1] + 1):
                d = f"{p['YEAR']:04d}-{p['MONTH']:02d}-{day:02d}"
                if start <= d <= end:
                    v = p.get(f"FLOW{day}")
                    v = None if pd.isna(v) else float(v)
                    rows.append(
                        row(
                            station,
                            metric,
                            d,
                            v,
                            "m3/s",
                            self.name,
                            station + ":HYDAT:discharge",
                            {"discharge_symbol": p.get(f"FLOW_SYMBOL{day}")},
                            envelope,
                            station + "." + d,
                        )
                    )
        return finalize(rows)

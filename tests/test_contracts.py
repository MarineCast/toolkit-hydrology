"""Synthetic offline fixtures only; no production observations."""

import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

from hydrology.core import Config, eligible, validate_observations
from hydrology.features import build_features, fit_climatology
from hydrology.http import (
    AuthenticationError,
    Client,
    ProviderError,
    UnsupportedVariable,
)
from hydrology.providers import HYDAT, USGS, WSC, convert, finalize, row
from hydrology.registry import load_registry, select_registry
from hydrology.temporal import aggregate_utc


def native(n=40, start="2020-01-01", value=5.0):
    rows = [
        row(
            "test",
            "discharge_mean",
            d.date(),
            value,
            "m3/s",
            "fixture",
            "s",
            {},
            {"retrieved_at": "2026-01-01T00:00:00Z", "source_release": "fixture"},
            str(d),
        )
        for d in pd.date_range(start, periods=n)
    ]
    f = finalize(rows)
    f["river_id"] = "r"
    return f


@pytest.mark.parametrize(
    "source,target,value,expected",
    [
        ("ft^3/s", "m3/s", 1, 0.028316846592),
        ("degF", "degC", 32, 0),
        ("degF", "degC", 212, 100),
        ("m3/s", "m3/s", 0, 0),
        ("m3/s", "m3/s", -2, -2),
        ("degC", "degC", None, None),
    ],
)
def test_units(source, target, value, expected):
    v = convert(value, source, target)
    assert v == pytest.approx(expected) if expected is not None else v is None


def test_units_reject():
    with pytest.raises(ValueError):
        convert(1, "ft", "m3/s")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"bbox": (1, 2, 0, 3)},
        {"h3_res": 16},
        {"start_date": "2020-02-31"},
        {"start_date": "2020-01-02", "end_date": "2020-01-01"},
        {"as_of": "2020-01-01"},
        {"workers": 5},
    ],
)
def test_config_invalid(kwargs):
    with pytest.raises(ValueError):
        Config(**kwargs)


def test_windows_and_future_invariance():
    f = native()
    f.loc[10, "value"] = np.nan
    f.loc[10, "status"] = "unavailable"
    a = build_features(f)
    b = build_features(pd.concat([f, native(10, "2020-02-10", 100)]))
    pd.testing.assert_frame_equal(
        a, b.loc[b.date <= "2020-02-09"].reset_index(drop=True)
    )
    seven = a.loc[a.metric == "discharge_mean_7d"].set_index("date").value
    assert pd.isna(seven["2020-01-17"])
    assert seven["2020-01-18"] == 5
    assert a.loc[a.metric == "discharge_seasonal_anomaly", "value"].isna().all()


def test_missing_dates_reindexed():
    f = native().drop(index=10)
    features = build_features(f)
    assert (
        features.loc[
            (features.date == "2020-01-11") & (features.metric == "discharge_mean"),
            "value",
        ]
        .isna()
        .all()
    )
    assert (
        features.loc[
            (features.date == "2020-01-15") & (features.metric == "discharge_mean_7d"),
            "value",
        ]
        .isna()
        .all()
    )


def test_baseline_cutoff_and_leap():
    f = native(365 * 4, "2016-01-01")
    baseline = fit_climatology(f, "2018-12-31")
    changed = f.copy()
    changed.loc[changed.date > "2018-12-31", "value"] = 10000
    assert baseline == fit_climatology(changed, "2018-12-31")
    features = build_features(f, climatology=baseline)
    a = features.loc[features.metric == "discharge_seasonal_anomaly"]
    assert a.loc[a.date <= "2018-12-31", "value"].isna().all()
    assert (a.loc[a.date > "2018-12-31", "value"] == 0).all()
    from hydrology.features import season_day

    assert season_day("2020-02-29") == season_day("2020-02-28")
    assert not fit_climatology(native(), "2020-02-09")["groups"][
        "r|test|discharge_mean|provider_daily"
    ]


def test_events_missing_and_zero():
    f = native(8, value=0)
    f["value"] = [20, 0, 0, np.nan, 0, 20, 1200, 1100]
    f.loc[3, "status"] = "unavailable"
    out = build_features(f, low_threshold=10, pulse_threshold=1000)
    lows = out.loc[out.metric == "low_flow_duration"].value.tolist()
    assert lows[:3] == [0, 1, 2]
    assert pd.isna(lows[4])
    assert lows[5] == 0
    pulse = out.loc[out.metric == "days_since_flow_pulse"].value.tolist()
    assert pd.isna(pulse[5])
    assert pulse[6:] == [0, 1]


def test_signed_flow_not_clipped():
    out = build_features(native(value=-3))
    assert set(out.loc[out.metric == "discharge_mean_7d", "value"].dropna()) == {-3}


def test_as_of_unknown_and_known_late():
    f = native(3)
    assert eligible(f, as_of="2020-01-10T00:00:00Z").empty
    f["available_at"] = ["2020-01-02T00:00:00Z", "2021-01-01T00:00:00Z", None]
    assert len(eligible(f, as_of="2020-01-10T00:00:00Z")) == 1


def test_duplicate_conflict():
    f = native(1)
    with pytest.raises(ValueError):
        validate_observations(pd.concat([f, f]))


def samples():
    return pd.DataFrame(
        {
            "time": pd.date_range("2020-03-08", periods=96, freq="15min", tz="UTC"),
            "value": 2.0,
            "series_id": "s",
            "raw_flags": "Approved",
            "source_release": "fixture",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "available_at": None,
        }
    )


def test_utc_hold_and_gaps():
    f = samples()
    a = aggregate_utc(
        f, "s", "temperature_max", "2020-03-08", "2020-03-08", max_hold_seconds=900
    )
    assert a.coverage.iloc[0] == 1
    assert a.value.iloc[0] == 2
    b = aggregate_utc(
        f.iloc[::4],
        "s",
        "temperature_max",
        "2020-03-08",
        "2020-03-08",
        max_hold_seconds=900,
    )
    assert b.coverage.iloc[0] == 0.25
    assert b.value.isna().all()


def test_dst_offsets_and_duplicate_samples():
    f = samples()
    f["time"] = f.time.dt.tz_convert("America/Los_Angeles")
    assert (
        aggregate_utc(
            f, "s", "discharge_mean", "2020-03-08", "2020-03-08", max_hold_seconds=900
        ).coverage.iloc[0]
        == 1
    )
    dup = pd.concat([f, f.iloc[:1].assign(value=9)])
    with pytest.raises(ValueError):
        aggregate_utc(dup, "s", "discharge_mean", "2020-03-08", "2020-03-08")
    f["time"] = f.time.dt.tz_localize(None)
    with pytest.raises(ValueError):
        aggregate_utc(f, "s", "discharge_mean", "2020-03-08", "2020-03-08")


def test_registry_requires_mouth_not_gauge():
    assert len(load_registry()["rivers"]) == 6
    r = select_registry(Config(bbox=(-123.3, 49, -123, 49.2), rivers=("fraser",)))
    assert (
        r[0]["stations"][0]["geometry"]["coordinates"][0] > -123
    )  # upstream gauge is outside marine domain


class Response:
    def __init__(self, body, status=200):
        self.body = body
        self.status_code = status
        self.headers = {"Retry-After": "0"}

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def get(self, *a, **kw):
        self.calls += 1
        return next(self.responses)


def test_pagination_retry_and_resume(tmp_path):
    first = {
        "features": [{"id": "a"}],
        "links": [{"rel": "next", "href": "https://example.test/next"}],
    }
    last = {"features": []}
    session = Session([Response({}, 429), Response(first), Response(last)])
    config = Config(cache=str(tmp_path), rate_seconds=0)
    client = Client(config, session)
    assert len(list(client.pages("https://example.test/first"))) == 2
    assert session.calls == 3
    assert (
        len(list(Client(config, Session([])).pages("https://example.test/first"))) == 2
    )
    assert len(list((tmp_path / "snapshots").glob("*.json"))) == 2


def test_http_failure_not_no_data(tmp_path):
    for code, error in [(403, AuthenticationError), (500, ProviderError)]:
        c = Client(
            Config(cache=str(tmp_path), rate_seconds=0, retries=0),
            Session([Response({}, code)]),
        )
        with pytest.raises(error):
            c.get("https://example.test/a")


def test_provider_unsupported():
    with pytest.raises(UnsupportedVariable):
        WSC(None).observations("x", "temperature_mean", "2020-01-01", "2020-01-02")
    with pytest.raises(UnsupportedVariable):
        USGS(None).observations("x", "level", "2020-01-01", "2020-01-02")


def test_local_hydat(tmp_path):
    path = tmp_path / "Hydat.sqlite3"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE STATIONS (STATION_NUMBER TEXT)")
        con.execute("INSERT INTO STATIONS VALUES ('x')")
        con.execute(
            "CREATE TABLE DLY_FLOWS (STATION_NUMBER TEXT,YEAR INTEGER,MONTH INTEGER,FLOW1 REAL,FLOW2 REAL,FLOW_SYMBOL1 TEXT)"
        )
        con.execute("INSERT INTO DLY_FLOWS VALUES ('x',2020,1,0,2,'A')")
    adapter = HYDAT(path)
    assert adapter.discover("x")["station"]["properties"]["STATION_NUMBER"] == "x"
    f = adapter.observations("x", "discharge_mean", "2020-01-01", "2020-01-02")
    assert f.value.tolist() == [0, 2]
    assert set(f.temporal_basis) == {"provider_daily"}


def test_climatology_tamper_rejected():
    f = native()
    b = fit_climatology(f, "2020-02-01")
    b["training_cutoff"] = "2019-01-01"
    with pytest.raises(ValueError, match="checksum"):
        build_features(f, climatology=b)


def test_no_observations_is_empty_not_failure(tmp_path):
    client = Client(
        Config(cache=str(tmp_path), rate_seconds=0),
        Session([Response({"features": []})]),
    )
    f = USGS(client).observations(
        "USGS-test", "discharge_mean", "2020-01-01", "2020-01-02"
    )
    assert f.empty


def test_registry_nested_gauges_rejected(tmp_path):
    r = load_registry()
    r["rivers"][0]["stations"].append(r["rivers"][0]["stations"][0])
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(r))
    with pytest.raises(ValueError, match="nested"):
        load_registry(path)


def test_shared_config_precedence(tmp_path, monkeypatch):
    shared = tmp_path / "shared.json"
    shared.write_text(json.dumps({"h3_res": 5, "workers": 2}))
    supplied = tmp_path / "supplied.json"
    supplied.write_text(json.dumps({"h3_res": 7}))
    monkeypatch.setenv("MARINECAST_HYDROLOGY_CONFIG", str(shared))
    c = Config.load(supplied, h3_res=8)
    assert c.h3_res == 8
    assert c.workers == 2

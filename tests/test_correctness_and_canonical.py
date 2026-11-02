"""Production repair regressions: synthetic fixtures only, never live acquisition."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydrology import pipeline
from hydrology.core import Config, digest, validate_observations
from hydrology.features import build_features, fit_climatology
from hydrology.http import Client, ProviderError, RequestDeferred
from hydrology.pipelines import acquisition
from hydrology.pipelines import publication as canonical
from hydrology.providers import convert, finalize, row
from hydrology.temporal import aggregate_utc


def config(tmp_path, **kwargs):
    return Config(
        start_date="2023-01-01",
        end_date="2023-01-07",
        rivers=("skagit",),
        cache=str(tmp_path / "cache"),
        output=str(tmp_path / "legacy"),
        product_output=str(tmp_path / "Hydrology"),
        **kwargs,
    )


def observation(
    day="2023-01-01", value=1, series="a", station="USGS-12200500", **kwargs
):
    return dict(
        row(
            station,
            "discharge_mean",
            day,
            value,
            "m3/s",
            "fixture",
            series,
            {},
            {"retrieved_at": "2026-01-01T00:00:00Z", "source_release": "input"},
            day + series,
        ),
        **kwargs,
    )


def acquired(config, metrics):
    records = [
        observation(
            day=day.date().isoformat(),
            station=r["stations"][0]["station_id"],
            value=i + 1,
            series=r["river_id"],
        )
        for i, r in enumerate(pipeline.select_registry(config))
        for day in pd.date_range("2022-12-02", "2023-01-07")
    ]
    return (
        finalize(records),
        {},
        {
            r["river_id"]: {"discharge_mean": "observed"}
            for r in pipeline.select_registry(config)
        },
        {},
    )


def test_metadata_only_change_invalidates_saved_release(tmp_path, monkeypatch):
    f = finalize([observation(series="a", value=1), observation(series="b", value=9)])
    primary = ["a"]

    def fake(config, metrics):
        return (
            f,
            {
                "skagit": {
                    "series": [
                        {
                            "id": s,
                            "properties": {
                                "primary": "Primary" if s == primary[0] else "Secondary"
                            },
                        }
                        for s in ["a", "b"]
                    ]
                }
            },
            {"skagit": {"discharge_mean": "observed"}},
            {},
        )

    monkeypatch.setattr(acquisition, "acquire", fake)
    c = config(tmp_path)
    r1, _ = pipeline.build(c)
    primary[0] = "b"
    r2, _ = pipeline.build(c)
    assert r1 != r2
    assert pd.read_parquet(r1 / "river_conditions.parquet").value.dropna().tolist() == [
        1
    ]
    assert pd.read_parquet(r2 / "river_conditions.parquet").value.dropna().tolist() == [
        9
    ]


@pytest.mark.parametrize(
    "damage", ["body", "url", "time", "missing_snapshot", "snapshot_body", "malformed"]
)
def test_verified_cached_envelopes_fail_closed(tmp_path, damage):
    url = "https://example.test/items"
    body = {"features": []}
    e = {
        "url": url,
        "retrieved_at": "2026-01-01T00:00:00Z",
        "source_release": digest(body),
        "body": body,
    }
    c = config(tmp_path)
    req = Path(c.cache) / "requests" / f"{digest(url)}.json"
    snap = Path(c.cache) / "snapshots" / f"{digest(body)}.json"
    req.parent.mkdir(parents=True)
    snap.parent.mkdir()
    req.write_text(json.dumps(e))
    snap.write_text(json.dumps(e))
    session = type(
        "NoNetwork",
        (),
        {"get": lambda *a, **kw: pytest.fail("No cache corruption fallback network")},
    )()
    assert Client(c, session).get(url)["body"] == body
    if damage == "body":
        e["body"] = {"features": [{"id": "corrupted"}]}
    if damage == "url":
        e["url"] += "?wrong"
    if damage == "time":
        e["retrieved_at"] = "2026-01-01"
    if damage == "missing_snapshot":
        snap.unlink()
    if damage == "snapshot_body":
        snap.write_text(json.dumps(dict(e, body={"features": [1]})))
    req.write_text("not json" if damage == "malformed" else json.dumps(e))
    with pytest.raises(ProviderError):
        Client(c, session).get(url)
    assert req.exists()  # no destructive cache cleanup


@pytest.mark.parametrize("failure", ["failed", "deferred"])
def test_completed_blocks_retained_ledger_and_resumed(tmp_path, monkeypatch, failure):
    fail = [True]

    class Adapter:
        def __init__(self, client):
            pass

        def discover(self, station):
            return {}

        def observations(self, station, metric, start, end):
            if start == "2023-01-01" and fail[0]:
                if failure == "deferred":
                    raise RequestDeferred(
                        "example.test", "https://example.test/x", 1, "fixture"
                    )
                raise ProviderError("later month failed")
            return finalize([observation(day=start)])

    monkeypatch.setattr(acquisition, "USGS", Adapter)
    c = config(tmp_path)
    f, _, outcomes, network = pipeline.acquire(c, metrics=("discharge_mean",))
    assert f.date.tolist() == ["2022-12-02"]
    blocks = [e for e in network["block_ledger"] if e["metric"] == "discharge_mean"]
    assert [e["state"] for e in blocks] == ["completed", failure]
    assert outcomes["skagit"]["discharge_mean"].startswith(
        "failure:" if failure == "failed" else "deferred:"
    )
    assert json.loads(Path(network["block_ledger_path"]).read_text())["blocks"]
    fail[0] = False
    f, _, _, network = pipeline.acquire(c, metrics=("discharge_mean",))
    blocks = [e for e in network["block_ledger"] if e["metric"] == "discharge_mean"]
    assert len(f) == 2
    assert all(e["state"] == "completed" for e in blocks)
    assert blocks[1]["previous_state"] == failure


def test_dense_calendar_partial_coverage_and_truthful_freshness(tmp_path, monkeypatch):
    monkeypatch.setattr(
        acquisition,
        "acquire",
        lambda *args: (
            finalize([observation()]),
            {},
            {"skagit": {"discharge_mean": "observed"}},
            {},
        ),
    )
    r, m = pipeline.build(config(tmp_path))
    assert m["execution_complete"] and not m["data_eligible"] and not m["complete"]
    f = pd.read_parquet(r / "river_conditions.parquet")
    assert len(f) == 7 * 3
    assert f.query("metric == 'discharge_mean'").value.notna().sum() == 1
    assert f.query("date == '2023-01-07'").value.isna().all()
    assert m["eligibility"]["skagit"]["metrics"]["discharge_mean"]["coverage"] == 1 / 7
    assert (
        m["eligibility"]["skagit"]["metrics"]["discharge_mean"]["latest_eligible_date"]
        == "2023-01-01"
    )
    assert len(pd.read_parquet(r / "river_features.parquet")) == 7 * 13
    a = pd.read_parquet(r / "coverage.parquet").query("metric == 'discharge_mean'")
    assert a.latest_observation.tolist() == ["2023-01-01"]


@pytest.mark.parametrize("value", [np.inf, -np.inf, "inf", "NaN"])
def test_nonfinite_provider_rejected(value):
    with pytest.raises(ValueError, match="finite"):
        convert(value, "m3/s", "m3/s")


@pytest.mark.parametrize("where", ["observations", "features", "fit", "utc"])
def test_nonfinite_inputs_rejected_at_public_boundaries(where):
    f = pd.DataFrame([observation(value=np.inf)])
    f["river_id"] = "skagit"
    with pytest.raises(ValueError, match="finite"):
        if where == "observations":
            validate_observations(f)
        if where == "features":
            build_features(f)
        if where == "fit":
            fit_climatology(f, "2023-01-01")
        if where == "utc":
            sample = pd.DataFrame(
                dict(
                    time=["2023-01-01T00:00:00Z"],
                    value=[np.inf],
                    series_id=["s"],
                    raw_flags=["Approved"],
                )
            )
            aggregate_utc(sample, "s", "discharge_mean", "2023-01-01", "2023-01-01")


def test_signed_zero_and_missing_values_preserved():
    f = finalize(
        [
            observation(day=f"2023-01-0{i + 1}", value=v)
            for i, v in enumerate([-2, 0, None])
        ]
    )
    assert f.value.iloc[:2].tolist() == [-2, 0]
    assert pd.isna(f.value.iloc[2])


def test_canonical_idempotent_schema_provenance_and_unknown_days(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    c = config(tmp_path)
    target, _ = canonical.publish_rivers(c)
    assert target.is_dir() and not target.is_symlink()
    first = target.resolve()
    canonical.validate_product(target)
    m = json.loads((target / "skagit/manifest.json").read_text())
    assert m["complete"] and m["data_eligible"] and m["execution_complete"]
    assert m["source_snapshot_hashes"] == ["input"]
    assert m["runtime"]["dependencies"]["pandas"]
    f = pd.read_parquet(target / "skagit/conditions.parquet")
    assert set(f.temporal_basis) == {"provider_daily"}
    assert f.interval_start.isna().all()
    assert f.query("metric == 'temperature_mean'").value.isna().all()
    assert all(
        json.loads(x)[0]["source_release"] == "input"
        for x in f.query("metric == 'discharge_mean'").source_references
    )
    canonical.publish_rivers(c)
    assert target.resolve() == first
    assert not list(canonical._paths(target)[1].glob("snapshot-*"))


def test_writer_unknown_empty_days_and_as_of_are_not_fabricated(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    c = replace(config(tmp_path), as_of="2023-01-08T00:00:00Z")
    target, _ = canonical.publish_rivers(c)
    f = pd.read_parquet(target / "skagit/conditions.parquet")
    assert len(f) == 21 and f.value.isna().all()
    assert set(f.query("metric == 'discharge_mean'").reason) == {
        "availability_not_proven_by_as_of"
    }
    assert not json.loads((target / "skagit/manifest.json").read_text())[
        "data_eligible"
    ]


def test_no_cross_river_contamination_and_unselected_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    c = replace(config(tmp_path), rivers=("skagit", "nooksack"))
    target, _ = canonical.publish_rivers(c)
    for rid, value in [("skagit", 1), ("nooksack", 2)]:
        f = pd.read_parquet(target / rid / "conditions.parquet")
        assert set(f.river_id) == {rid}
        assert set(f.value.dropna()) == {value}
    untouched = (target / "nooksack/manifest.json").read_bytes()
    canonical.publish_rivers(replace(c, rivers=("skagit",), refresh=True))
    assert (target / "nooksack/manifest.json").read_bytes() == untouched
    assert not list(canonical._paths(target)[1].glob("snapshot-*"))
    canonical.validate_product(target)


@pytest.mark.parametrize(
    "failure_point", ["write", "validate", "promote", "bytes", "rows"]
)
def test_failed_publication_preserves_previous_snapshot(
    tmp_path, monkeypatch, failure_point
):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    c = config(tmp_path)
    target, _ = canonical.publish_rivers(c)
    old = target.resolve()
    before = (target / "catalog.json").read_bytes()
    c = replace(c, refresh=True)
    if failure_point == "write":
        monkeypatch.setattr(
            canonical,
            "_parquet",
            lambda *a: (_ for _ in ()).throw(ValueError("injected")),
        )
    if failure_point == "validate":
        original = canonical._validate_snapshot
        monkeypatch.setattr(
            canonical,
            "_validate_snapshot",
            lambda root: (
                original(root)
                if root == old
                else (_ for _ in ()).throw(ValueError("injected"))
            ),
        )
    if failure_point == "promote":
        original = canonical.os.replace
        monkeypatch.setattr(
            canonical.os,
            "replace",
            lambda src, dst: (
                (_ for _ in ()).throw(ValueError("injected"))
                if Path(dst) == target and Path(src).name.startswith("snapshot-")
                else original(src, dst)
            ),
        )
    if failure_point == "bytes":
        c = replace(c, publication_max_bytes=10)
    if failure_point == "rows":
        c = replace(c, publication_max_rows=10)
    with pytest.raises(ValueError):
        canonical.publish_rivers(c)
    assert target.resolve() == old and (target / "catalog.json").read_bytes() == before
    assert not list(canonical._paths(target)[1].glob("snapshot-*"))


def test_unowned_destination_and_corruption_refused_before_acquisition(
    tmp_path, monkeypatch
):
    c = config(tmp_path)
    target = Path(c.product_output)
    target.mkdir()
    (target / "keep").write_text("user")
    monkeypatch.setattr(
        pipeline, "prepare", lambda *a: pytest.fail("must refuse before acquisition")
    )
    with pytest.raises(ValueError, match="unowned"):
        canonical.publish_rivers(c)
    assert (target / "keep").read_text() == "user"


def test_saved_product_tampering_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    target, _ = canonical.publish_rivers(config(tmp_path))
    (target / "skagit/metadata.json").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        canonical.validate_product(target)


def test_actual_verified_page_cache_resumes_completed_block(tmp_path, monkeypatch):
    from test_http_cooldowns import Response, Session

    c = replace(config(tmp_path), retries=0, rate_seconds=0)
    sessions = iter(
        [
            Session(Response(body={"features": [{"value": 1}]}), Response(500)),
            Session(Response(body={"features": [{"value": 2}]})),
        ]
    )
    calls = []

    def client(cfg):
        session = next(sessions)
        calls.append(session)
        return Client(cfg, session)

    class Adapter:
        def __init__(self, client):
            self.client = client

        def discover(self, station):
            return {}

        def observations(self, station, metric, start, end):
            e = self.client.get("https://example.test/" + start)
            return finalize(
                [
                    observation(
                        day=start,
                        value=e["body"]["features"][0]["value"],
                        source_release=e["source_release"],
                    )
                ]
            )

    monkeypatch.setattr(acquisition, "USGS", Adapter)
    monkeypatch.setattr(acquisition, "Client", client)
    first, _, _, _ = pipeline.acquire(c, metrics=("discharge_mean",))
    assert len(first) == 1
    # Remove the expired synthetic 500 backoff to keep this test clock independent.
    for path in (Path(c.cache) / "cooldowns").glob("*.json"):
        path.unlink()
    second, _, _, network = pipeline.acquire(c, metrics=("discharge_mean",))
    assert len(second) == 2 and network["cache_hits"] == 1
    assert len(calls[1].calls) == 1
    assert len(network["source_requests_by_river"]["skagit"]) == 2


def test_unsupported_empty_and_not_attempted_ledger_states(tmp_path, monkeypatch):
    from hydrology.http import UnsupportedVariable

    class Adapter:
        def __init__(self, client):
            pass

        def discover(self, station):
            return {}

        def observations(self, station, metric, start, end):
            if metric == "temperature_mean":
                raise UnsupportedVariable("fixture")
            return finalize([])

    monkeypatch.setattr(acquisition, "USGS", Adapter)
    _, _, outcomes, network = pipeline.acquire(
        config(tmp_path), metrics=("discharge_mean", "temperature_mean")
    )
    states = {e["metric"]: e["state"] for e in network["block_ledger"]}
    assert (
        states["temperature_mean"] == "unsupported"
        and states["discharge_mean"] == "empty"
    )
    assert outcomes["skagit"]["temperature_mean"].startswith("unsupported:")


def test_true_utc_schema_and_native_relabel_rejected(tmp_path, monkeypatch):
    def utc(config, metrics):
        f, meta, out, network = acquired(config, metrics)
        f.temporal_basis = "utc_daily"
        f.interval_start = pd.to_datetime(f.date, utc=True).astype(str)
        f.interval_end = (
            pd.to_datetime(f.date, utc=True) + pd.Timedelta(days=1)
        ).astype(str)
        f.coverage = 1.0
        return f, meta, out, network

    monkeypatch.setattr(acquisition, "acquire", utc)
    c = replace(config(tmp_path), temporal_requirement="utc_daily")
    target, _ = canonical.publish_rivers(c)
    f = pd.read_parquet(target / "skagit/conditions.parquet")
    assert set(f.temporal_basis) == {"utc_daily"} and f.interval_start.notna().all()
    assert set(f.query("metric == 'discharge_mean'").coverage) == {1}
    monkeypatch.setattr(acquisition, "acquire", acquired)
    with pytest.raises(ValueError, match="temporal basis"):
        canonical.publish_rivers(c)


def test_reader_lock_refuses_concurrent_promotion(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    c = config(tmp_path)
    target, _ = canonical.publish_rivers(c)
    with canonical.product_snapshot(target) as root:
        with pytest.raises(ValueError, match="lock"):
            canonical.publish_rivers(c)
        assert root.exists()


def test_feature_cutoff_and_baseline_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    baseline = fit_climatology(
        pd.DataFrame([{**observation(), "river_id": "skagit"}]),
        "2023-01-01",
        min_samples=1,
        min_years=1,
    )
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(baseline))
    c = replace(config(tmp_path), climatology=str(path))
    target, _ = canonical.publish_rivers(c)
    f = pd.read_parquet(target / "skagit/features.parquet")
    anomaly = f.query("metric == 'discharge_seasonal_anomaly'")
    assert pd.isna(anomaly.iloc[0].value) and anomaly.iloc[1:].value.notna().all()
    metadata = json.loads((target / "skagit/metadata.json").read_text())
    assert metadata["climatology"] == baseline


def test_missing_discharge_failure_does_not_block_optional_data_publication(
    tmp_path, monkeypatch
):
    def partial(c, metrics):
        f, meta, outcomes, network = acquired(c, metrics)
        f = f.iloc[:0]
        outcomes["skagit"] = {
            "discharge_mean": "deferred: fixture",
            "temperature_mean": "unsupported: fixture",
        }
        return f, meta, outcomes, network

    monkeypatch.setattr(acquisition, "acquire", partial)
    target, _ = canonical.publish_rivers(
        config(tmp_path), metrics=("discharge_mean", "temperature_mean")
    )
    m = json.loads((target / "skagit/manifest.json").read_text())
    assert not m["execution_complete"] and not m["data_eligible"] and not m["complete"]
    f = pd.read_parquet(target / "skagit/conditions.parquet")
    assert f.value.isna().all() and len(f) == 21
    assert set(f.query("metric == 'temperature_mean'").reason) == {"unsupported"}


def test_idempotent_retry_cleans_only_owned_crash_stages(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    c = config(tmp_path)
    target, _ = canonical.publish_rivers(c)
    store = canonical._paths(target)[1]
    crashed = store / "snapshot-crashed"
    crashed.mkdir()
    (crashed / "owner.json").write_bytes((store / "owner.json").read_bytes())
    unknown = store / "snapshot-user"
    unknown.mkdir()
    (unknown / "keep").write_text("preserve")
    original = target.resolve()
    canonical.publish_rivers(c)
    assert target.resolve() == original and not crashed.exists()
    assert (unknown / "keep").read_text() == "preserve"


def test_offline_mode_never_dispatches_cache_miss(tmp_path):
    session = type(
        "NoNetwork",
        (),
        {"get": lambda *args, **kwargs: pytest.fail("offline network dispatch")},
    )()
    with pytest.raises(ProviderError, match="Offline mode"):
        Client(replace(config(tmp_path), offline=True), session).get(
            "https://example.test/missing"
        )


def test_cli_publish_dry_run_reports_destination_and_discharge_default(
    tmp_path, capsys
):
    from hydrology.cli import main

    assert (
        main(
            [
                "publish",
                "--rivers",
                "skagit",
                "--start-date",
                "2023-01-01",
                "--end-date",
                "2023-01-07",
                "--product-output",
                str(tmp_path / "Hydrology"),
                "--dry-run",
            ]
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    assert plan["metrics"] == ["discharge_mean"]
    assert str(tmp_path / "Hydrology") in plan["writes"]
    assert not (tmp_path / "Hydrology").exists()


def test_cli_publish_and_validate_product(tmp_path, monkeypatch, capsys):
    from hydrology.cli import main

    monkeypatch.setattr(acquisition, "acquire", acquired)
    target = str(tmp_path / "Hydrology")
    args = [
        "publish",
        "--rivers",
        "skagit",
        "--start-date",
        "2023-01-01",
        "--end-date",
        "2023-01-07",
        "--product-output",
        target,
        "--cache",
        str(tmp_path / "cache"),
        "--offline",
    ]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["product_path"] == target
    assert main(["validate-product", target]) == 0
    assert (
        json.loads(capsys.readouterr().out)["schema_version"] == "hydrology-per-river-1"
    )


def test_later_block_failure_reason_does_not_poison_completed_block_days(
    tmp_path, monkeypatch
):
    def sparse(c, metrics):
        f = finalize([observation(day="2023-01-01")])
        ledger = [
            dict(
                river_id="skagit",
                metric="discharge_mean",
                start="2023-01-01",
                end="2023-01-03",
                state="completed",
            ),
            dict(
                river_id="skagit",
                metric="discharge_mean",
                start="2023-01-04",
                end="2023-01-07",
                state="failed",
            ),
        ]
        return (
            f,
            {},
            {"skagit": {"discharge_mean": "failure: later block"}},
            {"block_ledger": ledger},
        )

    monkeypatch.setattr(acquisition, "acquire", sparse)
    prepared = pipeline.prepare(config(tmp_path), ("discharge_mean",))
    f = prepared["conditions"].query("metric == 'discharge_mean'").set_index("date")
    assert f.loc["2023-01-02", "reason"] == "no_observation"
    assert f.loc["2023-01-04", "reason"] == "failed"


def test_retry_wait_diagnostics_do_not_change_scientific_identity(
    tmp_path, monkeypatch
):
    detail = ["deferred: host until 13:00; remaining wait budget below required 49s"]

    def same_inputs(config, metrics):
        frame, metadata, outcomes, network = acquired(config, metrics)
        outcomes["skagit"]["discharge_mean"] = detail[0]
        return frame, metadata, outcomes, network

    monkeypatch.setattr(acquisition, "acquire", same_inputs)
    c = config(tmp_path)
    first, _ = pipeline.build(c)
    before = (first / "manifest.json").read_bytes()
    detail[0] = "deferred: host until 13:00; remaining wait budget below required 43.5s"
    second, _ = pipeline.build(c)
    assert first == second
    assert (second / "manifest.json").read_bytes() == before
    detail[0] = "failure: different execution outcome"
    third, _ = pipeline.build(c)
    assert third != first

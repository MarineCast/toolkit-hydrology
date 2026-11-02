"""River curation and non-destructive publication acceptance with offline sources."""

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from test_correctness_and_canonical import acquired, config, observation

from hydrology.pipelines import acquisition, publication
from hydrology.utils.influence import validate_outlet_bindings
from hydrology.utils.providers import finalize
from hydrology.utils.publication_guard import (
    CoverageRegressionError,
    check_observations,
)
from hydrology.utils.registry import load_registry


def test_annual_native_request_blocks_cover_same_dates_and_bound_page_size(tmp_path):
    c = replace(
        config(tmp_path),
        start_date="2009-01-01",
        end_date="2026-10-15",
        rivers=tuple(NEW),
        acquisition_block_months=12,
    )
    planned = acquisition.plan(c)
    blocks = planned["blocks"]
    assert len(blocks) == 18
    dates = [day for a, b in blocks for day in pd.date_range(a, b)]
    assert dates == list(pd.date_range("2008-12-02", "2026-10-15"))
    assert max(len(pd.date_range(a, b)) for a, b in blocks) <= 366
    assert 4 * (len(blocks) + 2) == 80
    assert acquisition.plan(replace(c, acquisition_block_months=1))["blocks"] == list(
        acquisition.date_blocks("2008-12-02", "2026-10-15")
    )


@pytest.mark.parametrize("months", [0, 241, True, 1.5])
def test_acquisition_block_budget_rejects_invalid_or_utc_scope(tmp_path, months):
    with pytest.raises(ValueError, match="acquisition_block_months"):
        replace(config(tmp_path), acquisition_block_months=months)
    with pytest.raises(ValueError, match="provider-daily"):
        replace(
            config(tmp_path),
            acquisition_block_months=12,
            temporal_requirement="utc_daily",
        )


NEW = {
    "puyallup": "USGS-12101500",
    "elwha": "USGS-12045500",
    "skokomish": "USGS-12061500",
    "queets": "USGS-12040500",
}
OLD = ("fraser", "skagit", "snohomish", "nooksack", "cowichan", "columbia")


def tree_bytes(path):
    return {
        str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()
    }


def test_curated_station_and_outlet_identities():
    rows = {r["river_id"]: r for r in load_registry()["rivers"]}
    assert set(rows) == set(OLD) | set(NEW)
    for rid, sid in NEW.items():
        river = rows[rid]
        assert len(river["stations"]) == 1 and river["stations"][0]["station_id"] == sid
        assert set(river["stations"][0]["unsupported_metrics"]) == {
            "temperature_mean",
            "temperature_max",
        }
        assert river["allocation"] is None
        assert river["representation"] == "representative_gauge_proxy"
        assert river["research_outlet_binding"]["model_eligible"] is False
        assert [
            river["mouths"][0]["longitude"],
            river["mouths"][0]["latitude"],
        ] != river["stations"][0]["geometry"]["coordinates"]
    pilot = json.loads((Path(__file__).parents[1] / "config/pilot.json").read_text())
    assert set(pilot["rivers"]) == set(OLD)


@pytest.mark.parametrize(
    "damage", ["identity", "duplicate", "attachment", "eligibility"]
)
def test_outlet_curation_fails_closed(damage):
    expected = next(r for r in load_registry()["rivers"] if r["river_id"] == "queets")[
        "research_outlet_binding"
    ]
    config_row = {
        "name": expected["name"],
        "outlet_id": expected["outlet_id"],
        "gain": 1,
    }
    binding = {
        "name": expected["name"],
        "canonical_fluvial_mouth_id": expected["outlet_id"],
        "binding_kind": expected["binding_kind"],
        "model_eligible": False,
        "physical_delta_branches_qualified": False,
        "attachment_by_resolution": {
            "8": {"status": "connected_with_recorded_source_registration_gap"}
        },
    }
    assert (
        validate_outlet_bindings({"queets": config_row}, [binding])[0]["id"] == "queets"
    )
    rows = [binding]
    if damage == "identity":
        config_row["outlet_id"] = "another-basin"
    if damage == "duplicate":
        rows.append(binding.copy())
    if damage == "attachment":
        binding["attachment_by_resolution"]["8"]["status"] = (
            "source_connector_crosses_land"
        )
    if damage == "eligibility":
        binding["model_eligible"] = True
    with pytest.raises(ValueError):
        validate_outlet_bindings({"queets": config_row}, rows)


def test_all_new_rivers_preserve_gaps_flags_and_unsupported_temperature(
    tmp_path, monkeypatch
):
    calls = []

    class Adapter:
        def __init__(self, client):
            pass

        def discover(self, sid):
            return {"station": {"id": sid}, "series": []}

        def observations(self, sid, metric, start, end):
            calls.append((sid, metric))
            assert metric == "discharge_mean", (
                "unsupported temperature must not dispatch"
            )
            return finalize(
                [
                    observation(
                        day=day.date().isoformat(),
                        station=sid,
                        value=0 if day.day == 1 else 10,
                        raw_flags=json.dumps({"approval": "Approved"}),
                        source_release="official-fixture",
                    )
                    for day in pd.date_range(start, end)
                    if day.date().isoformat() != "2023-01-04"
                ]
            )

    monkeypatch.setattr(acquisition, "USGS", Adapter)
    c = replace(config(tmp_path), rivers=tuple(NEW))
    target, _ = publication.publish_rivers(
        c, metrics=("discharge_mean", "temperature_mean", "temperature_max")
    )
    for rid, sid in NEW.items():
        frame = pd.read_parquet(target / rid / "conditions.parquet")
        assert set(frame.station_id) == {sid}
        temperature = frame[frame.metric.str.startswith("temperature")]
        assert temperature.value.isna().all() and set(temperature.status) == {
            "unavailable"
        }
        assert set(temperature.reason) == {"unsupported"}
        q = frame[frame.metric == "discharge_mean"]
        assert q.loc[q.date.astype(str) == "2023-01-01", "value"].item() == 0
        assert q.loc[q.date.astype(str) == "2023-01-04", "value"].isna().all()
        observed = pd.read_parquet(target / rid / "observations.parquet")
        assert set(observed.source_release) == {"official-fixture"}
        assert observed.raw_flags.str.contains("Approved").all()
        m = json.loads((target / rid / "manifest.json").read_text())
        assert m["eligibility"]["metrics"]["discharge_mean"]["eligible_days"] == 6
        assert m["execution_complete"] is True and m["complete"] is False
        assert m["coverage_regression_guard"]["new_river"] is True
        features = pd.read_parquet(target / rid / "features.parquet")
        assert {
            "high_flow_duration",
            "low_flow_duration",
            "days_since_flow_pulse",
        } <= set(features.metric)
    assert {sid for sid, _ in calls} == set(NEW.values())
    publication.validate_product(target)


def test_additions_preserve_existing_six_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    c = replace(config(tmp_path), rivers=OLD)
    target, _ = publication.publish_rivers(c)
    before = {rid: tree_bytes(target / rid) for rid in OLD}
    _, catalog = publication.publish_rivers(replace(c, rivers=tuple(NEW)))
    assert set(catalog["rivers"]) == set(OLD) | set(NEW)
    assert all(tree_bytes(target / rid) == before[rid] for rid in OLD)
    publication.validate_product(target)


@pytest.mark.parametrize("refresh", [False, True])
@pytest.mark.parametrize(
    "window", [{"end_date": "2023-01-06"}, {"start_date": "2023-01-02"}]
)
def test_cropped_refresh_rejected_before_acquisition(
    tmp_path, monkeypatch, refresh, window
):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    c = config(tmp_path)
    target, _ = publication.publish_rivers(c)
    before = tree_bytes(target)
    monkeypatch.setattr(
        acquisition,
        "acquire",
        lambda *a: pytest.fail("scope guard dispatched provider"),
    )
    with pytest.raises(CoverageRegressionError, match="full retained window"):
        publication.publish_rivers(replace(c, refresh=refresh, **window))
    assert tree_bytes(target) == before


def test_temperature_cannot_be_erased_by_discharge_only_refresh(tmp_path, monkeypatch):
    def both(c, metrics):
        f, meta, outcomes, net = acquired(c, metrics)
        temp = f.copy()
        temp["metric"] = "temperature_mean"
        temp["unit"] = "degC"
        outcomes["skagit"]["temperature_mean"] = "observed"
        return pd.concat([f, temp], ignore_index=True), meta, outcomes, net

    monkeypatch.setattr(acquisition, "acquire", both)
    c = config(tmp_path)
    target, _ = publication.publish_rivers(
        c, metrics=("discharge_mean", "temperature_mean")
    )
    before = tree_bytes(target)
    monkeypatch.setattr(
        acquisition, "acquire", lambda *a: pytest.fail("omitted-metric acquisition")
    )
    with pytest.raises(CoverageRegressionError, match="omitted observed metrics"):
        publication.publish_rivers(replace(c, refresh=True))
    assert tree_bytes(target) == before


@pytest.mark.parametrize(
    "failure",
    ["missing", "partial", "provisional", "estimated", "support", "unknown_qualifier"],
)
def test_observed_support_cannot_regress(failure):
    old = finalize(
        [observation(value=0, raw_flags='{"approval":"Approved"}', coverage=1.0)]
    )
    new = old.copy()
    if failure == "missing":
        new.loc[0, ["value", "status"]] = [None, "unavailable"]
    if failure == "partial":
        new.loc[0, "status"] = "partial"
    if failure == "provisional":
        new.loc[0, "raw_flags"] = '{"approval":"Provisional"}'
    if failure == "estimated":
        new.loc[0, "raw_flags"] = '{"approval":"Approved","qualifier":"Estimated"}'
    if failure == "support":
        new.loc[0, "coverage"] = 0.99
    if failure == "unknown_qualifier":
        new.loc[0, "raw_flags"] = '{"approval":"Approved","qualifier":"e"}'
    with pytest.raises(CoverageRegressionError):
        check_observations(old, new, "skagit")


def test_equal_counts_cannot_hide_lost_day_and_failed_refresh_keeps_downloads(
    tmp_path, monkeypatch
):
    def initial(c, metrics):
        f, meta, outcomes, net = acquired(c, metrics)
        return f.loc[f.date != "2023-01-07"], meta, outcomes, net

    monkeypatch.setattr(acquisition, "acquire", initial)
    c = config(tmp_path)
    target, _ = publication.publish_rivers(c)
    before = tree_bytes(target)

    def poorer(c, metrics):
        cache = Path(c.cache)
        (cache / "completed-page").write_text("resume")
        f, meta, outcomes, net = acquired(c, metrics)
        return f.loc[f.date != "2023-01-01"], meta, outcomes, net

    monkeypatch.setattr(acquisition, "acquire", poorer)
    with pytest.raises(CoverageRegressionError, match="lost eligible"):
        publication.publish_rivers(replace(c, refresh=True))
    assert tree_bytes(target) == before
    downloads = publication._download_root(c, publication._paths(target)[1])
    assert (downloads / "completed-page").read_text() == "resume"


def test_official_value_revision_allowed_without_inventing_missing_values(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    c = config(tmp_path)
    target, _ = publication.publish_rivers(c)

    def revised(c, metrics):
        f, meta, outcomes, net = acquired(c, metrics)
        f["value"] = 2
        f["source_release"] = "revised-official-fixture"
        return f, meta, outcomes, net

    monkeypatch.setattr(acquisition, "acquire", revised)
    publication.publish_rivers(replace(c, refresh=True))
    m = json.loads((target / "skagit/manifest.json").read_text())
    assert m["coverage_regression_guard"]["revised_values"] == 7
    f = pd.read_parquet(target / "skagit/conditions.parquet")
    assert f[f.metric == "discharge_mean"].value.eq(2).all()
    assert f[f.metric == "temperature_mean"].value.isna().all()
    publication.validate_product(target)


def test_approved_full_window_fits_single_usgs_daily_page(tmp_path):
    c = replace(
        config(tmp_path),
        start_date="2009-01-01",
        end_date="2026-10-15",
        rivers=tuple(NEW),
        acquisition_block_months=216,
    )
    blocks = acquisition.plan(c)["blocks"]
    assert blocks == [("2008-12-02", "2026-10-15")]
    assert len(pd.date_range(*blocks[0])) == 6527 < 10000
    assert 4 * (len(blocks) + 2) == 12

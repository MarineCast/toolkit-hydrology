"""Focused synthetic regression checks for the four review repairs; no network."""

import json

import h3
import pandas as pd
import pytest
from shapely.geometry import Point, box, mapping

from hydrology import pipeline
from hydrology.core import Config, eligible, source_references
from hydrology.pipelines import acquisition
from hydrology.providers import finalize, row
from hydrology.spatial import map_rivers
from hydrology.temporal import aggregate_utc


def observation(**updates):
    result = row(
        "08MF005",
        "discharge_mean",
        "2023-01-01",
        1.0,
        "m3/s",
        "fixture",
        "s",
        {},
        {"retrieved_at": "2026-01-01T00:00:00Z", "source_release": "page1"},
        "record1",
    )
    return dict(result, **updates)


def test_page_duplicates_retain_all_provenance_and_are_deterministic():
    first = observation()
    second = observation(
        source_release="page2",
        retrieved_at="2026-01-02T00:00:00Z",
        record_id="record2",
        source_modified_at="2025-01-01T00:00:00Z",
    )
    result = finalize([first, second, first])
    reverse = finalize([second, first])
    pd.testing.assert_frame_equal(result, reverse)
    assert len(result) == 1
    refs = source_references(result.iloc[0])
    assert {r["source_release"] for r in refs} == {"page1", "page2"}
    assert {r["record_id"] for r in refs} == {"record1", "record2"}
    assert len(refs) == 2
    pd.testing.assert_frame_equal(
        result, finalize(result.to_dict("records")), check_dtype=False
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"value": 2.0},
        {"unit": "ft^3/s"},
        {"raw_flags": '{"approval": "Provisional"}'},
        {"status": "unavailable"},
        {"available_at": "2023-01-02T00:00:00Z"},
        {"coverage": 0.5},
        {"day_definition": "different provider day"},
    ],
)
def test_page_duplicates_reject_scientific_conflicts(updates):
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        finalize([observation(), observation(source_release="page2", **updates)])


def samples():
    return pd.DataFrame(
        dict(
            time=pd.date_range("2023-01-01", periods=192, freq="15min", tz="UTC"),
            value=2.0,
            series_id="s",
            raw_flags="Approved",
            source_release="page1",
            retrieved_at="2026-01-01T00:00:00Z",
            available_at=None,
        )
    )


@pytest.mark.parametrize("allow", [False, True])
def test_utc_flags_only_follow_positive_day_contributors(allow):
    f = samples()
    f.loc[191, ["raw_flags", "source_release"]] = ["Provisional", "provisional-page"]
    out = aggregate_utc(
        f,
        "s",
        "discharge_mean",
        "2023-01-01",
        "2023-01-03",
        max_hold_seconds=900,
        allow_provisional=allow,
    )
    selected = eligible(out, allow_provisional=allow)
    assert selected.value.iloc[0] == 2.0
    assert out.coverage.iloc[0] == 1.0
    assert "Provisional" not in out.raw_flags.iloc[0]
    assert out.coverage.iloc[1] == pytest.approx(1 if allow else 95 / 96)
    assert ("Provisional" in out.raw_flags.iloc[1]) == allow
    assert {r["source_release"] for r in source_references(out.iloc[0])} == {
        "page1",
        "provisional-page",
    }
    assert "provisional-page" in {
        r["source_release"] for r in source_references(out.iloc[1])
    }
    assert out.raw_flags.iloc[2] == "[]"
    assert pd.isna(out.value.iloc[2]) and out.coverage.iloc[2] == 0


def test_utc_midnight_hold_and_duplicate_page_provenance():
    f = samples().iloc[:1].copy()
    f["time"] = pd.to_datetime(["2022-12-31T23:45:00Z"])
    f["raw_flags"] = "midnight-hold"
    duplicate = f.assign(source_release="page2", retrieved_at="2026-01-02T00:00:00Z")
    out = aggregate_utc(
        pd.concat([f, duplicate]),
        "s",
        "discharge_mean",
        "2023-01-01",
        "2023-01-01",
        max_hold_seconds=1800,
        minimum_coverage=0.01,
    )
    assert out.value.iloc[0] == 2.0
    assert out.coverage.iloc[0] == 900 / 86400
    assert json.loads(out.raw_flags.iloc[0]) == ["midnight-hold"]
    assert {r["source_release"] for r in source_references(out.iloc[0])} == {
        "page1",
        "page2",
    }
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        aggregate_utc(
            pd.concat([f, duplicate.assign(value=9)]),
            "s",
            "discharge_mean",
            "2023-01-01",
            "2023-01-01",
        )


def test_warmup_revision_creates_new_release_and_retains_dependencies(
    tmp_path, monkeypatch
):
    revision = [1.0]

    def acquire(config, metrics):
        records = []
        for day in pd.date_range("2022-12-02", "2023-01-05"):
            warm = day < pd.Timestamp("2023-01-01")
            records.append(
                observation(
                    date=day.date().isoformat(),
                    value=revision[0] if warm else 1.0,
                    source_release=f"warm-{revision[0]}" if warm else "output-fixed",
                    record_id=str(day),
                )
            )
        # Equal warmup observation returned on another page must also be retained.
        records.append(dict(records[0], source_release="warm-duplicate-page"))
        return finalize(records), {}, {"fraser": {"discharge_mean": "observed"}}, {}

    monkeypatch.setattr(acquisition, "acquire", acquire)
    config = Config(
        start_date="2023-01-01",
        end_date="2023-01-05",
        rivers=("fraser",),
        output=str(tmp_path / "releases"),
        cache=str(tmp_path / "cache"),
    )
    first, _ = pipeline.build(config)
    original_manifest = (first / "manifest.json").read_bytes()
    revision[0] = 100.0
    second, manifest = pipeline.build(config)
    assert first != second
    assert (first / "manifest.json").read_bytes() == original_manifest
    features = pd.read_parquet(second / "river_features.parquet")
    value = features.query(
        "date == '2023-01-01' and metric == 'discharge_mean_7d'"
    ).value.iloc[0]
    assert value == pytest.approx((6 * 100 + 1) / 7)
    assert (
        pd.read_parquet(second / "station_observations.parquet").date.min()
        == "2023-01-01"
    )
    warmup = pd.read_parquet(second / "feature_warmup.parquet")
    assert len(warmup) == 30 and warmup.date.max() == "2022-12-31"
    assert {"warm-100.0", "warm-duplicate-page", "output-fixed"} <= set(
        manifest["source_snapshot_hashes"]
    )
    catalog = json.loads((second / "final/catalog.json").read_text())
    assert catalog["source_snapshot_hashes"] == manifest["source_snapshot_hashes"]
    assert "feature_warmup.parquet" in manifest["files"]
    assert any(
        a["path"] == "../feature_warmup.parquet"
        for a in catalog["supporting_artifacts"]
    )
    assert pipeline.build(config)[0] == second
    assert pipeline.validate_release(first)["complete"]


@pytest.mark.parametrize("mode", ["edge-gap", "snap-gap", "connected"])
def test_receiving_region_constrains_entire_edges_and_snaps(tmp_path, mode):
    water = box(-123.2, 48, -123, 48.2)
    cell = next(
        c
        for c in h3.geo_to_cells(mapping(water), 6)
        if water.contains(Point(tuple(reversed(h3.cell_to_latlng(c)))))
    )
    neighbor = next(
        c
        for c in h3.grid_disk(cell, 1)
        if c != cell and water.contains(Point(tuple(reversed(h3.cell_to_latlng(c)))))
    )
    p = tuple(reversed(h3.cell_to_latlng(cell)))
    q = tuple(reversed(h3.cell_to_latlng(neighbor)))
    if mode == "edge-gap":
        region = Point(p).buffer(0.001).union(Point(q).buffer(0.001))
        origin, snap_limit = p, 1
    elif mode == "snap-gap":
        origin = (p[0] + 0.003, p[1])
        region = Point(p).buffer(0.001).union(Point(origin).buffer(0.0001))
        snap_limit = 1000
    else:
        region, origin, snap_limit = water, p, 1
    mask_path = tmp_path / "water.json"
    mask_path.write_text(json.dumps(mapping(water)))
    regions_path = tmp_path / "regions.json"
    regions_path.write_text(
        json.dumps(
            dict(
                type="FeatureCollection",
                features=[
                    dict(
                        type="Feature",
                        properties={"receiving_region": "test"},
                        geometry=mapping(region),
                    )
                ],
            )
        )
    )
    config = Config(
        cache=str(tmp_path / "cache"),
        water_mask=str(mask_path),
        water_mask_version="fixture",
        receiving_regions=str(regions_path),
        max_snap_m=snap_limit,
    )
    rivers = [
        dict(
            river_id="r",
            receiving_region="test",
            mouths=[
                dict(
                    mouth_id="m",
                    longitude=origin[0],
                    latitude=origin[1],
                    source="SYNTHETIC",
                )
            ],
        )
    ]
    result = map_rivers(config, rivers)
    if mode == "snap-gap":
        assert (result.status == "unavailable").all()
    else:
        assert result.loc[result.h3_index == cell, "status"].iloc[0] == "valid"
        assert result.loc[result.h3_index == neighbor, "status"].iloc[0] == (
            "valid" if mode == "connected" else "unavailable"
        )
    pd.testing.assert_frame_equal(result, map_rivers(config, rivers))


def test_excluded_sample_boundary_remains_a_source_dependency():
    first = samples().iloc[:1].copy()
    first["time"] = pd.to_datetime(["2023-01-01T23:00:00Z"])
    boundary = first.assign(
        time=pd.to_datetime(["2023-01-01T23:30:00Z"]),
        raw_flags="Provisional",
        source_release="boundary-page",
    )
    out = aggregate_utc(
        pd.concat([first, boundary]),
        "s",
        "discharge_mean",
        "2023-01-01",
        "2023-01-01",
        max_hold_seconds=7200,
        minimum_coverage=0.01,
    )
    assert out.coverage.iloc[0] == 1800 / 86400
    assert "Provisional" not in out.raw_flags.iloc[0]
    assert "boundary-page" in {
        r["source_release"] for r in source_references(out.iloc[0])
    }
    boundary["time"] = pd.to_datetime(["2023-01-01T23:45:00Z"])
    boundary["source_release"] = "revised-boundary-page"
    revised = aggregate_utc(
        pd.concat([first, boundary]),
        "s",
        "discharge_mean",
        "2023-01-01",
        "2023-01-01",
        max_hold_seconds=7200,
        minimum_coverage=0.01,
    )
    assert revised.coverage.iloc[0] == 2700 / 86400
    assert revised.source_release.iloc[0] != out.source_release.iloc[0]

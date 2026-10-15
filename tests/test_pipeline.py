"""Transactional and reproducibility checks with explicitly synthetic observations."""

import json

import pandas as pd
import pytest

from hydrology import pipeline
from hydrology.core import Config
from hydrology.providers import finalize, row
from hydrology.registry import select_registry


def fake_acquire(config, metrics):
    records = []
    for river in select_registry(config):
        for day in pd.date_range("2022-12-02", "2023-01-05"):
            records.append(
                row(
                    river["stations"][0]["station_id"],
                    "discharge_mean",
                    day.date(),
                    1.0,
                    "m3/s",
                    "fixture",
                    "series",
                    {},
                    {
                        "retrieved_at": "2026-01-01T00:00:00Z",
                        "source_release": "synthetic",
                    },
                    str(day),
                )
            )
    return (
        finalize(records),
        {},
        {
            r["river_id"]: {"discharge_mean": "observed"}
            for r in select_registry(config)
        },
        {"http_requests": 0, "cache_hits": 0},
    )


def test_saved_repeat_immutable_and_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "acquire", fake_acquire)
    c = Config(
        start_date="2023-01-01",
        end_date="2023-01-05",
        output=str(tmp_path),
        cache=str(tmp_path / "cache"),
        rivers=("fraser",),
    )
    root, m = pipeline.build(c)
    assert m["complete"]
    assert pipeline.validate_release(root)["observations"] == 5
    before = (root / "manifest.json").read_bytes()
    root2, m2 = pipeline.build(c)
    assert root == root2
    assert before == (root / "manifest.json").read_bytes()
    (root / "river_features.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Checksum"):
        pipeline.build(c)


def test_h3_failure_keeps_native_and_has_different_release(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "acquire", fake_acquire)
    c = Config(
        start_date="2023-01-01",
        end_date="2023-01-05",
        output=str(tmp_path),
        cache=str(tmp_path / "cache"),
        rivers=("fraser",),
    )
    native, _ = pipeline.build(c)
    spatial, m = pipeline.build(c, make_h3=True)
    assert native != spatial
    assert not m["complete"]
    assert m["spatial_error"]
    assert (spatial / "station_observations.parquet").exists()


def test_source_precedence_conflicts_fail():
    c = Config(rivers=("fraser",))
    r = select_registry(c)
    f, _, _, _ = fake_acquire(c, ())
    revised = f.copy()
    revised["series_id"] = "other"
    revised["value"] = 2
    with pytest.raises(ValueError, match="ambiguous"):
        pipeline.river_conditions(pd.concat([f, revised]), r, {}, c)


@pytest.mark.parametrize("fail_stage", [None, "product", "source"])
def test_saved_h3_partition(tmp_path, monkeypatch, fail_stage):
    from shapely.geometry import box, mapping

    from hydrology.registry import load_registry

    reg = load_registry()
    reg["rivers"] = reg["rivers"][:1]
    r = reg["rivers"][0]
    r["mouths"] = [
        dict(mouth_id="fixture", longitude=-123.1, latitude=48.1, source="SYNTHETIC")
    ]
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(reg))
    mask = tmp_path / "water.json"
    mask.write_text(json.dumps(mapping(box(-123.2, 48, -123, 48.2))))
    regions = tmp_path / "regions.json"
    regions.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"receiving_region": r["receiving_region"]},
                        "geometry": mapping(box(-124, 47, -122, 49)),
                    }
                ],
            }
        )
    )

    def utc(config, metrics):
        f, meta, outcomes, network = fake_acquire(config, metrics)
        f.temporal_basis = "utc_daily"
        f.interval_start = pd.to_datetime(f.date, utc=True).astype(str)
        f.interval_end = (
            pd.to_datetime(f.date, utc=True) + pd.Timedelta(days=1)
        ).astype(str)
        from pathlib import Path

        cache = Path(config.cache)
        (cache / "requests").mkdir(parents=True, exist_ok=True)
        (cache / "snapshots").mkdir(exist_ok=True)
        envelope = {
            "url": "https://example.test/fixture",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "source_release": "synthetic",
            "body": {"features": []},
        }
        (cache / "requests" / "fixture.json").write_text(json.dumps(envelope))
        (cache / "snapshots" / "fixture.json").write_text(json.dumps(envelope))
        if fail_stage == "source":
            outcomes["fraser"]["discharge_mean"] = "failure: synthetic provider failure"
        return f, meta, outcomes, network

    if fail_stage == "product":

        def broken_product(*args):
            raise ValueError("Synthetic final product validation failure")

        monkeypatch.setattr(pipeline, "write_final", broken_product)
    monkeypatch.setattr(pipeline, "acquire", utc)
    c = Config(
        start_date="2023-01-01",
        end_date="2023-01-05",
        output=str(tmp_path / "out"),
        cache=str(tmp_path / "cache"),
        rivers=("fraser",),
        registry=str(registry),
        water_mask=str(mask),
        water_mask_version="SYNTHETIC",
        receiving_regions=str(regions),
        temporal_requirement="utc_daily",
        max_snap_m=10000,
    )
    (tmp_path / "cache").mkdir()
    shared = tmp_path / "cache" / "unrelated.json"
    shared.write_text("preserve")
    root, m = pipeline.build(c, make_h3=True)
    assert shared.read_text() == "preserve"
    staging = next((tmp_path / "cache" / "build-staging").iterdir())
    catalog = json.loads((root / "final" / "catalog.json").read_text())
    assert catalog["sources"][0]["url"] == "https://example.test/fixture"
    if fail_stage:
        assert not m["complete"]
        assert not catalog["complete"]
        assert (staging / "requests" / "fixture.json").exists()
        assert (staging / "snapshots" / "fixture.json").exists()
        return
    assert not (staging / "requests").exists()
    assert not (staging / "snapshots").exists()
    assert mask.exists() and registry.exists() and regions.exists()
    assert m["complete"]
    assert m["h3_rows"] > 0
    assert pipeline.validate_release(root)["complete"]
    f = pd.read_parquet(root / "final" / "dynamic.parquet")
    assert f.date.nunique() == 5
    assert not f.duplicated(["h3_index", "date", "metric"]).any()
    assert (root / "final" / "static.parquet").exists()
    catalog = json.loads((root / "final" / "catalog.json").read_text())
    assert catalog["complete"]
    assert len(catalog["products"]) == 2
    assert set(f.contributor_river_id) == {"fraser"}

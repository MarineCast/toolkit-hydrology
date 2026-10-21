"""Offline scenario math, source binding, missingness and regional-product adapter tests."""

import json
from datetime import date
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from test_correctness_and_canonical import acquired, config

from hydrology.pipelines import acquisition
from hydrology.pipelines.influence import build_influence
from hydrology.pipelines.publication import publish_rivers
from hydrology.utils.influence import (
    combine,
    distance_weights,
    lagged,
    validate_profiles,
)
from hydrology.utils.products import checksum


def settings():
    return json.loads(
        (Path(__file__).parents[1] / "config/river-influence.json").read_text()
    )


def test_distance_decay_offshore_peak_cutoff_and_unknown_route():
    p = settings()["distance_profiles"][1]
    values = distance_weights([0, 50000, 100000, 251000, np.nan], p)
    np.testing.assert_allclose(values[:3], [1, np.exp(-1), np.exp(-2)])
    assert values[3] == 0 and np.isnan(values[4])
    p = settings()["distance_profiles"][2]
    values = distance_weights([0, 20000, 40000], p, gain=2)
    assert values[1] == 2 and values[0] == values[2] < 2


def test_lags_are_past_only_normalized_and_do_not_invent_missing_support():
    p = {
        "weights": [
            {"days": 0, "weight": 1},
            {"days": 2, "weight": 3},
            {"days": 100, "weight": 0},
        ]
    }
    result = lagged([4, 8, 12, 16], p)
    assert np.isnan(result[:2]).all()
    np.testing.assert_allclose(result[2:], [6, 10])
    assert np.isnan(
        lagged([4, np.nan, 12], {"weights": [{"days": 1, "weight": 1}]})[-1]
    )


def test_overlap_adds_without_normalizing_away_attenuation_and_reports_unknown():
    assert combine([0.5, 0.25], [2, 4]) == {
        "value": 2,
        "known_rivers": 2,
        "active_rivers": 2,
        "total_rivers": 2,
    }
    assert combine([0.05, 0.025], [2, 4])["value"] == pytest.approx(0.2)
    assert combine([0.5, np.nan], [2, 999]) == {
        "value": 1,
        "known_rivers": 1,
        "active_rivers": 1,
        "total_rivers": 2,
    }
    assert combine([0.5, 0.25], [2, np.nan])["value"] is None
    assert combine([0, 0], [np.nan, np.nan])["value"] == 0
    assert combine([np.nan, np.nan], [2, 4])["value"] is None


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c["lag_profiles"][0]["weights"].append({"days": -1, "weight": 1}),
        lambda c: c["lag_profiles"][0]["weights"][0].update(weight=0),
        lambda c: c["distance_profiles"][0].update(scale_km=0),
        lambda c: c["rivers"]["fraser"].update(gain=-1),
        lambda c: c["rivers"]["fraser"].update(
            outlet_id=c["rivers"]["cowichan"]["outlet_id"]
        ),
    ],
)
def test_invalid_scenario_fails_closed(change):
    c = settings()
    change(c)
    with pytest.raises(ValueError):
        validate_profiles(c)


def test_factorized_pipeline_validates_keys_sources_and_idempotent_publication(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    hydrology, _ = publish_rivers(config(tmp_path))
    parent = h3.latlng_to_cell(48.3, -122.5, 6)
    children = sorted(h3.cell_to_children(parent, 8))[:2]
    links = tmp_path / "links.parquet"
    pd.DataFrame(
        [
            {
                "H3_INDEX": c,
                "H3_RESOLUTION": 8,
                "OUTLET_ID": "named-skagit",
                "WATER_NETWORK_DISTANCE_M": d,
                "REACHABILITY_STATUS": "reachable",
                "QC_REASON": None,
            }
            for c, d in zip(children, [1000.0, 2000.0])
        ]
    ).to_parquet(links, index=False)
    grid = tmp_path / "grid.txt"
    grid.write_text(parent + "\n")
    manifest = tmp_path / "study-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "research_artifacts": {
                    "outlet-relationships-r8": {
                        "relative_path": "links.parquet",
                        "sha256": checksum(links),
                    }
                }
            }
        )
    )
    study = tmp_path / "study.json"
    study.write_text(
        json.dumps(
            {
                "domain": {"status": "approved"},
                "grid_registry": {
                    "status": "validated",
                    "manifest_relative_path": "study-manifest.json",
                    "manifest_sha256": checksum(manifest),
                    "memberships": [
                        {
                            "role": "water_reporting",
                            "resolution": 6,
                            "relative_path": "grid.txt",
                            "sha256": checksum(grid),
                            "count": 1,
                        }
                    ],
                },
            }
        )
    )
    bindings = tmp_path / "bindings.json"
    bindings.write_text(
        json.dumps(
            {
                "locations": [
                    {
                        "name": "Skagit River",
                        "canonical_fluvial_mouth_id": "named-skagit",
                        "modeled_outlet_point_wgs84": [-122.5, 48.3],
                    }
                ]
            }
        )
    )
    c = settings()
    c.update(
        hydrology=str(hydrology),
        study=str(study),
        outlet_bindings=str(bindings),
        outlet_bindings_sha256=checksum(bindings),
        output=str(hydrology / "influence.parquet"),
        rivers={
            "skagit": {"name": "Skagit River", "outlet_id": "named-skagit", "gain": 1}
        },
    )
    cp = tmp_path / "influence.json"
    cp.write_text(json.dumps(c))
    from hydrology.utils.influence_product import native_catalog_sha256

    before = native_catalog_sha256(json.loads((hydrology / "catalog.json").read_text()))
    report = build_influence(cp)
    assert report["cells"] == 1 and report["river_days"] == 7
    out = Path(report["output"])
    table = pq.read_table(out)
    metadata = json.loads(table.schema.metadata[b"hydrology_influence"])
    frame = table.to_pandas()
    spatial = frame.loc[frame.factor_type == "spatial"]
    assert spatial["date"].isna().all()
    assert not (hydrology / "releases").exists()
    assert not (hydrology / "recipe.json").exists()
    assert set(p.name for p in hydrology.glob("influence*")) == {"influence.parquet"}
    assert spatial.water_distance_m.eq(1000).all()
    assert spatial.reachable_r8_children.eq(2).all()
    signals = frame.loc[frame.factor_type == "temporal"]
    assert isinstance(signals.date.iloc[0], date)
    assert signals.query("lag_profile == 'same-day'").relative_flow.eq(1).all()
    assert "pulse_excess" not in signals
    recipe = metadata["recipe"]
    assert recipe["method"].endswith("-v2")
    assert set(recipe["signals"]) == {"discharge", "relative_flow"}
    assert all(
        set(bounds) == set(recipe["signals"])
        for bounds in recipe["display_ranges"].values()
    )
    assert signals.query("lag_profile == 'seven-day'").discharge.isna().all()
    registered = json.loads((hydrology / "catalog.json").read_text())
    assert native_catalog_sha256(registered) == before
    entry = registered["products"]["influence"]
    assert entry["path"] == "influence.parquet" and entry["sha256"] == checksum(out)
    assert entry["source_status"] == "current" and entry["model_eligible"] is False
    catalog_before = checksum(hydrology / "catalog.json")
    assert build_influence(cp) == report
    assert checksum(hydrology / "catalog.json") == catalog_before
    # Pinned geometry mutations cannot silently change routing.
    links.write_bytes(b"changed")
    with pytest.raises(ValueError, match="binding mismatch"):
        build_influence(cp)
    assert checksum(out) == report["sha256"]


def test_flat_atomic_write_preserves_current_on_failure_and_refuses_unowned(tmp_path):
    from hydrology.utils.influence_product import factor_table, write_influence

    path = tmp_path / "influence.parquet"
    table = factor_table(
        [],
        [{"river_id": "test", "date": "2026-10-15", "relative_flow": 1.0}],
        {"version": 1},
    )
    before = write_influence(path, table, lambda: None)
    revised = factor_table(
        [],
        [{"river_id": "test", "date": "2026-10-15", "relative_flow": 2.0}],
        {"version": 1},
    )

    def changed():
        raise ValueError("Inputs changed")

    with pytest.raises(ValueError, match="Inputs changed"):
        write_influence(path, revised, changed)
    assert checksum(path) == before
    assert list(tmp_path.glob(".influence-*.tmp")) == []
    pq.write_table(table.replace_schema_metadata(None), path)
    unowned = checksum(path)
    with pytest.raises(ValueError, match="unowned"):
        write_influence(path, revised, lambda: None)
    assert checksum(path) == unowned


def test_native_publication_carries_flat_file_and_exclusive_builder_lock(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from hydrology.pipelines.publication import product_snapshot
    from hydrology.utils.influence_product import (
        factor_table,
        native_catalog_sha256,
        write_influence,
    )

    monkeypatch.setattr(acquisition, "acquire", acquired)
    destination, old = publish_rivers(config(tmp_path))
    with product_snapshot(destination):
        with pytest.raises(ValueError, match="holds the product lock"):
            with product_snapshot(destination, exclusive=True):
                pass
    table = factor_table(
        [],
        [{"river_id": "test", "date": "2026-10-15"}],
        {
            "version": 1,
            "signals": {"discharge": {"unit": "m3/s"}},
            "temporal_basis": "provider_daily",
            "model_eligible": False,
            "retrospective": True,
            "hydrology_catalog_sha256": native_catalog_sha256(old),
        },
    )
    before = write_influence(destination / "influence.parquet", table, lambda: None)
    from hydrology.utils.influence_product import catalog_with_influence
    from hydrology.utils.io import atomic_json

    old = catalog_with_influence(old, destination)
    atomic_json(destination / "catalog.json", old)
    _, new = publish_rivers(replace(config(tmp_path), end_date="2023-01-08"))
    assert old != new
    assert checksum(destination / "influence.parquet") == before
    assert new["products"]["influence"]["source_status"] == "requires_rebuild"

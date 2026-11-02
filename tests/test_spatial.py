"""Synthetic water polygons; these are not production validation."""

import json

import pandas as pd
import pytest
from shapely.geometry import box, mapping

from hydrology.core import Config
from hydrology.spatial import associations, dynamic_h3, map_rivers, water_segment


def setup(tmp_path, res=6):
    water = box(-123.2, 48, -123, 48.2).union(box(-122.9, 48, -122.7, 48.2))
    mask = tmp_path / "water.json"
    mask.write_text(json.dumps(mapping(water)))
    regions = tmp_path / "regions.json"
    regions.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"receiving_region": "test"},
                        "geometry": mapping(box(-124, 47, -122, 49)),
                    }
                ],
            }
        )
    )
    r = {
        "river_id": "r",
        "receiving_region": "test",
        "mouths": [
            {
                "mouth_id": "m",
                "longitude": -123.1,
                "latitude": 48.1,
                "source": "SYNTHETIC TEST ONLY",
            }
        ],
    }
    c = Config(
        cache=str(tmp_path / "cache"),
        water_mask=str(mask),
        water_mask_version="fixture",
        receiving_regions=str(regions),
        h3_res=res,
        max_snap_m=10000,
    )
    return c, [r], water


def test_land_barrier_and_reproducibility(tmp_path):
    config, rivers, water = setup(tmp_path)
    assert not water_segment(water, (-123.1, 48.1), (-122.8, 48.1))
    a = map_rivers(config, rivers)
    b = map_rivers(config, rivers)
    pd.testing.assert_frame_equal(a, b)
    assert (a.status == "valid").any()
    assert (a.status == "unavailable").any()
    assert a.loc[a.status == "unavailable", "water_distance_m"].isna().all()
    assert not associations(a).h3_index.duplicated().any()


def test_resolution_sensitivity_and_mouth_snap(tmp_path):
    c, r, _ = setup(tmp_path, 6)
    a = map_rivers(c, r)
    c, r, _ = setup(tmp_path, 7)
    b = map_rivers(c, r)
    assert len(b) > len(a)
    assert a.mapping_id.iloc[0] != b.mapping_id.iloc[0]
    r[0]["mouths"][0]["longitude"] = -124
    assert (map_rivers(c, r).status == "unavailable").all()


def test_distributary_not_duplicated(tmp_path):
    c, r, _ = setup(tmp_path)
    r[0]["mouths"].append({**r[0]["mouths"][0], "mouth_id": "m2"})
    links = map_rivers(c, r)
    assert not links.duplicated(["river_id", "h3_index"]).any()


def test_utc_contract_and_contributors(tmp_path):
    c, r, _ = setup(tmp_path)
    links = map_rivers(c, r)
    f = pd.DataFrame(
        [
            dict(
                date="2020-01-01",
                river_id="r",
                station_id="s",
                metric="discharge_mean",
                value=2.0,
                status="valid",
                temporal_basis="provider_daily",
            )
        ]
    )
    with pytest.raises(ValueError):
        list(dynamic_h3(f, links))
    f.temporal_basis = "utc_daily"
    _, out = list(dynamic_h3(f, links))[0]
    assert set(out.contributor_station_id) == {"s"}
    assert set(out.value) == {2}


def test_narrow_passage_does_not_jump_land(tmp_path):
    _, _, water = setup(tmp_path)
    # A slit below grid resolution cannot create a false straight-line connection.
    slit = box(-123, 48.0999, -122.9, 48.1001)
    joined = water.union(slit)
    assert not water_segment(joined, (-123.1, 48.15), (-122.8, 48.15))
    assert water_segment(joined, (-123.1, 48.1), (-122.8, 48.1))

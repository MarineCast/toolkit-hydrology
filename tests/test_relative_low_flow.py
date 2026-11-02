"""Relative low-flow and offline-product regressions; no provider requests."""

import json

import numpy as np
import pandas as pd
import pytest
from test_correctness_and_canonical import acquired, config

from hydrology import recompute_low_flow
from hydrology.core import Config
from hydrology.features import build_features
from hydrology.low_flow import METHOD, relative_low_flow, replace_low_flow
from hydrology.pipelines import acquisition
from hydrology.pipelines import publication as canonical


def conditions(values, river="r", start="2020-01-01"):
    return pd.DataFrame(
        [
            dict(
                river_id=river,
                station_id=river,
                metric="discharge_mean",
                date=d.date().isoformat(),
                temporal_basis="provider_daily",
                value=v,
                unit="m3/s",
                status="valid" if pd.notna(v) else "unavailable",
                series_id="source-" + river,
            )
            for d, v in zip(pd.date_range(start, periods=len(values)), values)
        ]
    )


def test_linear_quantile_is_river_relative_and_streak_resets():
    values = [100] * 40 + [1, 1, 1, 100, 1]
    frame = pd.concat([conditions(values), conditions([v * 100 for v in values], "s")])
    result, definitions = relative_low_flow(frame)
    assert (
        definitions["s"]["threshold_m3_s"] == 100 * definitions["r"]["threshold_m3_s"]
    )
    assert result.query("river_id == 'r'").value.tolist()[-5:] == [1, 2, 3, 0, 1]
    assert (
        result.query("river_id == 'r'").value.tolist()
        == result.query("river_id == 's'").value.tolist()
    )
    assert set(result.method_version) == {METHOD}
    assert all(
        d["retrospective"] and not d["model_eligible"] for d in definitions.values()
    )


def test_interpolation_preserves_sources_and_marks_dependent_streak():
    frame = conditions([100] * 40 + [1, np.nan, 3, 100])
    before = frame.copy(deep=True)
    result, definitions = relative_low_flow(frame)
    pd.testing.assert_frame_equal(frame, before)
    assert result.value.tolist()[-4:] == [1, 2, 3, 0]
    assert result.reason.tolist()[-3:-1] == [
        "interpolated_flow_input",
        "streak_includes_interpolated_flow",
    ]
    note = definitions["r"]
    assert note["interpolated_days"] == 1
    assert note["threshold_m3_s"] == float(
        pd.Series([100] * 40 + [1, 2, 3, 100]).quantile(0.1)
    )
    assert note["interpolation"][0]["value_m3_s"] == 2
    assert note["interpolation"][0]["left_series"] == "source-r"


def test_edges_not_extrapolated_start_censored_equality_not_low():
    frame = conditions([np.nan, 1, 1] + [100] * 30 + [np.nan])
    result, definitions = relative_low_flow(frame)
    assert result.value.iloc[:3].isna().all()
    assert result.value.iloc[3] == 0 and pd.isna(result.value.iloc[-1])
    assert definitions["r"]["unfilled_days"] == 2
    equal, _ = relative_low_flow(conditions([0] * 20))
    assert equal.value.eq(0).all()
    unsupported, _ = relative_low_flow(conditions([np.nan, 1, np.nan]))
    assert unsupported.value.isna().all()


def test_only_low_flow_changes_and_reference_uses_future_history():
    frame = conditions([100] * 40 + [1, np.nan, 3, 100])
    features = build_features(frame)
    result = replace_low_flow(features, frame)
    pd.testing.assert_frame_equal(
        features.query("metric != 'low_flow_duration'"),
        result.query("metric != 'low_flow_duration'"),
    )
    extended = pd.concat([frame, conditions([0] * 20, start="2020-02-14")])
    _, before = relative_low_flow(frame)
    _, after = relative_low_flow(extended)
    assert before["r"]["threshold_m3_s"] != after["r"]["threshold_m3_s"]


def test_duplicate_or_mixed_river_identity_rejected():
    frame = conditions([1, 2])
    with pytest.raises(ValueError, match="daily keys"):
        relative_low_flow(pd.concat([frame, frame]))
    with pytest.raises(ValueError, match="one station"):
        relative_low_flow(pd.concat([frame, frame.assign(station_id="other")]))
    with pytest.raises(ValueError, match="m3/s"):
        relative_low_flow(frame.assign(unit="cfs"))
    with pytest.raises(ValueError, match="calendar/identity"):
        replace_low_flow(
            build_features(frame).query("metric != 'low_flow_duration'"), frame
        )
    with pytest.raises(ValueError, match="low-flow method"):
        Config(low_flow_method="unknown")


def test_offline_recompute_preserves_companions_and_removes_snapshots(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    target, _ = canonical.publish_rivers(config(tmp_path, low_flow_method="fixed"))
    old = target.resolve()
    before = {
        p.name: (p.stat().st_ino, canonical.checksum(p))
        for p in (old / "skagit").iterdir()
    }

    def no_acquisition(*args, **kwargs):
        pytest.fail("offline recomputation acquired sources")

    monkeypatch.setattr(acquisition, "acquire", no_acquisition)
    recompute_low_flow(target)
    current = target.resolve()
    assert current == old and not target.is_symlink()
    assert not list(canonical._paths(target)[1].glob("snapshot-*"))
    for name in [
        "conditions.parquet",
        "observations.parquet",
        "warmup.parquet",
        "coverage.parquet",
        "acquisition-ledger.json",
    ]:
        path = current / "skagit" / name
        assert before[name] == (path.stat().st_ino, canonical.checksum(path))
    note = json.loads((current / "skagit/metadata.json").read_text())[
        "low_flow_definition"
    ]
    assert note["method"] == METHOD
    canonical.validate_product(target)
    recompute_low_flow(target)
    assert target.resolve() == current
    with canonical.product_snapshot(target):
        with pytest.raises(ValueError, match="lock"):
            recompute_low_flow(target)


def test_recompute_failure_keeps_current_and_rejects_unowned(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    target, _ = canonical.publish_rivers(config(tmp_path, low_flow_method="fixed"))
    old = target.resolve()
    with pytest.raises(ValueError, match="byte budget"):
        recompute_low_flow(target, max_bytes=1)
    assert target.resolve() == old
    with pytest.raises(ValueError, match="owned current"):
        recompute_low_flow(tmp_path)


def test_publisher_default_has_relative_definition(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    target, _ = canonical.publish_rivers(config(tmp_path))
    metadata = json.loads((target / "skagit/metadata.json").read_text())
    assert metadata["low_flow_definition"]["reference_start"] == "2023-01-01"
    assert metadata["low_flow_definition"]["reference_end"] == "2023-01-07"
    assert metadata["configured_feature_thresholds"]["low_flow_threshold_m3_s"] == 1


def test_features_cli_records_relative_definition(tmp_path):
    from hydrology.cli import main

    source, output = tmp_path / "conditions.parquet", tmp_path / "features.parquet"
    conditions([100] * 40 + [1, np.nan, 3, 100]).to_parquet(source)
    assert main(["features", str(source), "--output", str(output)]) == 0
    definition = json.loads((tmp_path / "features.parquet.low-flow.json").read_text())[
        "r"
    ]
    assert definition["interpolated_days"] == 1 and definition["retrospective"]
    assert (
        pd.read_parquet(output).query("metric == 'low_flow_duration'").value.iloc[-2]
        == 3
    )

"""Synthetic P90 crossing and offline-publication tests, without provider requests."""

import json

import numpy as np
import pandas as pd
import pytest
from test_correctness_and_canonical import acquired, config
from test_relative_low_flow import conditions

from hydrology import recompute_flow_pulse
from hydrology.features import build_features
from hydrology.flow_pulse import METHOD, relative_flow_pulse, replace_flow_pulse
from hydrology.pipelines import acquisition
from hydrology.pipelines import publication as canonical


def test_p90_upward_crossing_not_every_high_day_and_river_scaling():
    values = [1] * 30 + [10, 20, 30, 40, 1, 40, 40]
    frame = pd.concat([conditions(values), conditions([v * 100 for v in values], "s")])
    result, definitions = relative_flow_pulse(frame)
    assert definitions["r"]["threshold_m3_s"] == pytest.approx(24)
    assert definitions["s"]["threshold_m3_s"] == pytest.approx(2400)
    assert result.query("river_id == 'r'").value.tolist()[-5:] == [0, 1, 2, 0, 1]
    assert result.query("river_id == 'r'").value.iloc[:32].isna().all()
    assert set(result.method_version) == {METHOD}
    assert definitions["r"]["model_eligible"] is False


def test_threshold_equality_crosses_and_starting_high_is_unknown():
    frame = conditions(list(range(1, 12)))
    result, definitions = relative_flow_pulse(frame)
    assert definitions["r"]["threshold_m3_s"] == 10
    assert result.value.iloc[-2:].tolist() == [0, 1]
    frame = conditions([20, 20] + [1] * 30)
    result, _ = relative_flow_pulse(frame)
    assert result.value.isna().all()


def test_interpolated_crossing_provenance_and_raw_flow_preservation():
    frame = conditions([1] * 30 + [10, np.nan, 30, 40, 40])
    before = frame.copy(deep=True)
    result, definitions = relative_flow_pulse(frame)
    pd.testing.assert_frame_equal(frame, before)
    assert definitions["r"]["interpolation"][0]["value_m3_s"] == 20
    assert result.value.iloc[-4:].tolist() == [0, 1, 2, 3]
    assert result.reason.iloc[-4] == "interpolated_flow_input"
    assert result.reason.iloc[-3] == "pulse_history_includes_interpolated_flow"
    original = build_features(frame)
    changed = replace_flow_pulse(original, frame)
    pd.testing.assert_frame_equal(
        original.query("metric != 'days_since_flow_pulse'"),
        changed.query("metric != 'days_since_flow_pulse'"),
    )


def test_edges_and_insufficient_history_stay_unknown():
    result, notes = relative_flow_pulse(
        conditions([np.nan] + [1] * 30 + [10, 20, 30, 40, np.nan])
    )
    assert pd.isna(result.value.iloc[0]) and pd.isna(result.value.iloc[-1])
    assert notes["r"]["unfilled_days"] == 2
    empty, _ = relative_flow_pulse(conditions([np.nan, 1, np.nan]))
    assert empty.value.isna().all()


def test_offline_pulse_recompute_retains_low_flow_and_raw_companions(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    target, _ = canonical.publish_rivers(config(tmp_path, flow_pulse_method="fixed"))
    old = target.resolve()
    before = pd.read_parquet(old / "skagit/features.parquet")
    old_inode = (old / "skagit/conditions.parquet").stat().st_ino
    old_metadata = json.loads((old / "skagit/metadata.json").read_text())
    monkeypatch.setattr(
        acquisition, "acquire", lambda *a, **k: pytest.fail("unexpected acquisition")
    )
    recompute_flow_pulse(target)
    new = target.resolve()
    assert new == old and not target.is_symlink()
    assert not list(canonical._paths(target)[1].glob("snapshot-*"))
    after = pd.read_parquet(new / "skagit/features.parquet")
    pd.testing.assert_frame_equal(
        before.query("metric != 'days_since_flow_pulse'"),
        after.query("metric != 'days_since_flow_pulse'"),
    )
    assert old_inode == (new / "skagit/conditions.parquet").stat().st_ino
    metadata = json.loads((new / "skagit/metadata.json").read_text())
    assert metadata["flow_pulse_definition"]["method"] == METHOD
    assert metadata["low_flow_definition"] == old_metadata["low_flow_definition"]
    canonical.validate_product(target)
    recompute_flow_pulse(target)
    assert target.resolve() == new
    with canonical.product_snapshot(target):
        with pytest.raises(ValueError, match="lock"):
            recompute_flow_pulse(target)


def test_pulse_writer_failure_and_default_publisher_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    target, _ = canonical.publish_rivers(config(tmp_path, flow_pulse_method="fixed"))
    old = target.resolve()
    with pytest.raises(ValueError, match="byte budget"):
        recompute_flow_pulse(target, max_bytes=1)
    assert target.resolve() == old
    other, _ = canonical.publish_rivers(config(tmp_path / "other"))
    metadata = json.loads((other / "skagit/metadata.json").read_text())
    assert metadata["flow_pulse_definition"]["reference_start"] == "2023-01-01"
    assert metadata["configured_feature_thresholds"]["pulse_threshold_m3_s"] == 1

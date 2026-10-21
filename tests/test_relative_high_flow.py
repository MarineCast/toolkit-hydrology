"""P90 duration semantics and offline append/preservation regressions."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_correctness_and_canonical import acquired, config
from test_relative_low_flow import conditions

from hydrology import recompute_high_flow
from hydrology.features import build_features
from hydrology.pipelines import acquisition
from hydrology.pipelines import publication as canonical
from hydrology.utils.high_flow import METHOD, relative_high_flow, replace_high_flow


def test_relative_scaling_consecutive_days_and_equality_reset():
    values = [1] * 40 + [100, 100, 100, 1, 100]
    frame = pd.concat([conditions(values), conditions([v * 100 for v in values], "s")])
    result, definitions = relative_high_flow(frame)
    assert (
        definitions["s"]["threshold_m3_s"] == 100 * definitions["r"]["threshold_m3_s"]
    )
    for rid in ["r", "s"]:
        assert result.query("river_id == @rid").value.tolist()[-5:] == [1, 2, 3, 0, 1]
    equal, notes = relative_high_flow(conditions(list(range(1, 12))))
    assert notes["r"]["threshold_m3_s"] == 10
    assert equal.value.tolist()[-2:] == [0, 1]
    assert set(result.method_version) == {METHOD}
    assert not definitions["r"]["model_eligible"] and definitions["r"]["retrospective"]


def test_interpolation_only_for_calculation_and_dependent_streak_reasons():
    frame = conditions([1] * 40 + [100, np.nan, 300, 1])
    before = frame.copy(deep=True)
    result, definitions = relative_high_flow(frame)
    pd.testing.assert_frame_equal(frame, before)
    assert result.value.tolist()[-4:] == [1, 2, 3, 0]
    assert result.reason.tolist()[-3:-1] == [
        "interpolated_flow_input",
        "streak_includes_interpolated_flow",
    ]
    assert definitions["r"]["interpolation"][0]["value_m3_s"] == 200
    assert definitions["r"]["interpolated_days"] == 1


def test_edges_censored_start_insufficient_support_and_constant_history():
    result, notes = relative_high_flow(
        conditions([np.nan, 100, 100] + [1] * 30 + [np.nan])
    )
    assert result.value.iloc[:3].isna().all()
    assert result.value.iloc[3] == 0 and pd.isna(result.value.iloc[-1])
    assert notes["r"]["unfilled_days"] == 2
    unsupported, _ = relative_high_flow(conditions([np.nan, 1, np.nan]))
    assert unsupported.value.isna().all()
    constant, _ = relative_high_flow(conditions([5] * 20))
    assert constant.value.eq(0).all()


def test_append_preserves_all_rows_then_replaces_idempotently_and_checks_keys():
    frame = conditions([1] * 40 + [100, 200, 1])
    before = build_features(frame)
    result = replace_high_flow(before, frame)
    pd.testing.assert_frame_equal(
        before, result.query("metric != 'high_flow_duration'")
    )
    pd.testing.assert_frame_equal(result, replace_high_flow(result, frame))
    with pytest.raises(ValueError, match="calendar/identity"):
        replace_high_flow(before.query("metric != 'discharge_mean'"), frame)
    with pytest.raises(ValueError, match="calendar/identity"):
        replace_high_flow(result.iloc[:-1], frame)


def test_offline_append_retains_all_old_metrics_and_raw_companions(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    # Simulate a validated older product without high-flow duration.
    from hydrology.utils import high_flow

    monkeypatch.setattr(
        high_flow, "replace_high_flow", lambda features, conditions: features
    )
    target, _ = canonical.publish_rivers(config(tmp_path))
    monkeypatch.undo()
    old = target.resolve()
    before = pd.read_parquet(old / "skagit/features.parquet")
    inodes = {p.name: p.stat().st_ino for p in (old / "skagit").iterdir()}
    old_meta = json.loads((old / "skagit/metadata.json").read_text())
    monkeypatch.setattr(
        acquisition, "acquire", lambda *a, **k: pytest.fail("unexpected acquisition")
    )
    with pytest.raises(ValueError, match="byte budget"):
        recompute_high_flow(target, max_bytes=1)
    assert target.resolve() == old
    recompute_high_flow(target)
    new = target.resolve()
    after = pd.read_parquet(new / "skagit/features.parquet")
    pd.testing.assert_frame_equal(
        before, after.query("metric != 'high_flow_duration'").reset_index(drop=True)
    )
    assert new == old and not target.is_symlink()
    assert not list(canonical._paths(target)[1].glob("snapshot-*"))
    for name in [
        "conditions.parquet",
        "observations.parquet",
        "warmup.parquet",
        "coverage.parquet",
        "acquisition-ledger.json",
    ]:
        assert inodes[name] == (new / "skagit" / name).stat().st_ino
    meta = json.loads((new / "skagit/metadata.json").read_text())
    assert meta["low_flow_definition"] == old_meta["low_flow_definition"]
    assert meta["flow_pulse_definition"] == old_meta["flow_pulse_definition"]
    assert meta["high_flow_definition"]["method"] == METHOD
    canonical.validate_product(target)
    recompute_high_flow(target)
    assert target.resolve() == new
    with canonical.product_snapshot(target):
        with pytest.raises(ValueError, match="lock"):
            recompute_high_flow(target)


def test_default_publisher_and_features_cli_include_high_flow(tmp_path, monkeypatch):
    from hydrology.cli import main

    monkeypatch.setattr(acquisition, "acquire", acquired)
    target, _ = canonical.publish_rivers(config(tmp_path))
    meta = json.loads((target / "skagit/metadata.json").read_text())
    assert meta["high_flow_definition"]["reference_start"] == "2023-01-01"
    source, output = tmp_path / "input.parquet", tmp_path / "output.parquet"
    conditions([1] * 40 + [100, 200, 1]).to_parquet(source)
    assert main(["features", str(source), "--output", str(output)]) == 0
    assert pd.read_parquet(output).query(
        "metric == 'high_flow_duration'"
    ).value.tolist()[-3:] == [1, 2, 0]
    note = json.loads(Path(str(output) + ".high-flow.json").read_text())["r"]
    assert note["method"] == METHOD

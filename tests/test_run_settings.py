"""Private run defaults are always tested in isolated temporary directories."""

import json
import os
from dataclasses import replace

import pytest
from test_correctness_and_canonical import acquired, config

from hydrology import pipeline
from hydrology.cli import main
from hydrology.core import Config
from hydrology.pipelines import acquisition


def env(tmp_path, text=None):
    file = tmp_path / ".env"
    file.write_text(
        text
        or "DATA_DIR=output/Hydrology\nSTART_DATE=2023-01-01\nEND_DATE=2023-01-07\nVERBOSITY=True\n"
    )
    return file


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in [
        "DATA_DIR",
        "START_DATE",
        "END_DATE",
        "VERBOSITY",
        "MARINECAST_HYDROLOGY_CONFIG",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_cwd_file_paths_precedence_and_no_environment_mutation(tmp_path, monkeypatch):
    file = env(tmp_path)
    before = dict(os.environ)
    result = Config.load()
    assert result.product_output == str(tmp_path / "output/Hydrology")
    assert result.verbosity and result.start_date == "2023-01-01"
    assert dict(os.environ) == before and not (tmp_path / "output").exists()
    monkeypatch.setenv("DATA_DIR", "process-output")
    monkeypatch.setenv("VERBOSITY", "false")
    result = Config.load(env_file=file)
    assert (
        result.product_output == str(tmp_path / "process-output")
        and result.verbosity is False
    )
    supplied = tmp_path / "config.json"
    supplied.write_text(
        json.dumps({"product_output": "explicit-output", "verbosity": True})
    )
    result = Config.load(supplied, verbosity=False)
    assert (
        result.product_output == str(tmp_path / "explicit-output")
        and result.verbosity is False
    )


def test_explicit_file_resolves_beside_file_and_preserves_final_symlink(
    tmp_path, monkeypatch
):
    folder = tmp_path / "settings"
    folder.mkdir()
    env(folder)
    result = Config.load(env_file=folder / ".env")
    assert result.product_output == str(folder / "output/Hydrology")
    current = tmp_path / "current"
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    current.symlink_to(snapshot)
    env(
        tmp_path,
        f"DATA_DIR={current}\nSTART_DATE=2023-01-01\nEND_DATE=2023-01-07\nVERBOSITY=False\n",
    )
    assert Config.load().product_output == str(current)
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    assert Config.load().product_output == "Data/Hydrology"  # no parent search


def test_errors_aggregated_redacted_before_writes(tmp_path):
    file = env(
        tmp_path,
        "START_DATE=bad-secret\nSTART_DATE=also-secret\nEND_DATE=bad\nVERBOSITY=token-secret\nAPI_KEY=not-logged\n",
    )
    with pytest.raises(ValueError) as error:
        Config.load(env_file=file)
    message = str(error.value)
    for key in ["START_DATE", "END_DATE", "DATA_DIR", "VERBOSITY"]:
        assert key in message
    assert (
        "repeated" in message
        and "secret" not in message
        and "not-logged" not in message
    )
    assert list(tmp_path.iterdir()) == [file]
    with pytest.raises(ValueError, match="does not exist"):
        Config.load(env_file=tmp_path / "absent.env")


def test_preflight_and_false_override_stdout_stderr(tmp_path, capsys):
    env(tmp_path)
    assert main(["preflight", "--no-verbose"]) == 0
    captured = capsys.readouterr()
    settings = json.loads(captured.out)
    assert settings["VERBOSITY"] is False and captured.err == ""
    assert settings["DATA_DIR"] == str(tmp_path / "output/Hydrology")
    assert not (tmp_path / "output").exists()


def test_pipeline_progress_is_stderr_and_verbosity_does_not_change_identity(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    c = config(tmp_path)
    quiet = pipeline.prepare(c, ("discharge_mean",))
    assert capsys.readouterr().err == ""
    verbose = pipeline.prepare(replace(c, verbosity=True), ("discharge_mean",))
    captured = capsys.readouterr()
    assert (
        "[hydrology " in captured.err
        and "Prepared" in captured.err
        and captured.out == ""
    )
    assert quiet["identity"] == verbose["identity"]


def test_invalid_boolean_and_date_order(tmp_path):
    env(
        tmp_path,
        "DATA_DIR=output\nSTART_DATE=2023-02-01\nEND_DATE=2023-01-01\nVERBOSITY=1\n",
    )
    with pytest.raises(ValueError) as error:
        Config.load()
    assert "on or before" in str(error.value) and "True or False" in str(error.value)


def test_public_api_uses_file_dates_without_acquisition(tmp_path, monkeypatch):
    from hydrology import get_river_discharge

    env(tmp_path)
    seen = []

    def retained(config, metrics):
        seen.append(config)
        return acquired(config, metrics)

    monkeypatch.setattr(acquisition, "acquire", retained)
    frame = get_river_discharge()
    assert seen[0].start_date == "2023-01-01" and seen[0].end_date == "2023-01-07"
    assert seen[0].verbosity is True and len(frame) == 7 * len(seen[0].rivers)
    assert len(seen[0].rivers) == 10

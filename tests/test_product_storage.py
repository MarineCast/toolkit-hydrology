"""Storage lifecycle and interrupted directory promotion regressions."""

import os
import shutil
from dataclasses import replace

import pytest
from test_correctness_and_canonical import acquired, config

from hydrology.pipelines import acquisition, publication


def test_final_directory_and_owned_download_cleanup(tmp_path, monkeypatch):
    c = replace(config(tmp_path), product_output=str(tmp_path / "Data/Hydrology"))
    shared = tmp_path / "cache"
    shared.mkdir()
    (shared / "user-input").write_text("preserve")
    seen = []

    def acquire(settings, metrics):
        from pathlib import Path

        cache = Path(settings.cache)
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "response").write_text("download")
        seen.append(cache)
        return acquired(settings, metrics)

    monkeypatch.setattr(acquisition, "acquire", acquire)
    target, _ = publication.publish_rivers(c)
    publication.validate_product(target)
    assert target.is_dir() and not target.is_symlink()
    assert {p.name for p in target.parent.iterdir()} == {"Hydrology"}
    assert not seen[-1].exists()
    assert (shared / "user-input").read_text() == "preserve"
    assert publication._paths(target)[1].is_relative_to(tmp_path / ".marinecast-work")


def test_failed_acquisition_keeps_owned_downloads_for_resume(tmp_path, monkeypatch):
    c = config(tmp_path)
    downloads = publication._download_root(c, publication._paths(c.product_output)[1])

    def fail(settings, metrics):
        downloads.mkdir(parents=True, exist_ok=True)
        (downloads / "completed-page").write_text("resume")
        raise ValueError("provider failed")

    monkeypatch.setattr(acquisition, "acquire", fail)
    with pytest.raises(ValueError, match="provider failed"):
        publication.publish_rivers(c)
    assert (downloads / "completed-page").read_text() == "resume"
    monkeypatch.setattr(acquisition, "acquire", acquired)
    publication.publish_rivers(c)
    assert not downloads.exists()


@pytest.mark.parametrize(
    "phase,promoted", [("promoting", False), ("promoting", True), ("committed", True)]
)
def test_interrupted_promotion_recovers_exact_product(
    tmp_path, monkeypatch, phase, promoted
):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    c = config(tmp_path)
    target, _ = publication.publish_rivers(c)
    _, store, _ = publication._paths(target)
    before = (target / "catalog.json").read_bytes()
    stage = store / "snapshot-interrupted"
    shutil.copytree(target, stage)
    os.rename(target, store / "previous")
    if promoted:
        os.rename(stage, target)
    publication._journal(
        store / "promotion.json",
        {"owner": publication._owner(target), "phase": phase, "had_destination": True},
    )
    # A new writer recovers before inspecting or acquiring.
    publication.publish_rivers(c)
    assert (target / "catalog.json").read_bytes() == before
    publication.validate_product(target)
    assert not target.is_symlink()
    assert not (store / "previous").exists()
    assert not (store / "promotion.json").exists()
    assert not list(store.glob("snapshot-*"))


@pytest.mark.parametrize("relative", ["user-note.txt", "skagit/user-input.txt"])
def test_unrelated_file_in_owned_product_prevents_replacement(
    tmp_path, monkeypatch, relative
):
    monkeypatch.setattr(acquisition, "acquire", acquired)
    c = config(tmp_path)
    target, _ = publication.publish_rivers(c)
    note = target / relative
    note.write_text("keep")
    monkeypatch.setattr(
        acquisition,
        "acquire",
        lambda *a: pytest.fail("acquired before checking user file"),
    )
    with pytest.raises(ValueError, match="Unrelated files"):
        publication.publish_rivers(replace(c, end_date="2023-01-06"))
    assert note.read_text() == "keep"


def test_offline_recompute_recovers_missing_target_after_interruption(
    tmp_path, monkeypatch
):
    from hydrology import recompute_low_flow

    monkeypatch.setattr(acquisition, "acquire", acquired)
    target, _ = publication.publish_rivers(config(tmp_path))
    _, store, _ = publication._paths(target)
    before = (target / "catalog.json").read_bytes()
    os.rename(target, store / "previous")
    publication._journal(
        store / "promotion.json",
        {
            "owner": publication._owner(target),
            "phase": "promoting",
            "had_destination": True,
        },
    )
    monkeypatch.setattr(
        acquisition, "acquire", lambda *a: pytest.fail("offline acquisition")
    )
    recompute_low_flow(target)
    assert target.is_dir() and not target.is_symlink()
    assert (target / "catalog.json").read_bytes() == before
    assert not (store / "previous").exists()

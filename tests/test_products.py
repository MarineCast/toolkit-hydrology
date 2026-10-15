"""Final-product contracts and destructive-cleanup boundaries, synthetic only."""

import json

import pytest

from hydrology.core import Config
from hydrology.products import clean_downloads, staging_config


def test_cleanup_refuses_unowned_and_symlinked_downloads(tmp_path):
    with pytest.raises(ValueError, match="ownership"):
        clean_downloads(tmp_path)
    config, root = staging_config(Config(cache=str(tmp_path)), True)
    external = tmp_path / "external"
    external.mkdir()
    (external / "keep").write_text("user input")
    (root / "requests").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        clean_downloads(root)
    assert (external / "keep").read_text() == "user input"


def test_staging_resumes_same_namespace_and_preserves_native_cache(tmp_path):
    config = Config(cache=str(tmp_path))
    assert staging_config(config, False) == (config, None)
    first, root = staging_config(config, True)
    second, again = staging_config(config, True)
    assert root == again and first == second
    (root / "owner.json").write_text(json.dumps({"owner": "someone else"}))
    with pytest.raises(ValueError, match="ownership"):
        staging_config(config, True)

"""Refactor contracts: stable imports, dependency direction and source provenance."""

import ast
from importlib import import_module
from pathlib import Path

from hydrology.utils import provenance


def test_legacy_imports_resolve_to_canonical_implementations():
    for old, new, names in [
        ("hydrology.core", "hydrology.utils.config", ["Config"]),
        ("hydrology.pipeline", "hydrology.pipelines.acquisition", ["acquire", "plan"]),
        (
            "hydrology.pipeline",
            "hydrology.pipelines.processing",
            ["prepare", "river_conditions"],
        ),
        (
            "hydrology.pipeline",
            "hydrology.pipelines.releases",
            ["build", "validate_release"],
        ),
        (
            "hydrology.canonical",
            "hydrology.pipelines.publication",
            ["publish_rivers", "product_snapshot", "validate_product"],
        ),
        (
            "hydrology.low_flow",
            "hydrology.utils.low_flow",
            ["relative_low_flow", "replace_low_flow"],
        ),
        (
            "hydrology.flow_pulse",
            "hydrology.utils.flow_pulse",
            ["relative_flow_pulse", "replace_flow_pulse"],
        ),
        (
            "hydrology",
            "hydrology.main",
            ["get_river_discharge", "get_river_temperature", "publish_hydrology"],
        ),
    ]:
        before, after = import_module(old), import_module(new)
        for name in names:
            assert getattr(before, name) is getattr(after, name)


def test_utilities_do_not_depend_on_pipeline_or_entry_point_modules():
    package = Path(import_module("hydrology.utils").__file__).parent
    for file in package.glob("*.py"):
        for node in ast.walk(ast.parse(file.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    (
                        "hydrology.pipelines",
                        "hydrology.cli",
                        "hydrology.main",
                        "pipelines",
                    )
                ), file
                if node.level == 2:
                    assert node.module in {None, "utils"}, file
            elif isinstance(node, ast.Import):
                assert not any(
                    n.name.startswith(
                        ("hydrology.pipelines", "hydrology.cli", "hydrology.main")
                    )
                    for n in node.names
                ), file


def test_implementation_fingerprint_includes_nested_paths_and_duplicate_basenames(
    tmp_path, monkeypatch
):
    root = tmp_path / "hydrology"
    for folder in ["utils", "pipelines"]:
        path = root / folder
        path.mkdir(parents=True)
        (path / "config.py").write_text(folder)
    monkeypatch.setattr(provenance, "__file__", str(root / "utils/provenance.py"))
    before = provenance.implementation_fingerprint()
    assert before == provenance.digest(
        {"utils/config.py": "utils", "pipelines/config.py": "pipelines"}
    )
    (root / "utils/config.py").write_text("changed")
    assert provenance.implementation_fingerprint() != before

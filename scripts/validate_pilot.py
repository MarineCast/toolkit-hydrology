"""Explicit live/cached bounded pilot. Writes a small measured report, never source data to docs."""

import argparse
import time

import pandas as pd

from hydrology.core import Config, atomic_json
from hydrology.pipeline import build, validate_release

p = argparse.ArgumentParser()
p.add_argument("--config", default="config/pilot.json")
p.add_argument("--report", default="data/pilot-report.json")
a = p.parse_args()
started = time.perf_counter()
root, m = build(Config.load(a.config))
report = {
    "validation": validate_release(root),
    "elapsed_this_invocation_seconds": time.perf_counter() - started,
    "manifest": m,
    "release_path": str(root),
    "coverage": pd.read_parquet(root / "coverage.parquet").to_dict("records"),
}
atomic_json(a.report, report)
print(a.report)
raise SystemExit(0 if m["complete"] else 2)

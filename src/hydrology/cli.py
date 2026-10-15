"""Composable CLI; all network acquisition is explicit."""

import argparse
import json
from pathlib import Path

import pandas as pd

from .core import Config, atomic_json, atomic_parquet
from .features import build_features, fit_climatology
from .pipeline import acquire, build, plan, validate_release


def main(argv=None):
    parser = argparse.ArgumentParser(prog="hydrology")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["build", "fetch", "discover", "audit", "reconcile"]:
        p = sub.add_parser(name)
        for option in [
            "config",
            "start-date",
            "end-date",
            "cache",
            "output",
            "registry",
            "hydat",
            "climatology",
            "as-of",
            "water-mask",
            "water-mask-version",
            "receiving-regions",
        ]:
            p.add_argument("--" + option)
        p.add_argument("--stations", nargs="+")
        p.add_argument("--rivers", nargs="+")
        p.add_argument("--bbox", nargs=4, type=float)
        p.add_argument("--data-source", choices=["auto", "usgs", "wsc", "hydat"])
        p.add_argument("--h3-res", type=int)
        p.add_argument("--workers", type=int)
        p.add_argument(
            "--temporal-requirement", choices=["provider_daily", "utc_daily"]
        )
        p.add_argument("--allow-provisional", action="store_true", default=None)
        p.add_argument("--refresh", action="store_true", default=None)
        p.add_argument("--make-h3", action="store_true")
        p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("validate")
    p.add_argument("release")
    p = sub.add_parser("fit-climatology")
    p.add_argument("conditions")
    p.add_argument("--cutoff", required=True)
    p.add_argument("--reference-start")
    p.add_argument("--output", required=True)
    p.add_argument("--window", type=int, default=15)
    p.add_argument("--min-samples", type=int, default=60)
    p.add_argument("--min-years", type=int, default=3)
    p = sub.add_parser("features")
    p.add_argument("conditions")
    p.add_argument("--climatology")
    p.add_argument("--output", required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    if command == "validate":
        print(json.dumps(validate_release(args["release"]), indent=2))
        return 0
    if command == "fit-climatology":
        frame = pd.read_parquet(args.pop("conditions"))
        output = args.pop("output")
        atomic_json(output, fit_climatology(frame, **args))
        print(output)
        return 0
    if command == "features":
        baseline = (
            json.loads(Path(args["climatology"]).read_text())
            if args["climatology"]
            else None
        )
        atomic_parquet(
            args["output"],
            build_features(pd.read_parquet(args["conditions"]), climatology=baseline),
        )
        return 0
    path = args.pop("config")
    dry = args.pop("dry_run")
    make_h3 = args.pop("make_h3")
    if command == "reconcile":
        args["refresh"] = True
    config = Config.load(path, **args)
    if dry:
        print(json.dumps(plan(config), indent=2))
        return 0
    if command == "discover":
        _, metadata, outcomes, _ = acquire(config, metrics=())
        atomic_json(
            Path(config.output) / "discovery.json",
            {"metadata": metadata, "outcomes": outcomes},
        )
        print(json.dumps(metadata, indent=2))
        return 0 if all(metadata.values()) else 2
    root, manifest = build(
        config,
        make_h3=make_h3,
        metrics=("discharge_mean",)
        if command == "fetch"
        else ("discharge_mean", "temperature_mean", "temperature_max"),
    )
    print(json.dumps({"release_path": str(root), **manifest}, indent=2))
    return 0 if manifest["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

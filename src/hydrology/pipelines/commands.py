"""CLI command workflows; parsing stays in hydrology.cli."""

import json
from pathlib import Path

import pandas as pd

from ..utils.config import Config
from ..utils.features import build_features, fit_climatology
from ..utils.io import atomic_json, atomic_parquet
from .acquisition import acquire, plan
from .releases import build, validate_release


def execute(command, options):
    args = dict(options)
    if command == "build-influence":
        from .influence import build_influence

        print(json.dumps(build_influence(args["config"]), indent=2))
        return 0
    if command == "preflight":
        config = Config.load(args.pop("config"), **args)
        print(
            json.dumps(
                dict(
                    DATA_DIR=config.product_output,
                    START_DATE=config.start_date,
                    END_DATE=config.end_date,
                    VERBOSITY=config.verbosity,
                ),
                indent=2,
            )
        )
        return 0
    if command in {"recompute-low-flow", "recompute-flow-pulse", "recompute-high-flow"}:
        from .recompute import (
            recompute_flow_pulse,
            recompute_high_flow,
            recompute_low_flow,
        )

        config = Config.load(
            env_file=args["env_file"],
            product_output=args["destination"],
            verbosity=args["verbosity"],
        )
        recompute = {
            "recompute-flow-pulse": recompute_flow_pulse,
            "recompute-low-flow": recompute_low_flow,
            "recompute-high-flow": recompute_high_flow,
        }[command]
        root, catalog = recompute(config.product_output, verbosity=config.verbosity)
        print(json.dumps({"product_path": str(root), **catalog}, indent=2))
        return 0
    if command == "validate-product":
        from .publication import validate_product

        print(json.dumps(validate_product(args["destination"]), indent=2))
        return 0
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
        conditions = pd.read_parquet(args["conditions"])
        features = build_features(conditions, climatology=baseline)
        if args["low_flow_method"] == "historical_percentile":
            from ..utils.low_flow import replace_low_flow

            features = replace_low_flow(features, conditions)
        if args["flow_pulse_method"] == "historical_percentile":
            from ..utils.flow_pulse import replace_flow_pulse

            features = replace_flow_pulse(features, conditions)
        from ..utils.high_flow import replace_high_flow

        features = replace_high_flow(features, conditions)
        atomic_parquet(args["output"], features)
        atomic_json(
            str(args["output"]) + ".high-flow.json",
            features.attrs["high_flow_definitions"],
        )
        atomic_json(
            str(args["output"]) + ".low-flow.json",
            features.attrs.get("low_flow_definitions", {}),
        )
        atomic_json(
            str(args["output"]) + ".flow-pulse.json",
            features.attrs.get("flow_pulse_definitions", {}),
        )
        return 0
    path = args.pop("config")
    dry = args.pop("dry_run")
    make_h3 = args.pop("make_h3")
    metrics = tuple(args.pop("metrics", ("discharge_mean",)))
    if command == "reconcile":
        args["refresh"] = True
    config = Config.load(path, **args)
    from ..utils.settings import log

    log(
        config.verbosity,
        f"Preflight passed: {command}, {config.start_date} through {config.end_date}, DATA_DIR={config.product_output}",
    )
    if dry:
        planned = plan(config)
        if command == "publish":
            planned["writes"] = [config.cache, config.product_output]
            planned["metrics"] = metrics
            planned["publication"] = (
                "one current per-river product; private sibling staging and lock"
            )
        print(json.dumps(planned, indent=2))
        return 0
    if command == "discover":
        _, metadata, outcomes, _ = acquire(config, metrics=())
        atomic_json(
            Path(config.output) / "discovery.json",
            {"metadata": metadata, "outcomes": outcomes},
        )
        print(json.dumps(metadata, indent=2))
        return 0 if all(metadata.values()) else 2
    if command == "publish":
        from .publication import publish_rivers

        root, catalog = publish_rivers(config, metrics=metrics)
        print(json.dumps({"product_path": str(root), **catalog}, indent=2))
        from .publication import product_snapshot

        with product_snapshot(root) as snapshot:
            complete = all(
                json.loads((snapshot / rid / "manifest.json").read_text())["complete"]
                for rid in config.rivers
                if rid in catalog["rivers"]
            )
        return 0 if complete else 2
    root, manifest = build(
        config,
        make_h3=make_h3,
        metrics=("discharge_mean",)
        if command == "fetch"
        else ("discharge_mean", "temperature_mean", "temperature_max"),
    )
    print(json.dumps({"release_path": str(root), **manifest}, indent=2))
    return 0 if manifest["complete"] else 2

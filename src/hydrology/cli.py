"""Command-line parsing and dispatch; workflows live in pipelines.commands."""

import argparse

from .pipelines.commands import execute


def create_parser():
    parser = argparse.ArgumentParser(prog="hydrology")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["build", "fetch", "discover", "audit", "reconcile", "publish"]:
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
            "product-output",
        ]:
            p.add_argument("--" + option)
        p.add_argument("--stations", nargs="+")
        p.add_argument("--rivers", nargs="+")
        p.add_argument("--bbox", nargs=4, type=float)
        p.add_argument("--data-source", choices=["auto", "usgs", "wsc", "hydat"])
        p.add_argument("--h3-res", type=int)
        p.add_argument("--workers", type=int)
        p.add_argument("--acquisition-block-months", type=int)
        p.add_argument("--publication-max-bytes", type=int)
        p.add_argument("--publication-max-rows", type=int)
        p.add_argument("--minimum-daily-coverage", type=float)
        p.add_argument("--low-flow-method", choices=["historical_percentile", "fixed"])
        p.add_argument(
            "--flow-pulse-method", choices=["historical_percentile", "fixed"]
        )
        p.add_argument("--env-file")
        p.add_argument(
            "--verbose",
            dest="verbosity",
            action=argparse.BooleanOptionalAction,
            default=None,
        )
        if name == "publish":
            p.add_argument(
                "--metrics",
                nargs="+",
                choices=["discharge_mean", "temperature_mean", "temperature_max"],
                default=["discharge_mean"],
            )
        p.add_argument("--retry-wait-budget-seconds", type=float)
        p.add_argument(
            "--temporal-requirement", choices=["provider_daily", "utc_daily"]
        )
        p.add_argument("--allow-provisional", action="store_true", default=None)
        p.add_argument("--refresh", action="store_true", default=None)
        p.add_argument("--offline", action="store_true", default=None)
        p.add_argument("--make-h3", action="store_true")
        p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("build-influence")
    p.add_argument("--config", required=True)
    p = sub.add_parser("validate")
    p.add_argument("release")
    p = sub.add_parser("validate-product")
    p.add_argument("destination")
    for name in ["recompute-low-flow", "recompute-flow-pulse", "recompute-high-flow"]:
        p = sub.add_parser(name)
        p.add_argument("destination", nargs="?")
        p.add_argument("--env-file")
        p.add_argument(
            "--verbose",
            dest="verbosity",
            action=argparse.BooleanOptionalAction,
            default=None,
        )
    p = sub.add_parser("preflight")
    for option in ["config", "env-file", "start-date", "end-date", "product-output"]:
        p.add_argument("--" + option)
    p.add_argument(
        "--verbose",
        dest="verbosity",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
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
    p.add_argument(
        "--low-flow-method",
        choices=["historical_percentile", "fixed"],
        default="historical_percentile",
    )
    p.add_argument(
        "--flow-pulse-method",
        choices=["historical_percentile", "fixed"],
        default="historical_percentile",
    )
    return parser


def main(argv=None):
    parser = create_parser()
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    if command == "publish" and args.get("make_h3"):
        parser.error(
            "publish is native per-river only; H3 requires the separate build workflow"
        )
    return execute(command, args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Acquisition pipeline: explicit stages, qualified inputs and outputs."""

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from ..utils.contracts import empty_observations, validate_observations
from ..utils.http import Client, RequestDeferred, UnsupportedVariable
from ..utils.ledger import Ledger
from ..utils.providers import HYDAT, USGS, WSC
from ..utils.registry import select_registry
from ..utils.settings import log
from ..utils.temporal import aggregate_utc


def date_blocks(start, end, months=1):
    if type(months) is not int or not 1 <= months <= 240:
        raise ValueError("One to 240 acquisition months required")
    a = pd.Timestamp(start)
    stop = pd.Timestamp(end)
    while a <= stop:
        b = min(a + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(months - 1), stop)
        yield a.date().isoformat(), b.date().isoformat()
        a = b + pd.Timedelta(days=1)


def plan(config):
    rivers = select_registry(config)
    warmup = (
        (pd.Timestamp(config.start_date) - pd.Timedelta(days=30)).date().isoformat()
    )
    return {
        "config": config.as_dict(),
        "rivers": rivers,
        "acquisition_start": warmup,
        "blocks": list(
            date_blocks(warmup, config.end_date, config.acquisition_block_months)
        ),
        "cache_policy": "page snapshots reused unless refresh=true; refresh creates new content snapshots",
        "writes": [config.cache, config.output],
        "download": False,
    }


def acquire(config, metrics=("discharge_mean", "temperature_mean", "temperature_max")):
    rivers = select_registry(config)
    client = Client(config)
    metadata = {}
    outcomes = {}
    all_frames = []
    begin = (pd.Timestamp(config.start_date) - pd.Timedelta(days=30)).date().isoformat()

    blocks = list(date_blocks(begin, config.end_date, config.acquisition_block_months))
    ledger = Ledger(config, rivers, blocks, metrics)

    def one(river):
        log(
            config.verbosity,
            f"Acquiring retained/native support for river {river['river_id']}",
        )
        client.scope.river_id = river["river_id"]
        station = river["stations"][0]
        sid = station["station_id"]
        provider = station["provider"]
        result = {}
        frames = []
        meta = {}
        ledger.update(river, "metadata", None, None, "running")
        try:
            if config.data_source not in ("auto", provider) and not (
                provider == "wsc" and config.data_source == "hydat"
            ):
                raise ValueError(
                    f"Explicit source {config.data_source} incompatible with {sid}"
                )
            if config.data_source == "hydat" and not config.hydat:
                raise ValueError("hydat source requires a local snapshot path")
            adapter = (
                USGS(client)
                if provider == "usgs"
                else (HYDAT(config.hydat) if config.hydat else WSC(client))
            )
            meta = adapter.discover(sid)
        except Exception as exc:
            state = "deferred" if isinstance(exc, RequestDeferred) else "failed"
            ledger.update(river, "metadata", None, None, state, reason=str(exc))
            prefix = "deferred" if state == "deferred" else "failure"
            for metric in metrics:
                for a, b in blocks:
                    ledger.update(
                        river, metric, a, b, "not_attempted", reason=f"metadata {state}"
                    )
            return (
                river,
                frames,
                meta,
                {m: f"{prefix}: {exc}" for m in metrics or ("metadata",)},
            )
        ledger.update(river, "metadata", None, None, "completed")
        for metric in metrics:
            unsupported = station.get("unsupported_metrics", {}).get(metric)
            if unsupported:
                for a, b in blocks:
                    ledger.update(
                        river, metric, a, b, "unsupported", reason=unsupported
                    )
                result[metric] = f"unsupported: {unsupported}"
                continue
            chunks = []
            blocked = None
            for block_start, block_end in blocks:
                a = max(block_start, station["valid_from"])
                b = min(block_end, station.get("valid_to") or block_end)
                if blocked:
                    state = (
                        "unsupported"
                        if blocked[0] == "unsupported"
                        else "not_attempted"
                    )
                    ledger.update(
                        river, metric, block_start, block_end, state, reason=blocked[1]
                    )
                    continue
                if a > b:
                    ledger.update(
                        river, metric, block_start, block_end, "outside_relationship"
                    )
                    continue
                ledger.update(
                    river,
                    metric,
                    block_start,
                    block_end,
                    "running",
                    query_start=a,
                    query_end=b,
                )
                try:
                    if config.temporal_requirement == "utc_daily":
                        if not hasattr(adapter, "continuous"):
                            raise UnsupportedVariable(
                                "Local HYDAT daily cannot reconstruct UTC"
                            )
                        if (
                            provider == "wsc"
                            and b
                            < (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30))
                            .date()
                            .isoformat()
                        ):
                            raise UnsupportedVariable(
                                "Current WSC adapter has 30-day timestamp retention; native daily cannot reconstruct UTC"
                            )
                        samples = adapter.continuous(
                            sid,
                            metric,
                            (pd.Timestamp(a) - pd.Timedelta(days=1)).date().isoformat(),
                            b,
                        )
                        chunk = aggregate_utc(
                            samples,
                            sid,
                            metric,
                            a,
                            b,
                            max_hold_seconds=config.max_hold_seconds,
                            minimum_coverage=config.minimum_coverage,
                            allow_provisional=config.allow_provisional,
                            provider=provider,
                        )
                    else:
                        chunk = adapter.observations(sid, metric, a, b)
                    validate_observations(chunk)
                    chunks.append(chunk)
                    ledger.update(
                        river,
                        metric,
                        block_start,
                        block_end,
                        "completed" if len(chunk) else "empty",
                        rows=len(chunk),
                        nonnull_rows=int(chunk.value.notna().sum()),
                    )
                except Exception as exc:
                    state = (
                        "deferred"
                        if isinstance(exc, RequestDeferred)
                        else "unsupported"
                        if isinstance(exc, UnsupportedVariable)
                        else "failed"
                    )
                    detail = f"{type(exc).__name__}: {exc}"
                    ledger.update(
                        river, metric, block_start, block_end, state, reason=detail
                    )
                    blocked = state, detail
            f = pd.concat(chunks, ignore_index=True) if chunks else empty_observations()
            validate_observations(f)
            if len(f):
                frames.append(f)
            result[metric] = (
                f"{'failure' if blocked[0] == 'failed' else blocked[0]}: {blocked[1]}"
                if blocked
                else "observed"
                if f.value.notna().any()
                else "no_observations"
            )
        return river, frames, meta, result

    with ThreadPoolExecutor(max_workers=config.workers) as pool:
        for river, frames, meta, result in pool.map(one, rivers):
            all_frames.extend(frames)
            metadata[river["river_id"]] = meta
            outcomes[river["river_id"]] = result
    observations = (
        pd.concat(all_frames, ignore_index=True) if all_frames else empty_observations()
    )
    validate_observations(observations)
    return (
        observations,
        metadata,
        outcomes,
        {
            "http_requests": client.requests,
            "cache_hits": client.hits,
            "source_requests": sorted(client.sources.values(), key=lambda e: e["url"]),
            "source_requests_by_river": {
                rid: sorted(entries.values(), key=lambda e: e["url"])
                for rid, entries in client.scoped_sources.items()
            },
            "block_ledger": ledger.snapshot(),
            "block_ledger_path": str(ledger.path),
        },
    )

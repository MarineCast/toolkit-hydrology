"""Shared config helpers; no acquisition or output side effects on import."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass, fields
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


def iso_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
        raise ValueError("Dates must be YYYY-MM-DD")
    return date.fromisoformat(str(value))


@dataclass(frozen=True)
class Config:
    start_date: str = "2009-01-01"
    end_date: str = ""
    bbox: tuple | None = None
    rivers: tuple = (
        "fraser",
        "skagit",
        "snohomish",
        "nooksack",
        "cowichan",
        "columbia",
        "puyallup",
        "elwha",
        "skokomish",
        "queets",
    )
    stations: tuple | None = None
    data_source: str = "auto"
    cache: str = "data/cache"
    output: str = "data/releases"
    registry: str | None = None
    product_output: str = "Data/Hydrology"
    publication_max_bytes: int = 536870912
    publication_max_rows: int = 2000000
    minimum_daily_coverage: float = 1.0
    h3_res: int = 6
    timeout: float = 45
    retries: int = 3
    rate_seconds: float = 1.0
    retry_wait_budget_seconds: float = 60.0
    workers: int = 1
    acquisition_block_months: int = 1
    refresh: bool = False
    offline: bool = False
    allow_provisional: bool = False
    as_of: str | None = None
    temporal_requirement: str = "provider_daily"
    hydat: str | None = None
    climatology: str | None = None
    water_mask: str | None = None
    water_mask_version: str | None = None
    receiving_regions: str | None = None
    low_flow_threshold: float = 10.0
    low_flow_method: str = "historical_percentile"
    flow_pulse_method: str = "historical_percentile"
    high_flow_method: str = "historical_percentile"
    verbosity: bool = False
    pulse_threshold: float = 1000.0
    max_hold_seconds: int = 3600
    minimum_coverage: float = 0.9
    max_snap_m: float = 3000

    def __post_init__(self):
        if not self.end_date:
            object.__setattr__(
                self,
                "end_date",
                (pd.Timestamp.now(tz="UTC").date() - timedelta(days=1)).isoformat(),
            )
        if iso_date(self.start_date) > iso_date(self.end_date):
            raise ValueError("start_date > end_date")
        if iso_date(self.end_date) >= pd.Timestamp.now(tz="UTC").date():
            raise ValueError(
                "Only completed days are supported; end_date must precede today"
            )
        if (
            self.publication_max_bytes < 1
            or self.publication_max_rows < 1
            or not 0 < self.minimum_daily_coverage <= 1
        ):
            raise ValueError("Invalid publication/coverage limits")
        if not all(
            math.isfinite(x) for x in (self.low_flow_threshold, self.pulse_threshold)
        ):
            raise ValueError("Feature thresholds must be finite")
        if self.low_flow_method not in {"historical_percentile", "fixed"}:
            raise ValueError("Unknown low-flow method")
        if self.flow_pulse_method not in {"historical_percentile", "fixed"}:
            raise ValueError("Unknown flow-pulse method")
        if self.high_flow_method != "historical_percentile":
            raise ValueError("Unknown high-flow method")
        if type(self.verbosity) is not bool:
            raise ValueError("verbosity must be True or False")
        if not 0 <= self.h3_res <= 15:
            raise ValueError("H3 resolution must be 0..15")
        if not 1 <= self.workers <= 4:
            raise ValueError("workers must be 1..4")
        if (
            type(self.acquisition_block_months) is not int
            or not 1 <= self.acquisition_block_months <= 240
        ):
            raise ValueError(
                "acquisition_block_months must be an integer from 1 to 240"
            )
        if (
            self.temporal_requirement != "provider_daily"
            and self.acquisition_block_months != 1
        ):
            raise ValueError(
                "Larger acquisition blocks require native provider-daily data"
            )
        if self.timeout <= 0 or self.retries < 0 or self.rate_seconds < 0:
            raise ValueError("Invalid HTTP limits")
        if (
            not math.isfinite(self.retry_wait_budget_seconds)
            or self.retry_wait_budget_seconds < 0
        ):
            raise ValueError("retry_wait_budget_seconds must be finite and nonnegative")
        if not 0 < self.minimum_coverage <= 1 or self.max_hold_seconds <= 0:
            raise ValueError("Invalid aggregation support")
        if self.temporal_requirement not in {"provider_daily", "utc_daily"}:
            raise ValueError("Unsupported temporal requirement")
        if self.data_source not in {"auto", "usgs", "wsc", "hydat"}:
            raise ValueError("Unsupported data source")
        if self.bbox is not None:
            w, s, e, n = self.bbox
            if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
                raise ValueError(
                    "bbox must be west,south,east,north; dateline crossing unsupported"
                )
        if self.as_of and pd.Timestamp(self.as_of).tzinfo is None:
            raise ValueError("as_of must have an explicit timezone")

    @classmethod
    def load(cls, path=None, env_file=None, **overrides):
        shared = os.environ.get("MARINECAST_HYDROLOGY_CONFIG")
        raw = json.loads(Path(shared).read_text()) if shared else {}
        if path:
            raw.update(json.loads(Path(path).read_text()))
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown configuration fields: {unknown}")
        raw.update({k: v for k, v in overrides.items() if v is not None})
        from .settings import resolve

        raw = {**raw, **resolve(raw, env_file)}
        return cls(**raw)

    def as_dict(self):
        return asdict(self)

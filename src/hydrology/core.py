"""Versioned contracts, validated configuration, and atomic local artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, fields
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

VERSION = "0.1.0"
STATUSES = {"valid", "partial", "unavailable", "unknown", "not_applicable"}
OBS_KEY = ["station_id", "series_id", "metric", "date", "temporal_basis"]
OBS_COLUMNS = OBS_KEY + [
    "value",
    "unit",
    "status",
    "provider",
    "origin",
    "raw_flags",
    "coverage",
    "interval_start",
    "interval_end",
    "day_definition",
    "retrieved_at",
    "available_at",
    "source_modified_at",
    "source_release",
    "record_id",
]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(
                value, handle, indent=2, sort_keys=True, default=str, allow_nan=False
            )
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_parquet(path, frame):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(fd)
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


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
    )
    stations: tuple | None = None
    data_source: str = "auto"
    cache: str = "data/cache"
    output: str = "data/releases"
    registry: str | None = None
    h3_res: int = 6
    timeout: float = 45
    retries: int = 3
    rate_seconds: float = 1.0
    workers: int = 1
    refresh: bool = False
    allow_provisional: bool = False
    as_of: str | None = None
    temporal_requirement: str = "provider_daily"
    hydat: str | None = None
    climatology: str | None = None
    water_mask: str | None = None
    water_mask_version: str | None = None
    receiving_regions: str | None = None
    low_flow_threshold: float = 10.0
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
        if not 0 <= self.h3_res <= 15:
            raise ValueError("H3 resolution must be 0..15")
        if not 1 <= self.workers <= 4:
            raise ValueError("workers must be 1..4")
        if self.timeout <= 0 or self.retries < 0 or self.rate_seconds < 0:
            raise ValueError("Invalid HTTP limits")
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
    def load(cls, path=None, **overrides):
        shared = os.environ.get("MARINECAST_HYDROLOGY_CONFIG")
        raw = json.loads(Path(shared).read_text()) if shared else {}
        if path:
            raw.update(json.loads(Path(path).read_text()))
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown configuration fields: {unknown}")
        raw.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**raw)

    def as_dict(self):
        return asdict(self)


def empty_observations():
    return pd.DataFrame(columns=OBS_COLUMNS)


def validate_observations(frame):
    missing = set(OBS_COLUMNS) - set(frame)
    if missing:
        raise ValueError(f"Missing observation columns: {missing}")
    if frame.duplicated(OBS_KEY).any():
        raise ValueError("Duplicate observation keys")
    if not set(frame.status).issubset(STATUSES):
        raise ValueError("Invalid status")
    if ((frame.status == "valid") & frame.value.isna()).any():
        raise ValueError("Valid value cannot be null")
    if not set(frame.temporal_basis).issubset({"provider_daily", "utc_daily"}):
        raise ValueError("Invalid temporal basis")
    if (
        frame.loc[
            frame.temporal_basis == "utc_daily", ["interval_start", "interval_end"]
        ]
        .isna()
        .any()
        .any()
    ):
        raise ValueError("UTC records require known boundaries")
    return {"rows": len(frame), "unique": True}


def eligible(frame, as_of=None, allow_provisional=False):
    result = frame.copy()
    result.loc[result.status != "valid", "value"] = float("nan")
    if not allow_provisional:
        provisional = result.raw_flags.fillna("").str.contains(
            "Provisional", case=False
        )
        result.loc[provisional, ["value", "status"]] = [float("nan"), "unavailable"]
    if as_of:
        # Unknown historic availability is not proof of availability at cutoff.
        available = pd.to_datetime(result.available_at, utc=True, errors="coerce")
        result = result.loc[
            available.notna() & (available <= pd.Timestamp(as_of))
        ].copy()
        result = result.loc[
            pd.to_datetime(result.date, utc=True) < pd.Timestamp(as_of).normalize()
        ]
    return result

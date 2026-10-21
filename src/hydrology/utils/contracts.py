"""Shared contracts helpers; no acquisition or output side effects on import."""

from __future__ import annotations

import numpy as np
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


def empty_observations():
    return pd.DataFrame(columns=OBS_COLUMNS)


def validate_values(frame):
    """Nulls remain missing; any supplied numerical value must be finite."""
    values = pd.to_numeric(frame.value.dropna(), errors="raise")
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("Non-finite value")


def validate_observations(frame):
    missing = set(OBS_COLUMNS) - set(frame)
    if missing:
        raise ValueError(f"Missing observation columns: {missing}")
    validate_values(frame)
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

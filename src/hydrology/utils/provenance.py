"""Shared provenance helpers; no acquisition or output side effects on import."""

from __future__ import annotations

import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path

import pandas as pd


def runtime_fingerprint():
    return {
        "python": platform.python_version(),
        "dependencies": {
            name: version(name)
            for name in (
                "pandas",
                "pyarrow",
                "numpy",
                "requests",
                "h3",
                "shapely",
                "pyproj",
            )
        },
    }


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


SOURCE_FIELDS = ("source_release", "retrieved_at", "record_id", "source_modified_at")


def source_references(record):
    """Read additive provenance, accepting older rows with scalar references only."""
    refs = record.get("source_references")
    if isinstance(refs, str):
        return json.loads(refs)
    return [
        {k: record[k] for k in SOURCE_FIELDS if k in record and pd.notna(record[k])}
    ]


def merge_source_references(records):
    refs = {
        json.dumps(ref, sort_keys=True, allow_nan=False)
        for record in records
        for ref in source_references(record)
    }
    return "[" + ",".join(sorted(refs)) + "]"


def deduplicate_observations(frame, keys):
    """Collapse equal scientific rows; preserve each page/record provenance reference."""
    frame = frame.copy()
    repeated = frame.duplicated(keys, keep=False)
    if not repeated.any():
        return frame
    scientific = [c for c in frame if c not in (*SOURCE_FIELDS, "source_references")]
    rows = []
    for _, group in frame.loc[repeated].groupby(keys, dropna=False, sort=True):
        if len(group[scientific].drop_duplicates()) != 1:
            raise ValueError("Conflicting duplicate observations")
        records = group.to_dict("records")
        # A deterministic representative retains the original scalar interface.
        representative = min(records, key=lambda r: merge_source_references([r])).copy()
        representative["source_references"] = merge_source_references(records)
        rows.append(representative)
    return pd.concat([frame.loc[~repeated], pd.DataFrame(rows)], ignore_index=True)


def implementation_fingerprint():
    """Fingerprint all package Python sources by relative path after reorganization."""
    package = Path(__file__).parents[1]
    return digest(
        {
            p.relative_to(package).as_posix(): p.read_text()
            for p in sorted(package.rglob("*.py"))
        }
    )

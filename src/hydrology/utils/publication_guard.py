"""Fail closed before replacing retained observations with weaker support."""

import json

import pandas as pd

POLICY = "nondecreasing-observed-support-v1"
KEY = ["station_id", "metric", "date", "temporal_basis"]


class CoverageRegressionError(ValueError):
    """A proposed publication would discard or downgrade retained support."""


def check_scope(previous, config, metrics, river):
    """Reject incompatible or cropped replacements before provider dispatch."""
    rid = river["river_id"]
    if (
        previous["station_id"] != river["stations"][0]["station_id"]
        or previous["temporal_basis"] != config.temporal_requirement
    ):
        raise CoverageRegressionError(
            f"{rid}: coverage regression guard refuses station/temporal-basis replacement"
        )
    if (
        config.start_date > previous["start_date"]
        or config.end_date < previous["end_date"]
    ):
        raise CoverageRegressionError(
            f"{rid}: coverage regression guard requires the full retained window "
            f"{previous['start_date']} through {previous['end_date']}"
        )
    retained = previous["eligibility"]["metrics"]
    omitted = sorted(
        name
        for name, entry in retained.items()
        if entry["eligible_days"] > 0 and name not in metrics
    )
    if omitted:
        raise CoverageRegressionError(
            f"{rid}: coverage regression guard refuses omitted observed metrics: "
            + ", ".join(omitted)
        )


def _flags(raw):
    """Compare explicit provider flag values, without ranking unknown qualifiers."""
    if raw is None or pd.isna(raw):
        return set()
    parsed = json.loads(raw)

    def values(item):
        if isinstance(item, dict):
            return [v for child in item.values() for v in values(child)]
        if isinstance(item, list):
            return [v for child in item for v in values(child)]
        if isinstance(item, str):
            return [item.strip().lower()]
        return [] if item is None else ["opaque:" + json.dumps(item, sort_keys=True)]

    return set(values(parsed))


def check_observations(previous, candidate, river_id):
    """Require every previously eligible observation and its known quality/support.

    Revised official numerical values are allowed. No imputation, source fallback,
    gauge aggregation or automatic merge is performed by this policy.
    """
    previous = previous.copy()
    candidate = candidate.copy()
    for frame in (previous, candidate):
        frame["date"] = pd.to_datetime(frame.date).dt.strftime("%Y-%m-%d")
        if frame.duplicated(KEY).any():
            raise CoverageRegressionError(f"{river_id}: ambiguous replacement keys")
    old = previous.loc[previous.value.notna() & previous.status.eq("valid")].set_index(
        KEY
    )
    new = candidate.set_index(KEY).reindex(old.index)
    lost = new.value.isna() | new.status.ne("valid")
    if lost.any():
        examples = ", ".join(f"{key[1]}:{key[2]}" for key in old.index[lost][:3])
        raise CoverageRegressionError(
            f"{river_id}: coverage regression guard refuses {int(lost.sum())} "
            f"lost eligible observations ({examples}); retained product unchanged"
        )
    # Known interval support may improve, but cannot disappear or decrease.
    coverage_lost = old.coverage.notna() & (
        new.coverage.isna() | (new.coverage < old.coverage)
    )
    weaker = coverage_lost | new.unit.ne(old.unit) | new.origin.ne(old.origin)
    penalties = {"provisional", "estimated", "partial day"}
    known = penalties | {"approved"}
    for index, before, after in zip(old.index, old.raw_flags, new.raw_flags):
        a, b = _flags(before), _flags(after)
        if (
            ("approved" in a and "approved" not in b)
            or ((b - a) & penalties)
            or (a - known) != (b - known)
        ):
            weaker.loc[index] = True
    if weaker.any():
        raise CoverageRegressionError(
            f"{river_id}: coverage regression guard refuses {int(weaker.sum())} "
            "observations with downgraded units, origin, approval, flags or support"
        )
    return {
        "policy": POLICY,
        "previous_eligible_observations": len(old),
        "preserved_eligible_observations": len(old),
        "revised_values": int(new.value.ne(old.value).sum()),
    }

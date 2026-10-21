"""Species-neutral, explicitly exploratory distance and past-day lag factors."""

from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

from .registry import load_registry

METHOD = "river-influence-water-r8-min-child-lag-v2"
SIGNALS = {
    "discharge": ("Discharge influence", "weighted gauge m3/s"),
    "relative_flow": ("Relative flow influence", "index"),
}


def validate_outlet_bindings(rivers, binding_rows):
    """Bind curated river identities to exact named research outlets, never proximity."""
    curated = {r["river_id"]: r for r in load_registry()["rivers"]}
    outlets = []
    for rid, river in sorted(rivers.items()):
        expected = curated.get(rid, {}).get("research_outlet_binding")
        if expected and (
            river["name"] != expected["name"]
            or river["outlet_id"] != expected["outlet_id"]
        ):
            raise ValueError(f"{rid}: curated river/outlet identity mismatch")
        matches = [
            row
            for row in binding_rows
            if row["name"] == river["name"]
            and row["canonical_fluvial_mouth_id"] == river["outlet_id"]
        ]
        if len(matches) != 1:
            raise ValueError("Explicit named river/outlet binding mismatch")
        binding = matches[0]
        if expected and (
            binding.get("binding_kind") != expected["binding_kind"]
            or binding.get("model_eligible") is not False
            or binding.get("physical_delta_branches_qualified") is not False
            or binding.get("attachment_by_resolution", {}).get("8", {}).get("status")
            != "connected_with_recorded_source_registration_gap"
        ):
            raise ValueError(f"{rid}: unqualified curated R8 research outlet binding")
        outlets.append({"id": rid, **river, "binding": binding})
    return outlets


def validate_profiles(config):
    """Reject ambiguous, negative, non-finite or excessive scenario definitions."""
    for key in ["distance_profiles", "lag_profiles"]:
        profiles = config[key]
        if not 1 <= len(profiles) <= 20:
            raise ValueError("One to twenty profiles required")
        ids = [p["id"] for p in profiles]
        if len(set(ids)) != len(ids) or any(
            not re.fullmatch(r"[a-z0-9-]+", p) for p in ids
        ):
            raise ValueError("Unique simple profile ids required")
        for p in profiles:
            if not isinstance(p["label"], str) or not p["label"]:
                raise ValueError("Profile label required")
        if (
            config["defaults"]["distance" if key == "distance_profiles" else "lag"]
            not in ids
        ):
            raise ValueError("Default profile missing")
    for p in config["distance_profiles"]:
        if p["kind"] not in {"exponential", "gaussian"}:
            raise ValueError("Unknown distance kernel")
        if not all(
            type(p[k]) in (float, int) and math.isfinite(p[k])
            for k in ["scale_km", "peak_km", "cutoff_km"]
        ):
            raise ValueError("Finite distances required")
        if (
            not 0 < p["scale_km"] <= 2000
            or not 0 <= p["peak_km"] < p["cutoff_km"] <= 2000
        ):
            raise ValueError("Invalid distance scale/peak/cutoff")
        if p["kind"] == "exponential" and p["peak_km"] != 0:
            raise ValueError("Exponential peak must be zero")
    for p in config["lag_profiles"]:
        if not 1 <= len(p["weights"]) <= 367:
            raise ValueError("Bounded lag weights required")
        days = [v["days"] for v in p["weights"]]
        if len(set(days)) != len(days) or any(
            type(d) is not int or not 0 <= d <= 366 for d in days
        ):
            raise ValueError("Unique past-day lag offsets required")
        if (
            any(
                type(v["weight"]) not in (float, int)
                or not math.isfinite(v["weight"])
                or v["weight"] < 0
                for v in p["weights"]
            )
            or sum(v["weight"] for v in p["weights"]) <= 0
        ):
            raise ValueError(
                "Nonnegative finite lag weights with positive sum required"
            )
    if not 1 <= len(config["rivers"]) <= 30:
        raise ValueError("One to thirty explicit rivers required")
    for river in config["rivers"].values():
        if not math.isfinite(river["gain"]) or not 0 <= river["gain"] <= 100:
            raise ValueError("Invalid river gain")
    outlets = [v["outlet_id"] for v in config["rivers"].values()]
    if len(set(outlets)) != len(outlets):
        raise ValueError("One river per explicit outlet; no duplicated discharge")


def distance_weights(distances_m, profile, gain=1):
    distances = np.asarray(distances_m, dtype=float) / 1000
    if np.any(np.isfinite(distances) & (distances < 0)):
        raise ValueError("Negative water distance")
    weights = (
        np.exp(-distances / profile["scale_km"])
        if profile["kind"] == "exponential"
        else np.exp(
            -0.5 * ((distances - profile["peak_km"]) / profile["scale_km"]) ** 2
        )
    )
    weights[distances > profile["cutoff_km"]] = 0
    return weights * gain


def lagged(values, profile):
    series = pd.Series(values, dtype=float)
    terms = [(v["days"], v["weight"]) for v in profile["weights"] if v["weight"] > 0]
    total = sum(w for _, w in terms)
    # Arithmetic propagates unknown positive-weight days; no edge padding or renormalization.
    return sum(series.shift(d) * (w / total) for d, w in terms).to_numpy()


def combine(weights, signals):
    """Reference evaluation: known subtotal plus route coverage, strict temporal support."""
    weights, signals = (
        np.asarray(weights, dtype=float),
        np.asarray(signals, dtype=float),
    )
    if weights.shape != signals.shape or weights.ndim != 1:
        raise ValueError("One signal and weight per river required")
    known = np.isfinite(weights)
    active = known & (weights > 0)
    value = (
        None
        if not known.any() or np.any(active & ~np.isfinite(signals))
        else float(np.sum(weights[active] * signals[active]))
    )
    return {
        "value": value,
        "known_rivers": int(known.sum()),
        "active_rivers": int(active.sum()),
        "total_rivers": len(weights),
    }

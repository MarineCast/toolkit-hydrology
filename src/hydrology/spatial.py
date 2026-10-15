"""Conservative, versioned water-only H3 graph; never straight-line across land."""

from __future__ import annotations

import heapq
import json
from pathlib import Path

import h3
import pandas as pd
from pyproj import Geod
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import unary_union

from .core import atomic_parquet, digest

GEOD = Geod(ellps="WGS84")


def read_geometry(path):
    raw = json.loads(Path(path).read_text())
    if raw.get("type") == "FeatureCollection":
        return unary_union([shape(f["geometry"]) for f in raw["features"]])
    return shape(raw["geometry"] if raw.get("type") == "Feature" else raw)


def distance(a, b):
    return abs(GEOD.inv(*a, *b)[2])


def water_segment(mask, a, b):
    # Densify geodesic; each full segment must lie inside the supplied water polygon.
    n = max(0, int(distance(a, b) // 100))
    points = [a] + (GEOD.npts(*a, *b, n) if n else []) + [b]
    return mask.covers(LineString(points))


def map_rivers(config, rivers):
    if (
        not config.water_mask
        or not config.water_mask_version
        or not config.receiving_regions
    ):
        raise ValueError(
            "Mapping requires versioned water_mask GeoJSON and receiving_regions GeoJSON"
        )
    mask = read_geometry(config.water_mask)
    if not mask.is_valid:
        raise ValueError("Invalid water mask; repair in source producer")
    regions_raw = json.loads(Path(config.receiving_regions).read_text())
    regions = {
        f["properties"]["receiving_region"]: shape(f["geometry"])
        for f in regions_raw["features"]
    }
    for r in rivers:
        if not r["mouths"]:
            raise ValueError(f"{r['river_id']}: verified mouth geometries unavailable")
        if any(not m.get("source") for m in r["mouths"]):
            raise ValueError("Each mouth requires a provenance source")
        if r["receiving_region"] not in regions:
            raise ValueError("Missing receiving-region geometry")
    identity = digest(
        {
            "mask": mapping(mask),
            "version": config.water_mask_version,
            "regions": regions_raw,
            "resolution": config.h3_res,
            "domain": config.bbox,
            "rivers": rivers,
            "method": "water-graph-1",
            "snap": config.max_snap_m,
        }
    )
    cached = Path(config.cache) / "spatial" / f"{identity}.parquet"
    if cached.exists():
        return pd.read_parquet(cached)
    cells = sorted(h3.geo_to_cells(mapping(mask), config.h3_res))
    points = {cell: tuple(reversed(h3.cell_to_latlng(cell))) for cell in cells}
    points = {c: p for c, p in points.items() if mask.covers(Point(p))}
    if len(points) > 500000:
        raise ValueError("Graph exceeds bounded v1 limit; supply regional mask")
    graph = {c: [] for c in points}
    for c, p in points.items():
        for other in sorted(h3.grid_disk(c, 1)):
            if other in points and other > c and water_segment(mask, p, points[other]):
                d = distance(p, points[other])
                graph[c].append((other, d))
                graph[other].append((c, d))
    rows = []
    for river in rivers:
        region = regions[river["receiving_region"]]
        allowed = {c for c, p in points.items() if region.covers(Point(p))}
        best = {}
        queue = []
        # Multi-source mouth routing selects one shortest river path; never allocates discharge per mouth.
        for mouth in river["mouths"]:
            origin = (mouth["longitude"], mouth["latitude"])
            candidates = sorted((distance(origin, points[c]), c) for c in allowed)
            snap = next(
                (
                    (d, c)
                    for d, c in candidates
                    if d <= config.max_snap_m and water_segment(mask, origin, points[c])
                ),
                None,
            )
            if snap:
                d, c = snap
                if c not in best or d < best[c][0]:
                    best[c] = (d, mouth["mouth_id"])
                    heapq.heappush(queue, (d, c, mouth["mouth_id"]))
        while queue:
            d, c, mouth = heapq.heappop(queue)
            if (d, mouth) != best[c]:
                continue
            for other, edge in graph[c]:
                if other not in allowed:
                    continue
                candidate = (d + edge, mouth)
                if other not in best or candidate < best[other]:
                    best[other] = candidate
                    heapq.heappush(queue, (candidate[0], other, mouth))
        for cell in sorted(points):
            p = points[cell]
            if config.bbox:
                w, s, e, n = config.bbox
                if not (w <= p[0] <= e and s <= p[1] <= n):
                    continue
            reachable = cell in best
            rows.append(
                dict(
                    river_id=river["river_id"],
                    h3_index=cell,
                    mouth_id=best[cell][1] if reachable else None,
                    water_distance_m=best[cell][0] if reachable else None,
                    receiving_region=river["receiving_region"],
                    status="valid" if reachable else "unavailable",
                    mapping_id=identity,
                    method="receiving_region_then_shortest_water_graph_path",
                    water_mask_version=config.water_mask_version,
                    h3_resolution=config.h3_res,
                )
            )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("No H3 centers supported at requested resolution")
    atomic_parquet(cached, result)
    return result


def associations(links):
    # Stable lexicographic river ID tie break. All links remain available separately.
    return (
        links.loc[links.status == "valid"]
        .sort_values(["h3_index", "water_distance_m", "river_id"])
        .drop_duplicates("h3_index")
    )


def dynamic_h3(features, links):
    if len(features) and set(features.temporal_basis) != {"utc_daily"}:
        raise ValueError("Strict UTC H3 table rejects provider-native daily features")
    chosen = associations(links)
    for date, group in features.groupby("date", sort=True):
        merged = group.merge(
            chosen, on="river_id", suffixes=("", "_link"), validate="many_to_many"
        )
        merged["metric"] = "associated_river_" + merged.metric + "_proxy"
        merged["contributor_river_id"] = merged.river_id
        merged["contributor_station_id"] = merged.station_id
        if merged.duplicated(["date", "h3_index", "metric"]).any():
            raise ValueError("Duplicate H3 product keys")
        yield date, merged

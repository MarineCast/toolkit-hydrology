# Exploratory river influence

This configured research product selects ten representative upstream gauges
with Seascape's byte-pinned named-outlet R8 water-network relationships. It estimates an
influence index, not marine discharge, salinity, a transported plume or whale suitability.
Source rights and registration limits follow the retained Seascape research manifest and
named-outlet registry. No acquisition or source alteration is part of this pipeline.

Inputs are explicit paths in `config/river-influence.json`, resolved relative to that file.
The study manifest pins the exact R6 reporting membership and R8 relationship file.
River-to-outlet identities must agree with the supplied named bindings; nearest-coordinate
substitution is prohibited. One modeled main-basin outlet is used per river; distributary
flows are not duplicated. Columbia's modeled outlet is in the estuary, upstream of the
physical ocean mouth. Its distances originate there; all outlet coordinates and source
registration limits are retained for inspection. This first version does not qualify
physical mouth flux, gauge-to-mouth travel time, bathymetry-dependent transport or currents.

For each R6 reporting cell, the spatial proxy is the **minimum reachable R8 child-water
representative distance** from the named outlet, including the producer's connector costs.
This is an explicitly derived nearest-support distance, not an R6 center distance or area
mean. R8 routes are taken from the complete retained producer network before exact R6
reporting selection. Missing/disconnected routes remain unknown; no land-crossing fallback.

Distance profiles define either `exp(-d/scale)` or
`exp(-0.5*((d-peak)/scale)^2)`, multiplied by a nonnegative river gain; weights are zero
beyond an explicit cutoff. They are not normalized across rivers or across cells.
Overlaps add; weights do not allocate or conserve a river's discharge volume over the sea.
Lag profiles have nonnegative integer past-day offsets and nonnegative weights, normalized
to sum to one. Zero-weight offsets are ignored. These are scenario assumptions, not fitted
physical travel times or learned biological responses.

Signals are daily gauge discharge and discharge divided by each river's historical P90.
The active product and Explorer expose only **Discharge influence** and **Relative flow
influence**. Relative pulse influence and Overlapping pulse rivers were removed by user
decision on 2026-10-18. Method `river-influence-water-r8-min-child-lag-v2` omits pulse-excess
signals and pulse-count bounds; previous immutable releases remain historical. Native
gauge low/high-flow duration and days-since-pulse variables are unchanged.
P90 and interior-only linear interpolation use full
retained history; edge days are not extrapolated. Missing positive-weight lag support
makes that river-day signal unavailable. Source observations stay intact. All signals
retain native provider-date labels: simultaneous UTC support is not established. These
full-history/two-sided inputs are retrospective and `model_eligible=false`.

The delivery is one file: **`Data/Hydrology/influence.parquet`**. The JSON configuration
selects this file directly; no influence release directory, external recipe, manifest
or separate influence catalog is written. The existing Hydrology `catalog.json`
registers the file under `products.influence`. Method `river-influence-water-r8-min-child-lag-v2`
is unchanged; the storage format is `hydrology-influence-factors-1`.

The typed `factor_type` column distinguishes two native grains in one table:

| Factor | Identity | Values |
| --- | --- | --- |
| `spatial` | `river_id` × `h3_index` (R6) × `distance_profile` | `water_distance_m`, `reachable_r8_children`, `weight` |
| `temporal` | `river_id` × `date` × `lag_profile` | `discharge`, `relative_flow`, `interpolated_input_weight` |

`date` is Arrow `date32` on the declared **provider-day** basis, not UTC. Fields from
the other factor type are structurally null; within the applicable factor, null still
means unknown support. This factorization avoids expanding every cell across every
day and scenario. It preserves the app's configurable weights and river contributions.

Parquet schema metadata under `hydrology_influence` embeds the format, recipe identity,
a checksum of all logical factor rows, and the full recipe (configuration, units,
threshold/reference definitions, coordinates, source hashes and runtime/code provenance).
Both row identity and metadata/checksums are validated by the read-only app adapter.
No sibling toolkit module is needed to read the public Parquet contract.

A build pins the native Hydrology snapshot under its writer lock, writes a temporary
sibling file, checks exact readback and source bindings, then atomically replaces only
`influence.parquet`. An existing unrelated/unowned file is refused. Identical reruns
retain the same file. Native publication/recomputation carries the flat companion
forward; changed source hashes make it unavailable in the app until rebuilt. The
existing Hydrology catalog lists native gauges and the derived `products.influence`
entry. This entry contains the relative path, file checksum/size/row count, recipe
identity, metrics/units, provider-day basis, retrospective/model-ineligible flags and
`source_status` (`current` or `requires_rebuild`). The app discovers the path from this
entry and verifies its binding before decoding the Parquet.

To avoid circular hashes, `hydrology_catalog_sha256` fingerprints canonical native
catalog content **excluding the top-level `products` inventory**: sorted JSON keys,
two-space indentation, UTF-8 and no trailing newline. New recipes explicitly record
`hydrology_catalog_hash_scope=native_catalog_without_products`; the earlier flat file
remains compatible because its native-only catalog used that same serialization.
Native updates refresh the derived inventory and mark a carried file as requiring
a rebuild when its native fingerprint changes. Influence builds register/refresh the
entry after writing the verified file; an unchanged rerun keeps both file and catalog
stable. Catalog and Parquet replacements are individually atomic; the reader rejects
a mismatched pair during an interrupted update. The existing native
current-snapshot mechanism is unchanged; influence itself creates no snapshots/releases.

This provider-date research schema does not relabel dates as the strict UTC final
contract. Original inputs and prior migration evidence remain retained in the
configured toolkit source cache; they are not active delivery products.

The Explorer selects prepared distance/lag profiles and evaluates the literal sum of the
producer coefficients times the producer signals. It performs no routing, interpolation,
quantile fitting or kernel fitting. It shows the supported subtotal with spatial coverage;
unknown routes never establish zero influence. Any unavailable temporally required active
river makes the combined value null. If no route is known the value is null; known routes
all outside the cutoff can establish zero only for that known subset. Per-cell contributions,
shares of positive supported subtotal, active/known river counts and full settings accompany
inspection/export. Gains/profiles can be changed in the JSON and rebuilt; the app exposes
all prepared choices independently on both comparison sides.

```sh
PYTHONPATH=src python -m hydrology build-influence --config config/river-influence.json
```

Defaults are demonstration scenarios: 20/50 km exponential decay, a 20 km offshore-peaked
Gaussian, and same-day / 2–4-day / 6–8-day lag distributions. They are not calibrated.
Modeling must fit training-only references and test scales/lags against held-out years,
seasonality, salmon availability and observation effort before claiming whale relevance.


## Four additional research outlet bindings — 2026-10-20

The explicit configuration adds Puyallup `HYDRORIVERS_V10_70350974`, Elwha
`HYDRORIVERS_V10_70321298`, Skokomish `HYDRORIVERS_V10_70349282` and Queets
`HYDRORIVERS_V10_70341239`. The selected-outlet JSON checksum is pinned in the
configuration and the new native river registry records matching named basin IDs.
Builds reject mismatched identities, duplicate bindings, missing R8 attachment
qualification or an eligibility upgrade. Source coordinates, trace evidence and
resolution limits remain in the embedded recipe. In particular, Queets' unavailable
R6 attachment does not invalidate the separately qualified native R8 route used here.
These are existing source-linked research bindings, not newly inferred physical
mouths. All earlier source-registration, provider-day and model-ineligibility
qualifications remain unchanged.


Current rebuilt product (2026-10-20) contains ten rivers, 6,497 provider dates and
2,427 R6 reporting cells: 72,810 spatial and 194,910 temporal factor rows.
Independent verification matched all pinned R8 minimum-child distances and profile
coefficients. The original six rivers' logical factors remain identical. Each added
river has known routes to 2,348 cells; 79 remain unknown. Native Skokomish discharge
gaps remain missing; the existing qualified interior interpolation for retrospective
relative-flow indicators does not fill measured discharge. Both current Explorer
reader and localhost endpoint consumed this rebuilt product with scientific flags
intact. Influence SHA-256: `1922301967fbe166dab55bce90ac48b24b5ca598765759c44807d1920fb95e66`.

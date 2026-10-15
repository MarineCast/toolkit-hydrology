# Architecture, temporal semantics and metric dictionary

## Ownership and data flow

Official source → content-addressed response snapshots → native station observations →
explicit representative-gauge river conditions → causal daily features → optional
water-connected associations → date-partitioned strict UTC H3 proxy products.

The [MarineCast infrastructure contract](https://github.com/MarineCast/.github/blob/HEAD/INFRASTRUCTURE.md)
was inspected along with local Meteorology configuration and Seascape's public
`load_water_support`, water-network configuration and artifact contracts. Hydrology
uses independent packaging, Parquet, checksummed manifests and explicit configuration.
It does not import through sibling directories or claim adoption of a shared schema
that has not been implemented here. Oceanography and Salmon checkouts were absent.

`Config.load` precedence: explicit non-null arguments → supplied JSON config →
`MARINECAST_HYDROLOGY_CONFIG` JSON, if set → package defaults. Relative paths resolve
against the caller's working directory. No production MarineCast bounding box was
available: sibling config refers to `example_area`. Default native runs explicitly
select the six rivers; pass a sourced bbox to filter mouths. Gauges outside that box
remain eligible. No catchment is clipped. H3 defaults to R6. Dates are ISO dates,
inclusive; the current UTC day and future dates are rejected.

## Product contracts

| File | Grain/key |
|---|---|
| station_registry.parquet | river, station, series, relationship validity interval |
| river_registry.parquet | river; sourced mouth relationships as JSON |
| station_observations.parquet | station, series, metric, date, temporal_basis |
| river_conditions.parquet | river, metric, date, temporal_basis |
| river_features.parquet | river, metric, date, temporal_basis |
| coverage.parquet | river, station, metric, year, season |
| river_marine_links.parquet | river, marine H3 cell; closest reachable mouth retained |
| associations.parquet | H3 cell; associated river, mouth, distance and method |
| final/static.parquet | H3 cell, metric (all produced static metrics) |
| final/dynamic.parquet | H3 cell, UTC date, metric (all produced time-varying metrics) |
| final/catalog.json | product inventory, provenance, schemas, checksums |

Registry geometry is explicitly WGS84 JSON embedded in Parquet, not GeoParquet.
Station and river geometries are distinct. Raw metadata JSON accompanies normalized
registry tables. Native station records preserve all returned source series. Primary
series resolve multi-series native values only when unambiguous; conflicts fail closed.
`source_changed` exposes selected-series transitions. v1 allows exactly one station
relationship per river; changing station intervals requires a curated release rather
than automatically merging gauges. One river value is never summed across outlets.

Native rows retain units, source-series/record identity, provider, observed origin,
raw flags, interval boundaries where known, day definition, coverage, retrieval time,
source modification time, actual availability (usually null), and source-release hash.
A response hash identifies a retrieved snapshot, not an official revision vintage.
Status vocabulary is `valid`, `unavailable`, `unknown`, `not_applicable`, `partial`.
Provider approval/qualifier flags are separate. Zero and signed flow are retained.
Invalid or unsupported values remain null, never zero-filled. `valid` means eligible
under this method, not certification that a provider observation is error-free.

## Time and availability

USGS and HYDAT native daily records are `provider_daily`; their exact daily boundaries
are deliberately unknown until series-specific evidence establishes them. Station
PST/DST metadata alone is insufficient proof of the historical statistic's boundary.
Native daily interval coverage is null, not a fabricated 100% subdaily coverage.
Audit coverage is the fraction of requested calendar dates with eligible daily values.
The audit's freshness is relative to the audit date and must be interpreted alongside
the deliberately historical requested window.

`utc_daily` requires timezone-aware continuous observations. Each measurement is
held forward until the next timestamp or `max_hold_seconds`, whichever comes first.
No support extends backwards before a measurement. Integrate support clipped to each
UTC day, divide weighted sum by supported seconds, and require `minimum_coverage`
(default 0.9). Full UTC days are 86,400 seconds regardless of local DST. Exact duplicate
samples collapse; conflicting duplicates and ambiguous series fail. Missing samples
can produce unsupported gaps. Temperature maxima require the same dense continuous
coverage; grab samples are not an eligible maximum source. Native provider maxima
are retained as native statistics. UTC means are means of supported intervals, with
coverage explicitly stored, not estimates for unobserved intervals.

Provisional USGS records remain in station observations but are excluded from selected
conditions unless explicitly allowed. WSC real-time records are provisional. Recent
Canadian UTC data are retention-limited; older HYDAT daily data cannot enter this table.

`as_of` requires an aware timestamp and excludes unknown or known-later availability.
Neither retrieval nor `last_modified` proves original publication time. Thus current
historical provider extracts typically produce no eligible as-of records; the run
reports failure for required discharge. Retrospective outputs use revised historical
observations and **are not exact operational backtests**. Availability of revisions,
weather forecasts, and future observations is never inferred.

## Feature definitions

All windows are calendar-day reindexed, trailing, and include the current eligible day.
30 days of acquisition warmup precede the requested output; output stays within the
requested range. No baseline is fitted automatically. Feature contributors identify
the source station/series; dependencies resolve through river conditions and manifest.

| Metric | Definition / units / eligibility |
|---|---|
| discharge_mean | observed native mean or supported UTC mean, m³/s |
| discharge_mean_7d / 30d | arithmetic mean of exactly 7/30 eligible consecutive daily means; otherwise null |
| discharge_change_7d | Q(t) − Q(t−7), m³/s; all 8 dates must be eligible |
| discharge_seasonal_percentile | 100 × (count(reference<Q) + 0.5 count(reference=Q))/N |
| discharge_seasonal_anomaly | Q minus seasonal reference arithmetic mean, m³/s |
| low_flow_duration | consecutive days Q < configured low threshold; null after a gap or left-censored start until a known non-low day |
| days_since_flow_pulse | days since a known upward crossing of configured pulse threshold; null before a crossing or after a missing day |
| temperature_mean / max | provider daily statistic or supported UTC continuous statistic, °C |
| temperature_7dadm | trailing seven eligible daily maxima, °C |
| temperature_seasonal_anomaly | daily mean minus seasonal reference arithmetic mean, °C |
| water_distance_m | shortest supported graph path plus validated mouth connection, metres |

Defaults low=10 and pulse=1000 m³/s are demonstration hydrologic parameters, not
calibrated cross-river ecological thresholds. Configure them for the intended analysis.
Missing days reset event knowledge; the code does not bridge unknown event histories.
Constant/zero reference series are safe because anomalies do not divide by variance.
Climatology JSON has a checksum, training cutoff, reference start, ±15-day cyclic
seasonal window, minimum 60 samples from 3 unique years, source hashes and version.
Feb 29 pools with Feb 28 on a 365-day calendar. It is only applied AFTER its cutoff,
matching river, station, metric and temporal basis. Insufficient references return null.
Future test-period data cannot change the fitted artifact. Explicitly acquire training
history before fitting; the normal build only adds rolling-window warmup.

## Spatial inputs and safeguards

Supply a versioned WGS84 water polygon GeoJSON exported from Seascape (or another
explicitly sourced user mask) and receiving-region polygon FeatureCollection with
`properties.receiving_region` matching registry names. Use the full connected marine
mask, then bbox-filter output cells; do not clip routes at model-domain boundaries.
The existing Seascape graph loader is documented as an integration extension; v1's
standalone polygon adapter does not silently import or transform its graph artifacts.

Only adjacent H3 centers joined by a fully water-covered, densified geodesic segment
form graph edges. Mouth connections have the same water check and maximum snap
(default 3 km). Routing stays in the named receiving region. Disconnected cells have
null distances. Multi-mouth routing finds one shortest river path; it does not allocate
or duplicate discharge. Association chooses minimum water distance, ties by river ID.
Full links are retained; associated river IDs/station IDs are categorical contributors.
Numeric metrics are named `associated_river_<native metric>_proxy`; units are separate.
Source river temperature is not seawater temperature. No plume, salinity, freshwater
fraction, fish abundance or species relevance is inferred.

This conservative center graph can miss narrow channels at R6. Null/unreachable is
preserved. It does not guarantee all real passages are represented. Production use
requires mouth/region review and resolution sensitivity checks against a versioned
mask; only synthetic geometry has been tested here. Mapping cache identity includes
mask content/version, regions, registry, bbox, resolution, snap rule and method version.
H3 joins stream by date into row groups of one final dynamic Parquet file; no full history × full domain table is materialized.

## Reliability and deferred work

Monthly station/variable acquisition blocks; bounded 1–4 workers; shared per-provider
request pacing; retry/backoff for transient/network failures; explicit authentication,
unsupported, empty and failed outcomes. Completed pages resume from cache. Responses
are atomically stored by content hash; request pointers reference the selected snapshot.
`reconcile` refreshes those pointers and produces a new release when inputs change. Native-only runs retain their download cache. H3 builds use a dedicated owned staging cache and remove its HTTP request/snapshot folders only after successful final-product/catalog/release validation.
Recent provisional data require explicit refresh; the cache has no automatic freshness
TTL. Do not treat a warm cache as a live freshness check. Completed output manifests
are checksum-validated and immutable; failed releases are also retained, and rerunning
with corrected inputs yields a different identity. Output identity covers config,
registry, source snapshots, metrics, spatial inputs, baseline, outcomes and software.
Each artifact is atomic; interrupted runs without a manifest can resume. Avoid concurrent
writers to the same release root. No production promotion or whole-directory transaction
is claimed. Bounded historical retrieval is tested; multi-decade memory/runtime is not.

Deferred: expanded river and catchment curation, dated regulation histories, BC/Ecology
supplemental temperature, direct Seascape graph consumption, Meteorology basin summaries,
snow-water equivalent, separate validated modeled discharge, water quality, plume/transport
modeling, downstream OrcaCast evaluation, and recovered historical availability vintages.

`final/static.parquet` provides the numeric H3 × metric water-distance view
(metres), with associated river/mouth and mapping identity as contributor fields.
The full categorical receiving-region crosswalk remains in `associations.parquet`.
Explicit `stations` / `--stations` selects among stations in the curated registry;
new stations must first be added through a versioned registry with a river relationship.


## Final output standard and download lifecycle

Each release exposes a `final/` directory with:

- `static.parquet`: long-form `h3_index × metric`, with numeric `value`, `unit`,
  `status`, associated river/mouth and mapping identity. Time-varying observations
  are not flattened into this static file.
- `dynamic.parquet`: long-form `h3_index × date × metric`, with typed Arrow date32
  UTC calendar dates, value/unit/status, temporal basis, contributor river/station/
  series, mouth/mapping identity, method version and climatology identity. All
  produced dynamic metrics share this file, including unavailable/null features.
  Current output is daily; future subdaily output must use explicit UTC timestamps,
  never mix naive datetimes and dates under an ambiguous key.
- `catalog.json`: produced metric/unit inventory, row counts, keys, Arrow schemas,
  checksums, software/configuration, station metadata, river registry, request URLs,
  retrieval times, snapshot hashes, external-input checksums, availability limitations,
  and supporting native-artifact references. `complete=false` explicitly records a
  native-only or failed final-H3 build; such catalogs do not advertise partial final
  files as completed products.

The dynamic Parquet writer holds only one day's join in memory and uses a fixed schema
across row groups. Completed products and their catalog are reopened and validated
before cleanup. Cleanup never runs on provider, mapping, final validation or catalog
failure. Interrupted builds retain cached pages for resumption. The cache lives under
`CACHE/build-staging/CONFIG_HASH`, with an ownership marker; only its `requests/` and
`snapshots/` directories are removed. Ownership mismatches and symlinked download
folders are rejected. Do not run concurrent builds in the same staging namespace.

User-supplied water masks, regions, HYDAT databases, registry files and climatologies
are external inputs and are never deleted. Existing shared caches and prior releases
are not swept. Reusable generated spatial caches and native/QA products are retained;
these are supporting products, not downloaded intermediates. Source URLs, timestamps,
hashes, metadata and contributor references survive in the catalog after HTTP payloads
are removed. A later acquisition may need to download those responses again. Native-only
runs retain downloads because the requested final H3 products have not been completed.

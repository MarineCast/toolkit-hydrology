# Architecture, temporal semantics and metric dictionary

## Ownership and data flow

The implementation is organized into public Python entry points (`main.py`), CLI
parsing (`cli.py`), workflow orchestration (`pipelines/`) and focused shared/domain
helpers (`utils/`). Utilities do not depend on orchestration. The complete
[module map](../README.md#code-organization) identifies each stage and the retained
compatibility import paths. This organization does not change the data contracts
or the scientific qualifications below.

Official source → content-addressed response snapshots → native station observations →
explicit representative-gauge river conditions → daily features (retrospective flow indicators) → optional
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
select the ten curated rivers; pass a sourced bbox to filter mouths. Gauges outside that box
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
| feature_warmup.parquet | selected pre-output river conditions used to initialize features |
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
Identical scientific observations repeated across pages collapse to one row. An optional
`source_references` JSON column retains every page hash, retrieval timestamp, source
modification timestamp and record ID; scalar provenance remains a deterministic
representative. Differences in value, units, flags, availability or temporal support
remain conflicts. Older rows without this additive column remain readable.
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
coverage explicitly stored, not estimates for unobserved intervals. UTC-day flags
describe only measurements with positive eligible support in that day, including holds crossing midnight. Excluded provisional/null measurements do
not contribute flags; their gaps remain reflected in coverage. Source references
conservatively retain the acquisition block's inputs, including excluded samples
that terminate a preceding hold and therefore affect interval coverage.

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
requested range. `feature_warmup.parquet` retains the selected warmup conditions;
release identity and manifest/catalog snapshot inventories include all acquired input
hashes before output trimming, including warmup and duplicate-page references.
Warmup-only revisions therefore create new releases. No baseline is fitted automatically.
Feature contributors identify the source station/series; dependencies resolve through river conditions and manifest.

| Metric | Definition / units / eligibility |
|---|---|
| discharge_mean | observed native mean or supported UTC mean, m³/s |
| discharge_mean_7d / 30d | arithmetic mean of exactly 7/30 eligible consecutive daily means; otherwise null |
| discharge_change_7d | Q(t) − Q(t−7), m³/s; all 8 dates must be eligible |
| discharge_seasonal_percentile | 100 × (count(reference<Q) + 0.5 count(reference=Q))/N |
| discharge_seasonal_anomaly | Q minus seasonal reference arithmetic mean, m³/s |
| low_flow_duration | default: consecutive provider days Q < each river's full-output-history linear 10th percentile, after interior-only linear interpolation; no extrapolation, unknown spell starts remain null until a known non-low day; retrospective/model-ineligible |
| high_flow_duration | consecutive provider days Q > river historical P90; zero at/below P90; full-output-history linear quantile after interior-only interpolation; no edge extrapolation; unknown start stays null until a known non-high day; retrospective/model-ineligible |
| days_since_flow_pulse | default: days since upward crossing from Q(t−1) < river's historical P90 to Q(t) ≥ P90, zero on crossing day; full-output-history linear quantile and interior-only interpolation; unavailable before a known crossing/after unfilled gaps; retrospective/model-ineligible |
| temperature_mean / max | provider daily statistic or supported UTC continuous statistic, °C |
| temperature_7dadm | trailing seven eligible daily maxima, °C |
| temperature_seasonal_anomaly | daily mean minus seasonal reference arithmetic mean, °C |
| water_distance_m | shortest supported graph path plus validated mouth connection, metres |

`low_flow_method=historical_percentile` is the build/publish default as of 2026-10-18.
Within each river/station/temporal-basis series, sort/reindex to complete daily keys,
retain finite `valid` discharge in m³/s, linearly fill only gaps bounded by valid
observations and fit the 0.1 quantile with linear interpolation (index
`0.1 × (n−1)` over sorted supported values). Include filled days in that reference.
Use the full requested output range, excluding acquisition warmup. Require two
supported days; otherwise threshold and durations remain unavailable. Equality is
non-low and resets duration to zero. Below-threshold days increment only after a
known non-low day; leading/after-edge low spells with unknown starts stay null.

`low_flow_definition` records threshold, reference dates, counts, interpolated
dates/values and both observed endpoints/series, policy, qualification and a content
identity. Low-flow rows carry method `historical-p10-linear-interior-v1`, reference
identity in `climatology_id` (separate from any seasonal climatology), and per-day
reasons `interpolated_flow_input` / `streak_includes_interpolated_flow`. `valid` here
means a computable derived value, not an observed missing-day measurement. Source
conditions, flags, raw observations, coverage and other feature rows stay unchanged.

Full-history fitting and two-sided interpolation use future observations. This
metric is retrospective, explicitly `model_eligible=false`, and not a causal or
operational-backtest input. Appending/revising history can alter earlier values.
It is a user-selected descriptive rule, not a calibrated ecological/whale threshold.
`low_flow_method=fixed` retains the legacy configured threshold (default 10 m³/s)
without interpolation; the low-level `build_features` API retains that primitive.
`flow_pulse_method=historical_percentile` is also the default. Prepare discharge with
the same support and interior interpolation as low flow, then fit the linear 0.9
quantile (`0.9 × (n−1)` sorted index). On an upward crossing from below to at or above
P90, set days-since-pulse to zero. Otherwise increment calendar days since the last
known crossing; consecutive high days do not create new pulses. The first high day
of a left-censored series is not evidence of a crossing. Require two supported days;
without them, or before a known crossing/after an unfilled gap, return null.

`flow_pulse_definition` records the same reference/count/endpoint provenance as low
flow. Method is `historical-p90-linear-interior-v1`; rows bind the definition identity
in `climatology_id` and identify estimated inputs or dependent history with
`interpolated_flow_input` / `pulse_history_includes_interpolated_flow`. It uses future
observations, is retrospective and `model_eligible=false`, and is not an ecological
calibration. `flow_pulse_method=fixed` keeps the legacy unvalidated 1000 m³/s default
without interpolation. No training climatology is fitted for either relative rule.
Original observations and all other feature rows remain intact. Only remaining
unfilled gaps reset relative event knowledge; observed-source gaps stay missing.

`high_flow_duration` is included by default in build/publish and the `features` CLI.
It uses the same full-output-history P90 reference, two-supported-day minimum and
interior-only linear interpolation as relative pulse timing. Increment on Q > P90
only after a known at-or-below day. Q ≤ P90 resets to zero, including exact equality.
Leading high spells with unknown starts, insufficient reference support and unfilled
edge days remain unavailable. No extrapolation or warmup inclusion. The value is a
running spell duration on each date, in days, rather than a total event length.

`high_flow_definition` carries the same threshold, date/count, interpolation endpoint,
qualification and identity fields as low flow, with quantile 0.9 and comparison
`strictly above`. Rows bind this identity in `climatology_id` and carry method
`historical-p90-high-duration-linear-interior-v1`. Per-day reasons identify an
`interpolated_flow_input`, a `streak_includes_interpolated_flow`, or unavailable
`high_flow_start_unknown` / `flow_unavailable_no_extrapolation` /
`insufficient_reference_support`. Full-history/two-sided input remains retrospective,
`model_eligible=false`, and uncalibrated for ecological effects. Only
`high_flow_method=historical_percentile` is supported. Original discharge and all
other feature rows remain intact. `recompute-high-flow` adds or revises only this
metric in the owned current directory; it validates the complete calendar before
recoverable promotion, removes obsolete successful generations and performs no downloads.

### Training-only seasonal climatology

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
(default 3 km). Routing and mouth-snap segments stay entirely within the intersection
of the water mask and named receiving region. Mapping method `water-graph-2` invalidates older
cached associations that checked receiving-region centers only. Disconnected cells
have null distances. Multi-mouth routing finds one shortest river path; it does not allocate
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
unsupported, empty and failed outcomes. Completed pages resume from cache. `Retry-After` accepts nonnegative numeric seconds
or an aware HTTP-date; valid server deadlines are never shortened. Invalid/missing
headers use exponential backoff within the configured retry count. Request dispatch
is serialized per host, while other providers and completed cached reads remain usable.

`retry_wait_budget_seconds` (CLI `--retry-wait-budget-seconds`, default 60) bounds the
total retry/cooldown sleeping across one Client/acquisition invocation; ordinary
courteous request pacing and network timeouts are separate. A cooldown beyond the
remaining budget produces `RequestDeferred`, a `ProviderError` subclass with URL and
retry-at attributes; acquisition outcomes begin `deferred:` rather than reporting
empty data. The run remains incomplete for required discharge. Quota/retry exhaustion
also stops further network dispatch to that host in the invocation. Start a new
invocation with the same cache after the reported deadline to resume completed pages.

Absolute provider deadlines persist under `CACHE/cooldowns/` and survive interruption
and successful HTTP-payload cleanup. In-process monotonic guards prevent a forward
wall-clock jump from shortening a learned delay. An interrupted sleep propagates;
no retry occurs during interruption. Separate invocations must not concurrently write
the same cache (the existing single-writer limitation still applies). Responses
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

## Canonical per-river contract — hydrology-per-river-1

`publish` is a native per-river writer alongside the legacy release/H3 workflow. Its
configurable destination is `product_output`, independent of legacy `output`.
There is one current catalog; selected rivers replace only their explicitly requested
window, unselected river files retain their previous checksums and interval manifests.
Consumers must not infer one common interval or temporal basis across the catalog.

- `conditions.parquet`: river × station × date × metric × temporal_basis, explicit
  requested calendar for discharge/temperature mean/temperature max. Nullable source
  series and source identity on unknown days. `reason` describes missingness;
  unrequested metrics use `not_applicable` and `not_requested`.
- `features.parquet`: river × station × date × feature metric × temporal_basis, full
  calendar; unavailable rolling/baseline/event features retain null and reason.
- `observations.parquet`: provider-native station observations within output dates,
  preserving all returned series/flags and scientific conflicts failing closed.
- `warmup.parquet`: actual selected pre-output conditions, including their provenance;
  absent warmup dates are not invented. Feature computation reindexes the calendar.
- `metadata.json`: full river/gauge/mouth relationship, actual discovery metadata and
  its hash, river-scoped HTTP source references, exact supplied climatology and cutoff
  limitation. The baseline is never fitted during publication.
- `coverage.parquet`, `acquisition-ledger.json`: requested-date coverage by metric/year/
  season and block execution diagnostics. Latest observation means latest **eligible**
  date, excluding padded unknown days.
- `manifest.json`: interval, requested metrics, eligibility, execution/required-data
  flags, checksums, schema version, implementation/configuration and exact runtime
  dependency versions. `catalog.json` identifies and hashes each river manifest.

Conditions/features have typed `date32`, double values and explicit string units/basis/
status. Source references remain JSON strings; flags remain original provider JSON.
All supplied numeric values must be finite; signed/zero flow remain valid. UTC daily
interval bounds are explicit even on missing days; coverage stays unknown when no
source support was measured. Native boundaries remain unverified, never fabricated.

`execution_complete` excludes failure/deferred outcomes; unsupported optional metrics
are reported separately. `data_eligible` tests discharge eligible-days/requested-days
against `minimum_daily_coverage` (default 1.0). `complete` requires that gate and an
observed required-discharge outcome. Missing optional temperature cannot certify or
invalidate discharge coverage. These flags do not establish operational vintages or
whale-model validity. A relaxed coverage threshold is an explicit configuration choice.

The current product is a regular directory, never a symlink. Owned transient staging,
promotion journal and stable lock inode live under
`product_output.parent.parent/.marinecast-work/hydrology/<destination-hash>`.
An ownership marker binds both the final directory and work area to the exact destination.
POSIX advisory shared/exclusive locks coordinate `product_snapshot()` readers and
writers. After candidate validation, the writer journals intent, renames the old
directory into a recovery backup, promotes the candidate, records commit and deletes
the backup. A failed rename restores the old directory; a crash requires the next
writer to recover before readers proceed. There can be a brief missing destination
during the two renames: uncoordinated reads are not a snapshot transaction. This is
local filesystem recovery, not a remote/object-store or power-loss guarantee.

Canonical publication acquires into an owned `downloads/` inside the work area.
An explicit `Config.cache` / `--cache` supplies a work base with a destination-specific
owned child. Existing shared files are preserved; legacy/native APIs retain their
existing cache layout. Previously cached pages in the base are not silently
consumed as the canonical publisher's input archive. Successful execution-complete
publication removes owned downloads after full readback validation. Failed/deferred
runs retain them for resumption. Recompute removes previous successful generations
and retains failed candidates outside delivery. Source URLs, timestamps, hashes,
normalized observations, ledgers, metadata and native support stay in the final
product. External source files are never deleted. Future acquisition can require
fresh downloads and may see a different provider vintage.

The legacy release identity now includes current discovered metadata and acquired
response references (including discovery/empty responses), in addition to observations,
registry, warmup, code and configuration. This invalidates metadata-only primary-series
changes. HTTP pointers and snapshots are verified on reuse; a valid hash does not
establish source freshness. The block ledger never authorizes trusting a corrupted
cache or skipping provider refresh requested by configuration.


## River-influence research Parquet

[River influence](RIVER_INFLUENCE.md) is an explicit, factorized provider-date research
schema delivered as one `Data/Hydrology/influence.parquet` file. It combines pinned named-outlet R8 relationships with the exact shared R6
reporting keys using a documented nearest-reachable-child distance reduction. It does
not change the nearest-river `water-graph-2` path above or the strict UTC H3 final
contract. Its typed spatial/temporal factor rows and embedded recipe, source bindings,
logical factor checksum, units and qualifications are specified in its canonical method
page. There is no influence release directory, external recipe or delivery catalog;
the file is replaced atomically after readback and source validation. The existing
Hydrology catalog registers it at `products.influence` with checksum, dimensions,
metrics/units, qualification and source status. Native-input hashing excludes the
derived `products` inventory to avoid circular references.
The active v2 method exports only discharge and relative-flow signals; no pulse-excess
signal or pulse-count metric/bounds are delivered. Native gauge pulse indicators are
unchanged. It remains retrospective/model-ineligible and species-neutral.


## Non-decreasing retained observation support — 2026-10-20

Canonical publication uses policy `nondecreasing-observed-support-v1`. Before
acquisition, each existing selected river must retain its station, temporal basis,
full date window and all metrics with eligible retained observations. Before any
promotion, compare prior eligible station/metric/date/basis keys with the proposed
conditions. Every prior value must remain finite and valid; units and observed
origin must agree, known interval coverage cannot decrease, approval cannot be
removed, and explicit Provisional, Estimated or Partial Day flags cannot newly
downgrade a retained value. Changed unknown provider qualifiers are rejected; identical
opaque qualifiers are preserved without inventing a universal quality order. Official numerical revisions are allowed when
these support checks pass. The manifest records policy, compared/preserved counts,
revised values and previous conditions checksum.

This is rejection, not a historical merge or source fallback. A failed replacement
leaves the complete existing current directory unchanged and keeps resumable owned
downloads. Unselected rivers retain their bytes. New partial products still retain
missingness, actual coverage and source execution outcomes. Existing immutable
release builds do not replace the canonical product; HTTP response caches are source
work areas, not publication approval.

The registry's four new US stations explicitly declare temperature mean/max
unsupported. Acquisition records that outcome without issuing empty temperature
requests; requested condition rows remain null/unavailable. Their sourced daily
discharge still produces the existing trailing and retrospective flow features.
No seasonal baseline, ecological calibration, station sum or UTC relabeling is added.


`acquisition_block_months` defaults to 1 and accepts integers 1–240 for provider-native
daily acquisition. Blocks preserve the exact start/end dates, warmup and pagination;
no averaging or temporal conversion occurs. The 20-year maximum keeps each single
daily series below the USGS 10,000-row page limit. UTC acquisition requires 1.
This grouping option does not waive pacing, Retry-After, cache or runtime limits.


## Lagged causal discharge companion — 2026-10-26

The offline causal companion adds seasonal baselines, percentiles and pulse features
using only retained prior-day discharge and completed prior-year references. Existing
retrospective products remain unchanged. See [definitions, timing, storage and limitations](CAUSAL_FEATURES.md).

## Independent temperature stations — 2026-10-26

`catalog.products.station_temperature` registers the sparse native observation
companion described in [Station temperature](STATION_TEMPERATURE.md). Its station
identities and coordinates are separate from the per-river representative gauges.

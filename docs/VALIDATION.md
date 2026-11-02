# Validation and acceptance limits — 2026-10-15

## HTTP cooldown repair

All **85 offline tests passed**, including **25 new HTTP cooldown cases**, using the
temporary Python 3.14 review environment.

Offline mocked-clock/HTTP tests cover full long delays, immediate deferral when the
wait budget is insufficient, numeric and HTTP-date headers, malformed/missing headers,
retry exhaustion, shared budgets, persisted restart/interruption, cached-page resumption,
independent providers, forward wall-clock changes and early sleep returns. No live
requests or previously deferred source windows were run for this repair.

## Review repairs

The follow-up repairs add offline regressions for warmup-only revision identities
and retained provenance, day-specific UTC quality flags (including midnight holds,
excluded provisional samples and empty support), receiving-region edge/snap containment,
and identical page duplicates versus scientific conflicts for daily and continuous data.
All 60 offline tests passed in the temporary Python 3.14 review environment, including
16 new review regression cases. Existing releases are preserved; new builds use new
implementation identities and `water-graph-2` spatial cache keys. No new live or production coverage is claimed.

This is a working observed-data release candidate, with successful native pilot
products. Production marine mapping and the scientific gaps below remain unvalidated.
`manifest.complete` means the outputs requested in that run succeeded; it does not
certify these deferred inputs or every toolkit capability.

## Real-provider checks

Historical pilot: **2023-01-01 through 2023-03-31**, inclusive (90 days). Thirty warmup
days were fetched for rolling features, then excluded from output. All six station
identities, station coordinates, native drainage areas and available USGS series
metadata were retrieved from official endpoints and saved. No source IDs were invented.

| River | Official station | Discharge days | Temperature mean days | Temperature max days |
|---|---|---:|---:|---:|
| Fraser | WSC 08MF005, Fraser at Hope | 90/90 | unsupported | unsupported |
| Skagit | USGS-12200500, near Mount Vernon | 90/90 | 90/90 | 90/90 |
| Snohomish | USGS-12150800, near Monroe | 90/90 | 0/90 | 0/90 |
| Nooksack | USGS-12213100, at Ferndale | 90/90 | 90/90 | 90/90 |
| Cowichan | WSC 08HA011, near Duncan | 90/90 | unsupported | unsupported |
| Columbia | USGS-14105700, at The Dalles | 90/90 | 90/90 | 90/90 |

The pilot has **1,080 native station rows**. Daily temporal basis is `provider_daily`;
no observation was relabeled UTC. Coverage is also saved separately by year and
meteorological season, variable, station and river, including missing variables.
This is bounded observed coverage, not evidence of uninterrupted 2009–present records.

Additional real checks:

- Columbia **2023-01-01–2023-01-03**: 9 UTC daily rows (discharge, temperature mean and
  maximum), each with 1.0 interval coverage from timestamped USGS readings. Cold
  retrieval/aggregation was 3.73 seconds; a later cache-only rebuild was also validated.
- Fraser **2026-10-13**: 288 real-time WSC readings, explicitly provisional, integrated
  to a UTC mean of **2581.805556 m³/s**, coverage 1.0. Saved and read as Parquet at
  `data/recent-wsc-check.parquet`. This is a separate recent-source check, not a
  substitute for Canadian historical UTC validation.
- Native sample: Fraser 2023-01-01 **721 m³/s**, 2023-01-02 **702 m³/s**,
  2023-01-03 **685 m³/s**, all provider daily.
- UTC sample: Columbia 2023-01-01 discharge **2948.668632 m³/s**, mean temperature
  **3.316667 °C**, maximum **3.4 °C**. These UTC statistics differ legitimately from
  provider-native-day statistics.

All saved station/native/feature files are reopened and checked for uniqueness,
null/status consistency and checksums. Raw observations remain in ignored local data.
No production H3 records exist because the required marine geometry inputs are absent.
Do not interpret the synthetic spatial test's H3 records as actual marine predictions.

## Offline and packaging checks

- **40 offline tests passed in 1.94 seconds** on the final implementation, including saved H3 partitions. Fixtures are explicitly synthetic.
- Coverage includes HTTP pagination/rate-limit retries/resume, auth versus empty data,
  conversions and signed flow, HYDAT SQLite extraction, conflicting duplicates,
  native versus UTC support, aware timestamps/DST, sparse-temperature rejection,
  missing dates/windows, zero/constant flow, baseline cutoff and leap days, checksum
  tampering, causal event state, future-append invariance, historical availability,
  nested-gauge rejection, mouth-versus-gauge bbox selection, land barriers,
  disconnection, narrow passages, resolution sensitivity, distributary deduplication,
  cached mapping, saved H3 date partitions/contributors, immutable deterministic
  repeated builds, corruption detection and independent native outputs on H3 failure.
- Installed wheel loaded successfully from `/tmp/hydrology-wheel-check`, outside the
  checkout; package resources included all six registry entries and CLI dry-run worked.
  Runtime dependencies were reused from the isolated development environment for this
  import check. This was not a clean-machine dependency installation benchmark.
- `ruff check`, `git diff --check`, native and UTC saved-output validation passed.
- Dry-run of 2009–yesterday produced **215 monthly blocks**, including rolling warmup.
  No large backfill was launched. The baseline CLI was exercised on the pilot and
  correctly produced an insufficient-history artifact; multi-year fitting/leakage was
  tested offline, not with a multi-year production acquisition.

## Remaining acceptance gaps

1. **Production spatial inputs:** no generated/versioned Seascape water polygon,
   receiving-region polygon crosswalk, or agreed shared study bbox was accessible.
   Available sibling configs refer to an example area. Source-backed gazetteer mouths
   are approximate and require water-mask snap review; distributary inventories are
   incomplete. No production connectivity or narrow-channel sensitivity claim is made.
2. **Catchments and regulation:** basin polygons, mouth drainage areas and dated
   regulation changes are unknown. Gauge drainage areas are verified separately.
   Gauge proxies exclude downstream inflows; no area scaling or nested-gauge sums.
3. **Historical UTC Canada:** HYDAT daily means cannot yield UTC daily means. The recent
   WSC timestamped path only covers its retention window and is provisional.
4. **Temperature gaps:** no suitable record was retrieved for Snohomish in this window;
   HYDAT is not a temperature source. BC/Ecology supplemental station matching and
   temperature support remain to be curated; no placeholder adapters are advertised.
5. **Historical availability:** revised historical extracts do not reconstruct operational
   publication vintages. Strict `as_of` normally excludes them. Seasonal anomalies are
   unavailable without a separately fitted, sufficient training-only reference artifact.
6. **Local HYDAT and scale:** full official SQLite snapshot was not provisioned; only
   its reader's fixture test ran. Canadian historical OGC acquisition is live-validated.
   Full-domain H3 and multi-decade backfill runtime/memory are unmeasured. R6 center
   graphs can disconnect narrow real channels and require reviewed higher-resolution
   support. Direct consumption of Seascape's canonical graph is not yet implemented.

No push, merge, sibling modifications, production promotion or unrestricted acquisition
was performed. Source documentation and station/mouth evidence are in SOURCES.md and
the versioned registry; run manifests identify exact input snapshots and implementation.

## Measured performance and retained outputs

Machine: macOS 26.6.2, Apple ARM64, Python 3.12.12. Cold measurement preceded the final optional static H3 view addition; native processing was unchanged. Saved native station, river and feature tables are exactly equal between the cold and warm runs. Source/code identities are retained in the report.

| Stage | Cold cache | Warm cache |
|---|---:|---:|
| Acquisition/normalization | 62.907 s | 0.243 s |
| Selection and features | 0.206 s | 0.201 s |
| Audit and file writes | 0.096 s | 0.079 s |
| Total instrumented build | 63.209 s | 0.523 s |
| HTTP requests | 66 | 0 |
| Cached pages | 0 | 66 |
| Output bytes, excluding manifest | 305520 | 305520 |
| Peak RSS, macOS bytes | 120733696 | 141492224 |

The native release has 1,080 station rows, 1,080 river-condition rows, and 5,400 feature rows. Acquisition includes parsing/normalization; UTC interval integration also occurs in that stage. Native daily data need no subdaily aggregation. Peak RSS includes interpreter/dependencies; process startup is outside instrumented timing.

Production H3 mapping time is **unmeasured** because inputs are absent. A synthetic two-waterbody R6 microcheck produced 22 links in 0.0694 s cold and 0.0586 s cached. These numbers do not predict production performance.

Retained releases and exact validation commands, relative to this checkout:

```bash
.venv/bin/python -m hydrology validate data/benchmark-cold/498eff25536aea69ad78
.venv/bin/python -m hydrology validate data/benchmark-warm/d8af2e81e159ec2a4c7a
.venv/bin/python -m hydrology validate data/validated-utc/6e434228ce02b3e8df96
```

Full measurements and manifests: [benchmark-summary.json](benchmark-summary.json). Raw observations and snapshot responses remain in ignored local data.


## Final-product standard follow-up

The subsequent output-standard change was verified with **44 offline tests passing**,
including typed dynamic Parquet row groups, catalog checksums/source provenance,
success-only HTTP download cleanup, retention after provider/product failure,
external-input/shared-cache preservation, ownership checks and symlink rejection.
The previous live benchmarks above describe the earlier output layout and were not
rerun for this format-only change. Real production H3 validation remains blocked by
the spatial inputs described above. No previous pilot caches or releases were deleted.

## Correctness and canonical writer repair — 2026-10-16

The new offline regressions exercise metadata-only primary selection invalidation,
verified request/snapshot cache reuse and corruption refusal, retained completed blocks
with durable failed/deferred/empty/unsupported checkpoints and verified-page resume,
non-finite rejection, full expected calendars and truthful eligibility/freshness.
Canonical publication checks include typed schemas, provenance/warmup/baseline,
missing/unknown and native/UTC semantics, idempotence, selected-river replacement,
unselected preservation, cross-river isolation, exclusive/shared reader locks,
owned-stage cleanup and failure injection before promotion.

The earlier pilot release paths printed above are historical evidence: checkout
`data/` is currently absent. The retained qualification directory contains bounded
sample response caches and coverage artifacts; it is not a production history. The
shared MarineCast study mask/grid and canonical Seascape outlet products now exist,
but Hydrology's production spatial adapter and real-route qualification remain open.
This repair does not create final MarineCast/Data/Hydrology histories, expand the
river registry, substitute gauges or acquire new live data. See TODO.txt for next runs.

Prepared-implementation verification: **125 offline tests passed in 3.73 seconds**;
ruff passed. Fresh sdist and wheel built without fetching dependencies. An installed
wheel outside the source tree imported all six registry entries and passed CLI dry-run,
publication from a labeled synthetic local HYDAT fixture, and `validate-product`.
Retained-source replay used **22 verified cache hits and zero HTTP requests**: native
2009-01-01–2009-01-07 discharge for all six rivers (42/42 values), plus 2,304 continuous
samples across the four US stations yielding 28/28 eligible UTC discharge days. A
validation-only per-river native-week product passed readback/idempotence; it does not
claim full history, operational vintages or acquired rolling-window warmup.


## First current daily collection — 2026-10-16

Native daily products for the existing six gauges were collected and published for
2009-01-01–2026-10-15. Actual eligible discharge is 38,971/38,982 river-days; the
11 source gaps remain explicit. Current data include provider-flagged provisional
values by explicit run configuration. Optional temperature was collected only at
Skagit, Nooksack and Columbia. No climatology was fitted and no H3 influence product
was produced. All nine previously unfinished Columbia UTC qualification assessments
were completed separately: 63/63 eligible variable-days in the three one-week windows.

The collection exposed an idempotence defect in retry diagnostics: elapsed wait text
changed identity despite identical sources/values. Identity now hashes outcome
categories while preserving full error details in manifests and ledgers. **126 owner
offline tests passed** after the fix; 10 additional run-scoped annual/budget/CSV tests
passed. Strict source hashing, independent raw-value/unit checks and installed-wheel
product validation remain intact. No source refresh was used to hide the assertion.

## Relative low-flow duration — 2026-10-18

The user selected the historical 10th-percentile definition with interior linear
interpolation for this calculation only. The new producer method is
`historical-p10-linear-interior-v1`. All **135 offline tests** passed, including
river-relative scaling, strict threshold comparison, spell resets, interpolated
input/dependent-streak provenance, no edge extrapolation, unknown starts, inadequate
support, identity/calendar rejection, source preservation, locks, idempotence and
pre-promotion failure. Ruff passed. The missing owner `.venv` was replaced for these
checks by the existing workspace Meteorology Python interpreter; actual dependency
versions are recorded in each recomputation manifest. No dependencies were installed.

The offline current-product update validated the original snapshot, retained it,
hard-linked unchanged source companions into a new owned snapshot, replaced only
low-flow rows and relevant metadata/manifests, validated readback and atomically
switched `Data/Hydrology`. No source acquisition, prior-snapshot deletion or external
publication occurred. New current catalog SHA-256:
`26f349bd7ef7bddb66d0bf4e414765ca68a111747466b2769be613e859ae6179`.

Independent NumPy interpolation/explicit sorted-quantile calculation and sequential
spell counting matched **38,982/38,982 river-days**, 2009-01-01–2026-10-15. Raw
companions are byte-identical, and non-low-flow feature rows and floating-point bytes
match the previous snapshot. All 11 original discharge gaps remain missing; this
derived calculation fills Fraser 7, Columbia 2 and Nooksack 2 interior days.

| River | Historical P10 threshold (m³/s, rounded) | Positive-duration days |
| --- | ---: | ---: |
| Columbia | 2726.912327 | 649 |
| Cowichan | 4.376000 | 650 |
| Fraser | 862.600000 | 650 |
| Nooksack | 35.679227 | 639 |
| Skagit | 220.305066 | 646 |
| Snohomish | 51.140225 | 650 |

Strict comparison and ties mean the low-flow share need not equal exactly 10%.
These are full-history retrospective descriptors, not independently validated
hydrologic/ecological thresholds or causal forecast inputs. New observations can
revise thresholds and historical durations. Native/UTC source semantics and existing
spatial qualification limits remain applicable. No live provider or regional H3
validation was rerun.

## Relative flow pulses and local run settings — 2026-10-18

The user selected each river's historical P90 for days since flow pulse, with
interior-only linear interpolation restricted to that calculation. Method is
`historical-p90-linear-interior-v1`. An upward crossing is Q(t−1) < P90 ≤ Q(t);
the count is zero on that day and continues through later high days. Unknown
history stays unavailable until a crossing is established. All-history fitting
and two-sided interpolation are retrospective/model-ineligible, not ecological
calibration or operational-backtest inputs.

The offline update used the new toolkit-local `.env` through
`hydrology recompute-flow-pulse`, without an explicit destination. Preflight resolved
the canonical `Data/Hydrology` symlink, 2009-01-01–2026-10-15 and VERBOSITY=True.
The private file is ignored; `.env.example` documents the four settings. No provider
acquisition, source refresh or old-snapshot cleanup occurred. A new owned snapshot
was validated and atomically promoted; raw companions were hard-linked and the prior
snapshot retained. Current catalog SHA-256:
`f0b25f204786784f0ec7930b1e0773f75ddd36c3ff416d9818d29ca7798ce02a`.

Independent NumPy interpolation, explicit sorted linear P90 and sequential crossing
counting matched **38,982/38,982 river-days**. All non-pulse feature rows and floating
point bytes, including P10 low flow, matched the previous snapshot. Conditions,
observations, warmup, coverage and acquisition ledgers remain byte-identical. All
11 original missing discharge observations remain missing.

| River | Historical P90 threshold (m³/s, rounded) | Upward crossings |
| --- | ---: | ---: |
| Columbia | 8126.934972 | 52 |
| Cowichan | 123.000000 | 73 |
| Fraser | 6000.000000 | 21 |
| Nooksack | 196.518915 | 204 |
| Skagit | 773.049912 | 152 |
| Snohomish | 529.525031 | 176 |

Settings regressions cover precedence, file-relative output, final symlink
preservation, explicit false, no parent search/environment mutation, missing or
duplicate/invalid settings, safe error messages, preflight before side effects,
stderr progress, no verbosity effect on scientific identity and default public API
dates. Pulse tests cover scaling, equality/upward crossings, no repeated-high reset,
interpolated support, edge gaps, inadequate history, preservation, locks, rollback
and idempotence. Existing offline regressions remain applicable; no live provider,
regional H3 or native-browser visual qualification was rerun. Owner `.venv` remains
absent; checks use the existing Meteorology Python environment, without installation
or modification of that sibling repository. Recompute manifests record actual
runtime versions and algorithm/shared-history hashes.

Final checks for this revision: **148 owner offline tests passed**; Ruff and
`git diff --check` passed. Explorer checks passed with **50 targeted frontend tests,
9 adapter tests**, TypeScript, ESLint and production build. Browser encodings exactly
matched all 38,982 pulse values and per-day reasons with valid checksum bindings;
the running local endpoint served all six P90 definitions. Updated Markdown local
links and Knowledge properties/wiki links passed. These repositories have no separate
documented Markdown build for the changed files. Native-browser visual QA, live
provider, regional H3 and other Python environments were not rerun.

## Pipelines, utilities and entry points — 2026-10-18

The code is reorganized into `main.py` (public Python API), `cli.py` (argument
parsing/dispatch), `pipelines/` (acquisition, native access, processing, releases,
current-product publication, recomputation and command workflows), and `utils/`
(configuration/settings, contracts, I/O/provenance, sources and calculations).
Flat module names remain compatibility re-exports. Regression tests patch the
owning implementation modules, retaining their prior scientific/transactional
assertions. The [module map](../README.md#code-organization) is canonical.

Validation for this refactor:

- The pre-refactor owner suite passed **148 tests**. The reorganized checkout passed
  **151 tests**, including new compatibility, dependency-direction and recursive
  source-fingerprint checks. Ruff passed across source, tests and scripts.
- A wheel built without isolation or dependency downloads, was installed into a
  task-owned temporary target, and passed the same **151 tests outside the checkout**.
  Its package path was checked to ensure imports came from that installation.
- Every feature row and relative-flow definition for a saved, bounded 240-river-day
  synthetic fixture matched the pre-refactor baseline exactly through the installed
  wheel, including gaps, both river scales and P10/P90 calculations.
- Top-level CLI help matched the saved pre-refactor text byte-for-byte. Installed
  CLI preflight accepted the existing explicit `.env` file and false verbosity
  override; the bundled six-river registry loaded from the installed package.
- Current data target/catalog and private `.env` fingerprints remained unchanged.
  No provider acquisition, product recomputation/promotion or cache cleanup ran.

Implementation identities now hash Python sources recursively by package-relative
path, including nested files with duplicate basenames. Future builds correctly
identify reorganized code; prior data artifacts and their recorded hashes are not
rewritten. The missing owner `.venv` was not recreated; checks used the existing
Meteorology Python environment without modifying that sibling checkout. No native,
regional H3, live provider, frontend/browser or other Python-version validation was
rerun. These are organization/compatibility checks, not new scientific qualification.

## TODO review — 2026-10-18

The TODO list was checked against current pipeline/utility source, current six-river
manifests/metadata and the dated records below. Completed work was removed from the
active list; mixed items were narrowed to their unfinished scope. This was a bounded
documentation audit, not a new acquisition, dataset scan, live qualification or
model-readiness assessment.

| Removed completed scope | Evidence and remaining limits |
| --- | --- |
| Initial native-history collection / initial date-window setup | Current six-river manifests retain 2009-01-01–2026-10-15; the [first collection](#first-current-daily-collection--2026-10-16) records 38,971/38,982 observed discharge days. Eleven gaps and analysis-specific acceptance remain open. New acquisitions still require their own scoped windows/budgets. |
| Resume nine unfinished Columbia UTC sample assessments | The same dated collection record reports completion of all nine assessments, 63/63 eligible variable-days. This is historical bounded qualification, not full-history UTC coverage or today's provider quota. No UTC run was repeated for this review. |
| Initial Wateroffice historical/recent daily-CSV qualification | [Source qualification](SOURCES.md#wateroffice-daily-csv-qualification--2026-10-16) and current Fraser/Cowichan metadata record the run-scoped daily collector and nonnull GeoMet → historical Wateroffice → provisional daily precedence. Packaging that collector and investigating archived timestamped/unit records remain open. |
| Bounded native acquisition benchmark | [Measured performance](#measured-performance-and-retained-outputs) and [benchmark summary](benchmark-summary.json) record the six-river 90-day cold/warm native run. These are dated measurements; old release paths are not current validation, and larger UTC/H3 performance remains unmeasured. |
| Downstream Explorer adapter | The existing [read-only adapter](../../../Applications/applications-data-explorer/scripts/hydrology_input.py) and [Hydrology QA](../../../Applications/applications-data-explorer/docs/qa/hydrology.md) implement and document source-bound consumption, dates, missingness, P10/P90 definitions and provenance. This does not close archive/freshness, rights or ecological-modeling decisions. |
| Confirm current local filesystem promotion/lock support | Current delivery is an owned symlink, and the [writer/refactor checks](#pipelines-utilities-and-entry-points--2026-10-18) cover atomic promotion, advisory reader/writer locks and rollback on this local filesystem. Other platforms and migration of unowned directories remain separate scopes. |

The completed-status bullets formerly appended to TODO are represented by the dated
records above. Operational safeguards are retained as run constraints instead of
unfinished tasks. The old blanket "do not interpolate" wording was reconciled with
the user's approved derived-only P10/P90 interpolation; original observed-flow gaps
remain intact. Training climatology, source-refresh policy, cross-process acquisition
locking and production spatial qualification remain open. The README's stale claim
that no multi-decade acquisition had occurred was corrected to distinguish retained
native history from unestablished full-history UTC/H3 coverage.

The former collection note reported three quota deferrals followed by cached
resumption after the actual deadlines. That is dated collection history; future
runs still require current quota/cooldown checks and finite budgets.

Current review checks: local Markdown links and Knowledge properties/wiki links,
plus `git diff --check`. Behavioral suites, installed-wheel checks, live provider,
regional H3 and frontend/browser runs were not repeated for this prose-only audit.


## Relative high-flow duration — 2026-10-18

User-approved high-flow duration was added to the canonical six-river data and the
Explorer's Flow indicators variables. It counts consecutive provider days strictly
above each river's historical P90, resets to zero at/below P90 and preserves unknown
starts as null. Full-history linear quantiles include interior-only interpolated
flows; original observations stay unchanged. This is retrospective/model-ineligible,
not ecological calibration or an operational forecasting feature. See the
[feature contract](CONTRACTS.md#feature-definitions).

The offline writer used the configured `.env` DATA_DIR and retained conditions for
2009-01-01–2026-10-15. Source snapshot `snapshot-gc7wjwo0` is retained; validated current
snapshot is `snapshot-lk68nque`, with catalog SHA-256
`caf259097523e72774799e4c8ff7055999527d6f96a9431713f40684e277cc0e`.
Each river now has 13 feature calendars (84,461 rows). All 38,982 new metric values
and per-day reasons matched a separate NumPy interpolation, explicit sorted-rank
P90 calculation and manual streak counter. Existing feature rows and float bytes,
including low flow and pulse timing, matched exactly. Conditions, observations,
warmup, coverage and acquisition ledger companions remain byte-identical. The 11
original discharge gaps (Fraser 7, Columbia 2, Nooksack 2) remain missing in observations.

| River | P90 threshold (m³/s) | Positive high-flow days | Longest streak (days) |
| --- | ---: | ---: | ---: |
| Columbia | 8126.934971904 | 648 | 107 |
| Cowichan | 123 | 637 | 44 |
| Fraser | 6000 | 648 | 83 |
| Nooksack | 196.51891534848 | 645 | 18 |
| Skagit | 773.0499119616001 | 646 | 37 |
| Snohomish | 529.5250312704001 | 638 | 20 |

All six have positive durations in retained history; all latest-day durations are
zero. These strict-above counts can be less than 10% because of ties at P90. All
38,982 high-flow values are currently computable; the method's edge/censoring tests
still preserve nulls when history is unknown.

Current checks: **157 offline producer tests**, Ruff, current-product validation and
idempotent offline rerun passed. The suite covers equality, scaling, interpolation,
left censoring, constant/insufficient history, exact-key append/replacement, retention,
lock contention and failed staging rollback. Python checks used the existing
Meteorology environment (Python 3.12.13) with `PYTHONPATH=src`; the missing owner
`.venv` was not recreated. An initial invocation without PYTHONPATH could not import
the checkout and was corrected before executing the suite.

Explorer checks: **56 targeted frontend tests and 10 adapter tests** passed; TypeScript,
ESLint and production build passed. The build retains the existing large-chunk
warning. All 38,982 browser-cache high-flow values, statuses and reasons matched the
producer, with source-bound definitions for all six rivers. The running local endpoint
served the new variable and all six definitions against the catalog hash above.
Snapshot metadata and full definition/interpolation provenance are exported with the
selected variable. No native-browser visual pass, live-provider acquisition, full-history
UTC, regional H3 build, ecological/model evaluation or cross-platform run was performed.

Small replay scripts, code/runtime hashes and receipts are listed in the task manifest
`/private/tmp/marinecast-high-flow-manifest.json`; independent scientific results are
in `/private/tmp/marinecast-high-flow-evidence.json`. The single completed frontend
preview destination was reused. Previous snapshots, sources and failed synthetic
staging remain retained; no cleanup batch ran.


## River influence scenarios — 2026-10-18

Historical v1 receipt, superseded by the two-variable v2 product below.
Implemented and locally validated the user-requested first exploratory overlap layer.
The [method](RIVER_INFLUENCE.md) uses configurable exponential or offshore-peaked
water-distance weights, normalized past-day lag distributions and explicit river gains.
The signals are upstream discharge, relative P90 flow and positive relative P90 excess.
Six named bindings are checked against the supplied Seascape source-linked research
registry; no coordinate-nearest river substitution or distributary duplication occurs.
Original native data and source files remain unchanged.

Initial v1 product identity (historical):
`414ba582f939c3c84286c06a3b2564d9a44cc8ff7ed9bf70ceb7c1af26022a04`.
Catalog SHA-256:
`2866d93a9233ba41e9362c3dd48c47b46c705dc5abeccb69628186efbe518d4a`.
The factorized product covers **2,427 exact R6 reporting cells**, six rivers and
6,497 provider dates (2009-01-01–2026-10-15): **43,686 spatial factor rows** and
**116,946 river/date/lag rows**, with three numerical signals per lag row. Source
R8 relationships are pinned by study manifest SHA-256; their checksum is
`561cbabdf58353a01984e9e184e4da08e558169213c7e7a5e525f279141481bc`.
R8 routes are reduced to the minimum reachable child-water representative distance
within each R6 cell. This is a declared spatial proxy, not an R6 center or area mean.
The R6 route table could not attach Columbia, so it was not substituted for R8.

All six selected rivers have known routes to 2,348 reporting cells. **79 cells have
no supported route and remain unavailable**. Under the default broad 50 km decay
and 250 km cutoff, **1,086 cells have positive spatial weights from at least two
rivers**. This is potential distance support, distinct from simultaneous positive
pulse contributions. Counts of positive-weight cells by river: Columbia 252,
Cowichan 1,089, Fraser 1,025, Nooksack 985, Skagit 952, Snohomish 739. No current,
water-volume conservation, travel-time calibration or biological inference is made.
Columbia's named modeled source is in the estuary upstream of the physical mouth;
its origin and source registration limits are retained explicitly in recipe/Insights.

Independent checks recomputed **43,686 distances/coefficients** from the native
R8 product and explicit equations, and **350,838 lagged signal values** from retained
observations using separate NumPy interpolation, sorted-rank P90 and manual past-day
weighted sums. They matched, including unknown edges and strict lag support. All
encoded spatial and signal factors matched their Parquet sources exactly. The actual
frontend evaluator then matched independent Python results for **262,116 cell values
across 108 frames**, spanning every distance/lag/metric combination at three dates,
including the unknown initial lag support. Recipe source hashes still match every
retained input; native Hydrology catalog remains
`caf259097523e72774799e4c8ff7055999527d6f96a9431713f40684e277cc0e`.
An identical producer rerun reused the same immutable release and catalog.

Software checks: **166 offline producer tests**, Ruff and diff checks passed. The
nine new tests cover kernel shape/cutoff/gain, offshore peak, normalization and
past-only lag use, missing support, addition without attenuation normalization,
invalid settings, explicit pinned sources, exact reporting identities and idempotent
publication. Python 3.12.13 came from the existing Meteorology environment; the owner
`.venv` remains absent. No sibling checkout/environment was modified.

Explorer validation includes producer-factor preservation, checksum/path rejection,
live-reader invalidation after native-source change, independent map-side scenarios,
scenario swap, provider-date playback, contribution inspection and product switching.
Native browser checks rendered the live map, changed to the offshore profile and
inspected a cell with Fraser, Nooksack, Cowichan and Skagit contributions. Original
observations remain missing at the 11 retained source gaps; interpolation is derived-only.
The full frontend suite passed (387 tests in 73 files); TypeScript, ESLint and the
production build passed with the existing large-chunk warning. Details are in the [app QA](../../../Applications/applications-data-explorer/docs/qa/river-influence.md).

Task-owned bounded evidence and replay scripts are listed in
`/private/tmp/marinecast-influence-manifest.json`. Sources and earlier immutable
research releases remain retained; no cleanup batch or acquisition ran. The existing
frontend preview destination was reused. No live-provider run, new route-network
build, physical plume validation, UTC reconstruction, whale fitting, installed-wheel
acceptance or cross-platform test was performed. Full-history references and two-sided
interpolation remain retrospective/model-ineligible; forecasting requires training-only
references and availability-aware evaluation.


## Two-variable river influence — 2026-10-18

Historical release-layout receipt, superseded by the flat-file migration below.
User-requested scope reduction is implemented and rebuilt in the configured
`Data/HydrologyInfluence` root. Method `river-influence-water-r8-min-child-lag-v2`
exports only `discharge` and `relative_flow`; pulse-excess signals and pulse-count
bounds are absent from the active Parquet/recipe, browser encoding and app exports.
Native gauge flow indicators and observations are unchanged. Previous immutable
releases remain retained; the atomic catalog selects the new release.

Current product identity:
`4d1558b6b2f455b693accba0d3b60dff1c27e6b3a5d653bbbf4184403103125e`.
Catalog SHA-256:
`e36d95755fec1ec9007f6cc4dd91f97c7ae07d8eef13e3d708cc26315d97a942`.
Independent readback found all 43,686 spatial rows, 233,892 retained signal values
(two metrics × 116,946 river/date/lag rows), 116,946 interpolation-support values,
source bindings, dates, river definitions, settings and retained display bounds
exactly unchanged from v1. Active file checksums passed. The native Hydrology
catalog still matches its retained source hash. The real frontend evaluator matched
independent Python results for 131,058 cell values across 54 frames covering every
retained metric/distance/lag combination at three dates, including unavailable lag edges.

Validation: 166 offline producer tests, Ruff, 391 frontend tests in 74 files, two
adapter tests and seven live-reader tests passed. TypeScript, ESLint, production
build (existing chunk-size warning), diff and documentation checks passed. The
existing Meteorology Python environment was reused without modifying it. Native
browser QA confirmed the Hydrology family exposes only Relative flow influence and
Discharge influence and renders the retained surface. Pulse status/shortcut UI was
removed; lag controls now say Flow lag weights. Evidence and exact replay paths are
in `/private/tmp/marinecast-influence-manifest.json` and
`/private/tmp/marinecast-influence-removal-evidence.json`.

No acquisition, source rewrite, old-release deletion, new route-network build,
physical transport validation, model fitting, installed-wheel check or narrow-screen
QA was run. Retrospective/model-ineligible qualifications remain unchanged. See the
[current method](RIVER_INFLUENCE.md) and [app QA](../../../Applications/applications-data-explorer/docs/qa/river-influence.md#two-variable-product--2026-10-18).


## Single Parquet in Hydrology — 2026-10-18

The user requested one Parquet inside `Data/Hydrology` with no influence releases.
The active delivery is **`Data/Hydrology/influence.parquet`**, 1,557,830 bytes and
160,632 typed factor rows: 43,686 spatial rows plus 116,946 temporal rows. Its
`hydrology_influence` Parquet metadata embeds the recipe, logical factor checksum,
configuration, units, provider-day basis, exact source bindings and qualification.
There are no influence JSON companions or influence release directories in the
active Hydrology folder. The existing native gauge snapshot mechanism is unchanged.

File SHA-256:
`9bdb901708b4a99fb5caffe43185f3ef60154a6c0354663fab2e4f3d18ef7213`.
Recipe identity:
`1ea1f3b30033aada18f65aa1c93bf6de533c455cf8be8e1c8f1343e2b9432f8c`.
Logical factor SHA-256:
`be218db9cdd442252f289a0d8a433249eb6a21d93cf1f925fbbbe5cd0a653a13`.
All spatial and temporal factor values matched the preceding two-signal product
exactly; only string storage types and typed date representation changed. Dates,
reference definitions, units, support, scenarios, display bounds and qualifications
are unchanged. The native gauge catalog was not modified. Independent evaluation
matched 131,058 frontend cell values across 54 scenario/metric/date frames. An
identical production rerun retained the same file bytes, inode and modification time.

The writer uses the native product's exclusive lock, validates a sibling staging
file and source hashes before atomic replacement, and refuses unowned output files.
Native publication and indicator recomputation retain the flat companion; its source
binding remains explicit, so the app requires a rebuild after native data changes.
Tests cover rollback, idempotence, exclusive locking, companion retention, embedded
checksum/metadata rejection, duplicate identities and live replacement/invalidation.

Current checks: **168 offline producer tests**, **391 frontend tests in 74 files**,
**three influence-adapter tests**, seven live-reader tests, Ruff, TypeScript, ESLint,
production build (existing chunk-size warning), diff and local documentation checks.
After the full frontend run, six data/metadata tests were rerun following a source-info
typing correction. Native browser QA showed the retained influence surface with
`Hydrology/influence.parquet` as Source and its influence-specific Method/Coverage.
The existing Meteorology environment was reused; no environment changes occurred.

The former `Data/HydrologyInfluence` directory was moved intact into configured
source cache `Toolkits/toolkit-hydrology/data/cache/legacy-influence-2026-10-18`:
13 files, 4,754,075 bytes, with before/after file checksums matched. It is migration
history, not active delivery. No source deletion or acquisition occurred. Exact paths,
receipts and replay code are recorded in `/private/tmp/marinecast-flat-influence-manifest.json`
and `/private/tmp/marinecast-flat-influence-evidence.json`. The existing completed
preview destination was reused. Physical transport/whale validation, provider-network
acquisition, installed-wheel checks and narrow-screen QA were not rerun.


## Hydrology catalog registration — 2026-10-18

The existing `Data/Hydrology/catalog.json` now registers `products.influence` with
relative path `influence.parquet`, format, SHA-256, bytes, rows, recipe identity,
metrics/units, temporal basis, retrospective/model-ineligible flags, native-input
fingerprint and `source_status=current`. No extra delivery file or release layout
was created. Catalog SHA-256:
`2346e2b310931e4ce8765f27fbd5f7d22d3ba3891b6724219fa9e74112d3d08a`.
The Parquet SHA-256 remains
`9bdb901708b4a99fb5caffe43185f3ef60154a6c0354663fab2e4f3d18ef7213`;
all native catalog fields outside `products` are unchanged.

Native-input hashing excludes the derived product inventory, avoiding circular
catalog/file bindings. The canonical native fingerprint remains
`caf259097523e72774799e4c8ff7055999527d6f96a9431713f40684e277cc0e`.
Future builds refresh the catalog entry; native publication/recomputation retain the
entry and mark a carried product `requires_rebuild` when its native source changes.
Native validation rejects mismatched/missing file bindings. The app discovers the
file through the catalog and checks path, checksum, dimensions, identity, metrics,
qualifications and current source support before decoding it.

Current checks: 168 producer tests, four influence-adapter tests, seven live-reader
tests, Ruff and diff/local documentation checks passed. Actual current native-gauge
and influence readers both succeeded, preserving six rivers, 6,497 provider dates
and 2,427 influence reporting cells. The Parquet logical checksum and native-input
fingerprint were verified before catalog registration. Fixtures cover stable reruns,
stale carried products, unsafe pointers, checksum mismatches and source invalidation.
Evidence and the pre-change catalog are recorded in
`/private/tmp/marinecast-hydrology-catalog-manifest.json` and
`/private/tmp/marinecast-hydrology-catalog-evidence.json`. No acquisition, Parquet
regeneration, browser pass, frontend suite/build, physical validation or wheel test
was rerun for this catalog/reader-only change.


## Four additional US rivers and publication protection — 2026-10-20

Tyler approved Puyallup 12101500, Elwha 12045500, Skokomish 12061500 and Queets
12040500 for existing discharge-derived features, with missing temperature retained
and a coverage-regression safeguard. The original six-river pilot remains explicit
in `config/pilot.json`; native defaults and the configured influence roster now select ten.

Final implementation checks: **202 offline tests passed from the owning checkout**
with its local settings. Ruff and `git diff --check` passed. New regressions cover named basin IDs/R8 attachment checks,
all four stations, unsupported temperature without dispatch, observed zero, source
gaps/flags/provenance, unchanged bytes of six unselected rivers, pre-acquisition
rejection of cropped windows or omitted observed temperature, equal-count day loss,
known support/approval downgrades, retained inputs on rejection and accepted official
numerical revisions. Native request grouping covers exactly the same requested dates
as monthly grouping, accepts 1–240 months and is refused above one month for UTC
acquisition. The approved 216-month request contains 6,527 warmup-inclusive daily
dates, below the existing USGS 10,000-row page limit. Monthly remains the default.

A bounded live seven-day check (2009-01-01–2009-01-07 plus required warmup)
passed **28/28 discharge river-days**, with each requested temperature mean/max
calendar wholly null/unavailable and reason `unsupported`. This source check took
19.38 seconds with one worker and 1.25-second request pacing. It does not establish
gap-free full history or UTC support.

The first full-history monthly attempt was explicitly bounded to 868 expected
requests, 45 minutes, 256 MiB cache and 900 unique cached pages. USGS returned
HTTP 429 after 78 retained pages and an explicit 12:00 UTC retry deadline. The
client deferred further dispatch and retained resumable inputs. The existing writer
published explicit incomplete new-river calendars; this is not a completed source
collection. Puyallup retained 2,281 observed days through 2015-03-31, while the
other new discharge series were unattempted. All **48 files within the original
six river folders remained byte-identical**, including their original 11 gaps.

The 80-request annual resume honored that deadline, but encountered a further
429 and yielded only 334 Puyallup observations. The publication guard rejected the
loss of 1,947 retained observations before promotion; all current data remained
unchanged. This is an actual failed-replacement check, not just a synthetic test.

After the persisted second deadline, the same bounded source job resumed using
one existing-adapter daily request per gauge (12 planned requests including metadata,
with verified metadata reuse). It finished in **32.49 seconds**, at 12:07 UTC,
within the original 45-minute deadline, 256 MiB/900-page cache caps, one worker and
1.25-second pacing. Successful validated publication performed only its normal owned
download cleanup. No parallel acquisition or provider bypass was used.

| Added river | Station | Observed / expected discharge days | Source execution | Temperature |
|---|---|---:|---|---|
| Puyallup | USGS-12101500 | 6,497 / 6,497 | complete | unsupported/null |
| Elwha | USGS-12045500 | 6,497 / 6,497 | complete | unsupported/null |
| Skokomish | USGS-12061500 | 6,152 / 6,497 | complete; 345 source gaps | unsupported/null |
| Queets | USGS-12040500 | 6,497 / 6,497 | complete | unsupported/null |

Independent retained-file verification matched native/source observations and
provenance, all trailing 7/30-day means and 7-day changes, and all three retrospective
P10/P90 indicators. It confirmed null/unavailable/unsupported temperatures, no
climatology and all **48 original river files byte-identical**, including 11 earlier
discharge gaps. All ten rivers retain 64,614/64,970 measured discharge river-days;
Skokomish's `complete` and required-discharge-eligible flags remain false. Puyallup's
publication guard preserved all 2,281 earlier eligible observations with zero revised
values. Qualified relative-flow interpolation does not fill raw discharge.

The offline influence rebuild took 2.92 seconds: ten rivers, 6,497 dates, 2,427 cells,
72,810 spatial and 194,910 temporal factor rows. Independent checks matched exact
pinned R8 minimum-child distances/profile coefficients and all original six logical
factor arrays. Every river retains 2,348 known and 79 unknown reporting-cell routes.
Influence SHA-256: `1922301967fbe166dab55bce90ac48b24b5ca598765759c44807d1920fb95e66`.

The current app reader and running localhost Hydrology and river-influence endpoints
both passed checksum-bound readback: ten rivers, eleven unsnapped mouth references,
6,497 provider dates, ten display metrics and exact measured coverage above. Source
catalog SHA-256 after influence registration:
`611057e00110c339009dd3e524a70e9fa1b3459be2e360253d6bc3dfca48998e`.
The coordinated app changes passed 12 reader tests, 35 focused frontend tests and
TypeScript no-emit checking. No shared map/page/routing or Governance files changed.
Native-browser visual QA was not rerun for these roster/color additions.

The final wheel installed outside the source tree, loaded all ten bundled registry
entries and the 12-request plan offline, and its guard/config/acquisition modules
matched source bytes. Wheel SHA-256:
`0a51269043ced36cc69d5b2e9b8aa9985c16e56a0345e4c9b37c624dfba251d4`.
No Canadian acquisition, climatology fit, eligibility upgrade, station sum, Seascape
modification, physical plume validation, commit, push or merge was performed.


## Causal retained-discharge build — 2026-10-26

The single-worker offline build produced 519,760 rows (64,970 river-days × eight
metrics), 2009-01-01–2026-10-15, in 1,896,280 bytes. Runtime 11.96 seconds; measured
peak process RSS 712,523,776 bytes (includes validation/readback). All 82 pre-existing
non-catalog files retained identical SHA256, including discharge, other variables,
retrospective features and influence. Influence catalog source_status remains current.
The native catalog validator and Parquet frame readback passed.

Full offline suite: 207 passed in 12.02 seconds with the existing OrcaCast Python
3.12 environment and PYTHONPATH=src; toolkit .venv is absent. An earlier sandboxed
run had 205 passes and one configured-directory writability failure; the authorized
filesystem run resolved that environmental failure. No network acquisition, app
changes, model fitting, UTC conversion or H3 build was run.

Valid value counts out of 64,970 river-days per metric:

- `causal_days_since_discharge_pulse`: 52142
- `causal_discharge_pulse`: 53661
- `causal_discharge_seasonal_anomaly`: 53748
- `causal_discharge_seasonal_mean`: 54010
- `causal_discharge_seasonal_p90`: 54010
- `causal_discharge_seasonal_percentile`: 53748
- `causal_reference_samples`: 64970
- `causal_reference_years`: 64970

Seasonal references first qualify on 2012-01-02; 2012-01-01 still uses as-of
2011-12-31 and only two completed reference years. Baseline/P90 each have 5,401
valid days per river. Skokomish has 5,150 anomaly/percentile, 5,066 pulse and 3,896
pulse-age days; strict missing-day resets intentionally reduce pulse-age coverage.

Skagit output 2026-10-15 (as-of 2026-10-14): mean 370.222673 m3/s, P90
762.006342 m3/s, anomaly −158.412661 m3/s, percentile 23.225806%, pulse 0,
pulse age 211 days, reference 310 samples / 10 years. These are gauge descriptors,
not calibrated flood/ecological thresholds. See [method limits](CAUSAL_FEATURES.md).

SHA256 causal.parquet: `6e306d75cdb87daec0bd95de0781835c6fb0a6ac50080249467cac3f1bd9e3ef`.
One small prior catalog remains outside Data in the destination-owned work area
(`causal-prior-catalog.json`); no old data replay, downloads, preview or inhibitor
was created. Its inspection/cleanup is required before another companion publication;
permanent deletion was outside this task's authorization.

## Independent station-temperature delivery — 2026-10-26

Real official DFO report-text validation promoted 101 Qualark daily means in
`station_temperature.parquet` (130,243 bytes; SHA256
`a471a16751519e8f43c68e2ffa67a9f779bcf945230da4fc1a0f6066709a106c`).
Support: 2023 26 dates (July 26–October 29); 2024 32 (July 1–October 16);
2025 21 (July 9–September 21); 2026 22 (July 8–September 20). These are sparse
observations, not continuous date ranges. Seven early-2023 Hope-labelled rows were
excluded. All 83 pre-existing non-target product files retained identical checksums.
Publication/readback/complete canonical validation took 7.97 seconds, peak RSS
441,024,512 bytes. The 108 retained text responses total 1,366,186 bytes outside Data.

The final full suite passed 218 tests in 11.77 seconds, including all 11 focused
station tests and rollback coverage. No live Ecology importer was qualified:
10A040, 07A089, 18B070 and 16A070 remain pending public access/authorized exports.
DFO pre-2023 archives remain unqualified; 2022 is PDF-based and the 2019 directory
probe did not parse as a standard ZIP end record. No inferred station equivalence,
UTC daily reconstruction, discharge refresh or model readiness is claimed.

### Historical temperature extension, same day

The current station companion supersedes the initial checksum above: 217 rows,
236,185 bytes, SHA256 `66daaa4939c8335f0d75d3ff7a3154bf4e67abe18e14420cc68c28ae37c7de5f`.
All 101 existing rows and 83 non-target files are preserved. The 116 added distinct
dates comprise 113 in 2012–2017 and one reviewed date each in 2009–2011. Source row
NA and duplicate handling are explicit; no other station or interpolated day enters.
Build/promotion/readback took 10.31 seconds, peak RSS 417,234,944 bytes. Twenty focused
tests passed, including PDF dates/columns, tamper rejection and duplicate conflicts.

Final historical-extension suite: 227 tests passed in 12.30 seconds; all 20 focused
station tests also passed after the paired-HTML checksum guard. Diff checks passed.

### Read-only temperature follow-up — 2026-10-28

All 28 English PDF current-temperature tables in the retained official 2019 archive
were inspected using installed bsdtar and pdftotext; first report visually checked.
All explicitly name Hope, none Qualark. No observations were imported. Current
canonical validation passed, with 217 station rows and unchanged SHA256
`66daaa4939c8335f0d75d3ff7a3154bf4e67abe18e14420cc68c28ae37c7de5f`.
No Ecology exports were identified by scoped filename search in Downloads, Codex task
folders or Hydrology delivery. No previously denied Ecology endpoint was retried.
No behavior changed; the test suite was not rerun for this source qualification note.


### 2026-10-28 Ecology original browser export delivery

Normal official browser exports downloaded 2,970,150 bytes total, with no sign-in,
CAPTCHA, agreement acceptance or automated endpoint bypass. Original ZIPs retained
outside delivery. New adapter tests cover exact station identity/coordinates,
water-vs-air and Celsius checks, native PST, leap dates, quality semantics, gaps,
overlapping water-year files, future cutoff and conflicting duplicates.

Full owner offline suite: **240 passed in 13.21 s** in the installed `orcacast`
Python environment. The initial restricted-shell run had 239 passes and one
preflight failure because the configured DATA_DIR appeared unwritable; the same
suite passed with approved filesystem access. Focused station tests: 33 passed.
`git diff --check` passed. No USGS/ECCC network pilot or new discharge acquisition.

Transactional publication completed in 8.69 s, readback and preserved-row checks
passed, and all 83 non-target product files retained their hashes. Current
station companion: **2,136 rows**, **1,188,065 bytes**, SHA256
`ed520b383d5223b5263be930185455b1c35fa49368a35dc985a800ece6007a95`.
Qualark's 217 rows and station metadata remain exact. Added 842 Puyallup and 1,077
Snohomish daily means; their first-to-last intervals contain 17 and 125 absent
days respectively. 27 Snohomish values are unchecked (code 140), explicitly flagged.
No missing/rejected/incomplete day was filled or included as a measurement.

Elwha and Skokomish EIM original exports remain pending a user-specified delivery
email; no queue request was submitted. Availability counts are not imported
observations. App code and shared configuration were untouched. Knowledge-vault
upkeep is handed to the coordinating parent because this worker owns only Hydrology.

### Elwha EIM delivery, 2026-10-28

Final full offline suite: **254 passed in 15.20 s**; focused station suite:
34 passed. Real-source qualification matched all 39,746 expected CSV records and
verified 909 provider daily summaries against 48 unique native half-hour readings
per day. Tests cover leap dates, missing/duplicate timestamps, incompatible units,
wrong stations, altered values, incomplete/unknown-timezone exclusion and extreme
occurrence timestamps. No new network acquisition succeeded; user-delivered extracted
originals resolved the download blocker, and their per-file checksums are retained.

Current companion: **3,045 rows**, **1,251,158 bytes**, SHA256
`ec07d2b051e99a01ff0ba6b63937eaf94eaff5de22c10b7877244164388b454b`.
Added 909 Elwha rows over 303 seasonal days, preserving every prior 2,136 row and
station metadata exactly. All 83 non-target files stayed byte-identical. Locked
publication, canonical validation and readback passed in 9.28 s. Original pooling
comments remain explicit; no model-readiness assertion. Skokomish remains pending.


### Skokomish delivery, 2026-10-29

Full offline suite **256 passed in13.48s**. Source counts/identity, complete native
days, statistic values and extrema timestamps verified against retained records.
Locked publication plus checksum/readback took11.26s. All3,045prior rows and station
metadata preserved exactly;83non-target files remained byte-identical.
Current product **5,301rows**, **1,397,734bytes**, SHA256
`0b53ab51df95498b222ecda883cc7a7514de689b386625f1f0d99283074520ec`.
Added2,256rows across752seasonal days. No network pilot, app test, or discharge,
causal or influence rebuild. Source originals and bounded rollback evidence retained.

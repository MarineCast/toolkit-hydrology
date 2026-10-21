# Hydrology Toolkit

<img src="docs/assets/hydrology-toolkit-banner.png" alt="Watershed panorama" width="100%">

Observed river conditions for MarineCast. The six-river pilot includes Fraser,
Skagit, Snohomish, Nooksack, Cowichan and Columbia. It ingests official USGS OGC v1
and Canadian HYDAT/GeoMet discharge, preserves native daily support, computes daily
features (including explicitly retrospective relative flow indicators), and optionally
builds water-connected H3 association proxies.

The curated registry also includes Puyallup (USGS-12101500), Elwha
(USGS-12045500), Skokomish (USGS-12061500) and Queets (USGS-12040500),
added on 2026-10-20 for the same discharge features. The default native selection
is now all ten rivers; `config/pilot.json` preserves the original six-river pilot.
The four added gauges have no qualified native daily temperature mean/max source:
requested temperature stays null/`unavailable` with `unsupported` reasons.
See the dated expansion evidence in [validation](docs/VALIDATION.md).

**Validated:** 2023-01-01–2023-03-31 discharge for all six stations (90/90 days each),
and daily mean/max temperature for Skagit, Nooksack and Columbia (90/90 each).
Native daily data are not UTC daily data. Production marine mapping remains blocked
by missing versioned water-mask/receiving-region inputs; synthetic spatial tests are
not production validation. See [actual validation](docs/VALIDATION.md).

## Final products

A successful `--make-h3 --temporal-requirement utc_daily` build produces:

```text
RELEASE/final/static.parquet   # h3_index × metric
RELEASE/final/dynamic.parquet  # h3_index × date × metric
RELEASE/final/catalog.json    # inventory, sources, schema, units and checksums
```

All produced static metrics share the static file; all time-varying metrics share the
dynamic file. Dates are typed UTC calendar dates. Values, statuses and contributors
remain explicit. The dynamic file streams one day at a time during construction.

After both final files, their catalog and the release pass saved-output validation,
the build automatically deletes its owned downloaded response files. Failed builds
retain downloads for resumption. External input files and existing shared caches are
preserved. Native/QA outputs remain supporting artifacts outside `final/`. Native-only
pilot runs retain their cache until a final H3 build can be completed.

## Install and test

From this checkout (`MarineCast/Toolkits/toolkit-hydrology` in the inspected workspace):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

No sibling package installation is needed for native data access. Downloads, cache,
virtual environment and releases are ignored by Git. Optional `USGS_API_KEY` raises
provider rate limits; do not store it in a tracked file.

GitHub's [offline package workflow](.github/workflows/ci.yml) runs the synthetic
suite on Python 3.11 and 3.14, checks dependency consistency and the CLI, and builds
a regular wheel. A fresh environment then runs the contract tests and CLI outside
the checkout using that wheel. Live-marked tests, provider acquisition and retained
data products are excluded. Passing these checks establishes software/package
acceptance only; the scientific and regional limits in
[validation](docs/VALIDATION.md) still apply. This workflow does not change branch
protection requirements.

## Local run defaults

Copy `.env.example` to `.env` in this toolkit folder, following Meteorology's
setting names. The private `.env` is ignored; commit only the example:

```dotenv
DATA_DIR=../../Data/Hydrology
START_DATE=2009-01-01
END_DATE=2026-10-15
VERBOSITY=True
```

`DATA_DIR` selects the current native per-river delivery product for `publish` and
offline recomputation. File-relative paths resolve beside that file and preserve the
final regular `Hydrology` directory. Source `--cache` and legacy release `--output` stay separate;
raw cache/staging is never placed inside the delivery product. Dates bound acquisition
and newly produced output; recomputation always uses the entire existing retained
history and does not crop it to acquisition defaults.

Precedence is explicit CLI/API arguments > supplied JSON >
`MARINECAST_HYDROLOGY_CONFIG` JSON > process environment > local `.env` > defaults.
Only `.env` in the current working directory is read automatically; there is no parent
search or environment mutation. `--env-file` / Python `env_file` selects another
file. File-backed runs require all four effective values. Preflight reports invalid,
missing or duplicate settings together without exposing raw values; no locks, output
writes or provider calls occur before it succeeds.

```sh
hydrology preflight
hydrology publish --dry-run
hydrology recompute-flow-pulse --no-verbose
```

`VERBOSITY` accepts True/False. `--verbose` and `--no-verbose` override it, including
explicit false. Timestamped application progress goes to stderr; CLI stdout stays
JSON. Verbose output covers resolved run settings and acquisition/processing or
offline-validation/promotion stages without provider bodies or credentials.
Verbosity does not change scientific run identity. Direct `Config(...)` construction
remains explicit; `Config.load`, default public API calls such as
`get_river_discharge()`, and `publish_hydrology()` resolve local settings. No-file
API calls retain their existing defaults. Reading `.env` never initiates acquisition.

## Code organization

Start with `main.py` for the Python API or `cli.py` for command-line arguments.
Entry points resolve settings and delegate work to the relevant pipeline:

```text
src/hydrology/
├── main.py                  Public Python API and settings-to-workflow routing
├── cli.py                   Argument parser and command dispatch
├── __init__.py              Stable package-level API exports
├── __main__.py              python -m hydrology entry point
├── pipelines/
│   ├── acquisition.py       Request planning, provider calls and acquisition outcomes
│   ├── native.py            Native discharge/temperature access workflow
│   ├── processing.py        Source selection, daily support and feature preparation
│   ├── releases.py          Immutable releases, optional H3 output and release checks
│   ├── publication.py       Current per-river product transactions and reader locks
│   ├── recompute.py         Offline relative-flow updates from retained conditions
│   ├── influence.py         Pinned outlet relationships and factorized research product
│   └── commands.py          CLI command workflows and JSON results
└── utils/
    ├── config.py            Typed Config and date/config validation
    ├── settings.py          .env precedence, preflight and stderr logging
    ├── contracts.py         Observation keys, statuses, eligibility and value checks
    ├── io.py                Atomic file writes and checksums
    ├── provenance.py        Source references, runtime and implementation fingerprints
    ├── http.py/providers.py Provider transport, parsing and unit conversion
    ├── ledger.py            Durable acquisition checkpoints
    ├── registry.py          Bundled river/station registry and coverage summaries
    ├── daily.py/temporal.py Native calendars and supported UTC aggregation
    ├── features.py          Trailing features and training-only seasonal references
    ├── flow_history.py      Shared qualified/interpolated discharge preparation
    ├── low_flow.py          Retrospective P10 low-flow duration
    ├── flow_pulse.py        Retrospective P90 pulse timing
    ├── high_flow.py         Retrospective P90 high-flow duration
    ├── influence.py         Config validation, distance/lag factors and reference sums
    ├── spatial.py           Explicit water-connected association calculations
    └── products.py          Product schemas, catalogs, I/O validation and owned cleanup
```

For example, `get_river_discharge()` routes through `pipelines.native`, acquisition,
source selection and the daily-calendar utility. `publish` routes through
`pipelines.commands` to `pipelines.publication`, which calls feature preparation
before its existing validated transaction. Recompute workflows read retained
conditions and never invoke acquisition.

Utilities never import pipeline orchestration or entry points. Pipelines own the
order of operations and side effects; domain calculations, source semantics and
shared contracts remain in focused utilities. Existing flat module imports such as
`hydrology.core`, `hydrology.pipeline`, `hydrology.canonical` and
`hydrology.low_flow` remain small compatibility re-exports; new code should use the
canonical paths above. Patch/test a dependency in its owning module (for example,
`pipelines.acquisition.acquire`) rather than a compatibility export.

Implementation fingerprints cover all package Python files recursively, using paths
relative to the package so nested files with the same basename remain distinct.
Code refactors can change future build identities; existing saved products and
their recorded implementation hashes are not rewritten by importing new code.

## Bounded pilot and native API

```bash
.venv/bin/python -m hydrology build --config config/pilot.json --dry-run
.venv/bin/python -m hydrology build --config config/pilot.json
.venv/bin/python scripts/validate_pilot.py --report data/pilot-report.json
# Use the release_path printed by build:
.venv/bin/python -m hydrology validate data/releases/RELEASE_ID
# Discovery and coverage use the same explicit selection/configuration:
.venv/bin/python -m hydrology discover --config config/pilot.json
.venv/bin/python -m hydrology audit --config config/pilot.json
```

```python
from hydrology import (
    get_river_discharge, get_river_temperature,
    get_river_context, get_hydrology_features,
)
q = get_river_discharge('2023-01-01', '2023-03-31', rivers=['fraser'], cache='data/cache')
t = get_river_temperature('2023-01-01', '2023-03-31', rivers=['columbia'])
print(t.attrs['outcomes'])  # explicit observed/unsupported/empty/failure outcomes
registry = get_river_context(make_h3=False)
release, manifest = get_hydrology_features('2023-01-01', '2023-03-31', make_h3=False)
```

`bbox=(west,south,east,north)` filters river mouths, never upstream stations. No
production study extent was available, so default native access selects named rivers.
Without local settings, Config defaults to 2009-01-01 through yesterday; **supply bounded dates for tests**.
CLI/function overrides → supplied JSON → optional `MARINECAST_HYDROLOGY_CONFIG` →
process environment → CWD `.env` → package defaults. `--data-source auto` follows registry ownership, with optional local
HYDAT snapshot when supplied. It never silently falls back to modeled data.

## River influence scenarios

The separate [river influence product](docs/RIVER_INFLUENCE.md) selects all ten
rivers on the shared R6 reporting grid using pinned Seascape R8 water-network
relationships. It supports configurable exponential/offshore-peaked distance profiles,
normalized past-day lag weights, explicit river gains and per-cell overlapping
contributions. Its factorized storage keeps the full retained history small.

```sh
PYTHONPATH=src python -m hydrology build-influence --config config/river-influence.json
```

Paths and scenario definitions live in that explicit JSON, resolved beside the file;
it selects **`Data/Hydrology/influence.parquet`**, a single file with embedded recipe
and provenance and no influence release directory or separate sidecars. The existing
Hydrology catalog lists it under `products.influence`, which the app validates. Native acquisition
continues to use the existing `.env` settings. Python callers can use
`hydrology.build_influence(config_path)`. This command is offline and does not
modify native river data or Seascape sources. The Explorer offers the prepared
profiles under **Hydrology → Family → River influence**, with **Relative flow influence**
and **Discharge influence**. The two spatial pulse variables were removed from the active
product and app on 2026-10-18; native gauge flow indicators are unchanged.

These are retrospective research indices. Distances use the nearest reachable R8
child representative within each R6 reporting cell, rather than its center or an
area mean. Unknown routes remain unknown; coverage accompanies supported subtotals.
The named Columbia origin is in the estuary, upstream of the ocean mouth. Source
registration, gauge-to-mouth timing and physical transport remain unqualified.
This does not establish a plume, conserved marine discharge or whale response.
See the [method contract](docs/RIVER_INFLUENCE.md) and dated [validation](docs/VALIDATION.md#river-influence-scenarios--2026-10-18).

## Training-only baseline and later application

The following acquisition is intentionally explicit; it was **not** launched as part
of the 90-day smoke test. Change the dates for your training split.

```bash
.venv/bin/python -m hydrology build --rivers skagit --start-date 2009-01-01 --end-date 2018-12-31 --dry-run
.venv/bin/python -m hydrology build --rivers skagit --start-date 2009-01-01 --end-date 2018-12-31
.venv/bin/python -m hydrology fit-climatology data/releases/TRAIN_RELEASE/river_conditions.parquet --cutoff 2018-12-31 --reference-start 2009-01-01 --output data/baseline.json
.venv/bin/python -m hydrology build --rivers skagit --start-date 2019-01-01 --end-date 2019-03-31 --climatology data/baseline.json
```

An artifact requires 60 seasonal samples from at least 3 distinct training years by
default. A 90-day pilot cannot establish that baseline: its seasonal anomalies remain
unavailable. Apply an existing artifact to saved conditions using `hydrology features
CONDITIONS --climatology BASELINE --output FEATURES.parquet`.

## Strict UTC and H3

A bounded real Columbia UTC check can run without a spatial build:

```bash
.venv/bin/python -m hydrology build --rivers columbia --start-date 2023-01-01 --end-date 2023-01-03 --temporal-requirement utc_daily
```

For H3, provide a reviewed domain, full connected water polygon and named receiving
regions in WGS84 GeoJSON. The files below are **required external inputs**, not bundled
demonstration geometry. Names must match the registry; see [input contract](docs/CONTRACTS.md).

```bash
.venv/bin/python -m hydrology build --config config/pilot.json --rivers columbia --start-date 2023-01-01 --end-date 2023-01-03 --temporal-requirement utc_daily --make-h3 --h3-res 6 --water-mask /path/to/versioned-water.geojson --water-mask-version YOUR_RELEASE --receiving-regions /path/to/receiving-regions.geojson
```

Add `--bbox WEST SOUTH EAST NORTH` using your shared MarineCast study extent.
Provider-native daily builds reject the strict UTC H3 table. Canadian historical daily
data cannot reconstruct UTC; only retention-supported recent timestamped WSC records
can, with `--allow-provisional`. Do not claim a six-river historical UTC table from the
native pilot. H3 metric values are associated **river proxies**, not local seawater,
salinity, plume strength or freshwater fractions.

## Resumable backfill and reconciliation

```bash
# Review all selected rivers and monthly acquisition blocks first:
.venv/bin/python -m hydrology build --start-date 2009-01-01 --dry-run
# Explicit acquisition; defaults end date to yesterday:
.venv/bin/python -m hydrology build --start-date 2009-01-01 --cache data/cache --output data/backfill --workers 1
# Re-running the same command resumes cached pages. A local HYDAT snapshot is optional:
.venv/bin/python -m hydrology fetch --rivers fraser cowichan --start-date 2009-01-01 --hydat /path/to/Hydat.sqlite3
# Refresh a bounded recent/revision window; old releases remain immutable:
.venv/bin/python -m hydrology reconcile --start-date 2026-09-01 --end-date 2026-09-30
```

The first native collection retained 2009-01-01–2026-10-15, with 11 explicit
discharge gaps; see the [collection record](docs/VALIDATION.md#first-current-daily-collection--2026-10-16)
and [remaining work](TODO.txt). No full-history UTC/H3 product is established.
Native-only cached pages are reused until explicit refresh/reconcile; completed H3
builds remove their owned downloads. Cached pages are not evidence of provider freshness. Server `Retry-After` deadlines
are honored; if the required wait exceeds the remaining 60-second invocation budget,
the outcome is explicitly deferred and completed pages remain cached. Configure
`--retry-wait-budget-seconds` (or the matching JSON field) to choose a finite budget;
rerun with the same cache after the reported deadline. A deferred host receives no
further network requests in that invocation. See [contracts](docs/CONTRACTS.md) for
cooldown persistence. Runtime and
memory have only been measured on bounded pilots. CLI exits 2 for missing required
discharge or spatial build failures, while retaining independent native results.
Python native APIs return outcomes in DataFrame attrs, including empty/gap results.

Read [sources](docs/SOURCES.md), [architecture/contracts/metrics](docs/CONTRACTS.md),
and [validation, performance and remaining gaps](docs/VALIDATION.md) before production
use. Catchment geometry, expanded river curation, supplemental Canadian temperature,
meteorological basin aggregation, modeled fallback and transport remain extension work.

## Current per-river products

Use `publish` for a single current native product instead of accumulating release
folders. This command acquires data **only when explicitly executed**; dry-run first:

```bash
hydrology publish --rivers skagit --start-date 2023-01-01 --end-date 2023-01-07 --product-output /path/to/MarineCast/Data/Hydrology --dry-run
# Explicit acquisition/promotion, only after source-run scope is approved:
hydrology publish --rivers skagit --start-date 2023-01-01 --end-date 2023-01-07 --product-output /path/to/MarineCast/Data/Hydrology
hydrology validate-product /path/to/MarineCast/Data/Hydrology
```

`publish` requests discharge only by default. Add `--metrics discharge_mean
temperature_mean temperature_max` for optional temperature. Python:
`from hydrology import publish_hydrology`; pass a `Config` with explicit bounded dates
and `product_output`, or call `hydrology.canonical.publish_rivers(config, metrics=...)`.
`product_output` defaults to caller-relative `Data/Hydrology`; this independent package
does not guess the location of a MarineCast checkout.

Each river contains `conditions.parquet`, `features.parquet`, `metadata.json` and
`manifest.json`, plus supporting `observations.parquet`, `warmup.parquet`,
`coverage.parquet` and `acquisition-ledger.json`. The root `catalog.json` indexes
checksummed river manifests. Every requested date is explicit, including leading,
trailing and wholly absent variables. Unrequested temperature is null with
`not_applicable`/`not_requested`, never zero. Native daily dates remain provider days;
only timestamp-supported UTC builds use `utc_daily`.

`execution_complete` reports whether requested source work finished without failure
or deferral. `data_eligible` separately checks required discharge coverage, default
100% of requested dates (`minimum_daily_coverage`). `complete` additionally requires
successful required-discharge acquisition. Temperature gaps do not block this
required-discharge baseline. None of these flags establishes ecological model
readiness or operational historical availability. Partial products are readable and
explicitly marked; CLI exits 2 when the selected rivers fail the required gate.

Publication writes a regular directory at `product_output`, including `Data/Hydrology`.
Temporary candidates, a recoverable promotion journal and persistent advisory lock
live outside its delivery parent: `<delivery-parent>/../.marinecast-work/hydrology/<destination-hash>`.
Readers making several reads must use `with hydrology.canonical.product_snapshot(path)
as pinned:` and read through `pinned`. The shared lock prevents replacement during
that read. Writers validate the candidate, rename the previous directory to a
bounded recovery backup, promote the candidate and remove the backup. An interrupted
promotion is recovered by the next writer; readers reject an unrecovered journal.
Unowned directories and legacy symlinks are refused. The workspace's existing
symlink was explicitly migrated on 2026-10-18 with unchanged product bytes.

Canonical `publish` uses its own resumable `downloads/` under this work area,
by default. An explicit `Config.cache` / `--cache` selects a work base with
a destination-specific owned child; existing shared files there are preserved. After an execution-complete publication and final validation, owned downloads
and obsolete candidates are removed. Failed/deferred runs retain resumable inputs
outside delivery. User-provided HYDAT databases, masks, registries and climatologies
are preserved. No accumulated successful generations or source archives are kept.
An existing selected river requires a window covering its **entire retained history**
and every previously observed metric. Cropped windows, omitted observed temperature,
and station/temporal-basis substitutions fail before provider dispatch. Before
promotion, the coverage-regression guard checks every previously eligible observation:
missing/non-valid replacements, reduced known interval coverage, changed units/origin,
and known approval/estimated/partial-day downgrades are refused. Changed unranked
provider qualifiers also fail closed rather than assuming a quality ordering. Equal total counts
cannot hide a lost day. Official numerical revisions with equivalent or improved
support remain allowed and are counted in the manifest. No automatic merge, imputation
or force-bypass is provided. A rejection leaves the current product intact and retains
resumable downloads. New rivers may contain explicit source gaps; their eligibility
remains separate from execution completion. Defaults bound publication to 2,000,000 rows
and 512 MiB (`publication_max_rows`, `publication_max_bytes`). Byte limits are checked
after each staged file; one in-flight file can temporarily exceed the limit and is
removed on failure. The limits do not cap upstream HTTP acquisition; choose bounded
dates and source budgets separately. The existing `build` release/H3 API remains
available for compatibility and is not invoked by `publish`.

HTTP cache hits verify request URL, envelope shape, aware retrieval timestamp, body
hash and corresponding snapshot integrity. Corruption fails closed without deleting
inputs or silently fetching replacements. Release identities include discovered
metadata and successful response inventories, including empty queries. Acquisition
checkpoints under `cache/acquisition-ledgers` record each monthly block as pending,
running, completed, empty, unsupported, outside-relationship, deferred, failed or
not-attempted. A failed later block retains prior normalized blocks; reruns replay
verified cached pages and retry unfinished blocks. The ledger is diagnostic, not a
substitute for input verification. Use one acquisition job per shared cache/provider;
there is no cross-process provider rate limiter.

The current shared study mask/grid and Seascape outlet inventories now exist in the
MarineCast workspace, but this package has **not** implemented their adapter or
qualified production routes. Per-river publication does not imply H3 mapping,
measured river-mouth flux, plumes, or a validated whale response. See [TODOs](TODO.txt).

For cache-only validation use `--offline`; a cache miss or explicit refresh in offline
mode fails without dispatching an HTTP request. A local HYDAT fixture/snapshot can
still be read offline. Offline mode does not invent missing monthly pages.


By default, build/publish and the `features` CLI calculate `low_flow_duration` as
consecutive days strictly below each river's **historical 10th percentile** of daily
mean discharge. The reference is the full requested output history (not rolling or
seasonal). Interior gaps are linearly interpolated before fitting the linear quantile
and counting streaks. No edge extrapolation; a spell with an unknown start stays null
until a known non-low day. Interpolation is restricted to the three relative flow
indicators: observed discharge, flags, missingness, coverage and other metrics remain intact. Definitions
record thresholds, reference dates, observed/interpolated/unfilled counts, interpolation
endpoints and values, method and identity. Per-day reasons identify estimated inputs
and streaks depending on them. This uses future observations and is **retrospective,
model-ineligible and unsuitable for operational backtests**; it is not an ecological
threshold. New history can change thresholds and earlier durations.

`low_flow_method="fixed"` / `--low-flow-method fixed` retains the legacy fixed
`low_flow_threshold` (default 10 m³/s), with gaps resetting unknown history. The
low-level `build_features` function remains this legacy causal primitive; the pipeline
applies `hydrology.utils.low_flow.replace_low_flow` for the default relative calculation.
`days_since_flow_pulse` now defaults to each river's **historical 90th percentile**,
using the same full-history linear quantile and interior-only interpolation. A pulse
is an upward crossing from below P90 to at or above it; duration is zero that day,
then counts calendar days since that crossing. Sustained high days do not reset it.
History remains unavailable before a known crossing or after an unfilled gap.
`flow_pulse_definition` preserves threshold/reference/interpolation provenance, with
per-day `interpolated_flow_input` / `pulse_history_includes_interpolated_flow` reasons.
This indicator is also retrospective and model-ineligible.
`flow_pulse_method="fixed"` / `--flow-pulse-method fixed` preserves the legacy
`pulse_threshold` (default 1,000 m³/s) without interpolation. Neither metric
establishes ecological or whale effects.

`high_flow_duration` is included by default in build/publish and the `features` CLI.
It counts consecutive provider days **strictly above each river's historical P90**,
using the same full-output-history linear quantile and interior interpolation as
pulse timing. At or below P90 resets duration to zero. Unknown spell starts remain
null until a known at-or-below day; no edge extrapolation. Require two supported
days. `high_flow_definition` binds threshold, reference, endpoint provenance and
per-day estimates to method `historical-p90-high-duration-linear-interior-v1`.
It is retrospective/model-ineligible; original observations and other metrics remain
unchanged. `high_flow_method` currently supports only `historical_percentile`.

To update an existing current product **offline**, without provider acquisition:

```sh
hydrology recompute-low-flow /path/to/MarineCast/Data/Hydrology
hydrology recompute-flow-pulse  # DATA_DIR and verbosity from local .env
hydrology recompute-high-flow   # add/update high-flow duration from retained discharge
hydrology validate-product /path/to/MarineCast/Data/Hydrology
```

The public Python equivalents are `hydrology.recompute_low_flow(destination=None)`
`hydrology.recompute_flow_pulse(destination=None)` and
`hydrology.recompute_high_flow(destination=None)`, with optional `env_file` and
`verbosity`. They validate the current source, add or replace only the selected metric's rows and
provenance in a temporary owned candidate, validate readback and promote the regular
current directory under the publication lock. Unchanged immutable companions are
hard-linked; successful promotion removes the previous generation and candidate.
Repeated identical calls are idempotent. Failed staging is retained outside delivery
for repair; no source downloads occur. The `features`
CLI also writes `<output>.low-flow.json`, `<output>.flow-pulse.json` and
`<output>.high-flow.json` alongside
its feature Parquet.

`not_applicable` with `not_requested` on missing temperature identifies acquisition
scope/source availability in that run. It does **not** mean temperature is physically
or scientifically inapplicable to Fraser, Cowichan or Snohomish. No training
climatology is fitted unless explicitly supplied through the documented training path.

Native daily request grouping defaults to one calendar month. For reviewed bounded
USGS daily acquisitions, `--acquisition-block-months 12` (or the matching Config/JSON
field) reduces request overhead while preserving exact dates and source responses.
Values are limited to 1–240 (at most 20 years per block); the approved 216-month
plan contains 6,527 warmup-inclusive daily dates, below the USGS adapter's 10,000-row
page limit. Larger-than-monthly blocks are refused for UTC acquisition. Source
rate limits, explicit Retry-After deadlines and finite run/storage budgets still apply.


Current expansion validation (2026-10-20): the requested 2009-01-01–2026-10-15
source acquisition is execution-complete for all four additions. Puyallup, Elwha and
Queets each retain 6,497/6,497 observed discharge days; Skokomish retains 6,152/6,497
(345 explicit source gaps; its complete/required-discharge-eligible flags remain false).
All 48 original river files and the six original influence-factor contributions were
preserved. The ten-river influence product and both running Explorer endpoints passed
current-source readback. These results preserve provider-day, retrospective and
model-ineligibility qualifications; they do not establish physical plume validation.

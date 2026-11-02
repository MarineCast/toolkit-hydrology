# Lagged causal discharge companion

Implemented 2026-10-26. `Data/Hydrology/causal.parquet` is one current long table,
registered under `catalog.json → products.causal`. It does not alter existing river
features, retrospective indicators, influence values or source observations. Grain:
river × station × native provider date × metric × temporal basis; date and as_of_date
are Arrow dates. No river-to-cell join is supplied.

Run offline from the toolkit with its installed environment:

```sh
python -m hydrology.pipelines.causal /path/to/Data/Hydrology
```

Python `publish_causal(destination, **parameters)` accepts the same reference parameters
as `utils.causal.causal_features`: window=15, min_samples=60, min_years=3,
history_years=10 (maximum 30). These initial descriptive choices are adjustable,
not ecologically calibrated. No discharge is acquired. Only `status=valid` retained
discharge in m3/s is used, preserving the original eligibility decision (including
any admitted provisional/estimated source observations). Original flags, provenance
and source civil-day definitions remain in conditions/metadata and are bound by SHA256.
The publisher records exact implementation hash, dependency versions, parameters,
per-river support and source condition checksums in Parquet metadata.

## Timing and reference

For output date t, s=t−1 is the as-of provider date. All calculations use dates before
t, never t or later. A seasonal sample must be in one of the previous ten completed
calendar years before year(s), within circular ±15 days of s on a 365-day calendar.
February 29 pools with February 28 but remains a separate observation. December/January
windows wrap without admitting the current year. At least 60 observed samples from
three distinct reference years are required. There is no interpolation or zero filling.
A baseline can remain available when the latest discharge is missing; anomaly,
percentile and pulse cannot. Reference sample/year counts remain available in warmup.

Provider dates are civil-day labels, not UTC intervals. US registry station timezone
is recorded as PST; Canadian timezone is unspecified and retained daily boundaries
are unverified. This method does not invent DST handling, an IANA zone, or UTC edges.
The one-day lag establishes **event-date causality only**. Provider publication delays,
revisions and historical vintage availability remain unknown; model_eligible=false.
Operational backtests still need timestamp/vintage qualification and split-specific
validation. Pooling prior years assumes useful seasonal comparability despite trends,
regulation and nonstationarity; equal day weights are not independent samples.

## Metrics

| Metric | Definition | Unit |
|---|---|---|
| causal_discharge_seasonal_mean | Mean of qualified seasonal reference | m3/s |
| causal_discharge_seasonal_p90 | Linear-interpolated reference 90th quantile | m3/s |
| causal_discharge_seasonal_anomaly | q(s) minus reference mean | m3/s |
| causal_discharge_seasonal_percentile | 100 × (count below q(s) + half tied count) / n | percent |
| causal_discharge_pulse | 1 if q(s−1) < P90(s) ≤ q(s), otherwise 0 | 1 |
| causal_days_since_discharge_pulse | Elapsed days since a witnessed crossing | day |
| causal_reference_samples | Eligible seasonal sample count, including warmup | day |
| causal_reference_years | Distinct eligible reference years | year |

Both pulse endpoint values are compared to the **same** threshold for s, avoiding
false crossings solely from threshold movement. Missing s or s−1 and insufficient
reference reset event knowledge. Pulse age stays null until another witnessed
crossing; a missing observation never becomes a zero-event assertion. Explicit
status/reason fields distinguish missing as-of discharge, missing previous day,
insufficient reference, and unknown pulse history. Signed and zero discharge are
allowed. Existing fixed-training seasonal features and retrospective pulse names
retain their prior definitions and compatibility.

## Storage, validation and consumers

The canonical writer lock excludes coordinated readers during file/catalog promotion.
Readback and key/value checks precede promotion; caught failures restore the catalog
and old companion. A process crash between the two file replacements can leave a
catalog mismatch: validation fails closed; inspect the candidate and retained prior
catalog before recovery. This is not a whole-directory crash-atomic transaction.
One small prior catalog is retained outside Data in the destination-owned work area;
existing rollback files block a rerun pending explicit inspection, avoiding replay
accumulation. No permanent cleanup is performed by this command. Other canonical
publishers carry the companion forward and mark it requires_rebuild when condition
checksums change. Influence native-catalog binding is unaffected by this products-only
addition. Coordinated consumers must check source_status and use product_snapshot.

App wiring remains separate: read products.causal, verify SHA256 and source_status,
expose these eight native-river metrics and their status/reasons, display provider-day
and as-of labels, and show operational availability unknown. No H3 map conversion is
justified. Tests cover future/same-day perturbations, fixed ties and pulse crossings,
strict gaps/warmup, December/January and leap days, bounded history, units, key counts,
source-byte preservation and stale source detection.

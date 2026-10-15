# Validation and acceptance limits — 2026-10-15

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

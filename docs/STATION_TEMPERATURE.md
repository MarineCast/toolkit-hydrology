# Independent station temperature observations

Implemented 2026-10-26. `station_temperature.parquet` is an independent sparse native
station product, registered at `catalog.products.station_temperature`, format
`hydrology-station-temperature-1`. It does not replace river conditions or attach
measurements to discharge gauges, mouths or H3 cells. Existing USGS temperatures
remain in their original river products; this file does not duplicate them.

The key is station_id × date × statistic × temporal_basis. Typed columns are station_id,
river_id, date (date32), statistic, value (double), unit, status, temporal_basis,
quality_flags (JSON), source_url, source_sha256, retrieved_at, report_date (date32),
and source_title. Embedded JSON under `hydrology_station_temperature` contains format,
stations, provenance, missingness and model_eligible. Catalog stations maps identities
to real-site coordinates, river association, source and qualification. App consumers
must use those coordinates and expose sparse coverage; they must not draw interpolated
continuous daily history or replace the river's representative gauge.

## Qualified source

DFO-QUALARK is a local stable identity for Fraser River at Qualark. It is not a
provider-issued identifier. The published temperature-site coordinate is WGS84
49.5328138889, −121.4224083333, from Robinson et al. (2015), p.698,
[DOI](https://doi.org/10.1080/00028487.2015.1031282). That identifies the monitoring
site used in 2011, not a current surveyed sensor position or a verified relocation
history. Qualark is on the Fraser mainstem and distinct from WSC Hope. No catchment,
tributary, tidal or river-mouth equivalence is asserted.

[DFO Environmental Watch](https://www.pac.dfo-mpo.gc.ca/science/habitat/frw-rfo/index-eng.html)
provides observed daily mean water temperatures in explicitly dated “Current
temperatures” tables. The adapter selects only “Fraser River at Qualark” or its
literal “@ Qualark” spelling and the daily-mean column. It excludes Hope labels,
historical means, forecasts, graph estimates, modeled other rivers and unavailable
cells. Units are degrees Celsius. Dates are native provider days; timezone and
averaging boundaries are unverified and are not relabeled UTC. Report date is not
proof of original operational availability. Provider approval/provisional flags are
not supplied; their unknown status is preserved. `valid` means the source row passed
this parser, not provider approval or model readiness.

Reports are seasonal and sparse. Missing dates are absent observations, never zeros
or interpolated values. A 1950–2025 historical-reference label is not a claim that
this delivery contains those years. The historical extension below qualifies selected pre-2023 report formats; other
archives and any logger export still need separate qualification. In early July 2023, tables label Hope; those rows are
excluded even if a downstream consumer considers the two sites similar.

[DFO terms](https://www.dfo-mpo.gc.ca/terms-avis/terms-conditions-avis-eng.htm) permit
attributed non-commercial reproduction, with accuracy, title/author and source URL.
The product retains these. Commercial redistribution requires DFO permission. No
legal agreement was accepted and no public redistribution was performed.

## Acquisition, replay and publication

2026 HTML pages were fetched individually. Archived 2023–2025 English HTML members
were obtained through the official ZIP server's advertised byte-range support;
central-directory identity, member name, uncompressed size and CRC were checked.
Images and French duplicates were not acquired. Source hashes, retrieval timestamps,
archive/member references and acquisition evidence are retained outside delivery.
No authentication barrier was bypassed. The historical extension below subsequently qualifies selected PDF/image formats.

`scripts/import_dfo_temperature_reports.py LEDGER DESTINATION --completed-through DATE`
is an offline, checksum-verifying replay of retained source text. LEDGER is a JSON
list of path, url, sha256, retrieved_at, and optional archive_url/member records.
Unknown formats or missing Qualark observations are exclusions; ambiguous dates,
columns or units fail. The current importer is deliberately narrow; it does not
invent equivalence with another provider or automatically refresh approved data.

Publication uses the canonical exclusive lock, validates and reads back a staged
Parquet, preserves every existing station row exactly, inventories all other files,
and updates the file/catalog pair. On an exception it restores the old pair. An
interrupted transaction leaves an external journal and blocks cooperating readers
until inspected repair; this is not a power-loss durability guarantee. Uncoordinated
readers do not get a pairwise snapshot. Small rollback evidence is retained, without
permanent deletion; another publication requires inspection of that evidence first.
Normal river publication carries this independent companion forward unchanged.

Tests cover source identity, units, dates and exclusions, same-river different-site
keys, sparse/leap dates, duplicate rejection, preservation and interrupted readers.
No ecological inference, generic river-to-cell field or model-ready claim is added.

## Historical extension qualified 2026-10-26

The current delivery contains 217 distinct dates: the original 101 rows remain exact,
plus 113 report dates in 2012–2017 and one reviewed image-table sample each in
2009–2011. This remains sparse report coverage, not a full logger backfill.

`parse_dfo_pdf_text` reads Poppler layout text, checks the printed report and table
dates, selects the explicitly labelled Qualark daily mean and rejects other stations,
NA, historical means/medians, graphs and ambiguous formats. The table labels Qualark
even when a separate chart says Hope; no chart value is imported. Four 2012 source
rows are NA and stay absent. Six web-editor metadata files named PDF are excluded.

Ten source-hash-pinned exceptional records were visually reviewed and are recorded
in `data/dfo_reviewed_temperature_rows.json`: three French reports in files named
English, two image-only PDF tables, two printed-date/filename discrepancies, and the
three early GIF samples. Each records its printed dates and review qualification.
One duplicate August 17, 2016 observation agrees at 20.8°C; the correct-filename
report is the primary row and both complete source records survive in embedded
`historical_duplicate_sources`. Conflicting duplicates fail instead of selecting one.
Nine primary delivered rows use reviewed transcription; the tenth reviewed record
is that duplicate source. No OCR estimate or graph digitization was used.

`scripts/extend_dfo_temperature_history.py` replays the historical ledger against the
current file, verifies source hashes and preserves all prior rows. It requires the
existing `pdftotext` executable for PDFs. No package was installed. The app contract,
station identity, coordinates, native-day semantics and unit remain unchanged.

Sampled 2018, 2020 and 2022 reports explicitly label Hope, so their values are not
imported as Qualark. Unsampled reports cannot be inferred equivalent. The 2019
`.zip` link has 7-Zip magic bytes; no compatible reader is installed and its complete
5,479,239-byte archive would exceed this task's remaining original transfer budget.
Its station attribution remains unverified. Only one image-table sample per year
was acquired/reviewed for 2009–2011; broader image transcription remains pending.

### 2019 archive resolved — 2026-10-28

The existing macOS bsdtar/libarchive reader supports the official archive's 7-Zip
format; no installation was needed. A newly authorized bounded 5,479,239-byte read
(SHA256 `29433c3b3e25039340a97b3ec470ce96da9a8f82bee64ecaa69692b309480add`)
allowed inspection of all 28 English reports. Every current-temperature table
explicitly labels the Fraser observation **Hope**, not Qualark. No Qualark row was
found. The prior format/budget blocker is resolved; station attribution is now the
concrete scientific blocker. Do not assign these rows to Qualark or place a new Hope
temperature sensor at the discharge gauge without authoritative location evidence.
The 217-row delivery and its catalog remain unchanged and passed canonical validation.


## Ecology browser exports qualified 2026-10-28

The user-authorized normal Freshwater DataStream browser workflow successfully
exported original Water Temp. ZIPs for 10A040 and 07A089. No denied automated
endpoint was retried. Raw ZIPs (including fine-resolution and summary tables) remain
in the canonical external station source store; the delivered companion uses only
provider `WTM_DV.TXT` daily means. No locally computed means or interpolation.

| Separate station | Published coordinate | Observed daily means | Delivered dates |
| --- | --- | --- | --- |
| ECOLOGY-10A040, Puyallup R @ USGS Puyallup | 47.208287, -122.326841 | 842 | 2023-11-15–2026-03-22 |
| ECOLOGY-07A089, Snohomish R @ Snohomish PUD | 47.91248, -122.10647 | 1,077 | 2023-07-14–2026-10-27 |

Coordinates come from the exact provider station pages, which do not explicitly
state datum or sensor relocation history. They are not transplanted to mouths or
discharge nodes. Tables explicitly specify degrees Celsius and dates starting at
midnight PST; fixed PST is retained, not converted to UTC dates or daylight time.
The export date in `report_date` is a provenance date, not observation availability.

`utils/ecology_temperature.py` verifies station/name, daily statistic, units,
PST boundary, dates and exact quality-key meanings. Codes 2 and 3 mean good-quality
provisional data (3 edited); code 140 means not yet checked. The 27 code-140
Snohomish observations remain explicitly unchecked. `status=valid` means parser
acceptance, not provider approval. Codes 151 (missing), 215 (rejected), 255
(incomplete) are excluded even when accompanied by a numeric value. Original
values/codes and excluded dates remain in source ZIPs and embedded provenance.
Observed identical overlapping water-year rows collapse; conflicting observations
fail. An observed row can replace an incomplete placeholder in overlapping files.
Water-year labels do not become observation years. Future/current incomplete dates
are excluded by an explicit completed-through cutoff. No 2009–2022 observations
are invented for these two stations.

Replay: `scripts/import_ecology_temperature_exports.py LEDGER DESTINATION
--completed-through YYYY-MM-DD` validates without publishing. Add `--publish` only
after inspecting prior publication evidence. Ledger pins original file SHA256,
station code, retained path and actual download-completion time. The existing
transactional companion publisher preserves all prior rows/station metadata and
non-target product hashes. Product path, schema and catalog contract remain stable.
App consumers should show native-day text, provisional/unchecked quality and gaps.

18B070 DataStream exposes only stage/air temperature; neither was imported. Its
separate EIM water-quality archive does list water-temperature results. 16A070 is
an EIM water-quality station, not a valid DataStream telemetry entry. Both EIM
export queues require an email address; no queue submission or credentials change
has occurred. Their full historical result counts are availability evidence, not
a claim of daily coverage since 2009. These two station imports remain pending.


## Elwha EIM original export qualified 2026-10-28

Tyler manually downloaded export 5019205 after direct HTTP403 and an in-app browser
client block. The browser supplied an extracted folder, not a retained ZIP. All
five CSVs and the original disclaimer PDF were copied intact to the canonical
station source store; per-file SHA256 and original filenames are retained. ZIP CRC
cannot be claimed. CSV counts match the emailed 39,746 total: 1 location, 8 studies,
444 discrete results, 34,922 instantaneous results, 4,371 summaries. Every observation
is exact Location_ID18B070. Raw files are retained; no network route was retried.

`ECOLOGY-EIM-18B070` is Elwha River near Port Angeles, EIM location system174040,
at the Highway101 bridge. Exported coordinates are NAD83(HARN)/EPSG4152:
48.0654057072885,-123.577714914026, provider accuracy ±12m. The stored WGS84 map
coordinate is48.065411269954744,-123.57773005525759 using PROJ's
NAD83(HARN) to WGS84(3), stated transformation accuracy1m; the pipeline and native
coordinates remain metadata. This is not a new survey or proof of unchanged sensor
deployment. It is not the river mouth or a substituted discharge gauge.

Delivered **909 observations over303 complete seasonal days**,2009-06-19 through
2012-09-19:303each of `daily_mean`,`daily_min`,`daily_max`,degrees Celsius.
Native timezone is explicitly PST/GMT-8. Every delivered summary is Reviewed,
nonpartial, unqualified,100% expected data and48samples. It is independently
cross-checked against exactly48unique half-hour readings from00:00 through23:30
PST for the same instrument/day. Means agree to the source's four-decimal precision;
minimum/maximum values and recorded occurrence timestamps agree with raw readings.
For extremes, source start/end timestamps denote occurrence time, not the daily
averaging interval; original timestamps remain in quality_flags.

All contributing readings carry **Starting to pool**. This comment is retained in
every delivered row's quality_flags.source_comments and station quality metadata.
Reviewed does not establish reach representativeness or model suitability. The
303days span91days in2009,64in2010,90in2011,58in2012;886dates are absent between
first/last observation. Seasonal gaps are not filled, and the dam-removal transition
must not be treated as a stationary baseline without independent scientific review.

Of4,371summary rows,2,953are outside2009–2026scope,287are not daily,198lack
qualified timezone,24are incomplete/qualified;909pass. Discrete and instantaneous
records remain in originals rather than being mislabeled daily. Unknown old
summary derivations are not inferred. Review and record-created timestamps do not
establish historical operational availability. Retrieval metadata uses the time
user-delivered files were verified, not an asserted browser download time.

Replay: `scripts/import_eim_temperature_export.py FOLDER DESTINATION --source-url URL
--retrieved-at ISO_TIMESTAMP` validates only; `--publish` uses the existing locked
publisher after prior evidence inspection. Existing station refresh is refused.
App consumers retain the same schema/path, enumerate the new station, select the
statistic explicitly, expose PST, the pooling caveat, and seasonal gaps. Skokomish
remains queued; no resubmission. No app code was changed.


## Skokomish EIM delivery qualified 2026-10-29

User-delivered extracted export 01147 contains exactly 146,871 records: 1 location,
9 studies, 607 discrete, 136,449 instantaneous, and 9,805 summarized results.
Every observation identifies 16A070; location system ID is2333320. Original five
CSVs and disclaimer PDF are retained with individual hashes outside delivery
(73,538,105 bytes); no original ZIP/CRC is claimed. No blocked network retry or
export resubmission. The download-completion time is unknown; retrieved_at records
when the user-supplied files were verified.

New station **ECOLOGY-EIM-16A070**, Skokomish River near Potlatch at Highway101
bridge. Source NAD83(HARN) coordinate47.3100006125705,-123.17664399892, stated
accuracy ±30m. WGS84 map coordinate47.31000618128145,-123.17665889452056;
NAD83(HARN) to WGS84(3) pipeline and1m transformation accuracy retained. No
mouth/gauge substitution or assertion of sensor relocation history.

Delivered **2,256 observations over752days**,2009-06-19 through2017-09-13:
752each of daily_mean,daily_min,daily_max. All are reviewed, unqualified, complete
native PST/GMT-8 days corroborated by48unique half-hour readings from00:00–23:30.
Degrees Celsius; source extrema occurrence times and result IDs remain in flags.
Yearly complete-day counts:2009:91,2010:71,2011:76,2012:58,2013:79,2014:97,
2015:110,2016:105,2017:65. There are2,257absent days within the first/last interval;
no interpolation or year-round coverage claim. No pooling comment is transplanted
from Elwha. Provider review does not establish model readiness.

Summary exclusions:3,142outside scope,1,557not daily,219timezone unqualified,
2,631incomplete/qualified/unreviewed. The source also contains estimated and
unreviewed15-minute readings; these remain in retained originals and are not
reinterpreted as qualified daily observations. Discrete data are not daily averages.
The EIM adapter now accepts only the two explicitly qualified station/export IDs;
cross-station and estimated-underlying-record tests reject substitutions.

Existing path/schema/catalog contract remains unchanged; consumers enumerate the
new station and explicitly select daily_mean/min/max, display PST, and retain gaps.
Skokomish's source acquisition/import blocker is resolved. No app edits occurred.

## Manual source acquisition

See [manual input instructions](MANUAL_INPUTS.md) for official source links,
export selections, retained-file layouts, ingest/validation commands and the
explicit limits of fresh EIM export qualification. User-supplied originals are
a supported workflow; historical operational availability is a separate question.

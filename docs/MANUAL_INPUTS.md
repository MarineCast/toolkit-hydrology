# Manual hydrology inputs

Manual user downloads are a supported source-acquisition workflow. The toolkit
then validates and normalizes the supplied files offline. Manual acquisition is
not a reproducibility failure: retained inputs reproduced all 5,301 station rows.
A new export can contain provider revisions and is not evidence of the old vintage.
These instructions do not initiate downloads or publication. Checked 2026-10-29.

## Keep originals and record provenance

Use the existing source store outside delivery:
`MarineCast/.marinecast-work/hydrology/4625475e62f6a93b/station-temperature-sources/`.
Keep each new acquisition in a distinct dated subfolder; preserve original ZIPs,
member names, CSVs, disclaimer files and all quality fields. Do not put raw exports
in `Data/Hydrology`, edit files in a spreadsheet, replace old exports, or commit them.
The current store identifier is specific to this destination; it is not a universal
configuration constant. Importers take explicit paths, not an automatic watch folder.

Record actual source URL, station ID, requested selections, original filenames,
SHA256 (`shasum -a 256 FILE`), retrieval timestamp with offset and its meaning. If
browser completion time is unknown, record file-verification time and that limitation.
For extracted EIM folders, hash each file and retain the disclaimer. Do not claim
ZIP identity/CRC when only extracted files were supplied. Rebase ledger paths
explicitly if moving originals; retain their hashes. Do not reuse a historical
retrieval timestamp for a new download.

## Ecology Freshwater DataStream: Puyallup and Snohomish

Official station pages:
[Puyallup 10A040](https://apps.ecology.wa.gov/continuousflowandwq/StationDetails?sta=10A040)
and [Snohomish 07A089](https://apps.ecology.wa.gov/continuousflowandwq/StationDetails?sta=07A089).
The Puyallup page's export form was inspected for the selections below; the retained
2026-10-28 exports establish the successful workflow for both stations.

1. Open the exact station page and verify station code/name.
2. Open **Export Station Data**. Select **All Available Years** and the parameter
   **Water Temp.**; do not substitute air temperature or stage.
3. Choose **Export to File** and wait for completion. Save the original ZIP from
   the browser downloads area. The page warns that not every parameter exists in
   every year. Do not reconstruct data from plotted graphs.
4. Retain the full ZIP. Import consumes only exact `CODE_WTM_DV.TXT` or
   `CODE_YYYY_WTM_DV.TXT` members. Other fine-resolution/statistic files stay original.
5. Create a JSON list ledger, one record per export:

```json
[
  {
    "station_code": "10A040",
    "path": "/absolute/source-store/date/ORIGINAL.zip",
    "sha256": "ACTUAL_SHA256",
    "retrieved_at": "ACTUAL_ISO_TIMESTAMP_WITH_OFFSET"
  }
]
```

The daily-mean header must specify °C and dates beginning midnight PST. Keep fixed
UTC−08:00, including summer; do not relabel UTC or daylight time. Codes 2/3 remain
provisional, 140 unchecked; 151/215/255 are excluded even if numeric. Gaps stay absent.
Choose `--completed-through` strictly before the retrieval date. The current replay
uses 2026-10-27 with the original 2026-10-28 ZIPs, yielding 842 Puyallup and 1,077
Snohomish rows. New exports need not have those counts. Bounds are currently 16 MiB
compressed/32 MiB uncompressed; larger files require review, not silent truncation.

For a destination that has a station companion but does **not** yet contain these
stations, the expansion CLI validates without publication by default:

```sh
.venv/bin/python scripts/import_ecology_temperature_exports.py LEDGER.json DESTINATION \
  --completed-through YYYY-MM-DD
```

Adding `--publish` invokes the existing locked preservation-checking publisher.
The current delivery already contains both stations: this expansion command correctly
refuses to refresh them. Use the read-only replay below for existing products.

## Ecology EIM: Elwha and Skokomish

Start at the official [EIM information/search entry](https://ecology.wa.gov/research-data/data-resources/environmental-information-management-database)
and follow EIM Search's river/stream water-quality route. This is a download workflow,
not EIM Loader/submission. Exact station selections are:

| Location ID | Location system ID | Site |
| --- | --- | --- |
| 18B070 | 174040 | Elwha River near Port Angeles, Highway 101 bridge |
| 16A070 | 2333320 | Skokomish River near Potlatch, Highway 101 bridge |

Search/select one exact location per export and verify the system ID. Request the
complete location-associated river/stream export, retaining discrete, instantaneous
and summarized results, study details and location details. Do not request only daily
summaries: their qualification needs the underlying half-hour data. Preserve all
available years and original flags; the adapter performs date/statistic/quality
selection after acquisition. Do not apply a 2009 start filter if attempting to replay
the original export's pinned total record count.

Use the normal download queue and your own email when prompted; retrieve the resulting
file using the provider's emailed link. The prior exports were manually supplied after
automated access failed. A blocked endpoint is not a reason to retry alternate automated
routes. Exact current queue/button wording and the original parameter-filter selection
were **not independently verified in this review**; inspect the resulting fields/files
rather than inventing a click sequence. The search landing page redirected to a download
login during read-only inspection. No queue was submitted.

Expected files (original date/count suffixes vary):

```text
RiverStreamLocationDetails_*.csv
RiverStreamStudyDetails_*.csv
RiverStreamResults_*.csv
RiverStreamTimeSeriesResults_*.csv
RiverStreamSummarizedTimeSeriesResults_*.csv
EIMDataDisclaimerAndReliabilityStatement.pdf
```

Exactly one of each CSV type is required in the folder. The qualified retained exports
are Elwha `5019205` (39,746 total CSV records) and Skokomish `01147` (146,871).
**The current adapter pins these export URL identities and counts. A fresh export needs
reviewed adapter/manifest qualification; it is not a generic arbitrary-export importer.**
Do not rename a new download to an old ID or alter counts to pass validation.

The adapter checks exact station identity, water/°C, reviewed and unqualified complete
daily min/mean/max summaries, 100% expected data and 48 half-hour observations in fixed
PST/GMT−8. Means, extrema and occurrence timestamps must agree with underlying data.
Preserve Elwha's “Starting to pool” comment and original NAD83(HARN) coordinates;
conversion to WGS84 is explicit. EIM extreme timestamps denote occurrence, not daily
interval edges. Current qualification is bounded to 2009-01-01–2026-10-27.

For a qualified export and a companion destination that does not already contain
that station, this CLI validates only; `--publish` additionally publishes:

```sh
.venv/bin/python scripts/import_eim_temperature_export.py ORIGINAL_FOLDER DESTINATION \
  --source-url ORIGINAL_EXPORT_URL --retrieved-at ACTUAL_ISO_TIMESTAMP
```

Both stations are already delivered, so expansion correctly refuses repetition.
Expected retained outputs are 909 Elwha observations (303 per statistic) and 2,256
Skokomish observations (752 per statistic). Sparse seasonal days remain sparse.

## DFO Qualark reports and reviewed transcription

Use [DFO Fraser River Environmental Watch](https://www.pac.dfo-mpo.gc.ca/science/habitat/frw-rfo/index-eng.html)
and its **Archived Fraser River environmental watch reports** link. Save original
report HTML or official archive members (PDF/GIF included), retaining archive URL,
member name and checksum. Select only explicitly labelled **Fraser River at Qualark**
(or literal `@ Qualark`) **daily mean observed water temperature**, °C, and its printed
observation date. Keep report date separate. Do not import Hope-labelled tables,
forecasts, historical reference values or graph estimates as Qualark observations.
The time-zone/averaging boundaries are unverified provider days, not UTC.

HTML import ledger records require `path`, `url`, `sha256`, `retrieved_at`; archived
members also retain `archive_url` and `member`. Historical PDF/image ledger records
require `path`, `sha256`, `retrieved_at`, `archive_url`, `member`, and an optional
hash-pinned supporting report. PDF extraction requires Poppler `pdftotext -layout`.
Original acquisition can be manual; ordinary supported HTML/PDF table parsing is
programmatic. Manual transcription is needed only for qualified exceptional formats:
image-only tables, language/date mismatches and the reviewed early GIF samples.

The existing ten reviewed source records in
`src/hydrology/data/dfo_reviewed_temperature_rows.json` bind exact SHA256/member to
printed observation/report dates, value, unit, statistic, source title and review note/date.
Nine are primary delivered rows; one is corroborating duplicate evidence. For a new
exception, visually inspect the actual table and explicitly record those fields through
a reviewed code/data change. Do not estimate from a graph or let an unreviewed OCR value
become an observation. Existing pinned rows replay without new manual transcription.

The DFO CLI scripts **publish by default**, unlike the Ecology validation commands:

```sh
# Initial absent-station publication, only to a prepared canonical destination:
.venv/bin/python scripts/import_dfo_temperature_reports.py LEDGER.json DESTINATION --completed-through YYYY-MM-DD
# Qualified historical extension preserving prior rows:
.venv/bin/python scripts/extend_dfo_temperature_history.py HISTORY_LEDGER.json DESTINATION --completed-through YYYY-MM-DD
```

Do not rerun those publishers against the current complete companion for an audit.
The existing importer is incremental; a general fresh-destination bootstrap/refresh
workflow is not supplied by these commands. Recorded source terms and attribution
requirements are in [station qualification](STATION_TEMPERATURE.md); downloading
an original is not permission to redistribute it commercially.

## Validate existing inputs and preserve warmup

Install the toolkit as in README. For the current retained source tree, use the
read-only command from [the reproduction review](REPRODUCIBILITY_REVIEW.md):

```sh
.venv/bin/python scripts/review_replay.py \
  --product ../../Data/Hydrology \
  --sources ../../.marinecast-work/hydrology/4625475e62f6a93b/station-temperature-sources \
  --output /tmp/hydrology-manual-input-review
```

It checks hashes, replays all temperature sources, verifies station keys/statistics,
values, flags, dates and provenance against delivery, and preserves original checksums.
For new input qualification before any expansion, call `read_export` or `read_eim`
from the installed package with explicit original paths/timestamps; these parsers do
not publish. Passing parser checks does not authorize replacing an existing station.
Unknown flags, changed schema/export identity or conflicting duplicate values require
review. Use the existing offline test suite after adapter changes.

Retain native discharge `conditions.parquet` **and** `warmup.parquet` with manifests.
The four later-added rivers require 30 prior days each to reproduce initial rolling
features; never delete these as redundant manual-input clutter. Manual temperature
observations do not replace discharge-gauge observations or fill their nulls.
Reproducible user-supplied input is established; original operational availability
and whether a new provider export reproduces an old historical vintage remain distinct
unknowns. Neither prevents the supported offline replay from retained originals.

# Source inventory and verification

Official documentation and bounded API responses consulted **2026-10-15**:

- [USGS API](https://api.waterdata.usgs.gov/docs/ogcapi/),
  [API keys](https://api.waterdata.usgs.gov/docs/ogcapi/keys/),
  [integration guide](https://api.waterdata.usgs.gov/docs/agents/).
  OGC **v1** collections: `monitoring-locations`, `time-series-metadata`, `daily`,
  `continuous`. Location lookup uses `id`; series/data use `monitoring_location_id`.
  Date filter is `time`, not ECCC's `datetime`. Follow `rel=next` cursor links.
  Anonymous pilot succeeded. Optional `USGS_API_KEY` is sent only in the header to
  the official host. Large backfills should use a key and conservative request pacing.
  00060 discharge, 00010 water temperature; statistics 00003 mean, 00001 maximum.
  Native ft³/s is multiplied by 0.028316846592; degC remains degC.
  Discovery preserves primary series, computation periods, units, begin/end, station
  coordinates, drainage area and revision notes. USGS drainage area is in square miles.
- [ECCC hydrometric inventory](https://eccc-msc.github.io/open-data/msc-data/obs_hydrometric/readme_hydrometric_en/),
  [OGC technical documentation](https://eccc-msc.github.io/open-data/msc-geomet/ogc_api_en/),
  [daily collection](https://api.weather.gc.ca/collections/hydrometric-daily-mean),
  [real-time collection](https://api.weather.gc.ca/collections/hydrometric-realtime).
  Historical HYDAT daily discharge is available through the official GeoMet OGC
  collection. `STATION_NUMBER` and `datetime` bound retrieval; follow `rel=next`.
  `DISCHARGE` is m³/s; `LEVEL` is never interpreted as discharge. Station gross
  drainage area is km². Historical station responses do not provide a full period of
  record; requested-window coverage is measured, not extrapolated to 2009–present.
  Real-time data have a 30-day retention window and are treated as provisional.
  Recent UTC retrieval requires `allow_provisional=true`; no automatic daily fallback.
- [HYDAT download](https://www.canada.ca/en/environment-climate-change/services/water-overview/quantity/monitoring/survey/data-products-services/national-archive-hydat.html).
  Optional local SQLite snapshot is opened read-only and hashed once per adapter.
  `STATIONS` and `DLY_FLOWS` (`FLOW1`…`FLOW31`, `FLOW_SYMBOL1`…`FLOW_SYMBOL31`)
  are subset locally. The official whole snapshot was not downloaded during this pilot;
  the SQLite reader was exercised with a labeled synthetic schema fixture. GeoMet
  historical discharge was exercised with real Canadian observations.
- [USGS stream-mouth gazetteer layer](https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer/6):
  queried names and WGS84 geometry for U.S. rivers, including North and South Fork
  Skagit. Registry uses the first coastal reference point of each multipoint feature;
  it is a gazetteer reference, not a surveyed marine boundary. GNIS IDs are retained.
  Skagit mainstem's endpoint is its fork junction, so the two fork references are used.
- [Fraser reference](https://apps.gov.bc.ca/pub/bcgnws/names/48556.html) and
  [Cowichan reference](https://apps.gov.bc.ca/pub/bcgnws/names/4085.html): official BC
  WGS84 approximate mouth coordinates. These are incomplete delta outlet inventories.
  No distributary flow fractions are assumed. Mouth snapping requires an entirely
  water-supported path and remains unvalidated on production geometry.

Station metadata and response hashes are saved with every release; the packaged
registry contains the ten verified station names, coordinates, drainage areas and
metadata URLs. Release builds retain raw responses in their ignored content cache;
canonical per-river publication preserves normalized observations, discovered metadata
and response hashes, then removes only its owned HTTP downloads after validated,
execution-complete publication. Failed/deferred downloads remain resumable.
Official metadata support the station identity, not a claim that gauge discharge
represents the full coastal freshwater flux. Selection rationale is explicit.
Catchment polygons and dated regulation histories were not available in this workspace;
these fields remain null. The Columbia rationale warns about upstream regulation,
but no unsupported dated regulation series is encoded.

Temperature was successfully retrieved from USGS at Skagit, Nooksack and Columbia.
No Ecology, BC temperature, or DART provider is claimed as implemented. Their records
need a separate station/temporal-support review for the Canadian and Snohomish gaps.
No modeled discharge fallback is used. Follow the linked providers' data-use terms
before redistributing raw records; this repository stores code and metadata only.


### Wateroffice daily CSV qualification — 2026-10-16

The first collection additionally qualified official
[Wateroffice CSV services](https://wateroffice.ec.gc.ca/services/index_e.html):
historical `daily_data/csv/inline` with `parameters[]=flow`, and real-time daily means
with parameter 6. These were narrow Fraser/Cowichan station/range requests, not a
nationwide HYDAT download. The run-scoped adapter is retained with the collection
evidence; the package's default WSC adapter still uses GeoMet. Its parser/schema,
parameter/station/date/finite checks and nonnull source precedence were tested before
use. Exact CSV bytes are SHA256-cached alongside request metadata.

Precedence was nonnull retained GeoMet, then nonnull historical Wateroffice, then
provisional Wateroffice daily means. Every original nonnull value was preserved and
all returned source series/flags retained. Provider daily timestamp labels (including
08:00Z real-time labels), approval/qualifier/symbol/grade fields and unknown averaging
bounds remain explicit. They are provider daily means, never UTC reconstructions.
The service documents 60 months for daily means and 18 for unit values; that does
not establish station-specific coverage. Current products' actual gaps are authoritative.


### Four additional US river gauges — 2026-10-20

| River | USGS station | Native daily discharge metadata begins | Gauge support |
| --- | --- | --- | --- |
| Puyallup | 12101500 | 1914-05-01 | 948 mi²; river mile 6.6, above estuary |
| Elwha | 12045500 | 1897-10-01 | 269 mi²; river mile 8.6, above Little River; dam-removal history matters |
| Skokomish | 12061500 | 1943-07-01 | 227 mi² nominal; river mile 5.3, below fork confluence; Cushman diversion/regulation affects area interpretation |
| Queets | 12040500 | 1930-10-01 | 445 mi²; river mile 4.6, below Clearwater River |

Official monitoring-location and time-series metadata, and the USGS National Map
GNIS stream gazetteer, were inspected on the review date. Native daily parameter
00060/statistic 00003 metadata continued through 2026-10-18. Station-specific URLs,
coordinates, source response hashes and selection rationale are in the packaged
registry; acquisition retains discovered metadata and observation provenance.
The four gauges have no qualified native daily 00010 mean/max series. They are
explicitly unsupported for those variables until reviewed source curation changes.
An unrelated nearby gauge or diversion canal is not a temperature substitute.

Gazetteer first-coastal multipoint references are approximate mouth positions, not
surveyed estuarine boundaries. Duplicate gazetteer rows were identical and did not
create multiple outlets. Native registry mouths remain distinct from modeled research
outlet coordinates. Exact named basin bindings and R8 attachment qualifications
are read from the checksum-pinned Seascape selected-outlet inventory; no sibling
files, nearest-coordinate substitutions, flow allocation or route generation are used.
Queets retains its recorded 75.9 m source-registration gap, R8 connection and
unavailable R6 attachment. Physical mouth flux, transport and whale effects remain
unqualified. The dated validation record reports actual acquired coverage separately
from these period-of-record metadata.


Measured requested-window coverage on 2026-10-20 (2009-01-01–2026-10-15): USGS
12101500, 12045500 and 12040500 each supplied 6,497 observed native daily discharge
values; 12061500 supplied 6,152 with 345 explicit source gaps. All four requests
finished; execution completion is distinct from gap-free coverage. Unsupported
temperature remains null/unavailable. Official source responses and qualifiers were
preserved in normalized observations; no gauge was substituted or summed.

### DFO Qualark report observations — 2026-10-26

The independent [station-temperature adapter](STATION_TEMPERATURE.md) qualifies
explicitly labelled Qualark daily-mean report tables, with native dates and unknown
provider approval/timezone boundaries. This does not qualify Ecology access, older
DFO archive formats, a continuous logger history or Hope-to-Qualark substitution.

The subsequent 2026-10-26 historical review qualified 2012–2017 PDF tables and three
2009–2011 image samples at Qualark. Source-hash-pinned reviewed exceptions, duplicate
provenance, explicit Hope exclusions and remaining archive limits are documented in
[the historical extension](STATION_TEMPERATURE.md#historical-extension-qualified-2026-10-26).


Ecology original browser exports were qualified on 2026-10-28 for exact stations
[10A040](https://apps.ecology.wa.gov/continuousflowandwq/StationDetails?sta=10A040)
and [07A089](https://apps.ecology.wa.gov/continuousflowandwq/StationDetails?sta=07A089).
See [station temperature](STATION_TEMPERATURE.md#ecology-browser-exports-qualified-2026-10-28)
for native PST daily means, quality exclusions, original ZIP provenance and pending
EIM stations. This successful authorized UI route supersedes the old blanket
export-access blocker; it does not authorize bypassing automated endpoint denials.


Elwha EIM export5019205 was user-delivered on2026-10-28 as original extracted files.
Its39,746CSVrecords and exact18B070identity were verified. Complete reviewed native
PST daily summaries are cross-checked against retained half-hour observations;
[Elwha qualification](STATION_TEMPERATURE.md#elwha-eim-original-export-qualified-2026-10-28)
details the retained pooling caveat, coordinates/datum conversion and exclusions.


Skokomish EIM export01147 was user-delivered and qualified2026-10-29. Exact16A070
identity and146,871source records verified;2,256complete reviewed native PST daily
summaries imported. See [Skokomish qualification](STATION_TEMPERATURE.md#skokomish-eim-delivery-qualified-2026-10-29).

## Manual source acquisition

See [manual input instructions](MANUAL_INPUTS.md) for official source links,
export selections, retained-file layouts, ingest/validation commands and the
explicit limits of fresh EIM export qualification. User-supplied originals are
a supported workflow; historical operational availability is a separate question.

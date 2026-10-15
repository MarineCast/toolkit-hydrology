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
registry contains the six verified station names, coordinates, drainage areas and
metadata URLs. Raw source responses are retained in the ignored content cache.
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

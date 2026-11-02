"""Offline source-qualified Elwha EIM expansion; existing station refresh is refused."""
import argparse,json
from pathlib import Path
import pyarrow.parquet as pq
from hydrology.utils.eim_temperature import read_eim
from hydrology.utils.station_temperature import NAME,make_table,validate_table
from hydrology.pipelines.station_temperature import assert_preserved,publish_station_temperature

def build(folder,destination,source_url,retrieved_at):
    old=pq.read_table(Path(destination)/NAME);meta=validate_table(old)
    added,s,e=read_eim(folder,source_url,retrieved_at)
    if s['station_id'] in meta['stations']:raise ValueError('Station already present; do not repeat expansion')
    table=make_table(old.to_pylist()+added,{**meta['stations'],s['station_id']:s},{**meta['provenance'],s['river_id']+'_eim_export':e})
    assert_preserved(old,table);return table

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('folder');ap.add_argument('destination');ap.add_argument('--source-url',required=True);ap.add_argument('--retrieved-at',required=True);ap.add_argument('--publish',action='store_true');a=ap.parse_args()
    t=build(a.folder,a.destination,a.source_url,a.retrieved_at)
    print(json.dumps(publish_station_temperature(a.destination,t) if a.publish else dict(rows=len(t),published=False),indent=2))

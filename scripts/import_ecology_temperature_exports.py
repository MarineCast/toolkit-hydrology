"""Replay original browser exports; no network. A ledger pins station/path/hash/time."""
import argparse,json
from datetime import date
from pathlib import Path
import pyarrow.parquet as pq
from hydrology.utils.products import checksum
from hydrology.utils.ecology_temperature import read_export
from hydrology.utils.station_temperature import NAME,make_table,validate_table
from hydrology.pipelines.station_temperature import assert_preserved,publish_station_temperature

def build(ledger,destination,completed_through):
    old=pq.read_table(Path(destination)/NAME);meta=validate_table(old)
    rows=old.to_pylist();stations=dict(meta['stations']);provenance=dict(meta['provenance'])
    records=[]
    for item in ledger:
        if checksum(Path(item['path']))!=item['sha256']:raise ValueError('Export checksum mismatch')
        added,s,e=read_export(item['path'],item['station_code'],item['retrieved_at'],completed_through=completed_through)
        if s['station_id'] in stations:raise ValueError('Existing station requires separately reviewed refresh')
        rows.extend(added);stations[s['station_id']]=s;records.append(e)
    provenance['ecology_original_exports']=records
    table=make_table(rows,stations,provenance);assert_preserved(old,table)
    return table

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('ledger');ap.add_argument('destination');ap.add_argument('--completed-through',required=True,type=date.fromisoformat);ap.add_argument('--publish',action='store_true')
    args=ap.parse_args();table=build(json.loads(Path(args.ledger).read_text()),args.destination,args.completed_through)
    if args.publish:print(json.dumps(publish_station_temperature(args.destination,table),indent=2))
    else:print(json.dumps(dict(rows=len(table),stations=list(validate_table(table)['stations']),published=False)))

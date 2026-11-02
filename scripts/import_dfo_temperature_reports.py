"""Offline import of retained, verified official DFO report-text responses.

Input is a JSON list of records with path, url (original report identity), sha256,
retrieved_at, and optional archive_url/member. No network or gap filling occurs.
"""
import argparse
from datetime import date
import json
from pathlib import Path

from hydrology.utils.products import checksum
from hydrology.utils.station_temperature import QUALARK, make_table, parse_dfo_report
from hydrology.pipelines.station_temperature import publish_station_temperature


def import_reports(records, completed_through):
    rows=[]; exclusions=[]
    for source in records:
        path=Path(source['path'])
        if checksum(path)!=source['sha256']: raise ValueError('Source checksum mismatch')
        row=parse_dfo_report(path.read_text(encoding='utf-8-sig'),source['url'],
            source['sha256'],source['retrieved_at'],completed_through=completed_through)
        if row is None:
            exclusions.append(source['url'])
            continue
        if 'archive_url' in source:
            row['source_url']=source['archive_url']+'#'+source['member']
        rows.append(row)
    return make_table(rows,{'DFO-QUALARK':QUALARK},dict(
        author='Fisheries and Oceans Canada',copy_notice='Normalized copies of the linked official reports; not an official DFO product',
        sources=[{k:v for k,v in s.items() if k!='path'} for s in records],
        excluded_reports=exclusions,requested_start='2009-01-01',requested_end=str(completed_through),
        history_limit='Qualified HTML reports only; pre-2023 PDFs/older archives and full logger history pending; Hope-labelled rows excluded',
        no_interpolation=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger');parser.add_argument('destination')
    parser.add_argument('--completed-through',required=True,type=date.fromisoformat)
    args=parser.parse_args()
    records=json.loads(Path(args.ledger).read_text())
    table=import_reports(records,args.completed_through)
    print(json.dumps(publish_station_temperature(args.destination,table),indent=2))

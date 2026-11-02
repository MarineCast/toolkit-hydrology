"""Checksum-verified offline PDF/image expansion; preserves every delivered row."""
import argparse
from datetime import date
import json
from pathlib import Path
import subprocess
import pyarrow.parquet as pq
import hydrology
from hydrology.utils.station_temperature import KEY, make_table, parse_dfo_pdf_text
from hydrology.utils.products import checksum
from hydrology.pipelines.station_temperature import publish_station_temperature, assert_preserved


def historical_rows(records,completed_through):
    reviewed=json.loads((Path(hydrology.__file__).parent/'data'/'dfo_reviewed_temperature_rows.json').read_text())
    lookup={r['source_sha256']:r for r in reviewed};rows=[];exclusions=[]
    for source in records:
        path=Path(source['path']);sha=checksum(path)
        if sha!=source['sha256']:raise ValueError('Historical source checksum mismatch')
        support=source.get('supporting_report')
        if support and checksum(Path(support['path']))!=support['sha256']:
            raise ValueError('Supporting report checksum mismatch')
        url=source['archive_url']+'#'+source['member']
        if '/_vti_cnf/' in source['member']:
            exclusions.append(dict(source=url,reason='web-editor metadata, not a report'));continue
        if sha in lookup:
            reviewed_row=lookup[sha]
            if source['member']!=reviewed_row['member']:raise ValueError('Reviewed member identity mismatch')
            row={k:reviewed_row[k] for k in ('station_id','river_id','statistic','value','unit','source_title')}
            row.update(date=date.fromisoformat(reviewed_row['date']),report_date=date.fromisoformat(reviewed_row['report_date']),
                status='valid',temporal_basis='provider_daily',source_url=url,source_sha256=sha,retrieved_at=source['retrieved_at'],
                quality_flags=json.dumps(dict(approval='not_supplied',provisional='unknown',source='published_report',
                    extraction='visually_verified_transcription',review_note=reviewed_row['review_note'],review_date=reviewed_row['review_date'])))
            if row['date']>completed_through:raise ValueError('Incomplete reviewed date')
        else:
            if not path.read_bytes().startswith(b'%PDF-'):raise ValueError('Unqualified source format')
            text=subprocess.check_output(['pdftotext','-layout',str(path),'-'],timeout=30).decode()
            row=parse_dfo_pdf_text(text,url,sha,source['retrieved_at'],completed_through=completed_through)
        if row is None:exclusions.append(dict(source=url,reason='Qualark value NA or station not explicitly Qualark'))
        else:rows.append(row)
    return rows,exclusions


def coalesce_new_rows(rows):
    groups={}; duplicates=[]
    for row in rows:
        key=(row['station_id'],row['date'],row['statistic'],row['temporal_basis'])
        groups.setdefault(key,[]).append(row)
    result=[]
    for group in groups.values():
        first=group[0]
        for row in group[1:]:
            fields=('river_id','value','unit','status')
            flags=lambda r: {k:json.loads(r['quality_flags']).get(k) for k in ('approval','provisional','source')}
            if any(row[k]!=first[k] for k in fields) or flags(row)!=flags(first):
                raise ValueError('Conflicting historical duplicate observations')
        if len(group)>1: duplicates.append(group)
        # Prefer a report whose member filename agrees with its printed date.
        result.append(sorted(group,key=lambda r:(not r['source_url'].endswith(str(r['report_date'])+'-eng.pdf'),r['source_url']))[0])
    return result,duplicates


def extend_table(prior,records,completed_through):
    rows,exclusions=historical_rows(records,completed_through)
    rows,duplicates=coalesce_new_rows(rows)
    metadata=json.loads(prior.schema.metadata[KEY]);provenance=metadata['provenance'].copy()
    provenance.update(history_limit='2009–2011: one reviewed sample each; 2012–2017: qualified report tables; 2018/2020/2022 samples Hope-labelled and excluded; 2019 unresolved archive structure; not continuous logger history',
        historical_duplicate_sources=json.loads(json.dumps(duplicates,default=str)),historical_sources=[{k:v for k,v in s.items() if k!='path'} for s in records],historical_exclusions=exclusions,
        historical_review='Exact-source-hash manual exceptions in packaged dfo_reviewed_temperature_rows.json; PDF layout parser otherwise')
    result=make_table(prior.to_pylist()+rows,metadata['stations'],provenance)
    assert_preserved(prior,result)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('ledger');p.add_argument('destination');p.add_argument('--completed-through',required=True,type=date.fromisoformat)
    args=p.parse_args();old=pq.read_table(Path(args.destination)/'station_temperature.parquet')
    table=extend_table(old,json.loads(Path(args.ledger).read_text()),args.completed_through)
    print(json.dumps(publish_station_temperature(args.destination,table),indent=2))

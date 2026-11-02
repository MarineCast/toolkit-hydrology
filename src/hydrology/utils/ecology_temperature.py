"""Offline adapter for original Ecology Freshwater DataStream water-temperature ZIPs."""
from collections import Counter
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import zipfile

BASE='https://apps.ecology.wa.gov/continuousflowandwq/StationDetails?sta='
CODES={2:'Good quality provisional data',3:'Good quality provisional data - edited',
       140:'Data not yet checked',151:'Data Missing',215:'Data rejected',255:'Incomplete day'}
SITES={'10A040':('puyallup','Puyallup R @ USGS Puyallup',47.208287,-122.326841),
       '07A089':('snohomish','Snohomish R @ Snohomish PUD',47.91248,-122.10647)}

def station(code):
    river,name,lat,lon=SITES[code]
    return dict(station_id='ECOLOGY-'+code,provider='Washington State Department of Ecology',
        provider_station_id=code,provider_station_name=name,river_id=river,
        latitude=lat,longitude=lon,coordinate_source=BASE+code,
        coordinate_crs='not explicitly stated by station page',
        coordinate_precision='Published station coordinate; sensor relocation history unverified',
        day_definition='Provider mean daily table: listed date starting at midnight PST',
        timezone='PST (fixed UTC-08:00 as explicitly stated by provider table)',
        cadence='provider daily means from continuous monitoring; gaps preserved',
        unit='degC',statistics=['daily_mean'],model_eligible=False,
        relationship='Separate Ecology station at published coordinates; no discharge-gauge or river-mouth equivalence asserted',
        rights_url='https://ecology.wa.gov/About-us/Accountability-transparency/Our-website/Copyright-information',
        quality='Provisional and unchecked flags preserved; valid indicates parser acceptance, not provider approval',
        availability='Historical operational availability and revision times unknown')

def parse_daily(text,code):
    """Fail closed on identity, unit, day definition, date or unfamiliar quality semantics."""
    if code not in SITES: raise ValueError('Unqualified station')
    required=[code+'--'+SITES[code][1], 'DATE         Water Temp. (°C)   QUALITY',
              'For mean daily tables, data values are for the dates listed starting at\nmidnight PST.']
    text=text.replace('\r\n','\n')
    if not all(x in text for x in required): raise ValueError('Station/unit/statistic/timezone header mismatch')
    if text.count('Quality Codes Key:')!=1: raise ValueError('Missing quality key')
    body,key=text.split('Quality Codes Key:')
    meanings={int(k):v.strip() for k,v in re.findall(r'^(\d+) - (.+)$',key,re.M)}
    if not meanings or any(CODES.get(k)!=v for k,v in meanings.items()): raise ValueError('Unknown quality definition')
    rows=[];seen=set()
    for line in body.splitlines():
        if not re.match(r'^\d{2}/',line):continue
        m=re.fullmatch(r'(\d{2}/\d{2}/\d{4})\s+(?:(-?\d+(?:\.\d+)?)\s+)?(\d+)',line.strip())
        if not m:raise ValueError('Malformed daily row')
        day=datetime.strptime(m[1],'%m/%d/%Y').date(); value=float(m[2]) if m[2] is not None else None; q=int(m[3])
        if day in seen:raise ValueError('Duplicate date within member')
        seen.add(day)
        if q not in meanings:raise ValueError('Undefined quality code')
        if q in (2,3,140) and (value is None or not -5<=value<=45):raise ValueError('Invalid observed temperature')
        rows.append((day,value,q))
    if not rows:raise ValueError('Empty daily table')
    return rows

def read_export(path,code,retrieved_at,*,completed_through):
    path=Path(path)
    if path.stat().st_size>16*1024*1024:raise ValueError('Archive budget exceeded')
    archive_sha=hashlib.sha256(path.read_bytes()).hexdigest()
    export_day=datetime.fromisoformat(retrieved_at.replace('Z','+00:00')).date()
    if completed_through>=export_day:raise ValueError('Only completed prior dates permitted')
    selected={};sources={};excluded={};members=[];duplicates=0
    with zipfile.ZipFile(path) as z:
        if len(z.namelist())!=len(set(z.namelist())):raise ValueError('Duplicate archive members')
        if sum(i.file_size for i in z.infolist())>32*1024*1024:raise ValueError('Uncompressed budget exceeded')
        names=sorted(n for n in z.namelist() if re.fullmatch(re.escape(code)+r'(?:_20\d\d)?_WTM_DV.TXT',n))
        if not names:raise ValueError('No exact station daily water-temperature members')
        for name in names:
            raw=z.read(name);sha=hashlib.sha256(raw).hexdigest()
            entries=parse_daily(raw.decode('utf-8-sig'),code)
            members.append(dict(member=name,sha256=sha,rows=len(entries)))
            for day,value,q in entries:
                if not date(2009,1,1)<=day<=completed_through:continue
                evidence=dict(member=name,member_sha256=sha,quality_code=q,value=value)
                sources.setdefault(day,[]).append(evidence)
                if q not in (2,3,140):
                    excluded.setdefault(day,[]).append(evidence);continue
                if day in selected:
                    if selected[day][:2]!=(value,q):raise ValueError('Conflicting observed duplicate')
                    duplicates+=1
                else:selected[day]=(value,q,name,sha)
    rows=[]
    for day,(value,q,name,sha) in sorted(selected.items()):
        flags=dict(provider_quality_code=q,provider_quality_label=CODES[q],approval='not_approved',
            provisional=True,checked=q!=140,edited=q==3,source_member=name,source_member_sha256=sha)
        rows.append(dict(station_id='ECOLOGY-'+code,river_id=SITES[code][0],date=day,
            statistic='daily_mean',value=value,unit='degC',status='valid',temporal_basis='provider_daily',
            quality_flags=json.dumps(flags,sort_keys=True),source_url=BASE+code,
            source_sha256=archive_sha,retrieved_at=retrieved_at,report_date=export_day,
            source_title='Ecology Freshwater DataStream '+code+' original water-temperature export'))
    evidence=dict(path=str(path),sha256=archive_sha,source_url=BASE+code,retrieved_at=retrieved_at,
        members=members,rows=len(rows),duplicate_observations=duplicates,
        quality_counts=dict(Counter(str(r[1]) for r in selected.values())),
        excluded_days={str(d):v for d,v in sorted(excluded.items()) if d not in selected},
        overlapping_sources={str(d):v for d,v in sources.items() if len(v)>1},
        rule='Identical observed duplicates collapse; an observed day may replace an incomplete placeholder. Conflicting observed values or flags fail.')
    return rows,station(code),evidence

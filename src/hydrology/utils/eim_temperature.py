"""Qualified EIM daily summaries cross-checked against complete native half-hour days."""
import csv,json,hashlib,math,statistics
from collections import defaultdict,Counter
from datetime import date,datetime,time,timedelta
from pathlib import Path
from pyproj import Transformer

SITES={'18B070':('174040','elwha',39746,'5019205'), '16A070':('2333320','skokomish',146871,'01147')}
PST='PST - Pacific Standard Time (GMT-8)'
FIELDS={'Mean':('daily_mean','DailyAverage','Temperature, water (daily average)'),
        'Minimum':('daily_min','DailyMinimum','Temperature, water (daily minimum)'),
        'Maximum':('daily_max','DailyMaximum','Temperature, water (daily maximum)')}
def dt(value):return datetime.strptime(value,'%m/%d/%Y %I:%M:%S %p')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def records(folder,pattern):
    matches=list(Path(folder).glob(pattern))
    if len(matches)!=1:raise ValueError('Ambiguous or missing export member: '+pattern)
    return matches[0],list(csv.DictReader(matches[0].open(encoding='utf-8-sig',newline='')))

def qualify_summary(r,raw,code='18B070'):
    """None excludes scientifically unsupported summaries; malformed identities fail."""
    if r['Location_ID']!=code or r['Result_Value_Units']!='deg C' or r['Sample_Matrix'].lower()!='water':raise ValueError('Station/unit/matrix mismatch')
    start=dt(r['Field_Collection_Start_Date_Time'])
    day=start.date()
    if not date(2009,1,1)<=day<=date(2026,10,27):return None,'outside_scope'
    if r['Time_Basis']!='Daily':return None,'not_daily'
    if r['Time_Zone']!=PST:return None,'timezone_unqualified'
    if r['Statistical_Basis'] not in FIELDS:raise ValueError('Unknown daily statistic')
    stat,method,param=FIELDS[r['Statistical_Basis']]
    if r['Derivation_Method']!=method or r['Result_Parameter_Name']!=param:raise ValueError('Daily derivation mismatch')
    if (r['Result_Data_Review_Status']!='Reviewed' or r['Partial_Metric_Flag']!='N' or
        r['Data_Qualified_Flag']!='N' or r['Result_Data_Qualifier'] or r['Expected_Data_Percent']!='100.00'):
        return None,'incomplete_or_qualified'
    end=dt(r['Field_Collection_End_Date_Time'])
    if r['Sample_Size']!='48' or r['Base_Measurement_Interval']!='00:30:00' or start.date()!=end.date():raise ValueError('Unexpected daily support')
    if len(raw)!=48:raise ValueError('Expected 48 retained readings')
    stamps=[dt(x['Field_Collection_Date_Time']) for x in raw]
    expected={datetime.combine(day,time())+timedelta(minutes=30*i) for i in range(48)}
    if set(stamps)!=expected or len(set(stamps))!=48:raise ValueError('Duplicate/gapped native day')
    for x in raw:
        if (x['Location_ID']!=code or x['Result_Parameter_Name']!='Temperature, water' or
            x['Result_Value_Units']!='deg C' or x['Time_Zone']!=PST or x['Result_Data_Qualifier'] or
            x['Result_Data_Review_Status']!='Reviewed' or x['Measurement_Interval']!='00:30:00' or
            x['Sample_Matrix'].lower()!='water' or x['Instrument_ID']!=r['Instrument_ID']):raise ValueError('Unqualified underlying record')
    values=[float(x['Result_Value']) for x in raw]
    if not all(math.isfinite(x) and -5<=x<=45 for x in values):raise ValueError('Invalid underlying temperature')
    value=float(r['Result_Value']);calc={'Mean':statistics.mean,'Minimum':min,'Maximum':max}[r['Statistical_Basis']](values)
    if not math.isfinite(value) or abs(value-calc)>0.000051:raise ValueError('Summary does not match retained readings')
    if stat=='daily_mean' and (start!=min(stamps) or end!=max(stamps)):raise ValueError('Mean boundary mismatch')
    if stat!='daily_mean' and (start!=end or start not in stamps or values[stamps.index(start)]!=value):raise ValueError('Extreme timestamp mismatch')
    return (day,stat,value),None

def read_eim(folder,source_url,retrieved_at):
    folder=Path(folder)
    lp,locs=records(folder,'RiverStreamLocationDetails_*.csv')
    sp,summaries=records(folder,'RiverStreamSummarizedTimeSeriesResults_*.csv')
    tp,series=records(folder,'RiverStreamTimeSeriesResults_*.csv')
    dp,discrete=records(folder,'RiverStreamResults_*.csv')
    study,studies=records(folder,'RiverStreamStudyDetails_*.csv')
    if len(locs)!=1 or locs[0]['Location_ID'] not in SITES:raise ValueError('Location identity mismatch')
    code=locs[0]['Location_ID'];system_id,river,count,export_id=SITES[code]
    if locs[0]['Location_System_ID']!=system_id:raise ValueError('Location system identity mismatch')
    if not source_url.endswith('stevetylda'+export_id+'.zip'):raise ValueError('Source export identity mismatch')
    if sum(map(len,(locs,summaries,series,discrete,studies)))!=count:raise ValueError('Unexpected source record count')
    if any(x['Location_ID']!=code for x in summaries+series+discrete):raise ValueError('Foreign station')
    loc=locs[0]
    if loc['Location_Suspect_or_Rejected_Flag']:raise ValueError('Suspect location')
    lat=float(loc['Calculated_Latitude_Decimal_Degrees_NAD83HARN']);lon=float(loc['Calculated_Longitude_Decimal_Degrees_NAD83HARN'])
    transform=Transformer.from_crs(4152,4326,always_xy=True);wlon,wlat=transform.transform(lon,lat);op=transform.get_last_used_operation()
    if op.accuracy<0 or op.accuracy>2:raise ValueError('Coordinate conversion accuracy unqualified')
    station=dict(station_id='ECOLOGY-EIM-'+code,provider='Washington State Department of Ecology EIM',
        provider_station_id=code,provider_location_system_id=system_id,provider_station_name=loc['Location_Name'],river_id=river,
        latitude=wlat,longitude=wlon,coordinate_crs='EPSG:4326',coordinate_source=source_url,
        source_latitude=lat,source_longitude=lon,source_coordinate_crs='EPSG:4152 NAD83(HARN)',
        coordinate_accuracy=loc['Horizontal_Coordinate_Accuracy'],coordinate_conversion=op.description,
        coordinate_conversion_accuracy_metres=op.accuracy,coordinate_conversion_pipeline=op.definition,
        day_definition='Midnight PST native day, 48 half-hour samples from 00:00 through 23:30',timezone=PST,
        cadence='Sparse seasonal complete daily summaries; not continuous year-round history',unit='degC',
        statistics=['daily_mean','daily_min','daily_max'],model_eligible=False,
        relationship=loc['Location_Description']+'; distinct station identity, no river-mouth or discharge-gauge substitution',
        quality=('Reviewed source records; contributing records say Starting to pool. Review is not ecological representativeness.' if code=='18B070' else 'Reviewed complete daily summaries corroborated by unqualified reviewed native readings; no model-readiness claim.'),
        rights_url='https://ecology.wa.gov/About-us/Accountability-transparency/Our-website/Copyright-information',
        availability='Export retrieval and EIM record-created times do not establish original operational availability')
    grouped=defaultdict(list)
    for x in series:
        for field in ('Calculated_Latitude_Decimal_Degrees_NAD83HARN','Calculated_Longitude_Decimal_Degrees_NAD83HARN'):
            if float(x[field])!=float(loc[field]):raise ValueError('Underlying coordinate differs')
        grouped[(dt(x['Field_Collection_Date_Time']).date(),x['Instrument_ID'])].append(x)
    summary_sha=sha(sp);series_sha=sha(tp)
    rows=[];seen=set();excluded=Counter();export_day=datetime.fromisoformat(retrieved_at).date()
    for r in summaries:
        for field in ('Calculated_Latitude_Decimal_Degrees_NAD83HARN','Calculated_Longitude_Decimal_Degrees_NAD83HARN'):
            if float(r[field])!=float(loc[field]):raise ValueError('Summary coordinate differs')
        raw=grouped[(dt(r['Field_Collection_Start_Date_Time']).date(),r['Instrument_ID'])]
        qualified,reason=qualify_summary(r,raw,code)
        if qualified is None:excluded[reason]+=1;continue
        day,stat,value=qualified
        if (day,stat) in seen:raise ValueError('Duplicate station/day/statistic')
        seen.add((day,stat))
        flags={k:r[k] for k in ['Study_ID','Instrument_ID','Result_Data_Review_Status','Partial_Metric_Flag','Data_Qualified_Flag','Expected_Data_Percent','Sample_Size','Base_Measurement_Interval','Calculated_Result_System_ID','Record_Created_On','Field_Collection_Start_Date_Time','Field_Collection_End_Date_Time','Derivation_Method']}
        flags.update(source_comments=sorted(set(x['Result_Comment'] for x in raw if x['Result_Comment'])),source_csv=sp.name,source_csv_sha256=summary_sha,underlying_csv_sha256=series_sha,underlying_record_ids=sorted(x['Continuous_Result_System_ID'] for x in raw),approval='reviewed_not_model_ready')
        rows.append(dict(station_id=station['station_id'],river_id=river,date=day,statistic=stat,value=value,unit='degC',status='valid',temporal_basis='provider_daily',quality_flags=json.dumps(flags,sort_keys=True),source_url=source_url,source_sha256=summary_sha,retrieved_at=retrieved_at,report_date=export_day,source_title=('Ecology EIM Elwha 18B070 export 5019205: provider daily summaries verified against native time series' if code=='18B070' else 'Ecology EIM '+code+' export '+export_id+': provider daily summaries verified against native time series')))
    evidence=dict(source_url=source_url,folder=str(folder),retrieved_at=retrieved_at,source_records=count,
        source_form='User browser automatically extracted original download; original ZIP not present; individual member hashes retained',
        files=[dict(name=p.name,bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(folder.iterdir()) if p.is_file()],
        summary_exclusions=dict(excluded),discrete_rows_retained_not_delivered=len(discrete),instantaneous_rows_retained_not_delivered=len(series),
        qualification='Only complete reviewed provider daily summaries corroborated by exactly 48 unique native PST half-hours; unknown-timezone summaries and discrete/instantaneous rows not mislabeled daily')
    return rows,station,evidence

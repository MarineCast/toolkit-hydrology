"""Independent, sparse station temperature observations; no river/gauge substitution."""
from datetime import date, datetime
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.parquet as pq
from .products import checksum

KEY = b'hydrology_station_temperature'
FORMAT = 'hydrology-station-temperature-1'
NAME = 'station_temperature.parquet'
SCHEMA = pa.schema([(k,t) for k,t in [
    ('station_id',pa.string()),('river_id',pa.string()),('date',pa.date32()),
    ('statistic',pa.string()),('value',pa.float64()),('unit',pa.string()),
    ('status',pa.string()),('temporal_basis',pa.string()),('quality_flags',pa.string()),
    ('source_url',pa.string()),('source_sha256',pa.string()),('retrieved_at',pa.string()),
    ('report_date',pa.date32()),('source_title',pa.string())]])
QUALARK = dict(station_id='DFO-QUALARK',provider='DFO Environmental Watch',
    provider_station_name='Fraser River at Qualark',river_id='fraser',
    latitude=49+31/60+58.13/3600,longitude=-(121+25/60+20.67/3600),
    coordinate_crs='EPSG:4326',coordinate_precision='published coordinate; no current sensor survey',
    coordinate_source='https://doi.org/10.1080/00028487.2015.1031282',
    coordinate_source_detail='Robinson et al. 2015, p.698, Qualark water-temperature station used in 2011',
    identity_note='Local stable ID; not asserted to be a provider-issued station code',
    relationship='Fraser mainstem at Qualark; distinct from WSC Hope discharge station; not river-mouth temperature',
    timezone=None,day_definition='DFO report native daily mean; timezone and averaging boundaries unpublished/unverified',
    cadence='sparse report-date daily means; underlying loggers not acquired',
    unit='degC',statistics=['daily_mean'],model_eligible=False,
    quality='provider report; approval/provisional status not supplied',
    rights_url='https://www.dfo-mpo.gc.ca/terms-avis/terms-conditions-avis-eng.htm',
    rights='Attributed local non-commercial reproduction; commercial redistribution requires DFO permission',
    author='Fisheries and Oceans Canada',
    availability='original operational availability and revisions unknown')

class Report(HTMLParser):
    def __init__(self):
        super().__init__(); self.headings=[]; self.rows=[]; self.headers=[]
        self.tag=None; self.buf=[]; self.table=False; self.row=[]
    def handle_starttag(self,tag,attrs):
        if tag=='table' and dict(attrs).get('id')=='current-temp': self.table=True
        if tag in ('h1','h2') or (self.table and tag in ('td','th')):
            self.tag=tag; self.buf=[]
        if self.table and tag=='tr': self.row=[]
    def handle_data(self,data):
        if self.tag: self.buf.append(data)
    def handle_endtag(self,tag):
        if tag==self.tag:
            text=' '.join(''.join(self.buf).split())
            if tag in ('h1','h2'): self.headings.append((tag,text))
            elif tag=='th': self.headers.append(text)
            else: self.row.append(text)
            self.tag=None
        if tag=='tr' and self.table and self.row: self.rows.append(self.row)
        if tag=='table': self.table=False

def parse_dfo_report(html, url, sha256, retrieved_at, *, completed_through):
    """Only explicitly labelled observed daily-mean table; never graphs/forecasts."""
    p=Report(); p.feed(html)
    current=[x for tag,x in p.headings if tag=='h2' and x.startswith('Current temperatures:')]
    if not current: return None # Older report formats require separate qualification.
    if len(current)!=1 or p.headers != ['Location','Daily mean','Historic mean','Year range']:
        raise ValueError('Ambiguous current temperature table')
    day=datetime.strptime(current[0].split(':',1)[1].strip(),'%B %d, %Y').date()
    titles=[x for tag,x in p.headings if tag=='h1']
    if len(titles)!=1 or 'environmental watch report' not in titles[0].lower():
        raise ValueError('Unexpected report identity')
    m=re.search(r'/(20\d\d-\d\d-\d\d)-eng.html$',url)
    if not m or not url.startswith('https://www.pac.dfo-mpo.gc.ca/science/habitat/frw-rfo/reports-rapports/'):
        raise ValueError('Unexpected source URL')
    report_day=date.fromisoformat(m[1])
    if day>completed_through or day>report_day or (report_day-day).days>7 or day<date(2009,1,1):
        raise ValueError('Unqualified observation date')
    matches=[r for r in p.rows if r[0] in ('Fraser River at Qualark','Fraser River @ Qualark')]
    if not matches: return None
    if len(matches)!=1 or len(matches[0])!=4: raise ValueError('Ambiguous Qualark row')
    text=matches[0][1]
    if not re.fullmatch(r'-?\d+(?:\.\d+)?',text): return None
    # Celsius is explicit in the report's Qualark water-temperature section.
    if not re.search(r'(?:°|&deg;)C',html): raise ValueError('Celsius not documented')
    return dict(station_id='DFO-QUALARK',river_id='fraser',date=day,statistic='daily_mean',
        value=float(text),unit='degC',status='valid',temporal_basis='provider_daily',
        quality_flags=json.dumps({'approval':'not_supplied','provisional':'unknown','source':'published_report'}),
        source_url=url,source_sha256=sha256,retrieved_at=retrieved_at,
        report_date=report_day,source_title=titles[0])

def make_table(rows, stations, provenance):
    table=pa.Table.from_pylist(sorted(rows,key=lambda r:(r['station_id'],r['date'],r['statistic'])),schema=SCHEMA)
    meta=dict(format=FORMAT,stations=stations,provenance=provenance,
        missingness='Absent dates unobserved in acquired reports; no filling/interpolation',model_eligible=False)
    table=table.replace_schema_metadata({KEY:json.dumps(meta,sort_keys=True).encode()})
    validate_table(table)
    return table

def validate_table(table):
    if table.schema.remove_metadata()!=SCHEMA: raise ValueError('Station schema mismatch')
    meta=json.loads((table.schema.metadata or {})[KEY])
    if meta['format']!=FORMAT: raise ValueError('Unknown station format')
    stations=meta['stations']; seen=set()
    for sid,s in stations.items():
        if sid!=s['station_id'] or not (-90<=s['latitude']<=90 and -180<=s['longitude']<=180):
            raise ValueError('Invalid station identity/coordinates')
        if not s.get('coordinate_source') or not s.get('day_definition') or not s.get('rights_url'):
            raise ValueError('Missing station qualification')
    for r in table.to_pylist():
        s=stations[r['station_id']]
        key=(r['station_id'],r['date'],r['statistic'],r['temporal_basis'])
        if key in seen: raise ValueError('Duplicate station/date/statistic key')
        seen.add(key)
        if r['river_id']!=s['river_id'] or r['unit']!=s['unit'] or r['statistic'] not in s['statistics']:
            raise ValueError('Station/river/statistic/unit mismatch')
        if r['status']!='valid' or not math.isfinite(r['value']) or not -5<=r['value']<=45:
            raise ValueError('Invalid water temperature')
        if r['temporal_basis']!='provider_daily' or r['date']>r['report_date']:
            raise ValueError('Invalid temporal support')
        if not re.fullmatch('[0-9a-f]{64}',r['source_sha256']) or not r['source_url'] or not r['source_title']:
            raise ValueError('Missing source provenance')
        if not json.loads(r['quality_flags']): raise ValueError('Missing quality flags')
    return meta

def catalog_with_station_temperature(catalog,root):
    path=Path(root)/NAME
    if not path.exists():
        if 'station_temperature' in catalog.get('products',{}): raise ValueError('Missing station companion')
        return catalog
    if path.is_symlink(): raise ValueError('Station symlink forbidden')
    table=pq.read_table(path); meta=validate_table(table)
    rows=table.to_pylist()
    entry=dict(path=NAME,format=FORMAT,sha256=checksum(path),bytes=path.stat().st_size,rows=len(rows),
        stations=meta['stations'],model_eligible=False,temporal_basis='provider_daily',
        start=min(str(r['date']) for r in rows),end=max(str(r['date']) for r in rows),
        source_status='independent_observations',statistics=sorted(set(r['statistic'] for r in rows)))
    if not set(s['river_id'] for s in meta['stations'].values())<=set(catalog['rivers']):
        raise ValueError('Unknown associated river')
    return {**catalog,'products':{**catalog.get('products',{}),'station_temperature':entry}}


def parse_dfo_pdf_text(text, source_url, sha256, retrieved_at, *, completed_through):
    """Parse qualified Poppler-layout report text; table identity outranks chart titles.

    Older reports label the daily table Qualark while a separate graph says Hope.
    Only an explicit Qualark table row is used; no values are digitized from graphs.
    """
    title='Fraser River Environmental Watch Report'
    if title not in text: raise ValueError('Unexpected PDF report title')
    clean=re.sub(r'(\d)(?:st|nd|rd|th)\b',r'\1',text)
    clean=re.sub(r'\bSept\b','Sep',clean)
    match=re.search(re.escape(title)+r'\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})',clean)
    if not match: raise ValueError('Unknown PDF report date')
    def full_date(value):
        for fmt in ('%B %d, %Y','%b %d, %Y'):
            try: return datetime.strptime(value,fmt).date()
            except ValueError: pass
        raise ValueError('Invalid full date')
    report_day=full_date(match[1])
    member=re.search(r'#(?:[^#]*/)?(20\d\d-\d\d-\d\d)-eng.pdf$',source_url)
    if not source_url.startswith('https://www.pac.dfo-mpo.gc.ca/science/habitat/frw-rfo/reports-rapports/') or not member:
        raise ValueError('Unexpected PDF source identity')
    if date.fromisoformat(member[1])!=report_day: raise ValueError('PDF filename/report date mismatch')
    sections=clean.split('Current Temperatures')
    if len(sections)!=2: raise ValueError('Ambiguous current temperature section')
    section=sections[1].split('\f',1)[0]
    if not re.search(r'^\s*Fraser River\s+(?:@|at)\s+Qualark\b',section,re.M): return None
    header=re.search(r'^\s*(\S[^\n]*?)\s+Daily Mean(?:\s+Historic (?:Mean|Median))?\s*$',section,re.M)
    if not header: raise ValueError('Unknown daily-mean PDF columns')
    label=header[1].strip()
    if re.fullmatch(r'[A-Za-z]+\s+\d{1,2},\s*\d{4}',label): day=full_date(label)
    else:
        candidates=[]
        for year in (report_day.year,report_day.year-1):
            for fmt in ('%d-%b-%Y','%b-%d-%Y','%d-%B-%Y','%B-%d-%Y'):
                try: d=datetime.strptime(label+'-'+str(year),fmt).date()
                except ValueError: continue
                if 0<=(report_day-d).days<=7: candidates.append(d)
        if len(set(candidates))!=1: raise ValueError('Unqualified PDF observation date')
        day=candidates[0]
    if day<date(2009,1,1) or day>completed_through or not 0<=(report_day-day).days<=7:
        raise ValueError('Unqualified PDF observation date')
    lines=re.findall(r'^\s*Fraser River\s+(?:@|at)\s+Qualark\s+([^\n]+)',section,re.M)
    if len(lines)!=1: raise ValueError('Ambiguous Qualark PDF row')
    values=lines[0].split()
    if len(values) not in (1,2): raise ValueError('Unexpected Qualark PDF columns')
    if values[0] in ('NA','N/A'): return None
    if not re.fullmatch(r'-?\d+(?:\.\d+)?',values[0]): raise ValueError('Invalid PDF value')
    if not re.search(r'(?:°|º)C',clean): raise ValueError('PDF Celsius unsupported')
    return dict(station_id='DFO-QUALARK',river_id='fraser',date=day,statistic='daily_mean',
        value=float(values[0]),unit='degC',status='valid',temporal_basis='provider_daily',
        quality_flags=json.dumps({'approval':'not_supplied','provisional':'unknown','source':'published_report'}),
        source_url=source_url,source_sha256=sha256,retrieved_at=retrieved_at,
        report_date=report_day,source_title=title+' - '+match[1])

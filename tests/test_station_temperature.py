from copy import deepcopy
from datetime import date
import json
import pytest
from hydrology.utils.station_temperature import QUALARK, parse_dfo_report, make_table, validate_table
from hydrology.pipelines.station_temperature import assert_preserved, publish_station_temperature

URL='https://www.pac.dfo-mpo.gc.ca/science/habitat/frw-rfo/reports-rapports/2026/2026-09-21-eng.html'
HTML='''<h1>Fraser River environmental watch report - September 21, 2026</h1>
<h2>Current temperatures: September 20, 2026</h2><table id="current-temp"><tr>
<th>Location</th><th>Daily mean</th><th>Historic mean</th><th>Year range</th></tr>
<tr><td>Fraser River at Qualark</td><td>16.1</td><td>14.2</td><td>1950-2025</td></tr></table><h2>Fraser River water temperatures at Qualark</h2><p>18&deg;C</p>'''

def row(html=HTML,url=URL,through=date(2026,10,25)):
    return parse_dfo_report(html,url,'a'*64,'2026-10-26T00:00:00Z',completed_through=through)
def table(rows=None,station=None):
    s=station or QUALARK
    return make_table(rows or [row()],{s['station_id']:s},{'test':'synthetic'})

def test_reference_identity_statistic_and_native_day():
    r=row();assert r['value']==16.1 and r['date']==date(2026,9,20)
    assert r['unit']=='degC' and r['statistic']=='daily_mean'
    assert row(HTML.replace(' at Qualark',' @ Qualark'))==r
    assert QUALARK['latitude']==pytest.approx(49.5328138889)
    assert QUALARK['longitude']==pytest.approx(-121.4224083333)
    assert QUALARK['timezone'] is None
    assert json.loads(r['quality_flags'])['provisional']=='unknown'
    validate_table(table())

def test_forecast_historic_and_missing_are_not_observations():
    assert row(HTML.replace('Current temperatures:','Forecast temperatures:')) is None
    assert row(HTML.replace('<td>16.1</td>','<td>N/A</td>')) is None
    assert row(HTML.replace('Fraser River at Qualark','Unrelated river')) is None
    with pytest.raises(ValueError): row(HTML.replace('Daily mean','Daily maximum'))
    with pytest.raises(ValueError): row(through=date(2026,9,19))
    with pytest.raises(ValueError): row(HTML.replace('September 20,','September 22,'))
    with pytest.raises(ValueError): row(HTML.replace('&deg;C','F'))

@pytest.mark.parametrize('change',[{'unit':'degF'},{'river_id':'skagit'},{'value':float('nan')},{'quality_flags':'{}'},{'statistic':'daily_max'}])
def test_reject_invalid_rows(change):
    with pytest.raises(ValueError): table([{**row(),**change}])

def test_duplicate_gaps_leap_and_multiple_sites_same_river():
    r=row()
    with pytest.raises(ValueError): table([r,r])
    s=deepcopy(QUALARK);s['station_id']='TEST-OTHER';s['latitude']+=.1
    r2={**r,'station_id':s['station_id']}
    result=make_table([r,r2],{'DFO-QUALARK':QUALARK,s['station_id']:s},{})
    assert len(result)==2
    leap={**r,'date':date(2024,2,29),'report_date':date(2024,3,1)}
    sparse=table([leap,r]);assert len(sparse)==2
    assert_preserved(table(),sparse)
    with pytest.raises(ValueError): assert_preserved(table(),table([{**r,'value':17.}]))
    bad={**QUALARK,'latitude':100}
    with pytest.raises(ValueError): table(station=bad)

def test_publication_and_carry_forward_preserve_old_files(tmp_path,monkeypatch):
    from test_correctness_and_canonical import acquired,config
    from hydrology.pipelines import acquisition,publication
    from hydrology.utils.products import checksum
    monkeypatch.setattr(acquisition,'acquire',acquired)
    cfg=config(tmp_path)
    target,_=publication.publish_rivers(cfg)
    before={str(p.relative_to(target)):checksum(p) for p in target.rglob('*') if p.is_file() and p.name!='catalog.json'}
    s={**QUALARK,'station_id':'TEST-TEMP','river_id':'skagit'}
    r={**row(),'station_id':'TEST-TEMP','river_id':'skagit'}
    t=table([r],s)
    result=publish_station_temperature(target,t)
    assert result['preserved_files']==len(before)
    assert all(checksum(target/p)==v for p,v in before.items())
    assert publication.validate_product(target)['products']['station_temperature']['rows']==1
    publication.publish_rivers(cfg)
    assert publication.validate_product(target)['products']['station_temperature']['rows']==1

def test_interrupted_transaction_blocks_readers(tmp_path,monkeypatch):
    from test_correctness_and_canonical import acquired,config
    from hydrology.pipelines import acquisition,publication
    monkeypatch.setattr(acquisition,'acquire',acquired)
    target,_=publication.publish_rivers(config(tmp_path))
    _,store,_=publication._paths(target)
    (store/'station-temperature-transaction.json').write_text('{}')
    with pytest.raises(ValueError,match='Interrupted station-temperature'):
        publication.validate_product(target)

def test_failed_catalog_update_rolls_back(tmp_path,monkeypatch):
    from test_correctness_and_canonical import acquired,config
    from hydrology.pipelines import acquisition,publication
    from hydrology.pipelines import station_temperature as publisher
    from hydrology.utils.products import checksum
    monkeypatch.setattr(acquisition,'acquire',acquired)
    target,_=publication.publish_rivers(config(tmp_path))
    before={str(p.relative_to(target)):checksum(p) for p in target.rglob('*') if p.is_file()}
    real=publisher.atomic_json
    def fail(path,value):
        if path==target/'catalog.json' and 'station_temperature' in value.get('products',{}):
            raise OSError('synthetic publication failure')
        return real(path,value)
    monkeypatch.setattr(publisher,'atomic_json',fail)
    s={**QUALARK,'station_id':'TEST-TEMP','river_id':'skagit'}
    r={**row(),'station_id':'TEST-TEMP','river_id':'skagit'}
    with pytest.raises(OSError): publish_station_temperature(target,table([r],s))
    assert {str(p.relative_to(target)):checksum(p) for p in target.rglob('*') if p.is_file()}==before
    publication.validate_product(target)

PDF='''Fraser River Environmental Watch Report
September 3rd, 2015
Current Temperatures
 02-Sep                 Daily Mean       Historic Median
Fraser Mainstem
Fraser River @ Qualark   16.3             16.9
Fraser River @ Texas Creek 15.7           15.3
\fFraser River Water Temperatures at Hope
18°C - Decreased swimming performance'''
PDF_URL='https://www.pac.dfo-mpo.gc.ca/science/habitat/frw-rfo/reports-rapports/2015.zip#2015/2015-09-03/2015-09-03-eng.pdf'

def pdfrow(text=PDF,url=PDF_URL):
    from hydrology.utils.station_temperature import parse_dfo_pdf_text
    return parse_dfo_pdf_text(text,url,'b'*64,'2026-10-26T00:00:00Z',completed_through=date(2026,10,25))

def test_pdf_reference_exact_table_not_graph_or_historic():
    r=pdfrow();assert r['value']==16.3 and r['date']==date(2015,9,2)
    assert r['report_date']==date(2015,9,3)
    assert pdfrow(PDF.replace('02-Sep','Sep-02'))['date']==r['date']
    assert pdfrow(PDF.replace('Qualark','Hope')) is None
    assert pdfrow(PDF.replace('16.3','NA')) is None
    assert pdfrow(PDF.replace('Historic Median','Historic Mean'))['value']==16.3

@pytest.mark.parametrize('text',[PDF.replace('Daily Mean','Daily Maximum'),PDF.replace('02-Sep','01-Aug'),PDF.replace('°C','F'),PDF.replace('16.3','16.3 14.0'),PDF.replace('September 3rd, 2015','September 4, 2015')])
def test_pdf_ambiguities_fail_closed(text):
    with pytest.raises(ValueError):pdfrow(text)

def test_full_month_pdf_label():
    assert pdfrow(PDF.replace('02-Sep','02-September'))['date']==date(2015,9,2)


def test_historical_extension_rejects_tampering_and_preserves_rows(tmp_path,monkeypatch):
    import importlib.util
    from pathlib import Path
    from hydrology.utils.products import checksum
    spec=importlib.util.spec_from_file_location('history',Path(__file__).parents[1]/'scripts'/'extend_dfo_temperature_history.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    source=tmp_path/'sample.pdf';source.write_bytes(b'%PDF-synthetic-source')
    rec=dict(path=str(source),sha256=checksum(source),archive_url=PDF_URL.split('#')[0],member=PDF_URL.split('#')[1],retrieved_at='2026-10-26T00:00:00Z')
    monkeypatch.setattr(mod.subprocess,'check_output',lambda *a,**k:PDF.encode())
    old=table();new=mod.extend_table(old,[rec],date(2026,10,25))
    assert len(new)==2
    assert_preserved(old,new)
    assert new.to_pylist()[0]['value']==16.3
    support=tmp_path/'paired.html';support.write_text('verified units/date')
    rec['supporting_report']={'path':str(support),'sha256':'0'*64}
    with pytest.raises(ValueError,match='Supporting report checksum'):
        mod.extend_table(old,[rec],date(2026,10,25))
    rec.pop('supporting_report')
    source.write_bytes(b'%PDF-tampered')
    with pytest.raises(ValueError,match='checksum'):mod.extend_table(old,[rec],date(2026,10,25))

def test_historical_duplicate_sources_preserved_and_conflicts_rejected():
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('history_dedup',Path(__file__).parents[1]/'scripts'/'extend_dfo_temperature_history.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    r=pdfrow();other={**r,'source_url':r['source_url'].replace('2015-09-03-eng.pdf','2015-09-01-eng.pdf'),'source_sha256':'c'*64}
    rows,sources=mod.coalesce_new_rows([other,r])
    assert rows==[r] and len(sources[0])==2
    with pytest.raises(ValueError,match='Conflicting'):mod.coalesce_new_rows([r,{**other,'value':15.}])

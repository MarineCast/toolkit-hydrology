from datetime import date
import zipfile
import pytest
from hydrology.utils.ecology_temperature import parse_daily,read_export,station

def fixture(rows,code='10A040'):
    return f'''For mean daily tables, data values are for the dates listed starting at
midnight PST.
{code}--{station(code)['provider_station_name']}
DATE         Water Temp. (°C)   QUALITY
{rows}
Quality Codes Key:
2 - Good quality provisional data
3 - Good quality provisional data - edited
140 - Data not yet checked
151 - Data Missing
215 - Data rejected
255 - Incomplete day
'''

def test_reference_leap_gap_and_flags(tmp_path):
    p=tmp_path/'export.zip'
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('10A040_2024_WTM_DV.TXT',fixture('02/28/2024 8.2 2\n02/29/2024 8.3 3\n03/01/2024 8.4 151\n03/02/2024 255\n03/03/2024 215\n03/04/2024 8.5 140'))
    rows,s,e=read_export(p,'10A040','2026-10-28T15:30:00Z',completed_through=date(2026,10,27))
    assert [r['value'] for r in rows]==[8.2,8.3,8.5]
    assert rows[1]['date']==date(2024,2,29)
    assert len(e['excluded_days'])==3 and e['quality_counts']=={'2':1,'3':1,'140':1}
    assert s['latitude']==47.208287 and s['longitude']==-122.326841
    assert all(r['unit']=='degC' and r['temporal_basis']=='provider_daily' for r in rows)

@pytest.mark.parametrize('old,new',[('Water Temp.','Air Temp.'),('°C','°F'),('midnight PST','midnight UTC'),('10A040--','07A089--'),('Good quality provisional data','Approved data')])
def test_header_rejection(old,new):
    with pytest.raises(ValueError):parse_daily(fixture('02/29/2024 9 2').replace(old,new),'10A040')

@pytest.mark.parametrize('rows',['02/29/2023 9 2','02/29/2024 9 999','02/29/2024 2','02/29/2024 99 2','02/29/2024 9 2\n02/29/2024 9 2'])
def test_bad_rows(rows):
    with pytest.raises(ValueError):parse_daily(fixture(rows),'10A040')

def test_overlap_and_future(tmp_path):
    p=tmp_path/'x.zip'
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('10A040_2026_WTM_DV.TXT',fixture('10/01/2026 255\n10/02/2026 9 2'))
        z.writestr('10A040_WTM_DV.TXT',fixture('10/01/2026 8 140\n10/02/2026 9 2\n10/28/2026 10 140'))
    rows,_,e=read_export(p,'10A040','2026-10-28T15:30:00Z',completed_through=date(2026,10,27))
    assert len(rows)==2 and e['duplicate_observations']==1
    assert not e['excluded_days']

def test_conflict(tmp_path):
    p=tmp_path/'x.zip'
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('10A040_2026_WTM_DV.TXT',fixture('10/01/2026 8 2'))
        z.writestr('10A040_WTM_DV.TXT',fixture('10/01/2026 9 2'))
    with pytest.raises(ValueError,match='Conflicting'):read_export(p,'10A040','2026-10-28T15:30:00Z',completed_through=date(2026,10,27))

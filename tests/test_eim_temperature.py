from datetime import datetime,timedelta
import pytest
from hydrology.utils.eim_temperature import qualify_summary,PST

def example():
 day=datetime(2012,2,29);fmt='%m/%d/%Y %I:%M:%S %p'
 raw=[dict(Location_ID='18B070',Result_Parameter_Name='Temperature, water',Result_Value_Units='deg C',Time_Zone=PST,Result_Data_Qualifier='',Result_Data_Review_Status='Reviewed',Measurement_Interval='00:30:00',Sample_Matrix='WATER',Instrument_ID='sensor',Field_Collection_Date_Time=(day+timedelta(minutes=30*i)).strftime(fmt),Result_Value='8') for i in range(48)]
 r=dict(Location_ID='18B070',Result_Value_Units='deg C',Sample_Matrix='Water',Field_Collection_Start_Date_Time=raw[0]['Field_Collection_Date_Time'],Field_Collection_End_Date_Time=raw[-1]['Field_Collection_Date_Time'],Time_Basis='Daily',Time_Zone=PST,Statistical_Basis='Mean',Derivation_Method='DailyAverage',Result_Parameter_Name='Temperature, water (daily average)',Result_Data_Review_Status='Reviewed',Partial_Metric_Flag='N',Data_Qualified_Flag='N',Result_Data_Qualifier='',Expected_Data_Percent='100.00',Sample_Size='48',Base_Measurement_Interval='00:30:00',Instrument_ID='sensor',Result_Value='8')
 return r,raw

def test_complete_leap_day():
 r,a=example();q,reason=qualify_summary(r,a);assert q[0].isoformat()=='2012-02-29' and q[1:] == ('daily_mean',8.0) and reason is None

@pytest.mark.parametrize('field,value',[('Time_Zone',''),('Partial_Metric_Flag','Y'),('Expected_Data_Percent','97.90'),('Result_Data_Review_Status','Not Reviewed'),('Data_Qualified_Flag','Y')])
def test_exclusion(field,value):
 r,a=example();r[field]=value;assert qualify_summary(r,a)[0] is None

@pytest.mark.parametrize('mutation',['missing','duplicate','value','unit','station','extreme_time'])
def test_fail_closed(mutation):
 r,a=example()
 if mutation=='missing':a.pop()
 if mutation=='duplicate':a[-1]=a[0]
 if mutation=='value':r['Result_Value']='9'
 if mutation=='unit':a[0]['Result_Value_Units']='deg F'
 if mutation=='station':r['Location_ID']='16A070'
 if mutation=='extreme_time':r.update(Statistical_Basis='Maximum',Derivation_Method='DailyMaximum',Result_Parameter_Name='Temperature, water (daily maximum)')
 with pytest.raises(ValueError):qualify_summary(r,a)

def test_max_is_extreme_time_not_daily_interval():
 r,a=example();r.update(Statistical_Basis='Maximum',Derivation_Method='DailyMaximum',Result_Parameter_Name='Temperature, water (daily maximum)',Field_Collection_End_Date_Time=r['Field_Collection_Start_Date_Time'])
 assert qualify_summary(r,a)[0][1]=='daily_max'

def test_unknown_timezone_missing_end_is_excluded():
 r,a=example();r.update(Time_Zone='',Field_Collection_End_Date_Time='')
 assert qualify_summary(r,a)[1]=='timezone_unqualified'

def test_skokomish_identity_and_cross_station_rejection():
 r,a=example();r['Location_ID']='16A070'
 for x in a:x['Location_ID']='16A070'
 assert qualify_summary(r,a,'16A070')[0][1]=='daily_mean'
 with pytest.raises(ValueError):qualify_summary(r,a,'18B070')
 a[0]['Location_ID']='18B070'
 with pytest.raises(ValueError):qualify_summary(r,a,'16A070')

def test_estimated_underlying_reading_rejected():
 r,a=example();a[0]['Result_Data_Qualifier']='EST'
 with pytest.raises(ValueError):qualify_summary(r,a)

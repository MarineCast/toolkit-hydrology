import numpy as np
import pandas as pd
import pytest
from hydrology.utils.causal import causal_features, UNITS


def fixture():
    dates=pd.date_range("2017-01-01","2021-03-05")
    return pd.DataFrame(dict(date=dates,river_id="r",station_id="s",metric="discharge_mean",temporal_basis="provider_daily",unit="m3/s",status="valid",value=np.full(len(dates),10.)))


def wide(f, **kw):
    result,_=causal_features(f,**kw)
    return result.pivot(index="date",columns="metric",values="value")


def test_future_and_same_day_cannot_change_past():
    f=fixture(); before,_=causal_features(f)
    changed=f.copy(); changed.loc[changed.date>=pd.Timestamp("2020-06-01"),"value"]=900
    after,_=causal_features(changed)
    mask=pd.to_datetime(before.date)<=pd.Timestamp("2020-06-01")
    pd.testing.assert_frame_equal(before[mask],after[mask])


def test_reference_warmup_leap_units_and_keys():
    f=fixture(); result,definition=causal_features(f)
    assert len(result)==len(f)*len(UNITS)
    assert not result.duplicated(["date","metric","river_id","station_id","temporal_basis"]).any()
    assert result.groupby("metric").unit.first().to_dict()==UNITS
    w=wide(f)
    assert np.isnan(w.loc[pd.Timestamp("2020-01-01").date(),"causal_discharge_seasonal_mean"])
    for d in ["2020-01-02","2020-02-29","2020-03-01","2021-01-01"]:
        row=w.loc[pd.Timestamp(d).date()]
        assert row.causal_discharge_seasonal_mean==10
        assert row.causal_discharge_seasonal_percentile==50
        assert row.causal_discharge_seasonal_anomaly==0
    assert definition["model_eligible"] is False


def test_fixed_pulse_gap_and_no_interpolation():
    f=fixture()
    f.loc[f.date==pd.Timestamp("2020-06-01"),"value"]=5
    f.loc[f.date==pd.Timestamp("2020-06-02"),"value"]=20
    f.loc[f.date==pd.Timestamp("2020-06-04"),["value","status"]]=[np.nan,"unavailable"]
    w=wide(f)
    assert w.loc[pd.Timestamp("2020-06-03").date(),"causal_discharge_pulse"]==1
    assert w.loc[pd.Timestamp("2020-06-04").date(),"causal_days_since_discharge_pulse"]==1
    for d in ["2020-06-05","2020-06-06","2020-06-07"]:
        assert np.isnan(w.loc[pd.Timestamp(d).date(),"causal_days_since_discharge_pulse"])
    assert np.isnan(w.loc[pd.Timestamp("2020-06-05").date(),"causal_discharge_seasonal_percentile"])
    assert w.loc[pd.Timestamp("2020-06-05").date(),"causal_discharge_seasonal_mean"]==10


def test_reject_units_duplicates_and_bounded_reference():
    f=fixture()
    with pytest.raises(ValueError): causal_features(pd.concat([f,f.iloc[:1]]))
    with pytest.raises(ValueError): causal_features(f.assign(unit="cfs"))
    with pytest.raises(ValueError): causal_features(f,history_years=2)
    f.loc[f.date.dt.year==2017,"value"]=1000
    w=wide(f,history_years=3)
    assert w.loc[pd.Timestamp("2021-03-02").date(),"causal_discharge_seasonal_mean"]==10


def test_publication_preserves_sources_and_catalog(tmp_path, monkeypatch):
    from test_correctness_and_canonical import acquired, config
    from hydrology.pipelines import acquisition, publication
    from hydrology.pipelines.causal import publish_causal
    from hydrology.utils.products import checksum
    from hydrology.utils.causal import catalog_with_causal
    monkeypatch.setattr(acquisition, "acquire", acquired)
    target,_=publication.publish_rivers(config(tmp_path))
    before={str(p.relative_to(target)):checksum(p) for p in target.rglob("*") if p.is_file() and p.name!="catalog.json"}
    publish_causal(target)
    catalog=publication.validate_product(target)
    assert catalog["products"]["causal"]["source_status"]=="current"
    assert all(checksum(target/name)==value for name,value in before.items())
    river=next(iter(catalog["rivers"]))
    path=target/river/"conditions.parquet"
    path.write_bytes(path.read_bytes()+b"changed")
    assert catalog_with_causal(catalog,target)["products"]["causal"]["source_status"]=="requires_rebuild"

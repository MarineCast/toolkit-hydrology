"""Offline station-coordinate maps; requires matplotlib and installed hydrology."""
import argparse
from datetime import date
import json
from importlib.resources import files
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import pyarrow.parquet as pq
from hydrology.utils.station_temperature import validate_table


def panel(fig, ax, sites, values, title, unit, limits=None):
    xs=[s[1] for s in sites]; ys=[s[2] for s in sites]
    ax.scatter(xs,ys,c='#d5d9df',edgecolors='#687580',s=75,label='No value',zorder=2)
    good=[(s,values.get(s[0])) for s in sites if pd.notna(values.get(s[0]))]
    if good:
        points=ax.scatter([s[1] for s,v in good],[s[2] for s,v in good],c=[v for s,v in good],cmap='viridis',s=80,zorder=3, vmin=limits[0] if limits else None,vmax=limits[1] if limits else None)
        fig.colorbar(points,ax=ax,shrink=.68,label=unit)
    for s in sites: ax.annotate(s[3],(s[1],s[2]),xytext=(5,5),textcoords='offset points',fontsize=7)
    ax.set(xlim=(-125,-120.3),ylim=(45.3,50),xlabel='Longitude (°)',ylabel='Latitude (°)',title=title)
    ax.set_aspect(1/0.68);ax.grid(alpha=.2);ax.legend(loc='lower left',fontsize=7)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--product',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    registry=json.loads(files('hydrology').joinpath('data/registry.json').read_text())
    sites=[(r['river_id'],*r['stations'][0]['geometry']['coordinates'],r['name']) for r in registry['rivers']]
    causal=pd.read_parquet(a.product/'causal.parquet');day=date(2023,8,1)
    definitions=[('causal_discharge_seasonal_mean','Seasonal mean','m³/s'),('causal_discharge_seasonal_p90','Seasonal P90','m³/s'),('causal_discharge_seasonal_anomaly','Anomaly','m³/s'),('causal_discharge_seasonal_percentile','Percentile','%'),('causal_discharge_pulse','Pulse crossing','0 / 1'),('causal_days_since_discharge_pulse','Days since pulse','days'),('causal_reference_samples','Reference samples','days'),('causal_reference_years','Reference years','years')]
    fig,axs=plt.subplots(2,4,figsize=(18,11))
    for ax,(metric,label,unit) in zip(axs.flat,definitions):
        f=causal[(causal.date==day)&(causal.metric==metric)]
        panel(fig,ax,sites,dict(zip(f.river_id,f.value)),label,unit, {'causal_discharge_pulse':(0,1),'causal_discharge_seasonal_percentile':(0,100),'causal_reference_samples':(0,313),'causal_reference_years':(0,10)}.get(metric))
    fig.suptitle('Lagged discharge features • output 2023-08-01 • as-of provider day 2023-07-31',fontsize=16)
    fig.text(.5,.02,'Sources: retained USGS / WSC observations. Gauge points only; no marine interpolation. Event-date causality; operational availability unknown.',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.04,1,.96));fig.savefig(a.output/'causal-stations.png',dpi=130);plt.close(fig)
    t=pq.read_table(a.product/'station_temperature.parquet');meta=validate_table(t);df=t.to_pandas()
    sites=[(key,s['longitude'],s['latitude'],{'DFO-QUALARK':'Qualark','ECOLOGY-07A089':'Snohomish','ECOLOGY-10A040':'Puyallup','ECOLOGY-EIM-16A070':'Skokomish','ECOLOGY-EIM-18B070':'Elwha'}[key]) for key,s in meta['stations'].items()]
    fig,axs=plt.subplots(2,3,figsize=(14,12))
    for row,day in enumerate([date(2012,8,1),date(2024,8,1)]):
        for col,stat in enumerate(['daily_min','daily_mean','daily_max']):
            f=df[(df.date==day)&(df.statistic==stat)]
            panel(fig,axs[row,col],sites,dict(zip(f.station_id,f.value)),f'{day} • {stat.replace("daily_", "daily ")}', '°C',(0,25))
    fig.suptitle('Independent river temperature stations • sparse native-day observations',fontsize=16)
    fig.text(.5,.02,'Sources: DFO Environmental Watch / Washington Ecology. Ecology uses fixed PST; DFO day bounds unverified.\nGray = absent date/statistic, never zero. Site points only; no spatial interpolation. Elwha readings carry “Starting to pool”.',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.05,1,.96));fig.savefig(a.output/'temperature-stations.png',dpi=130);plt.close(fig)

if __name__=='__main__':main()

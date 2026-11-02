"""Plot retained retrospective and trailing gauge features without interpolation."""
import argparse,json
from datetime import date
from importlib.resources import files
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from example_maps import panel
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--product',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
registry=json.loads(files('hydrology').joinpath('data/registry.json').read_text())
sites=[(r['river_id'],*r['stations'][0]['geometry']['coordinates'],r['name']) for r in registry['rivers']]
f=pd.concat([pd.read_parquet(a.product/r['river_id']/'features.parquet') for r in registry['rivers']],ignore_index=True)
fig,axs=plt.subplots(2,3,figsize=(14,12));day=date(2023,8,1)
for ax,(metric,label,unit) in zip(axs.flat,[('discharge_mean_7d','Trailing 7-day discharge','m³/s'),('discharge_mean_30d','Trailing 30-day discharge','m³/s'),('discharge_change_7d','7-day discharge change','m³/s'),('low_flow_duration','Retrospective low-flow duration','days'),('high_flow_duration','Retrospective high-flow duration','days'),('days_since_flow_pulse','Retrospective days since pulse','days')]):
    g=f[(f.date==day)&(f.metric==metric)]
    panel(fig,ax,sites,dict(zip(g.river_id,g.value)),label,unit,(0,10) if metric=='high_flow_duration' else None)
fig.suptitle('Native gauge features • provider day 2023-08-01',fontsize=16)
fig.text(.5,.02,'Sources: retained USGS / WSC observations. Lower row uses full-history percentiles and two-sided gap interpolation.\nRetrospective research indicators; not causal predictors. Gauge points only; no marine interpolation. Gray = unavailable.',ha='center',fontsize=10)
fig.tight_layout(rect=(0,.05,1,.96));a.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.output,dpi=130)

"""Render retained H3 influence factors as supported subtotals, never physical flux."""
import argparse,json
from datetime import date
from pathlib import Path
import h3,numpy as np,pyarrow.parquet as pq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from hydrology.utils.influence import combine
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--product',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
t=pq.read_table(a.product/'influence.parquet');r=json.loads(t.schema.metadata[b'hydrology_influence'])['recipe'];f=t.to_pandas();day=date(2023,8,1)
s=f[(f.factor_type=='spatial')&(f.distance_profile=='broad')]
v=f[(f.factor_type=='temporal')&(f.lag_profile=='three-day')&(f.date==day)].set_index('river_id')
cells=r['cells'];values={k:[] for k in ['relative_flow','discharge']};coverage=[]
for cell in cells:
    w=s[s.h3_index==cell].set_index('river_id')
    for metric in values:
        result=combine(w.weight.to_numpy(),v.reindex(w.index)[metric].to_numpy());values[metric].append(result['value'])
    coverage.append(result['known_rivers'])
polygons=[[(lon,lat) for lat,lon in h3.cell_to_boundary(c)] for c in cells]
fig,axs=plt.subplots(1,3,figsize=(15,10))
for ax,(label,data,unit) in zip(axs,[('Relative flow influence',values['relative_flow'],'dimensionless weighted index'),('Discharge influence',values['discharge'],'m³/s-weighted index (not marine flux)'),('Route support',coverage,'known routes / 10 rivers')]):
    arr=np.array([np.nan if x is None else x for x in data]);coll=PolyCollection(polygons,array=arr,cmap='viridis',edgecolors='none');coll.cmap.set_bad('#d5d9df');ax.add_collection(coll);ax.autoscale();ax.set_aspect(1/.68);ax.set(xlabel='Longitude (°)',ylabel='Latitude (°)',title=label);ax.grid(alpha=.15);fig.colorbar(coll,ax=ax,shrink=.65,label=unit)
fig.suptitle('Retrospective river influence • native provider day 2023-08-01\nBroad 50 km decay • normalized 2/3/4-day lag • R6 reporting cells',fontsize=15)
fig.text(.5,.03,'Sources: retained USGS / WSC gauge discharge and Seascape R8 outlet relationships.\nSupported subtotals: unknown routes are excluded, never asserted zero. Gray = unavailable value.\nMinimum reachable R8-child distance; no current, plume, physical mouth-flux or whale-response calibration.',ha='center',fontsize=10)
fig.tight_layout(rect=(0,.1,1,.92));a.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.output,dpi=130)

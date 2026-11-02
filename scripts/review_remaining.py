"""Read-only installed-pipeline replay; intercept publication into isolated output."""
import argparse,json
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import patch
import pandas as pd
import pyarrow.parquet as pq
import pyarrow as pa
from hydrology.pipelines.publication import FEATURE_SCHEMA
from hydrology.utils.products import checksum
from hydrology.utils.features import build_features
from hydrology.utils.low_flow import replace_low_flow
from hydrology.utils.flow_pulse import replace_flow_pulse
from hydrology.utils.high_flow import replace_high_flow
from hydrology.pipelines import influence

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--product',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();a.product=a.product.resolve();a.output=a.output.resolve()
assert not a.output.is_relative_to(a.product)
a.output.mkdir(parents=True,exist_ok=True)
before={str(x.relative_to(a.product)):checksum(x) for x in a.product.rglob('*') if x.is_file()}
report={'feature_replay':{},'scope':'Read-only full retained-history feature calculations; influence publication intercepted, no transaction test'}
for folder in sorted(a.product.iterdir()):
    if not folder.is_dir():continue
    c=pd.read_parquet(folder/'conditions.parquet');old=pd.read_parquet(folder/'features.parquet')
    config=json.loads((folder/'manifest.json').read_text())['configuration']
    assert config['climatology'] is None
    warmup=pd.read_parquet(folder/'warmup.parquet')
    feature_input=pd.concat([warmup,c],ignore_index=True) if len(warmup) else c
    new=build_features(feature_input,low_threshold=config['low_flow_threshold'],pulse_threshold=config['pulse_threshold'])
    new=new.loc[pd.to_datetime(new.date).between(config['start_date'],config['end_date'])].copy()
    if config['low_flow_method']=='historical_percentile':new=replace_low_flow(new,c)
    if config['flow_pulse_method']=='historical_percentile':new=replace_flow_pulse(new,c)
    new=replace_high_flow(new,c)
    new['date']=pd.to_datetime(new.date).dt.date
    new=pa.Table.from_pandas(new,schema=FEATURE_SCHEMA,preserve_index=False).to_pandas()
    keys=['river_id','station_id','date','metric','temporal_basis']
    new=new.sort_values(keys).reset_index(drop=True);old=old.sort_values(keys).reset_index(drop=True)
    pd.testing.assert_frame_equal(new[old.columns],old,check_exact=True)
    new.to_parquet(a.output/(folder.name+'-features.parquet'),index=False)
    report['feature_replay'][folder.name]={'rows':len(new),'nulls':int(new.value.isna().sum()),'metrics':sorted(new.metric.unique()),'exact_row_parity':True}
    print(folder.name,len(new),flush=True)
old=pq.read_table(a.product/'influence.parquet');recipe=json.loads(old.schema.metadata[b'hydrology_influence'])['recipe']
report['input_bindings']={path:{'exists':Path(path).is_file(),'matches':Path(path).is_file() and checksum(Path(path))==sha} for path,sha in recipe['sources'].items()}
assert all(v['matches'] for v in report['input_bindings'].values()), 'Stored source binding changed; inspect report'
def write(path,table,check_sources):
    assert path.resolve()==a.product/'influence.parquet'
    check_sources()
    pd.testing.assert_frame_equal(table.to_pandas(),old.to_pandas(),check_exact=True)
    pq.write_table(table,a.output/'influence.parquet')
    return checksum(a.output/'influence.parquet')
def no_catalog_write(*args):raise AssertionError('Unexpected catalog mutation requested')
with patch.object(influence,'product_snapshot',lambda *args,**kwargs:nullcontext(a.product)),patch.object(influence,'write_influence',write),patch.object(influence,'atomic_json',no_catalog_write):
    result=influence.build_influence(a.config)
report['influence']={**result,'output':str(a.output/'influence.parquet'),'exact_row_parity':True,'recipe_runtime_identity_expected_to_differ':True}
after={str(x.relative_to(a.product)):checksum(x) for x in a.product.rglob('*') if x.is_file()}
assert before==after
report['original_product_unchanged']=True
report['strict_utc_h3_final_present']=(a.product/'final').exists()
report['delivered_inventory']={str(f.relative_to(a.product)):{'rows':pq.read_metadata(f).num_rows,'bytes':f.stat().st_size} for f in sorted(a.product.rglob('*.parquet'))}
(a.output/'remaining-review.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report['influence'],indent=2))

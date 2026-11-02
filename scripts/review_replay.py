"""Read-only replay of delivered causal features and five temperature stations.

Run with the installed hydrology package; source scripts are loaded explicitly.
No acquisition or publication. Output must be outside the delivered product.
"""
import argparse
from datetime import date
import importlib.util
import json
from pathlib import Path
import platform
import importlib.metadata
import pandas as pd
import pyarrow.parquet as pq
from hydrology.utils.causal import causal_features
from hydrology.utils.station_temperature import validate_table, make_table
from hydrology.utils.ecology_temperature import read_export
from hydrology.utils.eim_temperature import read_eim
from hydrology.utils.products import checksum


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compare(actual, expected, keys):
    actual = actual.sort_values(keys).reset_index(drop=True)
    expected = expected.sort_values(keys).reset_index(drop=True)
    assert not actual.duplicated(keys).any()
    pd.testing.assert_frame_equal(actual[expected.columns], expected, check_exact=True)
    return dict(rows=len(actual), null_values=int(actual.value.isna().sum()), exact_values=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--product', type=Path, required=True)
    p.add_argument('--sources', type=Path, required=True)
    p.add_argument('--scripts', type=Path, default=Path(__file__).parent)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    assert not a.output.resolve().is_relative_to(a.product.resolve())
    a.output.mkdir(parents=True, exist_ok=True)
    files = sorted(a.product.rglob('*'))
    before = {str(x.relative_to(a.product)): checksum(x) for x in files if x.is_file()}
    report = dict(scope='Retained-input replay; no source reacquisition or operational-vintage proof', python=platform.python_version(), packages={n: importlib.metadata.version(n) for n in ['marinecast-hydrology','pandas','numpy','pyarrow','pyproj']}, source_product_sha256=before)
    expected = pd.read_parquet(a.product/'causal.parquet')
    metadata = json.loads(pq.read_schema(a.product/'causal.parquet').metadata[b'hydrology_causal'])
    definition = metadata['definition']
    frames = []
    for river in sorted(expected.river_id.unique()):
        source = a.product/river/'conditions.parquet'
        assert checksum(source) == metadata['sources'][river]
        frame, method = causal_features(pd.read_parquet(source), window=definition['window_days'], min_samples=definition['min_samples'], min_years=definition['min_years'], history_years=definition['history_years'])
        assert method == definition
        frames.append(frame)
    replay = pd.concat(frames, ignore_index=True)
    report['causal'] = compare(replay, expected, ['river_id','station_id','date','metric','temporal_basis'])
    replay.to_parquet(a.output/'causal.parquet', index=False)
    report['causal']['metrics'] = {m:dict(rows=len(g),nonnull=int(g.value.count()),minimum=g.value.min(),maximum=g.value.max()) for m,g in replay.groupby('metric')}
    original = pq.read_table(a.product/'station_temperature.parquet')
    meta = validate_table(original)
    initial = load(a.scripts/'import_dfo_temperature_reports.py').import_reports(json.loads((a.sources/'import-ledger.json').read_text()), date(2026,10,25))
    historical = load(a.scripts/'extend_dfo_temperature_history.py')
    table = historical.extend_table(initial,json.loads((a.sources/'historical-probe/history-import-ledger.json').read_text()),date(2026,10,25))
    rows = table.to_pylist()
    for item in json.loads((a.sources/'ecology-2026-10-28/ledger.json').read_text()):
        assert checksum(Path(item['path'])) == item['sha256']
        added, station, evidence = read_export(item['path'], item['station_code'], item['retrieved_at'], completed_through=date(2026,10,27))
        rows.extend(added)
    for source in [a.sources/'ecology-2026-10-28/elwha-eim-5019205-source.json',a.sources/'skokomish-eim-01147-source.json']:
        record = json.loads(source.read_text())
        for f in record['files']:
            assert checksum(Path(record['folder'])/f['name']) == f['sha256']
        added, station, evidence = read_eim(record['folder'],record['source_url'],record['retrieved_at'])
        for key in ['latitude','longitude','coordinate_crs','day_definition']:
            assert station[key] == meta['stations'][station['station_id']][key]
        rows.extend(added)
    rebuilt = make_table(rows,meta['stations'],meta['provenance'])
    report['temperature'] = compare(rebuilt.to_pandas(), original.to_pandas(), ['station_id','date','statistic','temporal_basis'])
    pq.write_table(rebuilt,a.output/'station_temperature.parquet')
    report['temperature']['stations'] = {s:dict(rows=len(g),first=str(g.date.min()),last=str(g.date.max()),statistics=g.statistic.value_counts().to_dict()) for s,g in rebuilt.to_pandas().groupby('station_id')}
    after = {str(x.relative_to(a.product)):checksum(x) for x in files if x.is_file()}
    assert before == after
    report['original_product_unchanged'] = True
    (a.output/'review.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['source_product_sha256']},indent=2,default=str))

if __name__ == '__main__':
    main()

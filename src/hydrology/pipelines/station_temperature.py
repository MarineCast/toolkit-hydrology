"""Publish a qualified independent station companion under the canonical lock."""
import json
import os
from pathlib import Path
import pyarrow.parquet as pq
from ..utils.station_temperature import NAME, validate_table, catalog_with_station_temperature
from ..utils.io import atomic_json
from ..utils.products import checksum

def assert_preserved(old, new):
    """An expansion may add keys, but cannot revise or drop retained observations."""
    key=lambda r:(r['station_id'],r['date'],r['statistic'],r['temporal_basis'])
    incoming={key(r):r for r in new.to_pylist()}
    for row in old.to_pylist():
        if incoming.get(key(row))!=row: raise ValueError('Prior station observation changed or removed')
    old_meta=validate_table(old);new_meta=validate_table(new)
    for sid,station in old_meta['stations'].items():
        if new_meta['stations'].get(sid)!=station: raise ValueError('Prior station identity changed')

def publish_station_temperature(destination, table):
    from .publication import product_snapshot, _validate_snapshot, _paths
    validate_table(table)
    with product_snapshot(destination,exclusive=True) as root:
        catalog=_validate_snapshot(root)
        _,store,_=_paths(destination)
        target=root/NAME; candidate=store/'station-temperature-candidate.parquet'
        prior=store/'station-temperature-prior.parquet'
        backup=store/'station-temperature-prior-catalog.json'
        journal=store/'station-temperature-transaction.json'
        receipt=store/'station-temperature-receipt.json'
        if any(p.exists() for p in (candidate,prior,backup,journal,receipt)):
            raise ValueError('Prior station publication evidence exists; inspect before another publication')
        if target.exists(): assert_preserved(pq.read_table(target),table)
        before={str(p.relative_to(root)):checksum(p) for p in root.rglob('*') if p.is_file() and p.name not in ('catalog.json',NAME)}
        pq.write_table(table,candidate,compression='zstd')
        if candidate.stat().st_size>16*1024*1024: raise ValueError('16MiB station budget exceeded')
        if not pq.read_table(candidate).equals(table,check_metadata=True): raise ValueError('Readback mismatch')
        backup.write_bytes((root/'catalog.json').read_bytes())
        atomic_json(journal,dict(target=str(target),candidate=str(candidate),prior=str(prior),catalog_backup=str(backup),phase='promoting'))
        try:
            if target.exists(): os.replace(target,prior)
            os.replace(candidate,target)
            atomic_json(root/'catalog.json',catalog_with_station_temperature(catalog,root))
            _validate_snapshot(root)
            after={str(p.relative_to(root)):checksum(p) for p in root.rglob('*') if p.is_file() and p.name not in ('catalog.json',NAME)}
            if before!=after: raise ValueError('Non-target product changed')
        except BaseException:
            if target.exists(): os.replace(target,candidate)
            if prior.exists(): os.replace(prior,target)
            atomic_json(root/'catalog.json',catalog)
            atomic_json(journal,dict(phase='rolled_back',candidate=str(candidate)))
            os.replace(journal,store/'station-temperature-failed-receipt.json')
            raise
        atomic_json(journal,dict(phase='committed',sha256=checksum(target),rows=len(table),preserved_files=len(before)))
        os.replace(journal,receipt)
        return json.loads(receipt.read_text())

"""Bounded offline causal companion publication under the canonical writer lock."""
import json
import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..utils.causal import causal_features
from ..utils.io import atomic_json
from ..utils.products import checksum
from ..utils.provenance import runtime_fingerprint

from ..utils.causal import KEY, catalog_with_causal


def publish_causal(destination, **parameters):
    from .publication import product_snapshot, _validate_snapshot, _paths
    with product_snapshot(destination, exclusive=True) as root:
        catalog=_validate_snapshot(root)
        _,store,_=_paths(destination)
        candidate=store/"causal-candidate.parquet"
        if candidate.exists():
            raise ValueError("Prior candidate exists; inspect before retry")
        frames=[]; sources={}; support={}; civil={}
        for rid in sorted(catalog["rivers"]):
            source=root/rid/"conditions.parquet"
            conditions=pd.read_parquet(source)
            frame,definition=causal_features(conditions, **parameters)
            frames.append(frame); sources[rid]=checksum(source)
            support[rid]=frame.groupby("metric").value.count().to_dict()
            civil[rid]=sorted(conditions.day_definition.dropna().unique().tolist())
        frame=pd.concat(frames,ignore_index=True)
        if frame.duplicated(["river_id","station_id","date","metric","temporal_basis"]).any():
            raise ValueError("Duplicate causal keys")
        metadata=dict(definition=definition,sources=sources,support=support,day_definitions=civil,
            runtime=runtime_fingerprint(),implementation_sha256=checksum(Path(__file__).parents[1]/"utils"/"causal.py"))
        table=pa.Table.from_pandas(frame,preserve_index=False)
        table=table.replace_schema_metadata({**(table.schema.metadata or {}),KEY:json.dumps(metadata,sort_keys=True).encode()})
        pq.write_table(table,candidate,compression="zstd")
        pd.testing.assert_frame_equal(pq.read_table(candidate).to_pandas(),frame)
        if candidate.stat().st_size>32*1024*1024:
            raise ValueError("32 MiB candidate budget exceeded")
        # Preserve the small prior catalog/companion for rollback; no permanent deletion.
        backup=store/"causal-prior-catalog.json"
        if backup.exists():
            raise ValueError("Prior causal rollback catalog exists; inspect before retry")
        backup.write_bytes((root/"catalog.json").read_bytes())
        previous=root/"causal.parquet"
        prior=store/"causal-prior.parquet"
        if prior.exists():
            raise ValueError("Prior causal rollback product exists")
        if previous.exists():
            os.replace(previous,prior)
        try:
            os.replace(candidate,previous)
            atomic_json(root/"catalog.json",catalog_with_causal(catalog,root))
            _validate_snapshot(root)
        except BaseException:
            if previous.exists(): os.replace(previous,candidate)
            if prior.exists(): os.replace(prior,previous)
            atomic_json(root/"catalog.json",catalog)
            raise
        return metadata


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination")
    args=parser.parse_args()
    print(json.dumps(publish_causal(args.destination),indent=2))

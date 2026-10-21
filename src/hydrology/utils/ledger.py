"""Durable diagnostic checkpoints; resumption replays verified HTTP pages."""

import json
import threading
from pathlib import Path

from .io import atomic_json
from .provenance import digest


class Ledger:
    def __init__(self, config, rivers, blocks, metrics):
        identity = digest(
            {
                "rivers": rivers,
                "blocks": blocks,
                "metrics": metrics,
                "source": config.data_source,
                "hydat": config.hydat,
                "temporal_basis": config.temporal_requirement,
                "allow_provisional": config.allow_provisional,
                "max_hold_seconds": config.max_hold_seconds,
                "minimum_coverage": config.minimum_coverage,
            }
        )
        self.path = Path(config.cache) / "acquisition-ledgers" / f"{identity}.json"
        self.lock = threading.Lock()
        previous = json.loads(self.path.read_text()) if self.path.exists() else {}
        old = {e["key"]: e for e in previous.get("blocks", [])}
        self.entries = {}
        for river in rivers:
            for metric in ("metadata", *metrics):
                for start, end in [(None, None)] if metric == "metadata" else blocks:
                    key = digest([river["river_id"], metric, start, end])
                    self.entries[key] = {
                        "key": key,
                        "river_id": river["river_id"],
                        "station_id": river["stations"][0]["station_id"],
                        "metric": metric,
                        "start": start,
                        "end": end,
                        "state": "pending",
                        "previous_state": old.get(key, {}).get("state"),
                        "resume_policy": "replay verified HTTP cache; refresh explicitly reacquires",
                    }
        self.save()

    def save(self):
        atomic_json(
            self.path, {"schema_version": "1", "blocks": list(self.entries.values())}
        )

    def update(self, river, metric, start, end, state, **details):
        key = digest([river["river_id"], metric, start, end])
        with self.lock:
            self.entries[key].update(state=state, **details)
            self.save()

    def snapshot(self):
        return list(self.entries.values())

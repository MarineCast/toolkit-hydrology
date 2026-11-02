"""Native provider-daily access, shared by public discharge and temperature APIs."""

from ..utils.daily import calendar_conditions
from ..utils.registry import select_registry
from . import acquisition, processing


def read_native(config, metrics):
    observations, metadata, outcomes, network = acquisition.acquire(config, metrics)
    rivers = select_registry(config)
    selected = processing.river_conditions(observations, rivers, metadata, config)
    result = calendar_conditions(
        selected,
        observations,
        rivers,
        config,
        metrics,
        outcomes,
        network.get("block_ledger", []),
    )
    result = result.loc[result.metric.isin(metrics)]
    result = result.loc[result.date.between(config.start_date, config.end_date)].copy()
    result.attrs["outcomes"] = outcomes
    return result

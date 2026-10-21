"""Public Python entry points: resolve settings, then call the owning pipeline."""

from .pipelines.influence import build_influence as build_influence
from .pipelines.recompute import recompute_flow_pulse as recompute_flow_pulse
from .pipelines.recompute import recompute_high_flow as recompute_high_flow
from .pipelines.recompute import recompute_low_flow as recompute_low_flow
from .utils.config import Config


def _native(
    start_date, end_date, bbox, metrics, data_source="auto", config_path=None, **kwargs
):
    from .pipelines.native import read_native

    config = Config.load(
        config_path,
        start_date=start_date,
        end_date=end_date,
        bbox=bbox,
        data_source=data_source,
        **kwargs,
    )
    return read_native(config, metrics)


def get_river_discharge(
    start_date=None, end_date=None, bbox=None, data_source="auto", **kwargs
):
    return _native(
        start_date, end_date, bbox, ("discharge_mean",), data_source, **kwargs
    )


def get_river_temperature(
    start_date=None, end_date=None, bbox=None, data_source="auto", **kwargs
):
    return _native(
        start_date,
        end_date,
        bbox,
        ("temperature_mean", "temperature_max"),
        data_source,
        **kwargs,
    )


def get_river_context(bbox=None, make_h3=True, h3_res=6, config_path=None, **kwargs):
    from .utils.registry import select_registry
    from .utils.spatial import map_rivers

    config = Config.load(config_path, bbox=bbox, h3_res=h3_res, **kwargs)
    rivers = select_registry(config)
    return map_rivers(config, rivers) if make_h3 else rivers


def get_hydrology_features(
    start_date=None,
    end_date=None,
    bbox=None,
    h3_res=6,
    make_h3=False,
    config_path=None,
    **kwargs,
):
    from .pipelines.releases import build

    return build(
        Config.load(
            config_path,
            start_date=start_date,
            end_date=end_date,
            bbox=bbox,
            h3_res=h3_res,
            **kwargs,
        ),
        make_h3=make_h3,
    )


def publish_hydrology(config=None, *, metrics=("discharge_mean",), **kwargs):
    """Publish one current native per-river product; dates remain explicit in its manifests."""
    from .pipelines.publication import publish_rivers

    return publish_rivers(config or Config.load(**kwargs), metrics=metrics)

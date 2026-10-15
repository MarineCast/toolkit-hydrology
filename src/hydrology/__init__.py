"""MarineCast observed hydrology."""

from .core import Config


def _native(
    start_date, end_date, bbox, metrics, data_source="auto", config_path=None, **kwargs
):
    from .pipeline import acquire, river_conditions
    from .registry import select_registry

    config = Config.load(
        config_path,
        start_date=start_date,
        end_date=end_date,
        bbox=bbox,
        data_source=data_source,
        **kwargs,
    )
    obs, metadata, outcomes, _ = acquire(config, metrics)
    result = river_conditions(obs, select_registry(config), metadata, config)
    result = result.loc[result.date.between(config.start_date, config.end_date)].copy()
    result.attrs["outcomes"] = outcomes
    return result


def get_river_discharge(start_date, end_date, bbox=None, data_source="auto", **kwargs):
    return _native(
        start_date, end_date, bbox, ("discharge_mean",), data_source, **kwargs
    )


def get_river_temperature(
    start_date, end_date, bbox=None, data_source="auto", **kwargs
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
    from .registry import select_registry
    from .spatial import map_rivers

    config = Config.load(config_path, bbox=bbox, h3_res=h3_res, **kwargs)
    rivers = select_registry(config)
    return map_rivers(config, rivers) if make_h3 else rivers


def get_hydrology_features(
    start_date, end_date, bbox=None, h3_res=6, make_h3=False, config_path=None, **kwargs
):
    from .pipeline import build

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

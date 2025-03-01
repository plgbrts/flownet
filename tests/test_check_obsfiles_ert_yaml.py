import pathlib
from datetime import datetime, date
import collections

import numpy as np
import pandas as pd
import jinja2

from flownet.realization import Schedule
from flownet.ert import create_observation_file, resample_schedule_dates
from flownet.realization._simulation_keywords import WCONHIST, WCONINJH
from flownet.utils.observations import _read_ert_obs, _read_yaml_obs

_OBSERVATION_FILES = pathlib.Path("./tests/observation_files")
_PRODUCTION_DATA_FILE_NAME = pathlib.Path(_OBSERVATION_FILES / "ProductionData.csv")
_TRAINING_SET_FRACTION = 0.75

_MIN_ERROR = 10
_REL_ERROR = 0.05

_RESAMPLING = "M"

_TEMPLATE_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.PackageLoader("flownet", "templates"),
    undefined=jinja2.StrictUndefined,
)
_TEMPLATE_ENVIRONMENT.globals["isnan"] = np.isnan


def compare(ert_obs_dict: dict, yaml_obs_dict: dict) -> None:
    """This function compares if the given dictionaries: ert_obs_dict and yaml_obs_dict contain the same information.

    Args:
        ert_obs_dict: dictionary that contains the information in a ERT observation file
        yaml_obs_dict: dictionary that contains the information in a YAML observation file
    Returns:
        None: the function stops by assert functions if both dictionaries have different information.
    """
    yaml_obs: dict = {}
    for item in yaml_obs_dict:
        for list_item in yaml_obs_dict[item]:
            for lost_item in list_item["observations"]:
                if not list_item["key"] in yaml_obs:
                    yaml_obs[list_item["key"]] = [[], [], []]
                yaml_obs[list_item["key"]][0].append(lost_item["date"])
                yaml_obs[list_item["key"]][1].append(float(lost_item["value"]))
                yaml_obs[list_item["key"]][2].append(float(lost_item["error"]))
            assert yaml_obs[list_item["key"]][0] == ert_obs_dict[list_item["key"]][0]
            assert yaml_obs[list_item["key"]][1] == ert_obs_dict[list_item["key"]][1]
            assert yaml_obs[list_item["key"]][2] == ert_obs_dict[list_item["key"]][2]


def _create_schedule_from_data(
    df_production_data: pd.DataFrame, start_date: datetime.date
) -> Schedule:
    """This helper function creates a schedule object based on production data from a dataframe

    Args:
        df_production_data: dataframe containing production data
        start_date: starting date of the schedule
    Returns:
        schedule: created schedule object filled with provided production data
    """
    # Create schedule
    schedule = Schedule()

    # Feed schedule with production data
    for _, value in df_production_data.iterrows():
        if value["TYPE"] == "WI" and start_date and value["date"] >= start_date:
            schedule.append(
                WCONINJH(
                    date=value["date"],
                    well_name=value["WELL_NAME"],
                    inj_type="WATER",
                    status=value["WSTAT"],
                    rate=value["WWIR"],
                    total=value["WWIT"],
                    bhp=value["WBHP"],
                    thp=value["WTHP"],
                    inj_control_mode="RATE",
                )
            )
        elif value["TYPE"] == "GI" and start_date and value["date"] >= start_date:
            schedule.append(
                WCONINJH(
                    date=value["date"],
                    well_name=value["WELL_NAME"],
                    inj_type="GAS",
                    status=value["WSTAT"],
                    rate=value["WGIR"],
                    total=value["WGIT"],
                    bhp=value["WBHP"],
                    thp=value["WTHP"],
                    inj_control_mode="RATE",
                )
            )
        elif value["TYPE"] == "OP" and start_date and value["date"] >= start_date:
            schedule.append(
                WCONHIST(
                    date=value["date"],
                    well_name=value["WELL_NAME"],
                    status=value["WSTAT"],
                    prod_control_mode="RESV",
                    vfp_table="1*",
                    oil_rate=value["WOPR"],
                    water_rate=value["WWPR"],
                    gas_rate=value["WGPR"],
                    oil_total=value["WOPT"],
                    water_total=value["WWPT"],
                    gas_total=value["WGPT"],
                    bhp=value["WBHP"],
                    thp=value["WTHP"],
                )
            )

    return schedule


def test_resample_schedule_dates() -> None:
    """
    This function checks if the observation files (complete, training, and test) in ERT and YAML version are equal.

    Returns:
        Nothing
    """
    # Load production
    headers = [
        "date",
        "WOPR",
        "WGPR",
        "WWPR",
        "WOPT",
        "WGPT",
        "WWPT",
        "WBHP",
        "WTHP",
        "WGIR",
        "WWIR",
        "WGIT",
        "WWIT",
        "WSTAT",
        "WELL_NAME",
        "PHASE",
        "TYPE",
        "date",
    ]
    df_production_data: pd.DataFrame = pd.read_csv(
        _PRODUCTION_DATA_FILE_NAME, usecols=headers
    )

    df_production_data["date"] = pd.to_datetime(df_production_data["date"])

    start_date = date(2005, 10, 1)

    schedule = _create_schedule_from_data(df_production_data, start_date)

    days_original = [
        (d - start_date).days
        for d in resample_schedule_dates(schedule, resampling=None)
    ]
    days_monthly = [
        (d - start_date).days for d in resample_schedule_dates(schedule, resampling="M")
    ]
    days_quarterly = [
        (d - start_date).days for d in resample_schedule_dates(schedule, resampling="Q")
    ]
    days_yearly = [
        (d - start_date).days for d in resample_schedule_dates(schedule, resampling="A")
    ]

    assert (
        np.allclose(days_original[0:3], [31, 61, 62])
        and np.allclose(days_monthly[0:3], [31, 61, 92])
        and np.allclose(days_quarterly[0:3], [92, 182, 273])
        and np.allclose(days_yearly[0:3], [92])
    )


def test_check_obsfiles_ert_yaml() -> None:
    """
    This function checks if the observation files (complete, training, and test) in ERT and YAML version are equal.

    Returns:
        Nothing
    """

    # pylint: disable-msg=too-many-locals
    # pylint: disable-msg=too-many-statements
    # pylint: disable=maybe-no-member
    config = collections.namedtuple("configuration", "flownet")
    config.flownet = collections.namedtuple("flownet", "data_source")
    config.flownet.data_source = collections.namedtuple("data_source", "vectors")
    config.flownet.data_source.vectors = collections.namedtuple("vectors", "WTHP")
    config.flownet.data_source.vectors.WOPR = collections.namedtuple(
        "WOPR", "min_error"
    )
    config.flownet.data_source.vectors.WOPR.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WOPR.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WGPR = collections.namedtuple(
        "WGPR", "min_error"
    )
    config.flownet.data_source.vectors.WGPR.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WGPR.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WWPR = collections.namedtuple(
        "WWPR", "min_error"
    )
    config.flownet.data_source.vectors.WWPR.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WWPR.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WOPT = collections.namedtuple(
        "WOPT", "min_error"
    )
    config.flownet.data_source.vectors.WOPT.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WOPT.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WGPT = collections.namedtuple(
        "WGPT", "min_error"
    )
    config.flownet.data_source.vectors.WGPT.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WGPT.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WWPT = collections.namedtuple(
        "WWPT", "min_error"
    )
    config.flownet.data_source.vectors.WWPT.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WWPT.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WBHP = collections.namedtuple(
        "WBHP", "min_error"
    )
    config.flownet.data_source.vectors.WBHP.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WBHP.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WTHP = collections.namedtuple(
        "WTHP", "min_error"
    )
    config.flownet.data_source.vectors.WTHP.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WTHP.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WGIR = collections.namedtuple(
        "WGIR", "min_error"
    )
    config.flownet.data_source.vectors.WGIR.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WGIR.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WWIR = collections.namedtuple(
        "WWIR", "min_error"
    )
    config.flownet.data_source.vectors.WWIR.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WWIR.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WGIT = collections.namedtuple(
        "WGIT", "min_error"
    )
    config.flownet.data_source.vectors.WGIT.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WGIT.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WWIT = collections.namedtuple(
        "WWIT", "min_error"
    )
    config.flownet.data_source.vectors.WWIT.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WWIT.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WSPR = collections.namedtuple(
        "WSPR", "min_error"
    )
    config.flownet.data_source.vectors.WSPR.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WSPR.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WSPT = collections.namedtuple(
        "WSPT", "min_error"
    )
    config.flownet.data_source.vectors.WSPT.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WSPT.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WSIR = collections.namedtuple(
        "WSIR", "min_error"
    )
    config.flownet.data_source.vectors.WSIR.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WSIR.rel_error = _REL_ERROR

    config.flownet.data_source.vectors.WSIT = collections.namedtuple(
        "WSIT", "min_error"
    )
    config.flownet.data_source.vectors.WSIT.min_error = _MIN_ERROR
    config.flownet.data_source.vectors.WSIT.rel_error = _REL_ERROR

    config.flownet.data_source.resampling = _RESAMPLING

    # Load production
    headers = [
        "date",
        "WOPR",
        "WGPR",
        "WWPR",
        "WOPT",
        "WGPT",
        "WWPT",
        "WBHP",
        "WTHP",
        "WGIR",
        "WWIR",
        "WGIT",
        "WWIT",
        "WSTAT",
        "WELL_NAME",
        "PHASE",
        "TYPE",
        "date",
    ]
    df_production_data: pd.DataFrame = pd.read_csv(
        _PRODUCTION_DATA_FILE_NAME, usecols=headers
    )

    df_production_data["date"] = pd.to_datetime(df_production_data["date"])

    start_date = date(2005, 10, 1)

    schedule = _create_schedule_from_data(df_production_data, start_date)

    # Testing with resampling
    create_observation_file(
        schedule,
        _OBSERVATION_FILES / "observations.ertobs",
        config,
        _TRAINING_SET_FRACTION,
    )

    create_observation_file(
        schedule,
        _OBSERVATION_FILES / "observations.yamlobs",
        config,
        _TRAINING_SET_FRACTION,
        yaml=True,
    )

    dates_resampled = resample_schedule_dates(
        schedule, config.flownet.data_source.resampling
    )

    num_dates = len(dates_resampled)
    num_training_dates = round(num_dates * _TRAINING_SET_FRACTION)

    export_settings = [
        ["_complete", 0, num_dates],
        ["_training", 0, num_training_dates],
        ["_test", num_training_dates + 1, num_dates],
    ]

    file_root = pathlib.Path(_OBSERVATION_FILES / "observations")
    for setting in export_settings:
        ert_obs_file_name = f"{file_root}{setting[0]}.ertobs"
        yaml_obs_file_name = f"{file_root}{setting[0]}.yamlobs"
        # Comparing the complete observation data
        # Reading ERT file
        ert_obs = _read_ert_obs(ert_obs_file_name)
        # Reading YAML file
        parsed_yaml_file = _read_yaml_obs(yaml_obs_file_name)
        # Comparing observation data
        compare(ert_obs, parsed_yaml_file)

    # Testing without resampling
    config.flownet.data_source.resampling = None

    create_observation_file(
        schedule,
        _OBSERVATION_FILES / "observations.ertobs",
        config,
        _TRAINING_SET_FRACTION,
    )

    create_observation_file(
        schedule,
        _OBSERVATION_FILES / "observations.yamlobs",
        config,
        _TRAINING_SET_FRACTION,
        yaml=True,
    )

    dates_original = resample_schedule_dates(
        schedule, config.flownet.data_source.resampling
    )

    num_dates = len(dates_original)
    num_training_dates = round(num_dates * _TRAINING_SET_FRACTION)

    export_settings = [
        ["_complete", 0, num_dates],
        ["_training", 0, num_training_dates],
        ["_test", num_training_dates + 1, num_dates],
    ]

    file_root = pathlib.Path(_OBSERVATION_FILES / "observations")
    for setting in export_settings:
        ert_obs_file_name = f"{file_root}{setting[0]}.ertobs"
        yaml_obs_file_name = f"{file_root}{setting[0]}.yamlobs"
        # Comparing the complete observation data
        # Reading ERT file
        ert_obs = _read_ert_obs(ert_obs_file_name)
        # Reading YAML file
        parsed_yaml_file = _read_yaml_obs(yaml_obs_file_name)
        print(ert_obs)
        print(parsed_yaml_file)
        # Comparing observation data
        compare(ert_obs, parsed_yaml_file)

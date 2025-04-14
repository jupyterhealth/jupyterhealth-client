"""General utilties for jupyter_health"""

from __future__ import annotations

import base64
import json

import pandas as pd


def flatten_dict(d: dict | list, prefix: str = "") -> dict:
    """flatten a nested dictionary into

    adds nested keys to flat key names, so

    {
      "top": 1,
      "a": {"b": 5},
    }

    becomes

    {
      "top": 1,
      "a_b": 5,
    }
    """
    flat_dict = {}
    if isinstance(d, list):
        # treat list as dict with integer keys
        d = {i: item for i, item in enumerate(d)}
    for key, value in d.items():
        if prefix:
            key = f"{prefix}_{key}"

        if isinstance(value, (dict, list)):
            for sub_key, sub_value in flatten_dict(value, prefix=key).items():
                flat_dict[sub_key] = sub_value
        else:
            flat_dict[key] = value
    return flat_dict


def tidy_observation(observation: dict) -> dict:
    """
    Given an Observation from JupyterHealth (as returned by :meth:`.list_observations`),
    return a flat dictionary.

    Expands the base64 `valueAttachment` and
    reshapes data to a one-level dictionary,
    appropriate for `pandas.from_records`.
    Nested keys are joined with `_`, so::

        {"a": {"b": 5}}

    becomes::

        {"a_b": 5}

    any fields ending with 'date_time' are parsed as timestamps.
    To avoid problems with plotting libraries, all `date_time` fields are presented in UTC,
    and a separate `_date_time_local` field is the local timestamp in the observed timezone
    with timezone info removed.

    Example output::

        {
            "code": "omh:blood-glucose:4.0",
            "resourceType": "Observation",
            "id": 64914,
            "meta_lastUpdated": Timestamp("2025-03-12 16:00:50.952478+0000", tz="UTC"),
            "identifier_0_value": "u-u-i-d-4",
            "identifier_0_system": "https://commonhealth.org",
            "status": "final",
            "subject_reference": "Patient/46007",
            "code_coding_0_code": "omh:blood-glucose:4.0",
            "code_coding_0_system": "https://w3id.org/openmhealth",
            "uuid": "u-u-i-d-5",
            "modality": "self-reported",
            "schema_id_name": "blood-glucose",
            "schema_id_version": "3.1",
            "schema_id_namespace": "omh",
            "creation_date_time": Timestamp("2025-03-12 15:47:30.510000+0000", tz="UTC"),
            "external_datasheets_0_datasheet_type": "manufacturer",
            "external_datasheets_0_datasheet_reference": "Health Connect",
            "source_data_point_id": "u-u-i-d-6",
            "source_creation_date_time": Timestamp("2025-02-15 17:28:33.271000+0000", tz="UTC"),
            "blood_glucose_unit": "MGDL",
            "blood_glucose_value": 97,
            "effective_time_frame_date_time": Timestamp(
                "2025-02-15 17:28:33.271000+0000", tz="UTC"
            ),
            "temporal_relationship_to_meal": "unknown",
            "creation_date_time_local": Timestamp("2025-03-12 15:47:30.510000"),
            "source_creation_date_time_local": Timestamp("2025-02-15 17:28:33.271000"),
            "effective_time_frame_date_time_local": Timestamp("2025-02-15 17:28:33.271000"),
        }

    """
    id = observation["id"]
    attachment = observation["valueAttachment"]
    if "json" not in attachment["contentType"]:
        raise ValueError(
            f"Unrecognized contentType={attachment['contentType']} in observation {id}"
        )

    record = json.loads(base64.b64decode(attachment["data"]))

    if "body" in record:
        record_header = record.get("header", {})
        record_body = record["body"]
    else:
        # older format, not sure we need to deal with this
        record_header = {}
        record_body = record
    # resolve code
    # todo: handle more than one?
    coding = observation["code"]["coding"][0]
    data = {
        # deprecate 'resource_type', it's confusing with resourceType which is totally different
        "resource_type": coding["code"],
        "code": coding["code"],
    }
    top_level_dict = {
        key: value
        for key, value in observation.items()
        if key not in {"valueAttachment"}
    }
    data.update(flatten_dict(top_level_dict))
    # currently assumes header and body namespaces have no collisions
    # this seems to be true, though. Alternately, could add `header_` to header
    data.update(flatten_dict(record_header))
    data.update(flatten_dict(record_body))
    for key in list(data):
        if key.endswith("date_time"):
            timestamp = data[key]
            # vega-lite doesn't like timestamps with tz info, so must be utc or naive
            # data[_date_time] is the utc timestamp
            data[key] = pd.to_datetime(timestamp, utc=True)
            # data[_date_time_local] is local time for the measurement (without tz info)
            # used for e.g. time-of-day binning
            data[key + "_local"] = pd.to_datetime(timestamp).tz_localize(None)
    if "meta_lastUpdated" in data:
        data["meta_lastUpdated"] = pd.to_datetime(data["meta_lastUpdated"], utc=True)
    return data

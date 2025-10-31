"""JupyterHealth client implementation

wraps Exchange and FHIR APIs in convenience methods
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Generator
from enum import Enum
from typing import Any, Literal, cast, overload

import pandas as pd
import requests
from yarl import URL

from ._utils import tidy_observation

_ENV_URL_PLACEHOLDER = "$JHE_URL"
_EXCHANGE_URL = os.environ.get("JHE_URL", _ENV_URL_PLACEHOLDER)


class Code(Enum):
    """Enum of recognized coding values

    Can be used to filter Observations to on a given record type,
    e.g. with `list_observations`.
    """

    BLOOD_PRESSURE = "omh:blood-pressure:4.0"
    BLOOD_GLUCOSE = "omh:blood-glucose:4.0"
    HEART_RATE = "omh:heart-rate:2.0"


class RequestError(requests.HTTPError):
    """Subclass of request error that shows the actual error"""

    def __init__(self, requests_error: requests.HTTPError) -> None:
        """Wrap a requests HTTPError"""
        self.requests_error = requests_error

    def __str__(self) -> str:
        """Add the actual error, not just the generic HTTP status code"""
        response = self.requests_error.response
        chunks = [str(self.requests_error)]
        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type:
            detail = "(html error page)"
        else:
            try:
                # extract detail from JSON
                detail = response.json()["detail"]
            except Exception:
                # truncate so it doesn't get too long
                try:
                    detail = response.text[:1024]
                except Exception:
                    # encoding error?
                    detail = None
        if detail:
            chunks.append(detail)
        return "\n".join(chunks)


class JupyterHealthClient:
    """
    Client for JupyterHealth data Exchange
    """

    def __init__(
        self,
        url: str = _EXCHANGE_URL,
        *,
        token: str | None = None,
    ):
        """Construct a client for JupyterHealth  data exchange

        Credentials will be loaded from the environment and defaults.
        No arguments are required.

        By default, creates a client connected to the MVP application.
        """
        if url == _EXCHANGE_URL == _ENV_URL_PLACEHOLDER:
            raise ValueError("When $JHE_URL not defined, `url` argument is required")
        if token is None:
            token = os.environ.get("JHE_TOKEN", None)
            if token is None:
                token = os.environ.get("CHCS_TOKEN", None)
                warnings.warn(
                    "$CHCS_TOKEN env is deprecated, use $JHE_TOKEN",
                    DeprecationWarning,
                    stacklevel=2,
                )
        self._url = URL(url)
        self.session = requests.Session()
        self.session.headers = {"Authorization": f"Bearer {token}"}

    @overload
    def _api_request(
        self, path: str, *, return_response: Literal[True], **kwargs
    ) -> requests.Response: ...

    @overload
    def _api_request(
        self, path: str, *, method: str = "GET", check=True, fhir=False, **kwargs
    ) -> dict[str, Any] | None: ...

    def _api_request(
        self,
        path: str,
        *,
        method: str = "GET",
        check=True,
        return_response=False,
        fhir=False,
        **kwargs,
    ) -> dict[str, Any] | requests.Response | None:
        """Make an API request"""
        if "://" in path:
            # full url
            url = URL(path)
        else:
            if fhir:
                url = self._url / "fhir/r5"
            else:
                url = self._url / "api/v1"
            url = url / path
        r = self.session.request(method, str(url), **kwargs)
        if check:
            try:
                r.raise_for_status()
            except requests.HTTPError as e:
                raise RequestError(e) from None
        if return_response:
            return r
        if r.content:
            return r.json()
        else:
            # return None for empty response body
            return None

    def _list_api_request(self, path: str, **kwargs) -> Generator[dict[str, Any]]:
        """Get a list from an /api/v1 endpoint"""
        r: dict = self._api_request(path, **kwargs)
        yield from r["results"]
        # TODO: handle pagination fields

    def _fhir_list_api_request(
        self, path: str, *, limit=None, **kwargs
    ) -> Generator[dict[str, Any]]:
        """Get a list from a fhir endpoint"""
        r: dict = self._api_request(path, fhir=True, **kwargs)

        records = 0
        requests = 0
        seen_ids = set()

        while True:
            new_records = False
            requests += 1
            for entry in r:
                # entry seems to always be a dict with one key?
                if isinstance(entry, dict) and len(entry) == 1:
                    # return entry['resource'] which is ~always the only thing
                    # in the list
                    entry = list(entry.values())[0]
                if entry["id"] in seen_ids:
                    # FIXME: skip duplicate records
                    # returned by server-side pagination bugs
                    continue
                new_records = True
                seen_ids.add(entry["id"])

                yield entry
                records += 1
                if limit and records >= limit:
                    return

            # paginated request
            next_url = None
            for link in r.get("link") or []:
                if link["relation"] == "next":
                    next_url = link["url"]
            # only proceed to the next page if this page is empty
            if next_url and new_records:
                kwargs.pop("params", None)
                r = self._api_request(next_url, **kwargs)
            else:
                break

    def get_user(self) -> dict[str, Any]:
        """Get the current user.

        Example::

            {'id': 10001,
             'email': 'user@example.edu',
             'firstName': 'User',
             'lastName': 'Name',
             'patient': None}
        """
        user = cast(dict[str, Any], self._api_request("users/profile"))
        return user

    def get_patient(self, id: int) -> dict[str, Any]:
        """Get a single patient by id.

        Example::

            {'id': 45439,
             'jheUserId': 19259,
             'identifier': 'some-external-id',
             'nameFamily': 'Williams',
             'nameGiven': 'Heather',
             'birthDate': '1967-12-09',
             'telecomPhone': None,
             'telecomEmail': 'heather.williams@example.edu',
             'organizationId': 20026,
             'birthdate': datetime.date(1989, 7, 3)}
        """
        patient = cast(dict[str, Any], self._api_request(f"patients/{id}"))
        return patient

    def get_patient_by_external_id(self, external_id: str) -> dict[str, Any]:
        """Get a single patient by external id.

        For looking up the JHE Patient record by an external (e.g. EHR) patient id.
        """

        # TODO: this should be a single lookup, but no API in JHE yet
        for patient in self.list_patients():
            if patient["identifier"] == external_id:
                return patient
        raise KeyError(f"No patient found with external identifier: {external_id!r}")

    def list_patients(self) -> Generator[dict[str, dict[str, Any]]]:
        """Iterate over all patients.

        Patient ids are the keys that may be passed to e.g. :meth:`list_observations`.
        """
        yield from self._list_api_request("patients")

    def get_patient_consents(self, patient_id: int) -> dict[str, Any]:
        """Return patient consent status.

        Example::

            {
                "patient": {
                    "id": 48098,
                    "jheUserId": 17823,
                    "identifier": "some-external-id",
                    "nameFamily": "Dorsey",
                    "nameGiven": "Brittany",
                    "birthDate": "1967-12-09",
                    "telecomPhone": None,
                    "telecomEmail": "brittany.dorsey@example.edu",
                    "organizationId": 20026,
                    "birthdate": datetime.date(1977, 2, 8),
                },
                "consolidatedConsentedScopes": [
                    {
                        "id": 50002,
                        "codingSystem": "https://w3id.org/openmhealth",
                        "codingCode": "omh:blood-pressure:4.0",
                        "text": "Blood pressure",
                    },
                    {
                        "id": 50005,
                        "codingSystem": "https://w3id.org/openmhealth",
                        "codingCode": "omh:heart-rate:2.0",
                        "text": "Heart Rate",
                    },
                ],
                "studiesPendingConsent": [],
                "studies": [
                    {
                        "id": 30013,
                        "name": "iHealth Blood Pressure Study",
                        "description": "Blood Pressure Study using data from iHealth cuff",
                        "organization": {"id": 20026, "name": "BIDS - URAP", "type": "edu"},
                        "dataSources": [
                            {
                                "id": 70001,
                                "name": "iHealth",
                                "type": "personal_device",
                                "supportedScopes": [],
                            }
                        ],
                        "scopeConsents": [
                            {
                                "code": {
                                    "id": 50002,
                                    "codingSystem": "https://w3id.org/openmhealth",
                                    "codingCode": "omh:blood-pressure:4.0",
                                    "text": "Blood pressure",
                                },
                                "consented": True,
                                "consentedTime": "2025-03-12T16:48:56.342402Z",
                            },
                            {
                                "code": {
                                    "id": 50005,
                                    "codingSystem": "https://w3id.org/openmhealth",
                                    "codingCode": "omh:heart-rate:2.0",
                                    "text": "Heart Rate",
                                },
                                "consented": True,
                                "consentedTime": "2025-03-12T16:48:56.342402Z",
                            },
                        ],
                    }
                ],
            }
        """

        consents = cast(
            dict[str, Any], self._api_request(f"patients/{patient_id}/consents")
        )
        return consents

    def get_study(self, id: int) -> dict[str, Any]:
        """Get a single study by id.

        Example::

            {'id': 30001,
             'name': 'iHealth Blood Pressure Study',
             'description': 'Blood Pressure Study using data from iHealth cuff',
             'organization': {'id': 20002, 'name': 'Sample Org', 'type': 'edu'}}
        """
        return cast(dict[str, Any], self._api_request(f"studies/{id}"))

    def list_studies(self) -> Generator[dict[str, dict[str, Any]]]:
        """Iterate over studies.

        Only returns studies I have access to (i.e. owned by my organization(s)).
        """
        return self._list_api_request("studies")

    def get_organization(self, id: int) -> dict[str, Any]:
        """Get a single organization by id.

        The ROOT organization has `id=0`.

        Example::

            # A top-level organization:
            {'id': 20011,
             'name': 'UC Berkeley',
             'type': 'edu',
             'partOf': 0}

            # BIDS is part of UC Berkeley
            {'id': 20013,
             'name': 'Berkeley Institute for Data Science (BIDS)',
             'type': 'edu',
             'partOf': 20011}
        """
        return cast(dict[str, Any], self._api_request(f"organizations/{id}"))

    def list_organizations(self) -> Generator[dict[str, dict[str, Any]]]:
        """Iterate over all organizations.

        Includes all organizations, including those of which I am not a member.
        The ROOT organization has `id=0`.
        """
        return self._list_api_request("organizations")

    def list_observations(
        self,
        patient_id: int | None = None,
        study_id: int | None = None,
        code: Code | str | None = None,
        limit: int | None = 2000,
    ) -> Generator[dict]:
        """Fetch observations for given patient and/or study.

        At least one of patient_id and study_id is required.

        code is optional, and can be selected from enum :class:`jupyterhealth_client.Code`.

        An observation contains a `valueAttachment` field, which is a base64-encoded JSON record
        of the actual measurement.

        Observations can be tidied to a dataframe-friendly flat dictionary with :func:`tidy_observation`.

        Example::

            {
                "resourceType": "Observation",
                "id": "63602",
                "meta": {"lastUpdated": "2025-03-12T16:00:50.952478+00:00"},
                "identifier": [
                    {
                        "value": "u-u-i-d",
                        "system": "https://commonhealth.org",
                    }
                ],
                "status": "final",
                "subject": {"reference": "Patient/43373"},
                "code": {
                    "coding": [
                        {
                            "code": "omh:blood-glucose:4.0",
                            "system": "https://w3id.org/openmhealth",
                        }
                    ]
                },
                "valueAttachment": {"data": "eyJib...==\\n", "contentType": "application/json"},
            }

        Example of an unpacked `valueAttachment`::

            {
                "body": {
                    "blood_glucose": {"unit": "MGDL", "value": 109},
                    "effective_time_frame": {"date_time": "2025-02-15T17:28:33.271Z"},
                    "temporal_relationship_to_meal": "unknown",
                },
                "header": {
                    "uuid": "u-u-i-d-2",
                    "modality": "self-reported",
                    "schema_id": {"name": "blood-glucose", "version": "3.1", "namespace": "omh"},
                    "creation_date_time": "2025-03-12T15:47:30.510Z",
                    "external_datasheets": [
                        {"datasheet_type": "manufacturer", "datasheet_reference": "Health Connect"}
                    ],
                    "source_data_point_id": "u-u-i-d-3",
                    "source_creation_date_time": "2025-02-15T17:28:33.271Z",
                },
            }
        """
        if not patient_id and not study_id:
            raise ValueError("Must specify at least one of patient_id or study_id")
        params: dict[str, str | int] = {}
        if study_id:
            params["_has:Group:member:_id"] = study_id
        if patient_id:
            params["patient"] = patient_id
        if code:
            if isinstance(code, Code):
                code = code.value
            if code is None or "|" not in code:
                # no code system specified, default to openmhealth
                code = f"https://w3id.org/openmhealth|{code}"
            params["code"] = code
        yield from self._fhir_list_api_request(
            "Observation", params=params, limit=limit
        )

    def list_observations_df(
        self,
        patient_id: int | None = None,
        study_id: int | None = None,
        code: Code | None = None,
        limit: int | None = 2000,
    ) -> pd.DataFrame:
        """Wrapper around list_observations, returns a DataFrame.

        Observations are passed through `tidy_observation` to create a flat dictionary.

        Key columns tend to be:

        - `effective_time_frame_date_time`
        - `{measurement_type}_value` (e.g. `systolic_blood_pressure_value`)
        - `subject_reference` e.g. `Patient/1234` identifies the patient (for multi-patient queries)
        - `code_coding_0_code` specifies the coding (e.g. the enums in {class}`Code`)
        """
        observations = self.list_observations(
            patient_id=patient_id,
            study_id=study_id,
            code=code,
            limit=limit,
        )
        records = [tidy_observation(obs) for obs in observations]
        return pd.DataFrame.from_records(records)


class JupyterHealthCHClient(JupyterHealthClient):
    """Deprecated name for JupyterHealthClient"""

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "JupyterHealthCHClient is deprecated. Use JupyterHealthClient",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)

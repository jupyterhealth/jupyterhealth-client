import os
from importlib import reload
from unittest import mock

import numpy as np
import pytest
import requests

import jupyterhealth_client
from jupyterhealth_client import JupyterHealthClient


def test_client_constructor():
    client = JupyterHealthClient(url="https://jhe.example.org", token="abc")
    assert client.session.headers == {"Authorization": "Bearer abc"}
    assert str(client._url) == "https://jhe.example.org"
    with mock.patch.dict(
        os.environ, {"JHE_TOKEN": "xyz", "JHE_URL": "https://from.env"}
    ):
        _client = reload(jupyterhealth_client._client)
        assert _client._EXCHANGE_URL == "https://from.env"
        client = _client.JupyterHealthClient()
    assert client.session.headers == {"Authorization": "Bearer xyz"}
    assert str(client._url) == "https://from.env"


# TODO: really test the client, but we need mock responses first
def test_get_user(jh_client):
    user = jh_client.get_user()
    assert type(user) is dict
    assert user["id"] == 10008


def test_get_organization(jh_client):
    org = jh_client.get_organization(20013)
    assert org["id"] == 20013
    assert org["name"] == "Department"
    with pytest.raises(requests.HTTPError) as exc:
        org = jh_client.get_organization(404)
    assert exc.value.requests_error.response.status_code == 404


def test_list_organizations(jh_client):
    orgs = list(jh_client.list_organizations())
    assert len(orgs) == 4
    assert orgs[0]["id"] == 20013
    assert orgs[0]["name"] == "Department"


def test_get_study(jh_client):
    study = jh_client.get_study(30001)
    assert study["id"] == 30001
    assert study["name"] == "ACME Health CGM Study"
    assert study["organization"]["id"] == 20013
    with pytest.raises(requests.HTTPError) as exc:
        jh_client.get_study(404)
    assert exc.value.requests_error.response.status_code == 404
    str(exc.value)


def test_list_studies(jh_client):
    studies = list(jh_client.list_studies())
    assert len(studies) == 2
    assert studies[0]["id"] == 30001
    assert studies[1]["id"] == 30012

    studies = list(jh_client.list_studies(organization_id=20013))
    assert len(studies) == 1
    assert studies[0]["id"] == 30001

    studies = list(jh_client.list_studies(organization_id=404))
    assert len(studies) == 0


def test_get_patient(jh_client):
    patient = jh_client.get_patient(40001)
    assert patient["id"] == 40001
    with pytest.raises(requests.HTTPError) as exc:
        jh_client.get_patient(404)

    assert exc.value.requests_error.response.status_code == 404
    # test exception rendering
    strerror = str(exc.value)
    assert "No patient matches" in strerror
    assert "404" in strerror


def test_lookup_patient(jh_client):
    patient = jh_client.lookup_patient(email="demouser@jupyterhealth.example.org")
    assert patient["id"] == 40001
    with pytest.raises(KeyError):
        patient = jh_client.lookup_patient(email="nosuchuser@jupyterhealth.example.org")
    patient = jh_client.lookup_patient(external_id="demouser-min")
    assert patient["id"] == 40001
    with pytest.raises(KeyError):
        patient = jh_client.lookup_patient(external_id="nomatch")
    with pytest.raises(TypeError):
        jh_client.lookup_patient()


def test_list_data_sources(jh_client):
    data_sources = list(jh_client.list_data_sources())
    assert len(data_sources) == 2


def test_list_observations(jh_client):
    jh_client._default_page_size = 2
    observations = list(jh_client.list_observations(patient_id=40018))
    assert len(observations) == 3


def test_list_observations_df(jh_client):
    jh_client._default_page_size = 2
    df = jh_client.list_observations_df(patient_id=40018)
    assert len(df) == 3
    assert "code" in df.columns
    assert set(df.code.unique()) == {"omh:heart-rate:2.0"}
    assert "heart_rate_value" in df.columns
    assert df.heart_rate_value.dtype == np.float64
    assert "effective_time_frame_date_time" in df.columns
    assert df.effective_time_frame_date_time.dt.hour.all()
    assert "source_creation_date_time_local" in df.columns
    assert df.source_creation_date_time_local.dt.hour.all()

import os
from importlib import reload
from unittest import mock

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

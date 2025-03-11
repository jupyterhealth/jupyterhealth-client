import os
from unittest import mock

from jupyterhealth_client import JupyterHealthClient


def test_client_constructor():
    client = JupyterHealthClient(token="abc")
    assert client.session.headers == {"Authorization": "Bearer abc"}
    with mock.patch.dict(os.environ, {"JHE_TOKEN": "xyz"}):
        client = JupyterHealthClient()
    assert client.session.headers == {"Authorization": "Bearer xyz"}


# TODO: really test the client, but we need mock responses first

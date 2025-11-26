from pathlib import Path

import pytest
import yaml
from responses import RequestsMock

from jupyterhealth_client import JupyterHealthClient

HOST = "https://jhe.local"

# load mocked responses from a file
_response_yaml = Path(__file__).parent / "responses.yaml"
with _response_yaml.open() as f:
    response_list = yaml.safe_load(f)

for response in response_list:
    response.setdefault("method", "GET")
    response.setdefault("status", 200)
    if "://" not in response["url"]:
        assert response["url"].startswith("/")
        response["url"] = HOST + response["url"]


@pytest.fixture
def responses():
    with RequestsMock(assert_all_requests_are_fired=False) as responses:
        for response in response_list:
            responses.add(**response)
        yield responses


@pytest.fixture
def jh_client(responses):
    return JupyterHealthClient(url=HOST, token="abc123")

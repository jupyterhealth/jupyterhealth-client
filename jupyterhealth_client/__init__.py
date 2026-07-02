"""
client library for JupyterHealth Exchange
"""

__version__ = "0.3.1.dev"

from ._client import Code, JupyterHealthClient, RequestError
from ._utils import tidy_observation

__all__ = [
    "JupyterHealthClient",
    "Code",
    "RequestError",
    "tidy_observation",
]

# jupyterhealth-client documentation

A Python client library for the JupyterHealth exchange.

Install:

```
pip install jupyterhealth-client
```

Use:

```python
from jupyterhealth_client import JupyterHealthClient, Code

client = JupyterHealthClient()
df = client.list_observations_df(patient_id=1001, code=Code.BLOOD_GLUCOSE)
df.head()
```

Default values for Client constructor arguments are loaded from the environment, if defined.
So if no argument is specified, the following are equivalent:

```python
import os

client = JupyterHealthClient()
client = JupyterHealthClient(url=os.environ["JHE_URL"], token=os.environ["JHE_TOKEN"])
```

But you can specify `url` and/or `token` if they don't come from the environment.

For more information, see [examples](https://jupyterhealth.org/software-documentation/)

```{eval-rst}
.. toctree::
   :maxdepth: 2
   :caption: Contents:

   getting-started
   api
```

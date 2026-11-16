# Local evaluation environment

The source is based on jsonschema 4.26.0 and uses Python 3.11 on Linux ARM64.
Runtime, build and local test dependencies are pinned in requirements-cc-solo.txt.
All rule registries used by this evaluation are supplied in memory. No external
schema server, account or data service is required.

```bash
curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/jsonschema-get-pip.py
python3 /tmp/jsonschema-get-pip.py --user --break-system-packages pip==24.3.1
python3 -m pip install --user --break-system-packages -r requirements-cc-solo.txt
SETUPTOOLS_SCM_PRETEND_VERSION_FOR_JSONSCHEMA=4.26.0 python3 -m pip install --user --break-system-packages --no-build-isolation --no-deps -e .
python3 -m pytest -q jsonschema/tests/test_validators.py jsonschema/tests/test_utils.py jsonschema/tests/test_exceptions.py jsonschema/tests/test_types.py
```

The explicit build version is needed because each task starts from a shallow
snapshot without upstream tags. It does not change the validator's behavior.
Select additional relevant local tests for your changes. Some optional format
checks have additional extras, and remote integration services are not provided;
retain their actual status instead of reporting them as tested.

import pytest

from rulelib import load_sources


@pytest.fixture(scope="session")
def source_bundle():
    return load_sources()

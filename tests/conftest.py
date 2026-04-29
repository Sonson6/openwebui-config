import sys
from pathlib import Path

import pytest

# Allow `import client` from tests
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import client as _client


@pytest.fixture(scope="session")
def api():
    """Authenticated API client pointed at the active environment's instance."""
    return _client

"""Shared pytest fixtures.

Both `langsmith` and `deepeval` register pytest plugins (auto-discovered via
the `pytest11` entry point) that call `load_dotenv()` as an import-time side
effect -- this loads the *entire* `.env` file into the real process
environment, not just their own settings. `Settings(_env_file=None)`, used
throughout the test suite to build a "clean" config, only skips reading the
`.env` *file* per-instance; it was never meant to (and can't) shield a test
from real values already sitting in `os.environ`. Once real Azure Speech and
LangSmith values landed in `.env` this session, tests asserting "nothing
configured" against a bare `Settings(_env_file=None)` started intermittently
seeing those real values and failing -- not a code bug, a test-isolation gap.

This autouse fixture strips every env var that maps to a `Settings` field
before each test and restores the originals after, so `Settings(_env_file=
None)` reliably means "no external configuration" regardless of what a
plugin loaded into the real environment or what's actually in `.env`.
"""
import pytest

from backend.config import Settings


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="run tests that hit the live VNDB API")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: hits the live VNDB API (run with --live)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="live API test; use --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)

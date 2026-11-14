"""Run the full test suite and exit with pytest's exit code."""

from __future__ import annotations

import sys

import pytest

if __name__ == "__main__":
    sys.exit(pytest.main(["tests"]))

#!/usr/bin/env python3
"""Reuse upstream's zero-argument run-state tests through stdlib unittest.

No upstream test source is modified. Other pytest suites are not run here.
"""
from pathlib import Path
import inspect
import runpy
import sys
import unittest

root = Path(__file__).resolve().parents[1]
source = root / "vendor/aris/tests/test_run_state.py"
scope = runpy.run_path(str(source))
suite = unittest.TestSuite()
for name, function in sorted(scope.items()):
    if name.startswith("test_") and callable(function):
        if inspect.signature(function).parameters:
            raise SystemExit(f"Upstream test now needs fixtures: {name}; review adapter")
        suite.addTest(unittest.FunctionTestCase(function, description=name))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)

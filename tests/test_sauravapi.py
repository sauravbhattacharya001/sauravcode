#!/usr/bin/env python3
"""Tests for sauravapi.py — REST API server for sauravcode functions."""

import json
import os
import sys
import unittest
from unittest.mock import patch
from io import BytesIO

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sauravapi import load_srv, _serialise, list_endpoints


class TestLoadSrv(unittest.TestCase):
    """Test loading .srv files and extracting functions."""

    def setUp(self):
        self.demo = os.path.join(_ROOT, "demos", "api_demo.srv")

    def test_load_functions(self):
        interp = load_srv(self.demo)
        self.assertIn("add", interp.functions)
        self.assertIn("multiply", interp.functions)
        self.assertIn("greet", interp.functions)
        self.assertIn("_helper", interp.functions)

    def test_function_params(self):
        interp = load_srv(self.demo)
        self.assertEqual(list(interp.functions["add"].params), ["x", "y"])
        self.assertEqual(list(interp.functions["greet"].params), ["name"])

    def test_private_functions_loaded(self):
        interp = load_srv(self.demo)
        # _helper should exist but won't be exposed as endpoint
        self.assertIn("_helper", interp.functions)


class TestSerialise(unittest.TestCase):
    """Test the _serialise helper."""

    def test_none(self):
        self.assertIsNone(_serialise(None))

    def test_int(self):
        self.assertEqual(_serialise(42), 42)

    def test_float_whole(self):
        self.assertEqual(_serialise(5.0), 5)

    def test_float_decimal(self):
        self.assertEqual(_serialise(3.14), 3.14)

    def test_string(self):
        self.assertEqual(_serialise("hello"), "hello")

    def test_bool(self):
        self.assertTrue(_serialise(True))
        self.assertFalse(_serialise(False))

    def test_list(self):
        self.assertEqual(_serialise([1, 2.0, "a"]), [1, 2, "a"])

    def test_dict(self):
        self.assertEqual(_serialise({"a": 1.0}), {"a": 1})

    def test_unknown_type(self):
        # Should stringify unknown objects
        result = _serialise(object())
        self.assertIsInstance(result, str)


class TestListEndpoints(unittest.TestCase):
    """Test the --list mode."""

    def test_list_output(self):
        demo = os.path.join(_ROOT, "demos", "api_demo.srv")
        import io
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            list_endpoints(demo)
        output = buf.getvalue()
        self.assertIn("/add", output)
        self.assertIn("/greet", output)
        self.assertNotIn("/_helper", output)


if __name__ == "__main__":
    unittest.main()

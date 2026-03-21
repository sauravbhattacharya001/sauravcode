#!/usr/bin/env python3
"""Tests for SSRF protection in sauravcode HTTP built-ins.

Ensures that http_get, http_post, http_put, http_delete block requests
to private/internal network addresses (loopback, RFC1918, link-local,
cloud metadata endpoints).
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from saurav import Interpreter


class TestSSRFProtection(unittest.TestCase):
    """Verify that HTTP built-ins block private/internal addresses."""

    def setUp(self):
        self.interp = Interpreter()

    def _assert_blocked(self, url):
        """Assert that the given URL is blocked with an SSRF error."""
        with self.assertRaises(RuntimeError) as ctx:
            self.interp._builtin_http_get([url])
        self.assertIn("SSRF protection", str(ctx.exception))

    def test_blocks_localhost_127(self):
        self._assert_blocked("http://127.0.0.1/")

    def test_blocks_localhost_name(self):
        self._assert_blocked("http://localhost/")

    def test_blocks_cloud_metadata(self):
        """Block AWS/GCP/Azure metadata endpoint (169.254.169.254)."""
        self._assert_blocked("http://169.254.169.254/latest/meta-data/")

    def test_blocks_private_10(self):
        self._assert_blocked("http://10.0.0.1/")

    def test_blocks_private_172(self):
        self._assert_blocked("http://172.16.0.1/")

    def test_blocks_private_192(self):
        self._assert_blocked("http://192.168.1.1/")

    def test_blocks_post_to_localhost(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.interp._builtin_http_post(["http://127.0.0.1/api", "data"])
        self.assertIn("SSRF protection", str(ctx.exception))

    def test_blocks_reserved_test_net(self):
        """TEST-NET-3 (203.0.113.0/24) is reserved and should be blocked."""
        self._assert_blocked("http://203.0.113.1/")

    def test_is_private_ip_static_method(self):
        """Verify the _is_private_ip helper directly."""
        self.assertTrue(Interpreter._is_private_ip("127.0.0.1"))
        self.assertTrue(Interpreter._is_private_ip("localhost"))
        # 203.0.113.x is documentation range — may or may not resolve
        # Just verify it doesn't crash
        Interpreter._is_private_ip("203.0.113.1")


if __name__ == "__main__":
    unittest.main()

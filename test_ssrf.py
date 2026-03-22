"""Tests for SSRF protection in http builtins."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import Interpreter


class TestSSRFProtection:
    """Verify that _http_request blocks private/internal IPs."""

    def setup_method(self):
        self.interp = Interpreter()

    def test_blocks_localhost(self):
        assert self.interp._is_private_ip("127.0.0.1") is True

    def test_blocks_private_10(self):
        assert self.interp._is_private_ip("10.0.0.1") is True

    def test_blocks_private_192(self):
        assert self.interp._is_private_ip("192.168.1.1") is True

    def test_blocks_private_172(self):
        assert self.interp._is_private_ip("172.16.0.1") is True

    def test_allows_public(self):
        assert self.interp._is_private_ip("8.8.8.8") is False

    def test_blocks_ipv6_loopback(self):
        assert self.interp._is_private_ip("::1") is True

    def test_http_get_blocks_localhost(self):
        with pytest.raises(RuntimeError, match="SSRF protection"):
            self.interp._http_request("GET", "http://127.0.0.1/admin")

    def test_http_get_blocks_internal(self):
        with pytest.raises(RuntimeError, match="SSRF protection"):
            self.interp._http_request("GET", "http://192.168.1.1/")

    def test_http_post_blocks_internal(self):
        with pytest.raises(RuntimeError, match="SSRF protection"):
            self.interp._http_request("POST", "http://10.0.0.1/api", body='{"key":"val"}')

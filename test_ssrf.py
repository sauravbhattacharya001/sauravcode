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

    def test_http_request_pins_resolved_ip(self):
        """Verify that _http_request resolves and pins the IP, preventing
        DNS rebinding where a second resolution could return a different address."""
        import unittest.mock as mock
        import socket

        # Simulate DNS rebinding: first call returns public IP, second returns loopback.
        # With the fix, only one resolution happens and the IP is pinned for the request.
        call_count = [0]
        real_getaddrinfo = socket.getaddrinfo

        def rebinding_getaddrinfo(host, port, *args, **kwargs):
            if host == "rebind.attacker.example":
                call_count[0] += 1
                if call_count[0] == 1:
                    # First resolution: looks safe (public IP)
                    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 0))]
                else:
                    # Second resolution: rebinds to loopback
                    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 0))]
            return real_getaddrinfo(host, port, *args, **kwargs)

        with mock.patch('socket.getaddrinfo', side_effect=rebinding_getaddrinfo):
            # The request should use the pinned IP (93.184.216.34) from the
            # first and only resolution.  It will fail with a connection error
            # (not SSRF), proving the IP was pinned rather than re-resolved.
            try:
                self.interp._http_request("GET", "http://rebind.attacker.example/secret")
            except RuntimeError as e:
                # Should NOT be an SSRF error — the resolved IP was public.
                # A connection/timeout error is expected since it's a real IP.
                assert "SSRF" not in str(e), (
                    "Should not get SSRF error for a hostname that initially resolves to public IP"
                )
            # Verify getaddrinfo was called exactly once (no re-resolution)
            assert call_count[0] == 1, (
                f"Expected exactly 1 DNS resolution (pinned IP), got {call_count[0]}"
            )

    def test_blocks_unresolvable_hostname(self):
        """Hostnames that cannot be resolved should be blocked."""
        with pytest.raises(RuntimeError, match="SSRF protection"):
            self.interp._http_request("GET", "http://this-host-definitely-does-not-exist-xyz.invalid/")

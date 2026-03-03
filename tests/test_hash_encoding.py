"""Tests for hash, encoding, and utility built-in functions.

Covers: md5, sha256, sha1, base64_encode, base64_decode,
        hex_encode, hex_decode, crc32, url_encode, url_decode.
"""
import pytest
import subprocess
import sys
import os
import tempfile

INTERPRETER = os.path.join(os.path.dirname(__file__), '..', 'saurav.py')


def run_srv(code):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False, encoding='utf-8') as f:
        f.write(code)
        f.flush()
        result = subprocess.run(
            [sys.executable, INTERPRETER, f.name],
            capture_output=True, text=True, timeout=10
        )
    os.unlink(f.name)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def run_srv_error(code):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False, encoding='utf-8') as f:
        f.write(code)
        f.flush()
        result = subprocess.run(
            [sys.executable, INTERPRETER, f.name],
            capture_output=True, text=True, timeout=10
        )
    os.unlink(f.name)
    return result


# ── MD5 ──────────────────────────────────────────────────────────────

class TestMd5:
    def test_known_hash(self):
        # MD5 of "hello" is well-known
        assert run_srv('print md5 "hello"') == '5d41402abc4b2a76b9719d911017c592'

    def test_empty_string(self):
        assert run_srv('print md5 ""') == 'd41d8cd98f00b204e9800998ecf8427e'

    def test_deterministic(self):
        out = run_srv('a = md5 "test"\nb = md5 "test"\nprint a == b')
        assert out == 'true'

    def test_different_inputs(self):
        out = run_srv('a = md5 "hello"\nb = md5 "world"\nprint a == b')
        assert out == 'false'

    def test_returns_string(self):
        assert run_srv('print type_of (md5 "x")') == 'string'

    def test_hex_length(self):
        assert run_srv('print len (md5 "test")') == '32'

    def test_number_coerced_to_string(self):
        # Numbers get converted to string representation first
        out = run_srv('print md5 42')
        assert len(out) == 32

    def test_long_input(self):
        out = run_srv('s = repeat "a" 1000\nprint len (md5 s)')
        assert out == '32'


# ── SHA256 ───────────────────────────────────────────────────────────

class TestSha256:
    def test_known_hash(self):
        assert run_srv('print sha256 "hello"') == '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'

    def test_empty_string(self):
        assert run_srv('print sha256 ""') == 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'

    def test_returns_string(self):
        assert run_srv('print type_of (sha256 "x")') == 'string'

    def test_hex_length(self):
        assert run_srv('print len (sha256 "test")') == '64'

    def test_deterministic(self):
        out = run_srv('a = sha256 "abc"\nb = sha256 "abc"\nprint a == b')
        assert out == 'true'

    def test_different_inputs(self):
        out = run_srv('a = sha256 "a"\nb = sha256 "b"\nprint a == b')
        assert out == 'false'


# ── SHA1 ─────────────────────────────────────────────────────────────

class TestSha1:
    def test_known_hash(self):
        assert run_srv('print sha1 "hello"') == 'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d'

    def test_empty_string(self):
        assert run_srv('print sha1 ""') == 'da39a3ee5e6b4b0d3255bfef95601890afd80709'

    def test_hex_length(self):
        assert run_srv('print len (sha1 "test")') == '40'

    def test_returns_string(self):
        assert run_srv('print type_of (sha1 "x")') == 'string'

    def test_deterministic(self):
        out = run_srv('print sha1 "abc" == sha1 "abc"')
        assert out == 'true'


# ── Base64 ───────────────────────────────────────────────────────────

class TestBase64Encode:
    def test_known(self):
        assert run_srv('print base64_encode "hello"') == 'aGVsbG8='

    def test_empty(self):
        assert run_srv('print base64_encode ""') == ''

    def test_with_spaces(self):
        assert run_srv('print base64_encode "hello world"') == 'aGVsbG8gd29ybGQ='

    def test_returns_string(self):
        assert run_srv('print type_of (base64_encode "test")') == 'string'

    def test_special_chars(self):
        out = run_srv('print base64_encode "a+b=c"')
        assert len(out) > 0


class TestBase64Decode:
    def test_known(self):
        assert run_srv('print base64_decode "aGVsbG8="') == 'hello'

    def test_empty(self):
        assert run_srv('print base64_decode ""') == ''

    def test_roundtrip(self):
        out = run_srv('s = "Hello, World!"\nencoded = base64_encode s\ndecoded = base64_decode encoded\nprint s == decoded')
        assert out == 'true'

    def test_invalid_input(self):
        code = 'try\n  x = base64_decode "!!!not-valid"\n  print x\ncatch e\n  print "caught"'
        assert 'caught' in run_srv(code)

    def test_non_string_error(self):
        r = run_srv_error('print base64_decode 42')
        assert r.returncode != 0


# ── Hex Encode/Decode ────────────────────────────────────────────────

class TestHexEncode:
    def test_known(self):
        assert run_srv('print hex_encode "hello"') == '68656c6c6f'

    def test_empty(self):
        assert run_srv('print hex_encode ""') == ''

    def test_returns_string(self):
        assert run_srv('print type_of (hex_encode "x")') == 'string'

    def test_numbers(self):
        out = run_srv('print hex_encode "123"')
        assert out == '313233'


class TestHexDecode:
    def test_known(self):
        assert run_srv('print hex_decode "68656c6c6f"') == 'hello'

    def test_empty(self):
        assert run_srv('print hex_decode ""') == ''

    def test_roundtrip(self):
        out = run_srv('s = "test data"\nh = hex_encode s\nd = hex_decode h\nprint s == d')
        assert out == 'true'

    def test_invalid_hex(self):
        code = 'try\n  x = hex_decode "ZZZZ"\n  print x\ncatch e\n  print "caught"'
        assert 'caught' in run_srv(code)

    def test_odd_length(self):
        code = 'try\n  x = hex_decode "abc"\n  print x\ncatch e\n  print "caught"'
        assert 'caught' in run_srv(code)

    def test_non_string_error(self):
        r = run_srv_error('print hex_decode 42')
        assert r.returncode != 0


# ── CRC32 ────────────────────────────────────────────────────────────

class TestCrc32:
    def test_known(self):
        # CRC32 of "hello" is 907060870
        out = run_srv('print crc32 "hello"')
        assert float(out) == 907060870.0

    def test_empty(self):
        out = run_srv('print crc32 ""')
        assert float(out) == 0.0

    def test_returns_number(self):
        assert run_srv('print type_of (crc32 "x")') == 'number'

    def test_deterministic(self):
        out = run_srv('a = crc32 "test"\nb = crc32 "test"\nprint a == b')
        assert out == 'true'

    def test_different_inputs(self):
        out = run_srv('a = crc32 "hello"\nb = crc32 "world"\nprint a == b')
        assert out == 'false'

    def test_always_positive(self):
        # CRC32 should be unsigned (& 0xFFFFFFFF)
        out = run_srv('print crc32 "anything" >= 0')
        assert out == 'true'


# ── URL Encode/Decode ────────────────────────────────────────────────

class TestUrlEncode:
    def test_spaces(self):
        assert run_srv('print url_encode "hello world"') == 'hello%20world'

    def test_special_chars(self):
        assert run_srv('print url_encode "a&b=c"') == 'a%26b%3Dc'

    def test_already_safe(self):
        assert run_srv('print url_encode "hello"') == 'hello'

    def test_empty(self):
        assert run_srv('print url_encode ""') == ''

    def test_slash(self):
        assert run_srv('print url_encode "a/b"') == 'a%2Fb'

    def test_returns_string(self):
        assert run_srv('print type_of (url_encode "x")') == 'string'


class TestUrlDecode:
    def test_spaces(self):
        assert run_srv('print url_decode "hello%20world"') == 'hello world'

    def test_special_chars(self):
        assert run_srv('print url_decode "a%26b%3Dc"') == 'a&b=c'

    def test_already_decoded(self):
        assert run_srv('print url_decode "hello"') == 'hello'

    def test_roundtrip(self):
        out = run_srv('s = "hello world&foo=bar"\nencoded = url_encode s\ndecoded = url_decode encoded\nprint s == decoded')
        assert out == 'true'

    def test_plus_sign(self):
        # url_decode with + should keep as +
        assert run_srv('print url_decode "a+b"') == 'a+b'

    def test_non_string_error(self):
        r = run_srv_error('print url_decode 42')
        assert r.returncode != 0


# ── Cross-function tests ────────────────────────────────────────────

class TestHashComposition:
    def test_md5_of_sha256(self):
        """Chain hash functions."""
        out = run_srv('h = sha256 "test"\nm = md5 h\nprint len m')
        assert out == '32'

    def test_base64_of_hash(self):
        """Encode a hash in base64."""
        out = run_srv('h = md5 "test"\nb = base64_encode h\nprint len b > 0')
        assert out == 'true'

    def test_hex_of_hash_roundtrip(self):
        """Hex encode a hash then decode it back."""
        out = run_srv('h = sha1 "test"\ne = hex_encode h\nd = hex_decode e\nprint h == d')
        assert out == 'true'

    def test_url_encode_hash(self):
        """URL-encode a hash (should be no-op since hex chars are safe)."""
        out = run_srv('h = md5 "test"\ne = url_encode h\nprint h == e')
        assert out == 'true'

    def test_all_hashes_different(self):
        """MD5, SHA1, SHA256 of same input produce different outputs."""
        code = 'm = md5 "x"\ns1 = sha1 "x"\ns2 = sha256 "x"\nprint m != s1\nprint s1 != s2\nprint m != s2'
        lines = run_srv(code).split('\n')
        assert all(l == 'true' for l in lines)


# ── sort/min/max mixed-type fix (issue #23) ─────────────────────────

class TestMixedTypeErrorHandling:
    def test_sort_mixed_types_caught(self):
        code = 'try\n  x = sort [3, "b", 1, "a"]\n  print x\ncatch e\n  print "caught"'
        assert 'caught' in run_srv(code)

    def test_min_mixed_list_caught(self):
        code = 'try\n  x = min [3, "b", 1]\n  print x\ncatch e\n  print "caught"'
        assert 'caught' in run_srv(code)

    def test_max_mixed_list_caught(self):
        code = 'try\n  x = max [3, "b", 1]\n  print x\ncatch e\n  print "caught"'
        assert 'caught' in run_srv(code)

    def test_min_mixed_pair_caught(self):
        code = 'try\n  x = min 3 "b"\n  print x\ncatch e\n  print "caught"'
        assert 'caught' in run_srv(code)

    def test_max_mixed_pair_caught(self):
        code = 'try\n  x = max 3 "b"\n  print x\ncatch e\n  print "caught"'
        assert 'caught' in run_srv(code)

    def test_sort_homogeneous_strings(self):
        out = run_srv('x = sort ["c", "a", "b"]\nprint x')
        assert out == '["a", "b", "c"]'

    def test_sort_homogeneous_numbers(self):
        out = run_srv('x = sort [3, 1, 2]\nprint x')
        assert out == '[1, 2, 3]'

    def test_min_max_same_type(self):
        out = run_srv('print min [5, 2, 8]\nprint max [5, 2, 8]')
        lines = out.split('\n')
        assert lines[0] == '2'
        assert lines[1] == '8'

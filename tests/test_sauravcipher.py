"""Tests for sauravcipher — classical cipher implementations and analysis tools."""

import pytest

from sauravcipher import (
    caesar_encrypt,
    caesar_decrypt,
    rot13,
    atbash,
    vigenere_encrypt,
    vigenere_decrypt,
    xor_cipher,
    xor_decipher,
    railfence_encrypt,
    railfence_decrypt,
    morse_encode,
    morse_decode,
    make_substitution_key,
    substitution_encrypt,
    frequency_analysis,
    index_of_coincidence,
    chi_squared_score,
    crack_caesar,
    estimate_cipher,
    apply_cipher,
    chain_ciphers,
    parse_repl_args,
)


# ── Caesar ──────────────────────────────────────────────────────────────

class TestCaesar:
    def test_encrypt_basic(self):
        assert caesar_encrypt("Hello", 3) == "Khoor"

    def test_decrypt_basic(self):
        assert caesar_decrypt("Khoor", 3) == "Hello"

    def test_roundtrip(self):
        msg = "Attack at dawn!"
        for shift in (0, 1, 13, 25):
            assert caesar_decrypt(caesar_encrypt(msg, shift), shift) == msg

    def test_preserves_non_alpha(self):
        assert caesar_encrypt("Hi 123!", 5) == "Mn 123!"

    def test_wrap_around(self):
        assert caesar_encrypt("xyz", 3) == "abc"
        assert caesar_encrypt("XYZ", 3) == "ABC"

    def test_zero_shift(self):
        assert caesar_encrypt("Test", 0) == "Test"

    def test_negative_shift(self):
        assert caesar_encrypt("Khoor", -3) == "Hello"


# ── ROT13 ──────────────────────────────────────────────────────────────

class TestRot13:
    def test_basic(self):
        assert rot13("Hello") == "Uryyb"

    def test_involution(self):
        assert rot13(rot13("Any text 123!")) == "Any text 123!"


# ── Atbash ─────────────────────────────────────────────────────────────

class TestAtbash:
    def test_basic(self):
        assert atbash("A") == "Z"
        assert atbash("Z") == "A"
        assert atbash("a") == "z"

    def test_involution(self):
        assert atbash(atbash("Hello World!")) == "Hello World!"

    def test_preserves_non_alpha(self):
        assert atbash("123 !@#") == "123 !@#"


# ── Vigenère ───────────────────────────────────────────────────────────

class TestVigenere:
    def test_encrypt(self):
        assert vigenere_encrypt("HELLO", "KEY") == "RIJVS"

    def test_decrypt(self):
        assert vigenere_decrypt("RIJVS", "KEY") == "HELLO"

    def test_roundtrip(self):
        msg = "Attack at dawn"
        key = "SECRET"
        assert vigenere_decrypt(vigenere_encrypt(msg, key), key) == msg

    def test_non_alpha_passthrough(self):
        enc = vigenere_encrypt("Hi! 42", "K")
        # Only letters shifted, non-alpha unchanged
        assert enc[2:] == "! 42"[:4]  # approximate — just check non-alpha preserved
        assert "!" in enc


# ── XOR ────────────────────────────────────────────────────────────────

class TestXor:
    def test_roundtrip(self):
        msg = "Hello"
        key = "K"
        enc = xor_cipher(msg, key)
        assert xor_decipher(enc, key) == msg

    def test_hex_output(self):
        enc = xor_cipher("A", "A")
        assert enc == "00"  # A XOR A = 0

    def test_multichar_key(self):
        msg = "ABCD"
        key = "XY"
        assert xor_decipher(xor_cipher(msg, key), key) == msg


# ── Rail Fence ─────────────────────────────────────────────────────────

class TestRailFence:
    def test_encrypt_basic(self):
        assert railfence_encrypt("HELLO WORLD", 3) == "HOREL OLLWD"

    def test_roundtrip(self):
        msg = "HELLO WORLD"
        for rails in (2, 3, 4):
            assert railfence_decrypt(railfence_encrypt(msg, rails), rails) == msg

    def test_single_rail(self):
        assert railfence_encrypt("abc", 1) == "abc"
        assert railfence_decrypt("abc", 1) == "abc"


# ── Morse ──────────────────────────────────────────────────────────────

class TestMorse:
    def test_encode(self):
        assert morse_encode("SOS") == "... --- ..."

    def test_decode(self):
        assert morse_decode("... --- ...") == "SOS"

    def test_roundtrip_alpha(self):
        assert morse_decode(morse_encode("HELLO")) == "HELLO"

    def test_space(self):
        enc = morse_encode("A B")
        assert "/" in enc


# ── Substitution ───────────────────────────────────────────────────────

class TestSubstitution:
    def test_make_key_keyword(self):
        key = make_substitution_key("ZEBRA")
        assert key["A"] == "Z"
        assert key["B"] == "E"
        assert len(key) == 26

    def test_encrypt(self):
        key = make_substitution_key("ZEBRA")
        enc = substitution_encrypt("HELLO", key)
        assert enc != "HELLO"
        assert len(enc) == 5

    def test_non_alpha_passthrough(self):
        key = make_substitution_key("KEY")
        assert substitution_encrypt("!", key) == "!"


# ── Analysis ───────────────────────────────────────────────────────────

class TestAnalysis:
    def test_frequency_analysis_counts(self):
        freq, total = frequency_analysis("aab")
        assert total == 3
        assert freq["A"]["count"] == 2
        assert freq["B"]["count"] == 1

    def test_ioc_english_range(self):
        english = "The quick brown fox jumps over the lazy dog and some more text to make it longer"
        ic = index_of_coincidence(english)
        assert 0.04 < ic < 0.09  # Broad range for short text

    def test_ioc_single_char(self):
        assert index_of_coincidence("A") == 0.0

    def test_chi_squared_english(self):
        # English-like text should have lower chi-squared than random
        english_score = chi_squared_score("The quick brown fox jumps over the lazy dog")
        random_score = chi_squared_score("ZZZQQQQXXXJJJ")
        assert english_score < random_score

    def test_crack_caesar_finds_shift(self):
        original = "The quick brown fox jumps over the lazy dog and returns home safely"
        encrypted = caesar_encrypt(original, 7)
        results = crack_caesar(encrypted)
        assert results[0]["shift"] == 7

    def test_estimate_cipher_morse(self):
        guesses = estimate_cipher("... --- ...")
        assert any(g[0] == "morse" for g in guesses)


# ── apply_cipher & chain ───────────────────────────────────────────────

class TestApplyCipher:
    def test_caesar(self):
        assert apply_cipher("caesar", "encrypt", "Hello", ["3"]) == "Khoor"

    def test_rot13(self):
        assert apply_cipher("rot13", "encrypt", "Hello", []) == "Uryyb"

    def test_unknown_cipher(self):
        result = apply_cipher("unknown", "encrypt", "text", [])
        assert "Unknown cipher" in result

    def test_chain(self):
        result, log = chain_ciphers("Hello", ["caesar:3", "rot13"])
        # caesar:3 -> Khoor, then rot13 -> Xubbe
        assert result == rot13(caesar_encrypt("Hello", 3))
        assert len(log) == 3  # input + 2 steps


# ── parse_repl_args ────────────────────────────────────────────────────

class TestParseReplArgs:
    def test_simple(self):
        assert parse_repl_args("encrypt caesar Hello 3") == ["encrypt", "caesar", "Hello", "3"]

    def test_quoted(self):
        assert parse_repl_args('encrypt caesar "Hello World" 3') == ["encrypt", "caesar", "Hello World", "3"]

    def test_single_quotes(self):
        assert parse_repl_args("encrypt caesar 'Hello World' 3") == ["encrypt", "caesar", "Hello World", "3"]

    def test_empty(self):
        assert parse_repl_args("") == []

#!/usr/bin/env python3
"""sauravcipher — Interactive Cipher Workbench for sauravcode.

Encrypt, decrypt, analyze, and crack classical ciphers interactively.
Uses the same cipher builtins available in .srv files.

Usage:
    python sauravcipher.py                        # Launch interactive REPL
    python sauravcipher.py --encrypt caesar "Hello" 3
    python sauravcipher.py --decrypt caesar "Khoor" 3
    python sauravcipher.py --encrypt vigenere "HELLO" "KEY"
    python sauravcipher.py --analyze "Khoor Zruog"   # Frequency analysis
    python sauravcipher.py --crack "Khoor Zruog"     # Brute-force Caesar
    python sauravcipher.py --chain "Hello" caesar:3 rot13 atbash
    python sauravcipher.py --file encrypt caesar input.txt 3
    python sauravcipher.py --compare "Hello World"   # All ciphers side by side

Supported ciphers: caesar, rot13, vigenere, atbash, xor, morse,
                   railfence, substitution
"""

import sys
import os
import argparse
import json
import string
from collections import Counter
from pathlib import Path

# -- Cipher implementations (standalone, no .srv interpreter needed) -----

def caesar_encrypt(text, shift):
    result = []
    for ch in text:
        if ch.isalpha():
            base = ord('A') if ch.isupper() else ord('a')
            result.append(chr((ord(ch) - base + shift) % 26 + base))
        else:
            result.append(ch)
    return ''.join(result)

def caesar_decrypt(text, shift):
    return caesar_encrypt(text, -shift)

def rot13(text):
    return caesar_encrypt(text, 13)

def atbash(text):
    result = []
    for ch in text:
        if ch.isalpha():
            base = ord('A') if ch.isupper() else ord('a')
            result.append(chr(base + 25 - (ord(ch) - base)))
        else:
            result.append(ch)
    return ''.join(result)

def vigenere_encrypt(text, key):
    key = key.upper()
    result, ki = [], 0
    for ch in text:
        if ch.isalpha():
            base = ord('A') if ch.isupper() else ord('a')
            shift = ord(key[ki % len(key)]) - ord('A')
            result.append(chr((ord(ch) - base + shift) % 26 + base))
            ki += 1
        else:
            result.append(ch)
    return ''.join(result)

def vigenere_decrypt(text, key):
    key = key.upper()
    result, ki = [], 0
    for ch in text:
        if ch.isalpha():
            base = ord('A') if ch.isupper() else ord('a')
            shift = ord(key[ki % len(key)]) - ord('A')
            result.append(chr((ord(ch) - base - shift) % 26 + base))
            ki += 1
        else:
            result.append(ch)
    return ''.join(result)

def xor_cipher(text, key):
    result = []
    for i, ch in enumerate(text):
        result.append(format(ord(ch) ^ ord(key[i % len(key)]), '02x'))
    return ''.join(result)

def xor_decipher(hex_text, key):
    result = []
    for i in range(0, len(hex_text), 2):
        byte = int(hex_text[i:i+2], 16)
        result.append(chr(byte ^ ord(key[i // 2 % len(key)])))
    return ''.join(result)

def railfence_encrypt(text, rails):
    if rails < 2:
        return text
    fence = [[] for _ in range(rails)]
    rail, direction = 0, 1
    for ch in text:
        fence[rail].append(ch)
        if rail == 0:
            direction = 1
        elif rail == rails - 1:
            direction = -1
        rail += direction
    return ''.join(''.join(row) for row in fence)

def railfence_decrypt(text, rails):
    if rails < 2:
        return text
    n = len(text)
    pattern = []
    rail, direction = 0, 1
    for i in range(n):
        pattern.append(rail)
        if rail == 0:
            direction = 1
        elif rail == rails - 1:
            direction = -1
        rail += direction
    sorted_indices = sorted(range(n), key=lambda i: (pattern[i], i))
    result = [''] * n
    for pos, char in zip(sorted_indices, text):
        result[pos] = char
    return ''.join(result)

MORSE_MAP = {
    'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.',
    'G': '--.', 'H': '....', 'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..',
    'M': '--', 'N': '-.', 'O': '---', 'P': '.--.', 'Q': '--.-', 'R': '.-.',
    'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-',
    'Y': '-.--', 'Z': '--..', '0': '-----', '1': '.----', '2': '..---',
    '3': '...--', '4': '....-', '5': '.....', '6': '-....', '7': '--...',
    '8': '---..', '9': '----.', ' ': '/'
}
MORSE_REV = {v: k for k, v in MORSE_MAP.items()}

def morse_encode(text):
    return ' '.join(MORSE_MAP.get(ch.upper(), ch) for ch in text)

def morse_decode(text):
    return ''.join(MORSE_REV.get(tok, tok) for tok in text.split(' '))

def substitution_encrypt(text, key_map):
    return ''.join(key_map.get(ch, ch) for ch in text)

def make_substitution_key(keyword):
    """Create a substitution alphabet from a keyword."""
    keyword = keyword.upper()
    seen = set()
    alphabet = []
    for ch in keyword + string.ascii_uppercase:
        if ch not in seen and ch.isalpha():
            seen.add(ch)
            alphabet.append(ch)
    return dict(zip(string.ascii_uppercase, alphabet))

# -- Analysis tools ------------------------------------------------------

ENGLISH_FREQ = {
    'E': 12.7, 'T': 9.1, 'A': 8.2, 'O': 7.5, 'I': 7.0, 'N': 6.7,
    'S': 6.3, 'H': 6.1, 'R': 6.0, 'D': 4.3, 'L': 4.0, 'C': 2.8,
    'U': 2.8, 'M': 2.4, 'W': 2.4, 'F': 2.2, 'G': 2.0, 'Y': 2.0,
    'P': 1.9, 'B': 1.5, 'V': 1.0, 'K': 0.8, 'J': 0.2, 'X': 0.2,
    'Q': 0.1, 'Z': 0.1
}

def frequency_analysis(text):
    """Return letter frequency percentages and comparison to English."""
    letters = [ch.upper() for ch in text if ch.isalpha()]
    total = len(letters) or 1
    counts = Counter(letters)
    freq = {}
    for letter in string.ascii_uppercase:
        pct = counts.get(letter, 0) / total * 100
        eng = ENGLISH_FREQ.get(letter, 0)
        freq[letter] = {'count': counts.get(letter, 0), 'pct': round(pct, 1),
                         'english': eng, 'delta': round(pct - eng, 1)}
    return freq, total

def index_of_coincidence(text):
    """Calculate Index of Coincidence (IoC). English ≈ 0.0667."""
    letters = [ch.upper() for ch in text if ch.isalpha()]
    n = len(letters)
    if n < 2:
        return 0.0
    counts = Counter(letters)
    ic = sum(c * (c - 1) for c in counts.values()) / (n * (n - 1))
    return round(ic, 4)

def chi_squared_score(text):
    """Chi-squared statistic against English letter frequencies."""
    letters = [ch.upper() for ch in text if ch.isalpha()]
    n = len(letters) or 1
    counts = Counter(letters)
    score = 0
    for letter in string.ascii_uppercase:
        observed = counts.get(letter, 0)
        expected = ENGLISH_FREQ.get(letter, 0.1) / 100 * n
        if expected > 0:
            score += (observed - expected) ** 2 / expected
    return round(score, 2)

def crack_caesar(text):
    """Brute-force all 26 Caesar shifts, ranked by chi-squared score."""
    results = []
    for shift in range(26):
        decrypted = caesar_decrypt(text, shift)
        score = chi_squared_score(decrypted)
        results.append({'shift': shift, 'text': decrypted, 'score': score})
    results.sort(key=lambda x: x['score'])
    return results

def estimate_cipher(text):
    """Guess what cipher might have been used based on heuristics."""
    guesses = []
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        if all(c in '.-/ ' for c in text) and ('.' in text or '-' in text):
            guesses.append(('morse', 0.9))
        elif all(c in '0123456789abcdef' for c in text.lower().replace(' ', '')):
            guesses.append(('xor', 0.7))
        return guesses
    ic = index_of_coincidence(text)
    if 0.060 <= ic <= 0.075:
        guesses.append(('caesar', 0.6))
        guesses.append(('substitution', 0.5))
        guesses.append(('atbash', 0.4))
    elif ic < 0.050:
        guesses.append(('vigenere', 0.7))
    else:
        guesses.append(('caesar', 0.4))
    if text == rot13(rot13(text)):
        guesses.append(('rot13', 0.3))
    return sorted(guesses, key=lambda x: -x[1])

# -- Cipher registry ----------------------------------------------------

CIPHERS = {
    'caesar':     {'encrypt': caesar_encrypt, 'decrypt': caesar_decrypt,
                   'params': 'shift (int)', 'example': 'caesar "Hello" 3'},
    'rot13':      {'encrypt': lambda t, *a: rot13(t), 'decrypt': lambda t, *a: rot13(t),
                   'params': 'none', 'example': 'rot13 "Hello"'},
    'vigenere':   {'encrypt': vigenere_encrypt, 'decrypt': vigenere_decrypt,
                   'params': 'key (str)', 'example': 'vigenere "Hello" "KEY"'},
    'atbash':     {'encrypt': lambda t, *a: atbash(t), 'decrypt': lambda t, *a: atbash(t),
                   'params': 'none (self-inverse)', 'example': 'atbash "Hello"'},
    'xor':        {'encrypt': xor_cipher, 'decrypt': xor_decipher,
                   'params': 'key (str)', 'example': 'xor "Hello" "key"'},
    'railfence':  {'encrypt': railfence_encrypt, 'decrypt': railfence_decrypt,
                   'params': 'rails (int)', 'example': 'railfence "Hello World" 3'},
    'morse':      {'encrypt': lambda t, *a: morse_encode(t), 'decrypt': lambda t, *a: morse_decode(t),
                   'params': 'none', 'example': 'morse "SOS"'},
}

def apply_cipher(name, mode, text, params):
    """Apply a cipher by name. Returns result string."""
    cipher = CIPHERS.get(name)
    if not cipher:
        return f"Unknown cipher: {name}. Available: {', '.join(CIPHERS)}"
    fn = cipher['encrypt'] if mode == 'encrypt' else cipher['decrypt']
    try:
        if name == 'caesar' or name == 'railfence':
            return fn(text, int(params[0]) if params else 3)
        elif name in ('vigenere', 'xor'):
            return fn(text, params[0] if params else 'KEY')
        else:
            return fn(text)
    except Exception as e:
        return f"Error: {e}"

# -- Chain cipher --------------------------------------------------------

def chain_ciphers(text, steps):
    """Apply multiple ciphers in sequence. Steps like ['caesar:3', 'rot13', 'atbash']."""
    result = text
    log = [f"  Input: {result}"]
    for step in steps:
        parts = step.split(':')
        name = parts[0]
        params = parts[1:] if len(parts) > 1 else []
        result = apply_cipher(name, 'encrypt', result, params)
        log.append(f"  -> {name}({', '.join(params) if params else ''}): {result}")
    return result, log

# -- Display helpers -----------------------------------------------------

def print_frequency_table(text):
    freq, total = frequency_analysis(text)
    ic = index_of_coincidence(text)
    print(f"\n{'='*60}")
    print(f"  Frequency Analysis  ({total} letters, IoC={ic})")
    print(f"{'='*60}")
    print(f"  {'Letter':>6}  {'Count':>5}  {'Freq%':>6}  {'English%':>8}  {'Bar'}")
    print(f"  {'------':>6}  {'-----':>5}  {'------':>6}  {'--------':>8}  {'--------------------'}")
    sorted_freq = sorted(freq.items(), key=lambda x: -x[1]['pct'])
    for letter, data in sorted_freq:
        if data['count'] > 0:
            bar = '#' * int(data['pct'] / 0.8)
            marker = ' ^' if data['delta'] > 3 else (' v' if data['delta'] < -3 else '')
            print(f"  {letter:>6}  {data['count']:>5}  {data['pct']:>5.1f}%  {data['english']:>7.1f}%  {bar}{marker}")
    print(f"\n  Chi-squared score: {chi_squared_score(text)} (lower = more English-like)")
    guesses = estimate_cipher(text)
    if guesses:
        print(f"  Likely cipher(s): {', '.join(f'{g[0]} ({g[1]:.0%})' for g in guesses[:3])}")
    print()

def print_crack_results(text, top=5):
    results = crack_caesar(text)
    print(f"\n{'='*60}")
    print(f"  Caesar Brute-Force (top {top} candidates)")
    print(f"{'='*60}")
    for r in results[:top]:
        preview = r['text'][:50] + ('...' if len(r['text']) > 50 else '')
        medal = ' *BEST*' if r == results[0] else ''
        print(f"  Shift {r['shift']:>2}  (X2={r['score']:>7.1f}){medal}  {preview}")
    print(f"\n  Best guess: shift={results[0]['shift']}")
    print(f"  Decrypted: {results[0]['text']}")
    print()

def print_compare(text):
    print(f"\n{'='*60}")
    print(f"  Cipher Comparison: \"{text}\"")
    print(f"{'='*60}")
    for name, cipher in CIPHERS.items():
        try:
            if name in ('caesar', 'railfence'):
                result = cipher['encrypt'](text, 3)
                label = f"{name} (shift/rails=3)"
            elif name in ('vigenere', 'xor'):
                result = cipher['encrypt'](text, 'KEY')
                label = f"{name} (key=KEY)"
            else:
                result = cipher['encrypt'](text)
                label = name
            print(f"  {label:<25} -> {result}")
        except Exception as e:
            print(f"  {name:<25} -> Error: {e}")
    print()

# -- Interactive REPL ----------------------------------------------------

REPL_HELP = """
+----------------------------------------------------------+
|              Cipher Workbench REPL                        |
+----------------------------------------------------------+
|  Commands:                                               |
|    encrypt <cipher> <text> [params]  Encrypt text        |
|    decrypt <cipher> <text> [params]  Decrypt text        |
|    analyze <text>         Frequency analysis             |
|    crack <text>           Brute-force Caesar             |
|    compare <text>         All ciphers side by side       |
|    chain <text> <steps>   Chain multiple ciphers         |
|    ioc <text>             Index of Coincidence           |
|    ciphers                List available ciphers         |
|    history                Show command history           |
|    help                   Show this help                 |
|    quit / exit            Exit REPL                      |
|                                                          |
|  Examples:                                               |
|    encrypt caesar "Attack at dawn" 7                     |
|    decrypt vigenere "RIJVS" KEY                          |
|    chain "Hello" caesar:3 rot13 atbash                   |
|    analyze "Wkh txlfn eurzq ira"                         |
|    crack "Wkh txlfn eurzq ira"                           |
+----------------------------------------------------------+
"""

def parse_repl_args(line):
    """Simple arg parser that handles quoted strings."""
    args = []
    current = []
    in_quote = None
    for ch in line:
        if ch in ('"', "'") and in_quote is None:
            in_quote = ch
        elif ch == in_quote:
            in_quote = None
        elif ch == ' ' and in_quote is None:
            if current:
                args.append(''.join(current))
                current = []
        else:
            current.append(ch)
    if current:
        args.append(''.join(current))
    return args

def repl():
    print(REPL_HELP)
    history = []
    while True:
        try:
            line = input("cipher> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not line:
            continue
        history.append(line)
        args = parse_repl_args(line)
        cmd = args[0].lower()

        if cmd in ('quit', 'exit', 'q'):
            print("Bye!")
            break
        elif cmd == 'help':
            print(REPL_HELP)
        elif cmd == 'ciphers':
            print(f"\n  Available ciphers:")
            for name, info in CIPHERS.items():
                print(f"    {name:<12} params: {info['params']:<25} ex: {info['example']}")
            print()
        elif cmd == 'history':
            for i, h in enumerate(history, 1):
                print(f"  {i:>3}. {h}")
        elif cmd in ('encrypt', 'enc', 'e'):
            if len(args) < 3:
                print("  Usage: encrypt <cipher> <text> [params...]")
                continue
            result = apply_cipher(args[1], 'encrypt', args[2], args[3:])
            print(f"  -> {result}")
        elif cmd in ('decrypt', 'dec', 'd'):
            if len(args) < 3:
                print("  Usage: decrypt <cipher> <text> [params...]")
                continue
            result = apply_cipher(args[1], 'decrypt', args[2], args[3:])
            print(f"  -> {result}")
        elif cmd in ('analyze', 'freq'):
            if len(args) < 2:
                print("  Usage: analyze <text>")
                continue
            print_frequency_table(args[1])
        elif cmd == 'crack':
            if len(args) < 2:
                print("  Usage: crack <ciphertext>")
                continue
            print_crack_results(args[1])
        elif cmd == 'compare':
            if len(args) < 2:
                print("  Usage: compare <text>")
                continue
            print_compare(args[1])
        elif cmd == 'chain':
            if len(args) < 3:
                print("  Usage: chain <text> <cipher:param> [cipher:param] ...")
                continue
            result, log = chain_ciphers(args[1], args[2:])
            for line in log:
                print(line)
            print(f"\n  Final: {result}")
        elif cmd == 'ioc':
            if len(args) < 2:
                print("  Usage: ioc <text>")
                continue
            ic = index_of_coincidence(args[1])
            print(f"  Index of Coincidence: {ic}  (English ≈ 0.0667)")
        else:
            print(f"  Unknown command: {cmd}. Type 'help' for commands.")

# -- CLI entry point -----------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Cipher Workbench — encrypt, decrypt, analyze, crack',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Launch with no args for interactive REPL mode.')
    parser.add_argument('--encrypt', nargs='+', metavar='ARG',
                        help='Encrypt: <cipher> <text> [params]')
    parser.add_argument('--decrypt', nargs='+', metavar='ARG',
                        help='Decrypt: <cipher> <text> [params]')
    parser.add_argument('--analyze', metavar='TEXT',
                        help='Frequency analysis of ciphertext')
    parser.add_argument('--crack', metavar='TEXT',
                        help='Brute-force Caesar crack')
    parser.add_argument('--compare', metavar='TEXT',
                        help='Show text encrypted with all ciphers')
    parser.add_argument('--chain', nargs='+', metavar='ARG',
                        help='Chain ciphers: <text> cipher:param ...')
    parser.add_argument('--file', nargs='+', metavar='ARG',
                        help='File mode: <encrypt|decrypt> <cipher> <file> [params]')
    parser.add_argument('--ciphers', action='store_true',
                        help='List available ciphers')

    args = parser.parse_args()

    if args.ciphers:
        print("Available ciphers:")
        for name, info in CIPHERS.items():
            print(f"  {name:<12} params: {info['params']:<25} ex: {info['example']}")
        return

    if args.encrypt:
        a = args.encrypt
        result = apply_cipher(a[0], 'encrypt', a[1] if len(a) > 1 else '', a[2:])
        print(result)
        return

    if args.decrypt:
        a = args.decrypt
        result = apply_cipher(a[0], 'decrypt', a[1] if len(a) > 1 else '', a[2:])
        print(result)
        return

    if args.analyze:
        print_frequency_table(args.analyze)
        return

    if args.crack:
        print_crack_results(args.crack)
        return

    if args.compare:
        print_compare(args.compare)
        return

    if args.chain:
        if len(args.chain) < 2:
            print("Usage: --chain <text> cipher:param [cipher:param] ...")
            return
        result, log = chain_ciphers(args.chain[0], args.chain[1:])
        for line in log:
            print(line)
        print(f"\nFinal: {result}")
        return

    if args.file:
        a = args.file
        if len(a) < 3:
            print("Usage: --file <encrypt|decrypt> <cipher> <file> [params]")
            return
        mode, cipher_name, filepath = a[0], a[1], a[2]
        params = a[3:]
        try:
            text = Path(filepath).read_text(encoding='utf-8')
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            return
        result = apply_cipher(cipher_name, mode, text, params)
        out_path = Path(filepath).stem + f".{mode}ed" + Path(filepath).suffix
        Path(out_path).write_text(result, encoding='utf-8')
        print(f"Output written to: {out_path}")
        return

    # No args -> interactive REPL
    repl()


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""sauravregex -- Interactive regex tester & debugger for sauravcode.

Test, debug, and understand regular expressions interactively. Supports
all Python regex features used by sauravcode's built-in regex functions.

Usage:
    python sauravregex.py                      # interactive REPL mode
    python sauravregex.py --pattern "\\d+" --text "abc 123 def 456"
    python sauravregex.py --pattern "\\w+" --text "hello world" --mode findall
    python sauravregex.py --analyze "(\\d{3})-(\\d{4})"
    python sauravregex.py --file patterns.txt --text "test input"
    python sauravregex.py --cheatsheet
    python sauravregex.py --quiz

Modes:
    match     - Check if pattern matches at start of text
    fullmatch - Check if pattern matches entire text
    search    - Find first occurrence anywhere
    findall   - Find all non-overlapping matches
    split     - Split text by pattern
    sub       - Replace matches (requires --replace)

Features:
    - Interactive REPL with history
    - Pattern analysis & explanation
    - Group highlighting with colors
    - Performance warnings for catastrophic backtracking risks
    - Regex cheatsheet reference
    - Interactive regex quiz for learning
    - Batch testing from file
"""

import argparse
import re
import sys
import time
import os

# ── ANSI colors ──────────────────────────────────────────────────────────

_COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "bg_yellow": "\033[43m",
    "bg_green": "\033[42m",
    "bg_cyan": "\033[46m",
    "bg_magenta": "\033[45m",
    "bg_blue": "\033[44m",
    "bg_red": "\033[41m",
}

GROUP_COLORS = [
    "\033[42m",  # bg green
    "\033[43m",  # bg yellow
    "\033[44m",  # bg blue
    "\033[45m",  # bg magenta
    "\033[46m",  # bg cyan
    "\033[41m",  # bg red
]

def _c(color, text):
    """Wrap text in ANSI color."""
    return f"{_COLORS.get(color, '')}{text}{_COLORS['reset']}"


# ── Pattern Analyzer ─────────────────────────────────────────────────────

_PATTERN_ELEMENTS = [
    ('\\d', 'digit [0-9]'),
    ('\\D', 'non-digit'),
    ('\\w', 'word char [a-zA-Z0-9_]'),
    ('\\W', 'non-word char'),
    ('\\s', 'whitespace'),
    ('\\S', 'non-whitespace'),
    ('\\b', 'word boundary'),
    ('\\B', 'non-word boundary'),
    ('\\A', 'start of string'),
    ('\\Z', 'end of string'),
    ('\\n', 'newline'),
    ('\\t', 'tab'),
    ('\\r', 'carriage return'),
]

def analyze_pattern(pattern):
    """Break down a regex pattern into human-readable explanation."""
    explanations = []
    i = 0
    group_num = 0

    while i < len(pattern):
        ch = pattern[i]

        # Escape sequences
        if ch == '\\' and i + 1 < len(pattern):
            pair = pattern[i:i+2]
            found = False
            for esc, desc in _PATTERN_ELEMENTS:
                if pair == esc:
                    explanations.append((pair, desc))
                    found = True
                    break
            if not found:
                explanations.append((pair, f"literal '{pattern[i+1]}'"))
            i += 2
            continue

        # Character classes
        if ch == '[':
            end = pattern.find(']', i + 1)
            if end == -1:
                end = len(pattern) - 1
            cls = pattern[i:end+1]
            if cls.startswith('[^'):
                explanations.append((cls, f"any char NOT in {cls[2:-1]}"))
            else:
                explanations.append((cls, f"any char in {cls[1:-1]}"))
            i = end + 1
            continue

        # Groups
        if ch == '(':
            group_num += 1
            if i + 1 < len(pattern) and pattern[i+1] == '?':
                if i + 2 < len(pattern):
                    if pattern[i+2] == ':':
                        explanations.append(('(?:', 'non-capturing group start'))
                        i += 3
                        continue
                    elif pattern[i+2] == '=':
                        explanations.append(('(?=', 'positive lookahead'))
                        i += 3
                        continue
                    elif pattern[i+2] == '!':
                        explanations.append(('(?!', 'negative lookahead'))
                        i += 3
                        continue
                    elif pattern[i+2] == '<':
                        if i + 3 < len(pattern):
                            if pattern[i+3] == '=':
                                explanations.append(('(?<=', 'positive lookbehind'))
                                i += 4
                                continue
                            elif pattern[i+3] == '!':
                                explanations.append(('(?<!', 'negative lookbehind'))
                                i += 4
                                continue
                            else:
                                # Named group (?P<name>...)
                                name_end = pattern.find('>', i + 4)
                                if name_end != -1:
                                    name = pattern[i+4:name_end]
                                    explanations.append((pattern[i:name_end+1], f"named group '{name}' (group {group_num})"))
                                    i = name_end + 1
                                    continue
                if i + 2 < len(pattern) and pattern[i+2] == 'P':
                    if i + 3 < len(pattern) and pattern[i+3] == '<':
                        name_end = pattern.find('>', i + 4)
                        if name_end != -1:
                            name = pattern[i+4:name_end]
                            explanations.append((pattern[i:name_end+1], f"named group '{name}' (group {group_num})"))
                            i = name_end + 1
                            continue
            explanations.append(('(', f"capturing group {group_num} start"))
            i += 1
            continue

        if ch == ')':
            explanations.append((')', 'group end'))
            i += 1
            continue

        # Quantifiers
        if ch == '*':
            greedy = '' if (i + 1 < len(pattern) and pattern[i+1] == '?') else ''
            if i + 1 < len(pattern) and pattern[i+1] == '?':
                explanations.append(('*?', '0 or more (lazy)'))
                i += 2
            else:
                explanations.append(('*', '0 or more (greedy)'))
                i += 1
            continue
        if ch == '+':
            if i + 1 < len(pattern) and pattern[i+1] == '?':
                explanations.append(('+?', '1 or more (lazy)'))
                i += 2
            else:
                explanations.append(('+', '1 or more (greedy)'))
                i += 1
            continue
        if ch == '?':
            if i + 1 < len(pattern) and pattern[i+1] == '?':
                explanations.append(('??', '0 or 1 (lazy)'))
                i += 2
            else:
                explanations.append(('?', '0 or 1 (greedy)'))
                i += 1
            continue

        # Repetition {n,m}
        if ch == '{':
            end = pattern.find('}', i)
            if end != -1:
                rep = pattern[i:end+1]
                inner = rep[1:-1]
                if ',' in inner:
                    parts = inner.split(',', 1)
                    lo = parts[0].strip() or '0'
                    hi = parts[1].strip() or '∞'
                    explanations.append((rep, f"between {lo} and {hi} times"))
                else:
                    explanations.append((rep, f"exactly {inner} times"))
                i = end + 1
                continue

        # Anchors & alternation
        if ch == '^':
            explanations.append(('^', 'start of line/string'))
            i += 1
            continue
        if ch == '$':
            explanations.append(('$', 'end of line/string'))
            i += 1
            continue
        if ch == '|':
            explanations.append(('|', 'OR (alternation)'))
            i += 1
            continue
        if ch == '.':
            explanations.append(('.', 'any character (except newline)'))
            i += 1
            continue

        # Literal
        explanations.append((ch, f"literal '{ch}'"))
        i += 1

    return explanations


def check_backtracking_risk(pattern):
    """Detect patterns that may cause catastrophic backtracking."""
    warnings = []
    # Nested quantifiers like (a+)+ or (a*)*
    if re.search(r'\([^)]*[+*]\)[+*]', pattern):
        warnings.append("⚠️  Nested quantifiers detected — risk of catastrophic backtracking!")
    # Overlapping alternation like (a|a)
    alts = re.findall(r'\(([^)]+)\)', pattern)
    for alt in alts:
        parts = alt.split('|')
        if len(parts) != len(set(parts)):
            warnings.append("⚠️  Duplicate alternatives in group — may cause exponential matching.")
    # .* repeated
    if pattern.count('.*') > 2:
        warnings.append("⚠️  Multiple .* patterns — consider using more specific patterns.")
    return warnings


# ── Match Display ─────────────────────────────────────────────────────────

def display_match(text, match, show_groups=True):
    """Display a match with highlighted regions."""
    start, end = match.span()
    before = text[:start]
    matched = text[start:end]
    after = text[end:]

    print(f"  Text:  {before}{_c('bg_green', _c('bold', matched))}{after}")
    print(f"  Match: {_c('green', repr(matched))} at position {start}-{end}")

    if show_groups and match.groups():
        print(f"  Groups:")
        for i, g in enumerate(match.groups(), 1):
            color_idx = (i - 1) % len(GROUP_COLORS)
            if g is not None:
                span = match.span(i)
                print(f"    {GROUP_COLORS[color_idx]}{_COLORS['bold']} {i} {_COLORS['reset']} "
                      f"{repr(g)} at {span[0]}-{span[1]}")
            else:
                print(f"    {_c('dim', f'  {i}  (not captured)')}")

        # Named groups
        named = match.groupdict()
        if named:
            print(f"  Named groups:")
            for name, val in named.items():
                print(f"    {_c('cyan', name)}: {repr(val)}")


def display_findall(text, pattern_obj):
    """Display all matches with positions."""
    matches = list(pattern_obj.finditer(text))
    if not matches:
        print(f"  {_c('yellow', 'No matches found.')}")
        return

    print(f"  {_c('green', f'{len(matches)} match(es) found:')}")

    # Build highlighted text
    highlighted = []
    last_end = 0
    for i, m in enumerate(matches):
        highlighted.append(text[last_end:m.start()])
        color = GROUP_COLORS[i % len(GROUP_COLORS)]
        highlighted.append(f"{color}{_COLORS['bold']}{text[m.start():m.end()]}{_COLORS['reset']}")
        last_end = m.end()
    highlighted.append(text[last_end:])
    print(f"  Text: {''.join(highlighted)}")
    print()

    for i, m in enumerate(matches, 1):
        print(f"  [{i}] {_c('green', repr(m.group()))} at {m.start()}-{m.end()}")
        if m.groups():
            for j, g in enumerate(m.groups(), 1):
                if g is not None:
                    print(f"      group {j}: {repr(g)}")


# ── Cheatsheet ────────────────────────────────────────────────────────────

CHEATSHEET = """
┌─────────────────────────────────────────────────────────────────────┐
│                    REGEX CHEATSHEET (sauravcode)                    │
├──────────┬──────────────────────────────────────────────────────────┤
│ BASICS   │                                                          │
│  .       │ Any character (except newline)                           │
│  \\d      │ Digit [0-9]                                              │
│  \\D      │ Non-digit                                                │
│  \\w      │ Word character [a-zA-Z0-9_]                              │
│  \\W      │ Non-word character                                       │
│  \\s      │ Whitespace (space, tab, newline)                         │
│  \\S      │ Non-whitespace                                           │
├──────────┼──────────────────────────────────────────────────────────┤
│ ANCHORS  │                                                          │
│  ^       │ Start of string/line                                     │
│  $       │ End of string/line                                       │
│  \\b      │ Word boundary                                            │
│  \\B      │ Non-word boundary                                        │
├──────────┼──────────────────────────────────────────────────────────┤
│ QUANTITY │                                                          │
│  *       │ 0 or more                                                │
│  +       │ 1 or more                                                │
│  ?       │ 0 or 1                                                   │
│  {n}     │ Exactly n                                                │
│  {n,}    │ n or more                                                │
│  {n,m}   │ Between n and m                                          │
│  *? +?   │ Lazy versions (match as few as possible)                 │
├──────────┼──────────────────────────────────────────────────────────┤
│ GROUPS   │                                                          │
│  (...)   │ Capturing group                                          │
│  (?:...) │ Non-capturing group                                      │
│  (?=...) │ Positive lookahead                                       │
│  (?!...) │ Negative lookahead                                       │
│  (?<=..) │ Positive lookbehind                                      │
│  (?<!..) │ Negative lookbehind                                      │
│  (?P<n>) │ Named group                                              │
├──────────┼──────────────────────────────────────────────────────────┤
│ CLASSES  │                                                          │
│  [abc]   │ Any of a, b, c                                           │
│  [^abc]  │ Not a, b, or c                                           │
│  [a-z]   │ Range a to z                                             │
│  [A-Z]   │ Range A to Z                                             │
│  [0-9]   │ Range 0 to 9                                             │
├──────────┼──────────────────────────────────────────────────────────┤
│ SPECIAL  │                                                          │
│  |       │ Alternation (OR)                                         │
│  \\       │ Escape special character                                 │
│  \\1 \\2   │ Backreference to group                                   │
└──────────┴──────────────────────────────────────────────────────────┘

sauravcode regex builtins:
  regex_match(pattern, text)     → first match or null
  regex_findall(pattern, text)   → list of all matches
  regex_replace(pattern, repl, text) → replaced string
  regex_split(pattern, text)     → list of split parts
"""


# ── Quiz ──────────────────────────────────────────────────────────────────

QUIZ_QUESTIONS = [
    {
        "question": "Write a regex to match a US phone number like 555-123-4567",
        "test_cases": [
            ("555-123-4567", True),
            ("123-456-7890", True),
            ("12-345-6789", False),
            ("abc-def-ghij", False),
            ("1234567890", False),
        ],
        "hint": "Three digits, dash, three digits, dash, four digits",
        "example_solution": r"\d{3}-\d{3}-\d{4}",
    },
    {
        "question": "Write a regex to match a valid email address (simple version)",
        "test_cases": [
            ("user@example.com", True),
            ("name.last@domain.org", True),
            ("@missing.com", False),
            ("noat.com", False),
            ("user@.com", False),
        ],
        "hint": "word chars/dots before @, word chars/dots after, dot, 2-4 letter TLD",
        "example_solution": r"[\w.]+@[\w]+\.[\w]{2,4}",
    },
    {
        "question": "Write a regex to match a hex color code like #FF00AA or #abc",
        "test_cases": [
            ("#FF00AA", True),
            ("#abc", True),
            ("#1a2b3c", True),
            ("#GGG", False),
            ("FF00AA", False),
            ("#12", False),
        ],
        "hint": "Hash followed by exactly 3 or 6 hex digits",
        "example_solution": r"#([0-9a-fA-F]{3}){1,2}$",
    },
    {
        "question": "Write a regex to extract the domain from a URL like https://www.example.com/page",
        "test_cases": [
            ("https://www.example.com/page", True),
            ("http://test.org", True),
            ("ftp://files.net/dir", True),
            ("not a url", False),
        ],
        "hint": "Protocol, ://, then capture until the next /",
        "example_solution": r"\w+://([^/]+)",
    },
    {
        "question": "Write a regex to match a date in YYYY-MM-DD format",
        "test_cases": [
            ("2024-01-15", True),
            ("2023-12-31", True),
            ("24-01-15", False),
            ("2024/01/15", False),
            ("2024-1-5", False),
        ],
        "hint": "Four digits, dash, two digits, dash, two digits",
        "example_solution": r"\d{4}-\d{2}-\d{2}",
    },
    {
        "question": "Write a regex to match words that start with a capital letter",
        "test_cases": [
            ("Hello", True),
            ("World", True),
            ("hello", False),
            ("123abc", False),
        ],
        "hint": "Use \\b for word boundary and [A-Z] for uppercase",
        "example_solution": r"\b[A-Z]\w*",
    },
    {
        "question": "Write a regex to match an IPv4 address like 192.168.1.1",
        "test_cases": [
            ("192.168.1.1", True),
            ("10.0.0.1", True),
            ("256.1.1.1", False),
            ("1.2.3", False),
            ("a.b.c.d", False),
        ],
        "hint": "Four groups of 1-3 digits separated by dots (basic, don't worry about 0-255 range)",
        "example_solution": r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
    },
    {
        "question": "Write a regex to find all words with exactly 3 letters",
        "test_cases": [
            ("the cat sat", True),
            ("I am ok", True),
            ("hello world", False),
        ],
        "hint": "Word boundary, exactly 3 word characters, word boundary",
        "example_solution": r"\b\w{3}\b",
    },
]


def run_quiz():
    """Interactive regex quiz."""
    print(_c('bold', "\n🧩 Regex Quiz — Test Your Skills!\n"))
    print("Type your regex pattern for each challenge.")
    print(f"Type {_c('cyan', 'hint')} for a hint, {_c('cyan', 'skip')} to skip, {_c('cyan', 'quit')} to exit.\n")

    score = 0
    total = len(QUIZ_QUESTIONS)

    for i, q in enumerate(QUIZ_QUESTIONS, 1):
        print(f"{_c('bold', f'Question {i}/{total}')}: {q['question']}")
        print(f"  Test cases: {', '.join(repr(tc[0]) for tc in q['test_cases'][:3])}...")

        while True:
            try:
                answer = input(f"  {_c('cyan', 'regex>')} ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return score, total

            if answer.lower() == 'quit':
                print(f"\n{_c('bold', f'Score: {score}/{i-1}')} ({int(score/(i-1)*100) if i > 1 else 0}%)")
                return score, total
            if answer.lower() == 'skip':
                print(f"  {_c('yellow', 'Skipped.')} Solution: {_c('green', q['example_solution'])}\n")
                break
            if answer.lower() == 'hint':
                print(f"  {_c('yellow', '💡 ' + q['hint'])}")
                continue

            try:
                pat = re.compile(answer)
            except re.error as e:
                print(f"  {_c('red', f'Invalid regex: {e}')}")
                continue

            passed = 0
            failed = 0
            for test_text, should_match in q['test_cases']:
                result = bool(pat.search(test_text))
                if result == should_match:
                    passed += 1
                else:
                    failed += 1
                    expected = "match" if should_match else "not match"
                    print(f"  {_c('red', '✗')} {repr(test_text)} should {expected}")

            if failed == 0:
                print(f"  {_c('green', '✓ All test cases passed!')}")
                score += 1
                print()
                break
            else:
                print(f"  {_c('yellow', f'{passed}/{passed+failed} passed. Try again or type hint/skip.')}")

    print(f"\n{_c('bold', f'🏆 Final Score: {score}/{total}')} ({int(score/total*100)}%)")
    if score == total:
        print(_c('green', "   Perfect score! You're a regex master! 🎉"))
    elif score >= total * 0.7:
        print(_c('green', "   Great job! Solid regex knowledge. 💪"))
    elif score >= total * 0.4:
        print(_c('yellow', "   Not bad! Keep practicing. 📚"))
    else:
        print(_c('yellow', "   Keep learning! Try the --cheatsheet for reference. 🔍"))
    return score, total


# ── REPL ──────────────────────────────────────────────────────────────────

def run_repl():
    """Interactive regex REPL."""
    print(_c('bold', "\n🔍 sauravregex — Interactive Regex Tester"))
    print(f"  Commands: {_c('cyan', 'pattern')} {_c('cyan', 'text')} {_c('cyan', 'mode')} "
          f"{_c('cyan', 'analyze')} {_c('cyan', 'cheat')} {_c('cyan', 'quiz')} {_c('cyan', 'help')} {_c('cyan', 'quit')}\n")

    current_pattern = None
    current_text = None
    current_mode = "search"
    current_replace = None
    current_flags = 0

    while True:
        try:
            prompt = f"  {_c('magenta', 'regex')}"
            if current_pattern:
                prompt += f" [{_c('dim', current_pattern.pattern[:30])}]"
            cmd = input(f"{prompt}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{_c('dim', 'Bye!')}")
            break

        if not cmd:
            continue

        if cmd.lower() in ('quit', 'exit', 'q'):
            print(_c('dim', 'Bye!'))
            break

        if cmd.lower() == 'help':
            print(f"""
  {_c('bold', 'Commands:')}
    {_c('cyan', 'pattern <regex>')}   Set the regex pattern
    {_c('cyan', 'text <string>')}     Set the test text
    {_c('cyan', 'mode <mode>')}       Set mode: match|fullmatch|search|findall|split|sub
    {_c('cyan', 'replace <str>')}     Set replacement string (for sub mode)
    {_c('cyan', 'flags <flags>')}     Set flags: i=ignorecase m=multiline s=dotall x=verbose
    {_c('cyan', 'run')}               Run current pattern against text
    {_c('cyan', 'analyze')}           Explain the current pattern
    {_c('cyan', 'cheat')}             Show cheatsheet
    {_c('cyan', 'quiz')}              Start interactive quiz
    {_c('cyan', 'clear')}             Reset everything
    {_c('cyan', 'quit')}              Exit

  {_c('bold', 'Quick test:')} Just type a pattern when text is set (or vice versa)
""")
            continue

        if cmd.lower() == 'cheat':
            print(CHEATSHEET)
            continue

        if cmd.lower() == 'quiz':
            run_quiz()
            continue

        if cmd.lower() == 'clear':
            current_pattern = None
            current_text = None
            current_mode = "search"
            current_replace = None
            current_flags = 0
            print(f"  {_c('dim', 'Cleared.')}")
            continue

        if cmd.lower().startswith('pattern '):
            raw = cmd[8:].strip()
            try:
                current_pattern = re.compile(raw, current_flags)
                print(f"  {_c('green', '✓')} Pattern set: {_c('bold', raw)}")
                # Auto-run if text is set
                if current_text is not None:
                    _run_test(current_pattern, current_text, current_mode, current_replace)
            except re.error as e:
                print(f"  {_c('red', f'Invalid regex: {e}')}")
            continue

        if cmd.lower().startswith('text '):
            current_text = cmd[5:]
            print(f"  {_c('green', '✓')} Text set: {repr(current_text)}")
            if current_pattern:
                _run_test(current_pattern, current_text, current_mode, current_replace)
            continue

        if cmd.lower().startswith('mode '):
            m = cmd[5:].strip().lower()
            if m in ('match', 'fullmatch', 'search', 'findall', 'split', 'sub'):
                current_mode = m
                print(f"  {_c('green', '✓')} Mode: {m}")
            else:
                print(f"  {_c('red', 'Unknown mode.')} Use: match|fullmatch|search|findall|split|sub")
            continue

        if cmd.lower().startswith('replace '):
            current_replace = cmd[8:]
            print(f"  {_c('green', '✓')} Replacement: {repr(current_replace)}")
            continue

        if cmd.lower().startswith('flags '):
            flag_str = cmd[6:].strip().lower()
            current_flags = 0
            flag_map = {'i': re.IGNORECASE, 'm': re.MULTILINE, 's': re.DOTALL, 'x': re.VERBOSE}
            for f in flag_str:
                if f in flag_map:
                    current_flags |= flag_map[f]
            active = [k for k, v in flag_map.items() if current_flags & v]
            print(f"  {_c('green', '✓')} Flags: {' '.join(active) if active else 'none'}")
            if current_pattern:
                try:
                    current_pattern = re.compile(current_pattern.pattern, current_flags)
                except re.error as e:
                    print(f"  {_c('red', f'Pattern recompile failed: {e}')}")
            continue

        if cmd.lower() == 'analyze':
            if not current_pattern:
                print(f"  {_c('yellow', 'Set a pattern first.')}")
            else:
                _show_analysis(current_pattern.pattern)
            continue

        if cmd.lower() == 'run':
            if not current_pattern:
                print(f"  {_c('yellow', 'Set a pattern first.')}")
            elif current_text is None:
                print(f"  {_c('yellow', 'Set text first.')}")
            else:
                _run_test(current_pattern, current_text, current_mode, current_replace)
            continue

        # Quick: if pattern is set, treat input as text; if text is set, treat as pattern
        if current_pattern and current_text is None:
            current_text = cmd
            print(f"  {_c('green', '✓')} Text: {repr(current_text)}")
            _run_test(current_pattern, current_text, current_mode, current_replace)
        elif current_text is not None and current_pattern is None:
            try:
                current_pattern = re.compile(cmd, current_flags)
                print(f"  {_c('green', '✓')} Pattern: {_c('bold', cmd)}")
                _run_test(current_pattern, current_text, current_mode, current_replace)
            except re.error as e:
                print(f"  {_c('red', f'Invalid regex: {e}')}")
        else:
            # Try as pattern against existing text
            try:
                current_pattern = re.compile(cmd, current_flags)
                print(f"  {_c('green', '✓')} Pattern: {_c('bold', cmd)}")
                if current_text is not None:
                    _run_test(current_pattern, current_text, current_mode, current_replace)
            except re.error as e:
                print(f"  {_c('red', f'Unknown command. Type help for usage.')}")


def _show_analysis(pattern):
    """Display pattern analysis."""
    print(f"\n  {_c('bold', 'Pattern Analysis:')} {_c('cyan', pattern)}\n")

    elements = analyze_pattern(pattern)
    for token, desc in elements:
        print(f"    {_c('yellow', token):20s} -> {desc}")

    warnings = check_backtracking_risk(pattern)
    if warnings:
        print()
        for w in warnings:
            print(f"    {_c('red', w)}")
    print()


def _run_test(pattern, text, mode, replace_str):
    """Execute a regex test and display results."""
    print()
    t0 = time.perf_counter()

    try:
        if mode == "match":
            m = pattern.match(text)
            elapsed = time.perf_counter() - t0
            if m:
                print(f"  {_c('green', '✓ Match found!')}")
                display_match(text, m)
            else:
                print(f"  {_c('red', '✗ No match at start of string.')}")

        elif mode == "fullmatch":
            m = pattern.fullmatch(text)
            elapsed = time.perf_counter() - t0
            if m:
                print(f"  {_c('green', '✓ Full match!')}")
                display_match(text, m)
            else:
                print(f"  {_c('red', '✗ Pattern does not match entire string.')}")

        elif mode == "search":
            m = pattern.search(text)
            elapsed = time.perf_counter() - t0
            if m:
                print(f"  {_c('green', '✓ Match found!')}")
                display_match(text, m)
            else:
                print(f"  {_c('red', '✗ No match found.')}")

        elif mode == "findall":
            elapsed_start = time.perf_counter()
            display_findall(text, pattern)
            elapsed = time.perf_counter() - elapsed_start

        elif mode == "split":
            parts = pattern.split(text)
            elapsed = time.perf_counter() - t0
            print(f"  {_c('green', f'{len(parts)} part(s):')}")
            for i, p in enumerate(parts):
                print(f"    [{i}] {repr(p)}")

        elif mode == "sub":
            if replace_str is None:
                print(f"  {_c('yellow', 'Set a replacement string with: replace <string>')}")
                return
            result = pattern.sub(replace_str, text)
            elapsed = time.perf_counter() - t0
            count = len(pattern.findall(text))
            print(f"  {_c('green', f'{count} replacement(s):')}")
            print(f"  Before: {repr(text)}")
            print(f"  After:  {repr(result)}")

        else:
            elapsed = time.perf_counter() - t0

    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  {_c('red', f'Error: {e}')}")

    print(f"  {_c('dim', f'({elapsed*1000:.2f}ms)')}\n")


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sauravregex",
        description="Interactive regex tester & debugger for sauravcode",
    )
    parser.add_argument("--pattern", "-p", help="Regex pattern to test")
    parser.add_argument("--text", "-t", help="Text to test against")
    parser.add_argument("--mode", "-m", default="search",
                        choices=["match", "fullmatch", "search", "findall", "split", "sub"],
                        help="Matching mode (default: search)")
    parser.add_argument("--replace", "-r", help="Replacement string for sub mode")
    parser.add_argument("--flags", "-f", default="",
                        help="Regex flags: i=ignorecase m=multiline s=dotall x=verbose")
    parser.add_argument("--analyze", "-a", metavar="PATTERN",
                        help="Analyze/explain a regex pattern")
    parser.add_argument("--file", help="File with patterns (one per line) to test")
    parser.add_argument("--cheatsheet", action="store_true", help="Show regex cheatsheet")
    parser.add_argument("--quiz", action="store_true", help="Start interactive quiz")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args()

    if args.cheatsheet:
        print(CHEATSHEET)
        return

    if args.quiz:
        run_quiz()
        return

    if args.analyze:
        _show_analysis(args.analyze)
        return

    # Parse flags
    flags = 0
    flag_map = {'i': re.IGNORECASE, 'm': re.MULTILINE, 's': re.DOTALL, 'x': re.VERBOSE}
    for f in args.flags:
        if f in flag_map:
            flags |= flag_map[f]

    # File mode: test multiple patterns
    if args.file:
        if not args.text:
            print("Error: --text is required with --file", file=sys.stderr)
            sys.exit(1)
        try:
            with open(args.file) as f:
                patterns = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        except FileNotFoundError:
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)

        results = []
        for pat_str in patterns:
            try:
                pat = re.compile(pat_str, flags)
                m = pat.search(args.text)
                result = {
                    "pattern": pat_str,
                    "matched": bool(m),
                    "match": m.group() if m else None,
                    "span": list(m.span()) if m else None,
                }
                results.append(result)
                if not args.json:
                    status = _c('green', '✓') if m else _c('red', '✗')
                    match_info = f" → {repr(m.group())}" if m else ""
                    print(f"  {status} {pat_str}{match_info}")
            except re.error as e:
                results.append({"pattern": pat_str, "error": str(e)})
                if not args.json:
                    print(f"  {_c('red', '!')} {pat_str} — {e}")

        if args.json:
            import json as _json
            print(_json.dumps(results, indent=2))
        return

    # Single pattern + text
    if args.pattern and args.text:
        try:
            pat = re.compile(args.pattern, flags)
        except re.error as e:
            print(f"Error: Invalid regex: {e}", file=sys.stderr)
            sys.exit(1)

        if args.json:
            import json as _json
            if args.mode == "findall":
                matches = [{"match": m.group(), "span": list(m.span()),
                            "groups": list(m.groups())}
                           for m in pat.finditer(args.text)]
                print(_json.dumps({"pattern": args.pattern, "text": args.text,
                                   "mode": args.mode, "matches": matches}, indent=2))
            elif args.mode == "split":
                print(_json.dumps({"pattern": args.pattern, "text": args.text,
                                   "mode": args.mode, "parts": pat.split(args.text)}, indent=2))
            elif args.mode == "sub":
                result = pat.sub(args.replace or "", args.text)
                print(_json.dumps({"pattern": args.pattern, "text": args.text,
                                   "mode": args.mode, "result": result}, indent=2))
            else:
                fn = getattr(pat, args.mode)
                m = fn(args.text)
                print(_json.dumps({"pattern": args.pattern, "text": args.text,
                                   "mode": args.mode, "matched": bool(m),
                                   "match": m.group() if m else None,
                                   "span": list(m.span()) if m else None,
                                   "groups": list(m.groups()) if m else None}, indent=2))
            return

        # Show analysis first
        _show_analysis(args.pattern)
        # Then run test
        _run_test(pat, args.text, args.mode, args.replace)
        return

    if args.pattern and not args.text:
        _show_analysis(args.pattern)
        return

    # No args → REPL
    run_repl()


if __name__ == "__main__":
    main()

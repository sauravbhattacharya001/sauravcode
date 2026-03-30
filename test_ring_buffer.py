"""Tests for ring buffer (circular buffer) builtins.

Covers: ring_create, ring_push, ring_pop, ring_peek, ring_size,
ring_capacity, ring_is_empty, ring_is_full, ring_to_list, ring_clear,
ring_get — including overflow/wrap-around, error handling, and edge cases.
"""

import subprocess
import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SAURAV = os.path.join(ROOT, "saurav.py")


def run(code: str) -> str:
    tmp = os.path.join(ROOT, "_tmp_ring_test.srv")
    with open(tmp, "w") as f:
        f.write(code)
    try:
        r = subprocess.run(
            [sys.executable, SAURAV, tmp],
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout + r.stderr).strip()
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ── Basic creation and emptiness ────────────────────────────────

def test_create_and_empty():
    out = run("rb = ring_create 3\nprint ring_is_empty rb")
    assert "true" in out.lower(), f"Got: {out}"


def test_initial_size_zero():
    out = run("rb = ring_create 5\nprint ring_size rb")
    assert "0" in out, f"Got: {out}"


def test_capacity():
    out = run("rb = ring_create 4\nprint ring_capacity rb")
    assert "4" in out, f"Got: {out}"


# ── Push and peek ───────────────────────────────────────────────

def test_push_and_peek():
    out = run('rb = ring_create 3\nring_push (rb) "hello"\nprint ring_peek rb')
    assert "hello" in out, f"Got: {out}"


def test_push_multiple_peek_oldest():
    out = run('''rb = ring_create 3
ring_push (rb) "a"
ring_push (rb) "b"
ring_push (rb) "c"
print ring_peek rb
''')
    assert "a" in out, f"Got: {out}"


# ── Pop (FIFO order) ───────────────────────────────────────────

def test_pop_fifo_order():
    out = run('''rb = ring_create 3
ring_push (rb) "first"
ring_push (rb) "second"
ring_push (rb) "third"
print ring_pop rb
print ring_pop rb
print ring_pop rb
''')
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    assert lines == ["first", "second", "third"], f"Got: {lines}"


def test_pop_decrements_size():
    out = run('''rb = ring_create 3
ring_push (rb) 1
ring_push (rb) 2
ring_pop rb
print ring_size rb
''')
    assert "1" in out, f"Got: {out}"


# ── Overflow / wrap-around ─────────────────────────────────────

def test_overflow_evicts_oldest():
    """When buffer is full, pushing evicts the oldest element."""
    out = run('''rb = ring_create 3
ring_push (rb) "a"
ring_push (rb) "b"
ring_push (rb) "c"
ring_push (rb) "d"
print ring_peek rb
''')
    # "a" was evicted, oldest is now "b"
    assert "b" in out, f"Got: {out}"


def test_overflow_returns_evicted():
    """ring_push returns the evicted value when buffer overflows."""
    out = run('''rb = ring_create 2
ring_push (rb) "x"
ring_push (rb) "y"
evicted = ring_push (rb) "z"
print evicted
''')
    assert "x" in out, f"Got: {out}"


def test_overflow_size_stays_at_capacity():
    out = run('''rb = ring_create 2
ring_push (rb) 1
ring_push (rb) 2
ring_push (rb) 3
ring_push (rb) 4
print ring_size rb
''')
    assert "2" in out, f"Got: {out}"


def test_is_full():
    out = run('''rb = ring_create 2
ring_push (rb) "a"
ring_push (rb) "b"
print ring_is_full rb
''')
    assert "true" in out.lower(), f"Got: {out}"


def test_not_full_after_pop():
    out = run('''rb = ring_create 2
ring_push (rb) "a"
ring_push (rb) "b"
ring_pop rb
print ring_is_full rb
''')
    assert "false" in out.lower(), f"Got: {out}"


# ── to_list ────────────────────────────────────────────────────

def test_to_list_ordered():
    out = run('''rb = ring_create 3
ring_push (rb) 10
ring_push (rb) 20
ring_push (rb) 30
print ring_to_list rb
''')
    assert "10" in out and "20" in out and "30" in out, f"Got: {out}"


def test_to_list_after_overflow():
    out = run('''rb = ring_create 3
ring_push (rb) 1
ring_push (rb) 2
ring_push (rb) 3
ring_push (rb) 4
ring_push (rb) 5
items = ring_to_list rb
print items
''')
    # Should contain [3, 4, 5] — the 3 most recent
    assert "3" in out and "4" in out and "5" in out, f"Got: {out}"


# ── ring_get (indexed access) ─────────────────────────────────

def test_get_by_index():
    out = run('''rb = ring_create 3
ring_push (rb) "a"
ring_push (rb) "b"
ring_push (rb) "c"
print ring_get (rb) 0
print ring_get (rb) 1
print ring_get (rb) 2
''')
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    assert lines == ["a", "b", "c"], f"Got: {lines}"


def test_get_after_overflow():
    """Index 0 should be the oldest surviving element after overflow."""
    out = run('''rb = ring_create 2
ring_push (rb) "old"
ring_push (rb) "mid"
_ = ring_push (rb) "new"
x = ring_get (rb) 0
y = ring_get (rb) 1
print x
print y
''')
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    assert lines == ["mid", "new"], f"Got: {lines}"


# ── ring_clear ─────────────────────────────────────────────────

def test_clear():
    out = run('''rb = ring_create 3
ring_push (rb) 1
ring_push (rb) 2
ring_clear rb
print ring_size rb
print ring_is_empty rb
''')
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    assert "0" in lines[0], f"Got: {lines}"
    assert "true" in lines[1].lower(), f"Got: {lines}"


def test_reuse_after_clear():
    out = run('''rb = ring_create 2
ring_push (rb) "old"
ring_clear rb
ring_push (rb) "new"
print ring_peek rb
print ring_size rb
''')
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    assert "new" in lines[0], f"Got: {lines}"
    assert "1" in lines[1], f"Got: {lines}"


# ── Error handling ─────────────────────────────────────────────

def test_pop_empty_error():
    out = run('''rb = ring_create 3
try
    ring_pop rb
catch e
    print e
''')
    assert "empty" in out.lower(), f"Got: {out}"


def test_peek_empty_error():
    out = run('''rb = ring_create 3
try
    ring_peek rb
catch e
    print e
''')
    assert "empty" in out.lower(), f"Got: {out}"


def test_get_out_of_range():
    out = run('''rb = ring_create 3
ring_push (rb) "a"
try
    ring_get (rb) 5
catch e
    print e
''')
    assert "out of range" in out.lower() or "index" in out.lower(), f"Got: {out}"


def test_create_zero_capacity_error():
    out = run('''try
    rb = ring_create 0
catch e
    print e
''')
    assert "positive" in out.lower() or "capacity" in out.lower(), f"Got: {out}"


# ── Mixed types ────────────────────────────────────────────────

def test_mixed_types():
    out = run('''rb = ring_create 3
ring_push (rb) 42
ring_push (rb) "hello"
ring_push (rb) true
items = ring_to_list rb
print items
''')
    assert "42" in out and "hello" in out, f"Got: {out}"


# ── Capacity 1 edge case ──────────────────────────────────────

def test_capacity_one():
    out = run('''rb = ring_create 1
ring_push (rb) "a"
print ring_is_full rb
ring_push (rb) "b"
print ring_peek rb
print ring_size rb
''')
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    assert "true" in lines[0].lower(), f"Got: {lines}"
    assert "b" in lines[1], f"Got: {lines}"
    assert "1" in lines[2], f"Got: {lines}"


# ── Push returns None when not full ───────────────────────────

def test_push_returns_null_when_not_full():
    out = run('''rb = ring_create 3
result = ring_push (rb) "a"
print result
''')
    assert "null" in out.lower() or "none" in out.lower(), f"Got: {out}"


# ── Interleaved push/pop ──────────────────────────────────────

def test_interleaved_push_pop():
    """Push and pop interleaved to test head pointer tracking."""
    out = run('''rb = ring_create 3
ring_push (rb) 1
ring_push (rb) 2
ring_pop rb
ring_push (rb) 3
ring_push (rb) 4
print ring_to_list rb
''')
    # Should have [2, 3, 4]
    assert "2" in out and "3" in out and "4" in out, f"Got: {out}"


def test_many_wrap_arounds():
    """Stress test: push many elements through a small buffer."""
    out = run('''rb = ring_create 3
i = 0
while i < 100
    ring_push (rb) i
    i = i + 1
print ring_to_list rb
print ring_size rb
''')
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    # Last 3 values: 97, 98, 99
    assert "97" in lines[0] and "98" in lines[0] and "99" in lines[0], f"Got: {lines}"
    assert "3" in lines[1], f"Got: {lines}"

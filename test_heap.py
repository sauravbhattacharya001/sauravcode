"""Tests for heap / priority queue builtins."""

import subprocess
import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SAURAV = os.path.join(ROOT, "saurav.py")


def run(code: str) -> str:
    tmp = os.path.join(ROOT, "_tmp_heap_test.srv")
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


def test_create_and_empty():
    out = run("h = heap_create\nprint heap_is_empty h")
    assert "true" in out.lower(), f"Got: {out}"


def test_push_pop_order():
    out = run('''h = heap_create
heap_push (h) 3 "c"
heap_push (h) 1 "a"
heap_push (h) 2 "b"
print heap_pop h
print heap_pop h
print heap_pop h
''')
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    assert lines == ["a", "b", "c"], f"Got: {lines}"


def test_peek_and_size():
    out = run('''h = heap_create
heap_push (h) 5 "five"
heap_push (h) 2 "two"
print heap_peek h
print heap_size h
''')
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    assert lines[0] == "two"
    assert "2" in lines[1]


def test_merge():
    out = run('''a = heap_create
b = heap_create
heap_push (a) 1 "x"
heap_push (b) 2 "y"
c = heap_merge (a) b
print heap_size c
print heap_pop c
print heap_pop c
''')
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    assert "2" in lines[0]
    assert lines[1] == "x"
    assert lines[2] == "y"


def test_clear():
    out = run('''h = heap_create
heap_push (h) 1 "a"
heap_clear h
print heap_is_empty h
''')
    assert "true" in out.lower()


def test_push_pop_builtin():
    out = run('''h = heap_create
heap_push (h) 5 "five"
heap_push (h) 10 "ten"
r = heap_push_pop (h) 1 "one"
print r
print heap_peek h
''')
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    assert lines[0] == "one"
    assert lines[1] == "five"


def test_to_list():
    out = run('''h = heap_create
heap_push (h) 3 "c"
heap_push (h) 1 "a"
heap_push (h) 2 "b"
items = heap_to_list h
print len items
''')
    assert "3" in out


if __name__ == "__main__":
    test_create_and_empty()
    test_push_pop_order()
    test_peek_and_size()
    test_merge()
    test_clear()
    test_push_pop_builtin()
    test_to_list()
    print("All heap tests passed!")

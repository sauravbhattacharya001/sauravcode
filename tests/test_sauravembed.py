"""Tests for sauravembed -- Python embedding API for sauravcode."""

import os
import sys
import tempfile

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sauravembed import SauravEmbed, RunResult


# ── RunResult ────────────────────────────────────────────────────

def test_run_result_bool():
    """RunResult is truthy on success, falsy on error."""
    ok = RunResult(success=True)
    fail = RunResult(success=False, error="oops")
    assert bool(ok) is True
    assert bool(fail) is False


def test_run_result_repr():
    ok = RunResult(success=True, variables={"x": 1, "y": 2}, elapsed_ms=1.5)
    assert "success=True" in repr(ok)
    assert "vars=2" in repr(ok)

    fail = RunResult(success=False, error="boom")
    assert "success=False" in repr(fail)
    assert "boom" in repr(fail)


# ── Basic Execution ──────────────────────────────────────────────

def test_basic_assignment():
    srv = SauravEmbed()
    result = srv.run("x = 42")
    assert result.success
    assert srv.get("x") == 42


def test_arithmetic():
    srv = SauravEmbed()
    result = srv.run("x = 5 + 3")
    assert result.success
    assert srv.get("x") == 8


def test_string_operations():
    srv = SauravEmbed()
    srv.run('name = "hello"')
    srv.run("upper_name = upper name")
    assert srv.get("upper_name") == "HELLO"


def test_output_capture():
    srv = SauravEmbed()
    result = srv.run("print 42")
    assert result.success
    assert "42" in result.output


def test_no_capture_mode():
    srv = SauravEmbed(capture_output=False)
    result = srv.run("x = 1")
    assert result.success
    assert result.output == ""


def test_elapsed_timing():
    srv = SauravEmbed()
    result = srv.run("x = 1")
    assert result.elapsed_ms >= 0


# ── Variable Access ──────────────────────────────────────────────

def test_set_and_get():
    srv = SauravEmbed()
    srv.set("x", 42)
    assert srv.get("x") == 42


def test_get_default():
    srv = SauravEmbed()
    assert srv.get("missing") is None
    assert srv.get("missing", "default") == "default"


def test_has():
    srv = SauravEmbed()
    srv.set("x", 1)
    assert srv.has("x")
    assert not srv.has("y")


def test_delete():
    srv = SauravEmbed()
    srv.set("x", 1)
    assert srv.delete("x")
    assert not srv.has("x")
    assert not srv.delete("nonexistent")


def test_variables_list():
    srv = SauravEmbed()
    srv.set("a", 1)
    srv.set("b", 2)
    names = srv.variables()
    assert "a" in names
    assert "b" in names


def test_get_all():
    srv = SauravEmbed()
    srv.run("x = 10")
    srv.run("y = 20")
    all_vars = srv.get_all()
    assert all_vars["x"] == 10
    assert all_vars["y"] == 20


def test_set_many():
    srv = SauravEmbed()
    srv.set_many({"a": 1, "b": 2, "c": 3})
    srv.run("total = a + b + c")
    assert srv.get("total") == 6


# ── Type Conversion ──────────────────────────────────────────────

def test_inject_int():
    srv = SauravEmbed()
    srv.set("x", 42)
    srv.run("y = x + 1")
    assert srv.get("y") == 43


def test_inject_float():
    srv = SauravEmbed()
    srv.set("pi", 3.14)
    srv.run("r = pi * 2")
    assert abs(srv.get("r") - 6.28) < 0.001


def test_inject_string():
    srv = SauravEmbed()
    srv.set("name", "World")
    srv.run('greeting = f"Hello {name}!"')
    assert srv.get("greeting") == "Hello World!"


def test_inject_bool():
    srv = SauravEmbed()
    srv.set("flag", True)
    result = srv.run('if flag\n    x = "yes"')
    assert srv.get("x") == "yes"


def test_inject_list():
    srv = SauravEmbed()
    srv.set("items", [1, 2, 3])
    code = "total = 0\nfor item in items\n    total = total + item"
    srv.run(code)
    assert srv.get("total") == 6


def test_inject_dict():
    srv = SauravEmbed()
    srv.set("config", {"host": "localhost", "port": 8080})
    srv.run('h = config["host"]')
    assert srv.get("h") == "localhost"


def test_inject_none():
    srv = SauravEmbed()
    srv.set("nothing", None)
    assert srv.get("nothing") is None


def test_nested_list():
    srv = SauravEmbed()
    srv.set("matrix", [[1, 2], [3, 4]])
    assert srv.get("matrix") == [[1, 2], [3, 4]]


# ── Function Registration ───────────────────────────────────────

def test_register_single_arg():
    srv = SauravEmbed()
    srv.register("double", lambda x: x * 2)
    srv.run("y = double 21")
    assert srv.get("y") == 42


def test_register_multi_arg_literals():
    srv = SauravEmbed()
    srv.register("add", lambda a, b: a + b)
    srv.run("z = add 10 20")
    assert srv.get("z") == 30


def test_register_string_return():
    """Python function returning a string."""
    srv = SauravEmbed()
    srv.register("greet", lambda name: f"hello {name}")
    srv.run('msg = greet "world"')
    assert srv.get("msg") == "hello world"


def test_unregister():
    srv = SauravEmbed()
    srv.register("myfn", lambda: 42)
    assert "myfn" in srv.registered_functions()
    assert srv.unregister("myfn")
    assert "myfn" not in srv.registered_functions()
    assert not srv.unregister("nonexistent")


def test_registered_functions():
    srv = SauravEmbed()
    srv.register("fn1", lambda: 1)
    srv.register("fn2", lambda: 2)
    fns = srv.registered_functions()
    assert "fn1" in fns
    assert "fn2" in fns


def test_function_names_includes_registered():
    srv = SauravEmbed()
    srv.register("pyfn", lambda: 1)
    assert "pyfn" in srv.function_names


def test_function_names_includes_sauravcode_fns():
    srv = SauravEmbed()
    srv.run("function myfunc x\n    return x")
    assert "myfunc" in srv.function_names


# ── Error Handling ───────────────────────────────────────────────

def test_throw_error():
    srv = SauravEmbed()
    result = srv.run('throw "oops"')
    assert not result.success
    assert result.error_type == "throw"
    assert "oops" in result.error


def test_syntax_error():
    srv = SauravEmbed()
    result = srv.run("if if if")
    assert not result.success
    assert result.error_type == "syntax"


def test_runtime_error():
    srv = SauravEmbed()
    result = srv.run("nosuchfn 42")
    assert not result.success
    assert result.error_type == "runtime"


def test_partial_output_on_error():
    srv = SauravEmbed()
    result = srv.run('print "before"\nthrow "boom"')
    assert "before" in result.output
    assert not result.success


def test_variables_preserved_on_error():
    srv = SauravEmbed()
    srv.run("x = 42")
    result = srv.run('throw "err"')
    assert not result.success
    assert "x" in result.variables
    assert result.variables["x"] == 42


# ── Eval ─────────────────────────────────────────────────────────

def test_eval_expression():
    srv = SauravEmbed()
    assert srv.eval("3 + 4") == 7


def test_eval_with_variables():
    srv = SauravEmbed()
    srv.set("x", 10)
    assert srv.eval("x * 2") == 20


def test_eval_error_raises():
    srv = SauravEmbed()
    try:
        srv.eval("nosuchvar + 1")
        assert False, "Should have raised"
    except ValueError:
        pass


# ── State Management ────────────────────────────────────────────

def test_persistent_state():
    srv = SauravEmbed()
    srv.run("x = 1")
    srv.run("y = x + 1")
    assert srv.get("y") == 2


def test_reset():
    srv = SauravEmbed()
    srv.run("x = 42")
    srv.reset()
    assert srv.get("x") is None
    assert srv.run_count == 0


def test_reset_preserves_registered():
    srv = SauravEmbed()
    srv.register("triple", lambda x: x * 3)
    srv.run("a = 1")
    srv.reset()
    assert srv.get("a") is None
    srv.run("t = triple 5")
    assert srv.get("t") == 15


def test_run_count():
    srv = SauravEmbed()
    assert srv.run_count == 0
    srv.run("x = 1")
    srv.run("y = 2")
    assert srv.run_count == 2


def test_context_manager():
    with SauravEmbed() as srv:
        srv.run("foo = 99")
        assert srv.get("foo") == 99


# ── Isolation ────────────────────────────────────────────────────

def test_isolated_instances():
    a = SauravEmbed()
    b = SauravEmbed()
    a.run("x = 100")
    b.run("x = 200")
    assert a.get("x") == 100
    assert b.get("x") == 200


# ── Bulk Operations ─────────────────────────────────────────────

def test_run_many():
    srv = SauravEmbed()
    results = srv.run_many(["a = 1", "b = a + 2", "c = b * 3"])
    assert all(r.success for r in results)
    assert srv.get("c") == 9


def test_run_many_stops_on_error():
    srv = SauravEmbed()
    results = srv.run_many(["d = 10", 'throw "stop"', "e = 20"])
    assert len(results) == 2
    assert results[0].success
    assert not results[1].success
    assert srv.get("e") is None


# ── File Execution ──────────────────────────────────────────────

def test_run_file():
    srv = SauravEmbed()
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hello_path = os.path.join(script_dir, "hello.srv")
    if os.path.isfile(hello_path):
        result = srv.run_file(hello_path)
        assert result.success
        assert "Hello, World!" in result.output


def test_run_file_not_found():
    srv = SauravEmbed()
    result = srv.run_file("nonexistent_file.srv")
    assert not result.success
    assert "not found" in result.error.lower()


def test_run_file_with_temp():
    srv = SauravEmbed()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".srv", delete=False, encoding="utf-8"
    ) as f:
        f.write('x = 42\nprint x')
        f.flush()
        result = srv.run_file(f.name)
    os.unlink(f.name)
    assert result.success
    assert "42" in result.output
    assert srv.get("x") == 42


# ── Sauravcode Features ────────────────────────────────────────

def test_function_definition():
    srv = SauravEmbed()
    srv.run("function greet name\n    return f\"Hi {name}\"")
    srv.run('msg = greet "Alice"')
    assert srv.get("msg") == "Hi Alice"


def test_return_value():
    srv = SauravEmbed()
    srv.run("function add_one n\n    return n + 1")
    result = srv.run("add_one 5")
    assert result.return_value == 6


def test_enum():
    srv = SauravEmbed()
    srv.run("enum Color\n    RED\n    GREEN\n    BLUE")
    assert "Color" in srv.enum_names


def test_list_comprehension():
    srv = SauravEmbed()
    srv.run("squares = [x * x for x in [1, 2, 3, 4, 5]]")
    assert srv.get("squares") == [1, 4, 9, 16, 25]


# ── Chaining ─────────────────────────────────────────────────────

def test_set_chaining():
    srv = SauravEmbed()
    result = srv.set("a", 1).set("b", 2)
    assert result is srv


def test_register_chaining():
    srv = SauravEmbed()
    result = srv.register("fn1", lambda: 1).register("fn2", lambda: 2)
    assert result is srv


# ── Repr ─────────────────────────────────────────────────────────

def test_repr():
    srv = SauravEmbed()
    srv.set("x", 1)
    srv.register("f", lambda: 1)
    r = repr(srv)
    assert "SauravEmbed" in r
    assert "vars=1" in r
    assert "python_fns=1" in r


# ── Runner ───────────────────────────────────────────────────────

if __name__ == "__main__":
    # Simple test runner — collect all test_* functions and run them
    test_fns = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]

    passed = 0
    failed = 0
    errors = []
    for name, fn in test_fns:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as e:
            failed += 1
            errors.append((name, e))
            print(f"  FAIL  {name}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {passed + failed}")
    if errors:
        print("\nFailures:")
        for name, e in errors:
            print(f"  {name}: {e}")
        sys.exit(1)

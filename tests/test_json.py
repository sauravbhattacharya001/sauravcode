"""Tests for JSON built-in functions: json_parse, json_stringify, json_pretty."""
import pytest
import subprocess
import sys
import os
import tempfile

INTERPRETER = os.path.join(os.path.dirname(__file__), '..', 'saurav.py')


def run_srv(code):
    """Run sauravcode and return stdout."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False) as f:
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


class TestJsonStringify:
    def test_map(self):
        out = run_srv('print json_stringify {"a": 1}')
        assert out == '{"a":1}'

    def test_list(self):
        out = run_srv('print json_stringify [1, 2, 3]')
        assert out == '[1,2,3]'

    def test_string(self):
        out = run_srv('print json_stringify "hello"')
        assert out == '"hello"'

    def test_number(self):
        out = run_srv('print json_stringify 42')
        assert out == '42'

    def test_bool_true(self):
        out = run_srv('print json_stringify true')
        assert out == 'true'

    def test_bool_false(self):
        out = run_srv('print json_stringify false')
        assert out == 'false'

    def test_nested(self):
        out = run_srv('print json_stringify {"a": [1, 2], "b": {"c": 3}}')
        assert '"a":[1,2]' in out
        assert '"b":{"c":3}' in out

    def test_empty_map(self):
        out = run_srv('print json_stringify {}')
        assert out == '{}'

    def test_empty_list(self):
        out = run_srv('print json_stringify []')
        assert out == '[]'


class TestJsonPretty:
    def test_map(self):
        out = run_srv('print json_pretty {"x": 1}')
        assert '"x": 1' in out
        assert '\n' in out

    def test_list(self):
        out = run_srv('print json_pretty [1, 2]')
        assert '1,' in out
        assert '\n' in out


class TestJsonParse:
    def test_roundtrip_map(self):
        code = '''
data = {"name": "Alice", "age": 30}
s = json_stringify data
restored = json_parse s
print restored["name"]
print restored["age"]
'''
        out = run_srv(code)
        assert 'Alice' in out
        assert '30' in out

    def test_roundtrip_list(self):
        code = '''
data = [1, 2, 3]
s = json_stringify data
restored = json_parse s
print len restored
'''
        out = run_srv(code)
        assert '3' in out

    def test_nested_access(self):
        code = '''
data = {"server": {"host": "localhost", "port": 8080}}
s = json_stringify data
obj = json_parse s
print obj["server"]["host"]
'''
        out = run_srv(code)
        assert out == 'localhost'

    def test_parse_with_booleans(self):
        code = '''
data = {"active": true, "deleted": false}
s = json_stringify data
obj = json_parse s
print obj["active"]
print obj["deleted"]
'''
        out = run_srv(code)
        lines = out.split('\n')
        assert lines[0].strip() == 'true'
        assert lines[1].strip() == 'false'

    def test_empty_structures(self):
        code = '''
m = json_parse "{}"
print len (keys m)
a = json_parse "[]"
print len a
'''
        out = run_srv(code)
        lines = out.split('\n')
        assert lines[0].strip() == '0'
        assert lines[1].strip() == '0'

    def test_invalid_json(self):
        with pytest.raises(RuntimeError):
            run_srv('json_parse "not valid json"')

    def test_non_string_arg(self):
        with pytest.raises(RuntimeError):
            run_srv('json_parse 42')


class TestJsonIntegration:
    def test_stringify_then_parse_preserves_types(self):
        code = '''
data = {"str": "hello", "num": 3.14, "bool": true, "list": [1, 2]}
s = json_stringify data
obj = json_parse s
v1 = obj["str"]
v2 = obj["num"]
v3 = obj["bool"]
v4 = obj["list"]
print type_of v1
print type_of v2
print type_of v3
print type_of v4
'''
        out = run_srv(code)
        lines = [l.strip() for l in out.split('\n')]
        assert lines[0] == 'string'
        assert lines[1] == 'number'
        assert lines[2] == 'bool'
        assert lines[3] == 'list'

    def test_pretty_then_parse(self):
        code = '''
data = {"x": 1, "y": 2}
p = json_pretty data
restored = json_parse p
print restored["x"]
print restored["y"]
'''
        out = run_srv(code)
        lines = out.split('\n')
        assert '1' in lines[-2]
        assert '2' in lines[-1]

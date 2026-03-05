"""Tests for sauravdoc — documentation generator for sauravcode."""

import json
import os
import sys
import tempfile
import pytest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravdoc import SourceParser, MarkdownGenerator, HtmlGenerator, JsonGenerator, DocItem


# ─── Fixtures ────────────────────────────────────────────────────────────────

SAMPLE_SOURCE = """\
# Sample module
# This is a test module for sauravdoc

import utils
import math_helpers

# Calculate the sum of two numbers
# x: first number
# y: second number
function add x y
    return x + y  # the sum

# Private helper
function _internal_helper val
    return val * 2

# --- Math Operations ---

# Multiply two numbers
function multiply a b
    return a * b

# Directions enum
# Represents cardinal directions
enum Direction
    North
    South
    East
    West

# Application config
max_retries = 5

# The greeting message
greeting = "hello world"

_secret = "hidden"
"""

MINIMAL_SOURCE = """\
function greet name
    print name
"""

EMPTY_SOURCE = ""

DECORATED_SOURCE = """\
# Cached fibonacci
@memoize
function fib n
    if n <= 1
        return n
    return fib(n - 1) + fib(n - 2)
"""

ENUM_SOURCE = """\
# Color options for rendering
enum Color
    Red
    Green
    Blue
    Alpha

# Status codes
enum Status
    Active
    Inactive
    Pending
"""

SECTION_SOURCE = """\
# --- Utilities ---

function util_a
    return 1

# --- Core Logic ---

function core_b
    return 2
"""


# ─── SourceParser Tests ─────────────────────────────────────────────────────

class TestSourceParser:
    def test_module_comment_extracted(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        assert 'Sample module' in parser.module_comment
        assert 'test module' in parser.module_comment

    def test_functions_found(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        funcs = [i for i in parser.items if i.kind == 'function']
        names = [f.name for f in funcs]
        assert 'add' in names
        assert 'multiply' in names
        assert '_internal_helper' in names

    def test_function_params(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        add = next(i for i in parser.items if i.name == 'add')
        assert add.params == ['x', 'y']

    def test_function_comment(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        add = next(i for i in parser.items if i.name == 'add')
        assert 'sum of two numbers' in add.comment

    def test_function_return_comment(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        add = next(i for i in parser.items if i.name == 'add')
        assert 'the sum' in add.return_comment

    def test_enums_found(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        enums = [i for i in parser.items if i.kind == 'enum']
        assert len(enums) == 1
        assert enums[0].name == 'Direction'

    def test_enum_variants(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        direction = next(i for i in parser.items if i.name == 'Direction')
        assert 'North' in direction.params
        assert 'West' in direction.params
        assert len(direction.params) == 4

    def test_enum_comment(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        direction = next(i for i in parser.items if i.name == 'Direction')
        assert 'cardinal directions' in direction.comment

    def test_variables_found(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        variables = [i for i in parser.items if i.kind == 'variable']
        names = [v.name for v in variables]
        assert 'max_retries' in names
        assert 'greeting' in names

    def test_variable_value(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        mr = next(i for i in parser.items if i.name == 'max_retries')
        assert mr.params[0] == '5'

    def test_variable_comment(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gr = next(i for i in parser.items if i.name == 'greeting')
        assert 'greeting message' in gr.comment

    def test_imports_found(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        imports = [i for i in parser.items if i.kind == 'import']
        names = [i.name for i in imports]
        assert 'utils' in names
        assert 'math_helpers' in names

    def test_sections_found(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        sections = [i for i in parser.items if i.kind == 'section']
        names = [s.name for s in sections]
        assert 'Math Operations' in names

    def test_items_sorted_by_line(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        line_numbers = [i.line_number for i in parser.items]
        assert line_numbers == sorted(line_numbers)

    def test_private_detection(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        helper = next(i for i in parser.items if i.name == '_internal_helper')
        assert helper.is_private()
        add = next(i for i in parser.items if i.name == 'add')
        assert not add.is_private()

    def test_empty_source(self):
        parser = SourceParser(EMPTY_SOURCE, 'empty.srv')
        assert parser.items == []
        assert parser.module_comment == ''

    def test_minimal_source(self):
        parser = SourceParser(MINIMAL_SOURCE, 'min.srv')
        funcs = [i for i in parser.items if i.kind == 'function']
        assert len(funcs) == 1
        assert funcs[0].name == 'greet'
        assert funcs[0].params == ['name']

    def test_decorated_function(self):
        parser = SourceParser(DECORATED_SOURCE, 'dec.srv')
        fib = next(i for i in parser.items if i.name == 'fib')
        assert 'memoize' in fib.decorators

    def test_multiple_enums(self):
        parser = SourceParser(ENUM_SOURCE, 'enums.srv')
        enums = [i for i in parser.items if i.kind == 'enum']
        assert len(enums) == 2
        color = next(e for e in enums if e.name == 'Color')
        assert len(color.params) == 4
        status = next(e for e in enums if e.name == 'Status')
        assert len(status.params) == 3

    def test_section_extraction(self):
        parser = SourceParser(SECTION_SOURCE, 'sec.srv')
        sections = [i for i in parser.items if i.kind == 'section']
        assert len(sections) == 2

    def test_no_false_variable_on_keywords(self):
        source = "function test\n    return 1\n"
        parser = SourceParser(source, 't.srv')
        variables = [i for i in parser.items if i.kind == 'variable']
        assert len(variables) == 0


# ─── Stats Tests ─────────────────────────────────────────────────────────────

class TestStats:
    def test_stats_keys(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        stats = parser.get_stats()
        expected_keys = ['total_lines', 'code_lines', 'blank_lines', 'comment_lines',
                         'functions', 'enums', 'variables', 'imports',
                         'avg_function_length', 'documentation_ratio', 'comment_ratio']
        for key in expected_keys:
            assert key in stats

    def test_function_count(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        stats = parser.get_stats()
        assert stats['functions'] == 3

    def test_enum_count(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        stats = parser.get_stats()
        assert stats['enums'] == 1

    def test_empty_stats(self):
        parser = SourceParser(EMPTY_SOURCE, 'empty.srv')
        stats = parser.get_stats()
        assert stats['functions'] == 0
        assert stats['documentation_ratio'] == 100.0

    def test_comment_ratio(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        stats = parser.get_stats()
        assert stats['comment_ratio'] > 0
        assert stats['comment_ratio'] < 100


# ─── MarkdownGenerator Tests ────────────────────────────────────────────────

class TestMarkdownGenerator:
    def test_title_present(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert '# test' in md

    def test_module_comment_in_output(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert 'Sample module' in md

    def test_function_documented(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert '`add x y`' in md
        assert '`multiply a b`' in md

    def test_private_excluded_by_default(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser, include_private=False)
        md = gen.generate()
        assert '_internal_helper' not in md

    def test_private_included_when_requested(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser, include_private=True)
        md = gen.generate()
        assert '_internal_helper' in md

    def test_toc_present(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser, include_toc=True)
        md = gen.generate()
        assert 'Table of Contents' in md

    def test_toc_excluded(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser, include_toc=False)
        md = gen.generate()
        assert 'Table of Contents' not in md

    def test_stats_included(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser, include_stats=True)
        md = gen.generate()
        assert 'Statistics' in md
        assert 'Total lines' in md

    def test_stats_excluded_by_default(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert 'Statistics' not in md

    def test_enum_in_output(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert '`Direction`' in md
        assert 'North' in md

    def test_variables_in_output(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert 'max_retries' in md
        assert '5' in md

    def test_imports_in_output(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert 'import utils' in md

    def test_source_included(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser, include_source=True)
        md = gen.generate()
        assert '<details>' in md
        assert 'Source' in md

    def test_source_excluded_by_default(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert '<details>' not in md

    def test_footer_present(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert 'Generated by sauravdoc' in md

    def test_param_description_extracted(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert 'first number' in md

    def test_return_comment_in_output(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert 'the sum' in md

    def test_decorators_shown(self):
        parser = SourceParser(DECORATED_SOURCE, 'dec.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert '@memoize' in md


# ─── HtmlGenerator Tests ────────────────────────────────────────────────────

class TestHtmlGenerator:
    def test_html_output(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = HtmlGenerator(parser)
        html = gen.generate()
        assert '<!DOCTYPE html>' in html
        assert 'sauravdoc' in html

    def test_html_escaping(self):
        source = '# Test with <angle> & "quotes"\nfunction test\n    return 1\n'
        parser = SourceParser(source, 'esc.srv')
        gen = HtmlGenerator(parser)
        html = gen.generate()
        assert '&lt;angle&gt;' in html
        assert '&amp;' in html


# ─── JsonGenerator Tests ────────────────────────────────────────────────────

class TestJsonGenerator:
    def test_valid_json(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = JsonGenerator(parser)
        result = gen.generate()
        data = json.loads(result)
        assert 'file' in data
        assert 'items' in data
        assert 'stats' in data

    def test_json_function_entry(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = JsonGenerator(parser)
        data = json.loads(gen.generate())
        funcs = [i for i in data['items'] if i['kind'] == 'function']
        assert len(funcs) >= 2
        add = next(f for f in funcs if f['name'] == 'add')
        assert add['params'] == ['x', 'y']

    def test_json_private_excluded(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = JsonGenerator(parser, include_private=False)
        data = json.loads(gen.generate())
        names = [i['name'] for i in data['items']]
        assert '_internal_helper' not in names
        assert '_secret' not in names

    def test_json_private_included(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = JsonGenerator(parser, include_private=True)
        data = json.loads(gen.generate())
        names = [i['name'] for i in data['items']]
        assert '_internal_helper' in names

    def test_json_enum_variants(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = JsonGenerator(parser)
        data = json.loads(gen.generate())
        enums = [i for i in data['items'] if i['kind'] == 'enum']
        assert len(enums) == 1
        assert 'variants' in enums[0]
        assert 'North' in enums[0]['variants']


# ─── DocItem Tests ───────────────────────────────────────────────────────────

class TestDocItem:
    def test_is_private(self):
        item = DocItem('function', '_helper', 1)
        assert item.is_private()

    def test_not_private(self):
        item = DocItem('function', 'helper', 1)
        assert not item.is_private()

    def test_repr(self):
        item = DocItem('function', 'test', 42)
        assert 'function' in repr(item)
        assert 'test' in repr(item)

    def test_defaults(self):
        item = DocItem('variable', 'x', 1)
        assert item.params == []
        assert item.comment == ''
        assert item.decorators == []


# ─── File I/O Tests ─────────────────────────────────────────────────────────

class TestFileIO:
    def test_directory_documentation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create sample files
            (Path(tmpdir) / 'a.srv').write_text(
                '# Module A\nfunction foo x\n    return x\n')
            (Path(tmpdir) / 'b.srv').write_text(
                '# Module B\nfunction bar y\n    return y\n')
            outdir = Path(tmpdir) / 'docs'

            from sauravdoc import document_directory
            document_directory(tmpdir, str(outdir), format='markdown')

            assert (outdir / 'a.md').exists()
            assert (outdir / 'b.md').exists()
            assert (outdir / 'index.md').exists()

    def test_index_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / 'test.srv').write_text(
                'function hello\n    print "hi"\n')
            outdir = Path(tmpdir) / 'docs'

            from sauravdoc import document_directory
            document_directory(tmpdir, str(outdir))

            index = (outdir / 'index.md').read_text()
            assert 'Documentation Index' in index
            assert 'test.srv' in index


# ─── Edge Cases ──────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_function_no_params(self):
        source = 'function init\n    return 0\n'
        parser = SourceParser(source, 't.srv')
        func = next(i for i in parser.items if i.kind == 'function')
        assert func.params == []

    def test_multiline_comment_block(self):
        source = '# Line 1\n# Line 2\n# Line 3\nfunction documented\n    return 1\n'
        parser = SourceParser(source, 't.srv')
        func = next(i for i in parser.items if i.kind == 'function')
        assert 'Line 1' in func.comment
        assert 'Line 3' in func.comment

    def test_no_comment_function(self):
        source = 'function bare\n    return 1\n'
        parser = SourceParser(source, 't.srv')
        func = next(i for i in parser.items if i.kind == 'function')
        assert func.comment == ''

    def test_special_characters_in_string_value(self):
        source = 'msg = "hello \\"world\\""\n'
        parser = SourceParser(source, 't.srv')
        var = next(i for i in parser.items if i.kind == 'variable')
        assert var.name == 'msg'

    def test_body_extraction_stops_at_dedent(self):
        source = 'function a\n    return 1\nfunction b\n    return 2\n'
        parser = SourceParser(source, 't.srv')
        funcs = [i for i in parser.items if i.kind == 'function']
        assert len(funcs) == 2
        assert len(funcs[0].body_lines) == 1

    def test_filename_in_output(self):
        parser = SourceParser('function x\n    return 1\n', 'myfile.srv')
        gen = MarkdownGenerator(parser)
        md = gen.generate()
        assert 'myfile.srv' in md

    def test_json_roundtrip_structure(self):
        parser = SourceParser(SAMPLE_SOURCE, 'test.srv')
        gen = JsonGenerator(parser)
        data = json.loads(gen.generate())
        assert isinstance(data['stats']['total_lines'], int)
        assert isinstance(data['items'], list)

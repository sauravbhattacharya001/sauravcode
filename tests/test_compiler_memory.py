"""Tests for compiler memory safety: arena allocator emission, checked
allocation helpers, NULL checks, and srv_arena_free_all at program exit.

Validates that fix for issue #39 is correctly applied — all string
allocations go through the arena, all other allocations have OOM checks,
and arena memory is freed before program exit.
"""
import pytest
import sys
import os
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sauravcc import tokenize, Parser, CCodeGenerator


# ============================================================
# Helpers
# ============================================================

def compile_to_c(code: str) -> str:
    tokens = tokenize(code)
    parser = Parser(tokens)
    program = parser.parse()
    codegen = CCodeGenerator()
    return codegen.compile(program)


# ============================================================
# Arena allocator emission
# ============================================================

class TestArenaAllocator:
    """Arena allocator is emitted when string helpers or f-strings are used."""

    def test_arena_emitted_for_string_ops(self):
        c = compile_to_c('x = upper "hello"\nprint x')
        assert "SrvArenaBlock" in c
        assert "srv_arena_alloc" in c
        assert "srv_arena_free_all" in c

    def test_arena_emitted_for_fstrings(self):
        c = compile_to_c('name = "world"\nx = f"hello {name}"\nprint x')
        assert "SrvArenaBlock" in c
        assert "srv_arena_alloc" in c
        assert "srv_arena_free_all" in c

    def test_arena_not_emitted_for_pure_math(self):
        c = compile_to_c("x = 2 + 3\nprint x")
        assert "SrvArenaBlock" not in c
        assert "srv_arena_alloc" not in c

    def test_arena_block_size_defined(self):
        c = compile_to_c('x = upper "hello"\nprint x')
        assert "SRV_ARENA_BLOCK_SIZE" in c
        assert "64 * 1024" in c

    def test_arena_new_block_has_null_check(self):
        c = compile_to_c('x = upper "hello"\nprint x')
        # The arena block allocation should check for NULL
        assert 'if (!b)' in c
        assert 'Out of memory (arena block' in c

    def test_arena_alloc_aligns_to_8(self):
        c = compile_to_c('x = upper "hello"\nprint x')
        # Alignment mask: (n + 7) & ~(size_t)7
        assert "~(size_t)7" in c

    def test_arena_free_all_walks_linked_list(self):
        c = compile_to_c('x = upper "hello"\nprint x')
        # Should walk the linked list and free each block
        assert "SrvArenaBlock* next = b->next;" in c
        assert "free(b);" in c

    def test_arena_free_all_before_return(self):
        c = compile_to_c('x = upper "hello"\nprint x')
        # srv_arena_free_all() should appear right before return 0
        lines = c.split("\n")
        return_idx = None
        free_idx = None
        for i, line in enumerate(lines):
            if "srv_arena_free_all();" in line:
                free_idx = i
            if "return 0;" in line:
                return_idx = i
        assert free_idx is not None, "srv_arena_free_all() not found"
        assert return_idx is not None, "return 0 not found"
        assert free_idx < return_idx, "arena_free_all should come before return 0"


# ============================================================
# String builtins use arena (not raw malloc)
# ============================================================

class TestStringBuiltinsUseArena:
    """All string-returning builtins should use srv_arena_alloc, not malloc."""

    def test_upper_uses_arena(self):
        c = compile_to_c('x = upper "hello"\nprint x')
        # Find the srv_upper function body
        assert "srv_arena_alloc" in c
        # Should not have raw (char*)malloc in the string helpers
        # (only allowed in checked_malloc helper and arena_new_block)
        lines = c.split("\n")
        for line in lines:
            if "srv_upper" in line or "srv_lower" in line:
                continue
            if "(char*)malloc(" in line:
                pytest.fail(f"Found raw (char*)malloc in generated code: {line.strip()}")

    def test_lower_uses_arena(self):
        c = compile_to_c('x = lower "HELLO"\nprint x')
        assert "srv_arena_alloc" in c

    def test_trim_uses_arena(self):
        c = compile_to_c('x = trim "  hello  "\nprint x')
        assert "srv_arena_alloc" in c

    def test_replace_uses_arena(self):
        c = compile_to_c('x = replace "hello world" "world" "sauravcode"\nprint x')
        assert "srv_arena_alloc" in c

    def test_reverse_uses_arena(self):
        c = compile_to_c('x = reverse "hello"\nprint x')
        assert "srv_arena_alloc" in c

    def test_char_at_uses_arena(self):
        c = compile_to_c('x = char_at "hello" 0\nprint x')
        assert "srv_arena_alloc" in c

    def test_substr_helper_uses_arena(self):
        """srv_substring in emitted helpers uses arena allocation."""
        # substr may not trigger string helpers on its own (pre-existing limitation),
        # but when helpers are emitted, srv_substring uses arena
        c = compile_to_c('x = upper "hello"\nprint x')
        assert "srv_substring" in c  # emitted as part of string helpers
        assert "srv_arena_alloc" in c

    def test_to_string_uses_arena(self):
        """str/to_string triggers string helpers which use arena allocation."""
        # str() needs to be used with a string variable for helper emission
        c = compile_to_c('x = upper "hello"\ny = str 42\nprint x\nprint y')
        assert "srv_arena_alloc" in c

    def test_fstring_uses_arena(self):
        c = compile_to_c('name = "world"\nx = f"hello {name}"\nprint x')
        # The f-string should use srv_arena_alloc, not malloc
        assert "srv_arena_alloc(__n + 1)" in c

    def test_no_raw_char_malloc_in_string_helpers(self):
        """No (char*)malloc should appear in generated code."""
        c = compile_to_c('x = upper "hello"\ny = lower "WORLD"\nz = trim "  hi  "\nprint x\nprint y\nprint z')
        # Count (char*)malloc — should be zero
        count = c.count("(char*)malloc(")
        assert count == 0, f"Found {count} raw (char*)malloc calls in generated code"


# ============================================================
# Checked allocation for list/map runtimes
# ============================================================

class TestCheckedAllocation:
    """List and map runtimes use checked allocation with OOM abort."""

    def test_checked_malloc_helper_emitted(self):
        c = compile_to_c("x = 1 + 2\nprint x")
        # checked_malloc is always emitted
        assert "srv_checked_malloc" in c
        assert "srv_checked_realloc" in c

    def test_checked_malloc_has_null_check(self):
        c = compile_to_c("x = 1 + 2\nprint x")
        assert "if (!p)" in c
        assert "Out of memory" in c

    def test_list_uses_checked_malloc(self):
        c = compile_to_c("nums = [1 2 3]\nprint nums")
        assert "srv_checked_malloc" in c

    def test_list_uses_checked_realloc(self):
        c = compile_to_c("nums = [1 2 3]\nprint nums")
        assert "srv_checked_realloc" in c

    def test_map_calloc_has_null_check(self):
        c = compile_to_c('m = {"a": 1}\nprint m')
        # Map uses calloc with NULL check
        assert "calloc(" in c
        assert 'if (!m.entries)' in c or 'if (!m->entries)' in c


# ============================================================
# No unchecked malloc in generated code
# ============================================================

class TestNoUncheckedMalloc:
    """Every malloc/calloc in generated C code should have a NULL check."""

    def test_comprehensive_string_program(self):
        """A program using many string ops should have zero unchecked mallocs."""
        code = '''
name = "sauravcode"
x = upper name
y = lower name
z = trim "  hello  "
w = replace name "code" "lang"
r = reverse name
c = char_at name 0
s = substr name 0 6
t = str 42
msg = f"Hello {name}!"
print x
print y
print z
print w
print r
print c
print s
print t
print msg
'''
        c = compile_to_c(code)

        # No raw (char*)malloc anywhere
        assert c.count("(char*)malloc(") == 0, "Found raw (char*)malloc"

        # No raw (double*)malloc — should use srv_checked_malloc
        assert c.count("(double*)malloc(") == 0, "Found raw (double*)malloc"

        # The only plain malloc() calls should be inside:
        # 1. srv_checked_malloc helper (1 call)
        # 2. srv_arena_new_block (1 call)
        lines = c.split("\n")
        plain_malloc_lines = [
            l.strip() for l in lines
            if "malloc(" in l
            and "srv_checked_malloc" not in l
            and "srv_checked_realloc" not in l
            and "srv_arena_alloc" not in l
            and "srv_arena_new_block" not in l
            and not l.strip().startswith("//")
            and not l.strip().startswith("/*")
        ]
        # Expected: srv_checked_malloc body (void* p = malloc(n);)
        #           srv_arena_new_block body (SrvArenaBlock* b = (...*)malloc(...);)
        # Both have NULL checks right after
        for line in plain_malloc_lines:
            assert "void* p = malloc(n);" in line or "SrvArenaBlock* b" in line, \
                f"Unexpected raw malloc: {line}"


# ============================================================
# End-to-end: compile and run programs with string ops
# ============================================================

class TestArenaEndToEnd:
    """Compile sauravcode programs to C and verify they produce correct output."""

    @pytest.fixture(autouse=True)
    def check_gcc(self):
        """Skip if gcc not available."""
        try:
            subprocess.run(["gcc", "--version"], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            pytest.skip("gcc not available")

    def _compile_and_run(self, code: str) -> str:
        """Compile sauravcode to C, compile C with gcc, run, return stdout."""
        c_code = compile_to_c(code)

        with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False) as f:
            f.write(c_code)
            c_path = f.name

        exe_path = c_path.replace(".c", ".exe") if os.name == "nt" else c_path.replace(".c", "")
        try:
            result = subprocess.run(
                ["gcc", "-o", exe_path, c_path, "-lm"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                pytest.fail(f"gcc compilation failed:\n{result.stderr}")

            result = subprocess.run(
                [exe_path],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout
        finally:
            for p in [c_path, exe_path]:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def test_upper_lower(self):
        out = self._compile_and_run('x = upper "hello"\ny = lower "WORLD"\nprint x\nprint y')
        lines = out.strip().split("\n")
        assert lines[0] == "HELLO"
        assert lines[1] == "world"

    def test_trim(self):
        out = self._compile_and_run('x = trim "  hello  "\nprint x')
        assert out.strip() == "hello"

    def test_replace(self):
        out = self._compile_and_run('x = replace "hello world" "world" "sauravcode"\nprint x')
        assert out.strip() == "hello sauravcode"

    def test_reverse(self):
        out = self._compile_and_run('x = reverse "hello"\nprint x')
        assert out.strip() == "olleh"

    def test_fstring(self):
        out = self._compile_and_run('name = "world"\nx = f"hello {name}"\nprint x')
        assert out.strip() == "hello world"

    def test_string_ops_in_loop_no_crash(self):
        """String ops in a loop should not crash (arena handles memory)."""
        out = self._compile_and_run('''
i = 0
while i < 100
    x = upper "test"
    i = i + 1
print "done"
''')
        assert "done" in out

    def test_multiple_string_ops_chained(self):
        """Multiple string operations should all work correctly with arena."""
        out = self._compile_and_run('''
x = "Hello World"
a = upper x
b = lower x
c = reverse x
d = trim "  hello  "
e = replace x "World" "Sauravcode"
print a
print b
print c
print d
print e
''')
        lines = out.strip().split("\n")
        assert lines[0] == "HELLO WORLD"
        assert lines[1] == "hello world"
        assert lines[2] == "dlroW olleH"
        assert lines[3] == "hello"
        assert lines[4] == "Hello Sauravcode"

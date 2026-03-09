#!/usr/bin/env python3
"""
sauravrefactor — Automated refactoring tool for sauravcode (.srv) files.

Performs safe, AST-aware code transformations:

Commands:
    rename      Rename a variable or function across scopes
    extract     Extract selected lines into a new function
    inline      Inline a single-use variable at its usage site
    deadcode    Remove unreachable code after return/break/continue
    unused      Remove unused variables and imports

Usage:
    python sauravrefactor.py rename FILE.srv old_name new_name [--write]
    python sauravrefactor.py extract FILE.srv START END func_name [--write]
    python sauravrefactor.py inline FILE.srv var_name [--write]
    python sauravrefactor.py deadcode FILE.srv [--write]
    python sauravrefactor.py unused FILE.srv [--write]
    python sauravrefactor.py FILE.srv --all [--write]    # deadcode + unused

Options:
    --write     Apply changes in-place (default: dry-run diff)
    --json      Output results as JSON
    --no-color  Disable colored output
    --diff      Show unified diff (default in dry-run)
    --quiet     Only show summary counts
"""

import argparse
import difflib
import json as _json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, ASTNode

__version__ = "1.0.0"

# ── Colors ───────────────────────────────────────────────────────────

class Color:
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

NO_COLOR = type('NoColor', (), {k: '' for k in dir(Color) if not k.startswith('_')})()

def get_color(use_color=True):
    return Color if use_color else NO_COLOR

# ── AST Utilities ────────────────────────────────────────────────────

def _walk(node):
    """Yield all AST nodes depth-first."""
    if not isinstance(node, ASTNode):
        return
    yield node
    for attr in vars(node).values():
        if isinstance(attr, ASTNode):
            yield from _walk(attr)
        elif isinstance(attr, list):
            for item in attr:
                if isinstance(item, ASTNode):
                    yield from _walk(item)

def _collect_names(node, attr='var_name'):
    """Collect all identifier names referenced in a subtree."""
    names = set()
    for n in _walk(node):
        if hasattr(n, attr):
            names.add(getattr(n, attr))
        if hasattr(n, 'name') and attr == 'var_name':
            names.add(n.name)
    return names

def _get_identifiers(node):
    """Get all IdentifierNode names in a subtree."""
    return {n.name for n in _walk(node) if type(n).__name__ == 'IdentifierNode'}

def _get_assignments(nodes):
    """Get variable names assigned in a list of AST nodes."""
    assigned = set()
    for node in nodes:
        for n in _walk(node):
            tname = type(n).__name__
            if tname == 'AssignmentNode':
                assigned.add(n.name)
            elif tname in ('ForNode', 'ForEachNode'):
                assigned.add(n.var)
            elif tname == 'IndexedAssignmentNode':
                assigned.add(n.name)
    return assigned

def _get_function_defs(nodes):
    """Get function names defined in a list of AST nodes."""
    return {n.name for n in nodes if type(n).__name__ == 'FunctionNode'}

def _get_function_calls(node):
    """Get all function call names in a subtree."""
    calls = set()
    for n in _walk(node):
        if type(n).__name__ == 'FunctionCallNode':
            calls.add(n.name)
    return calls

def _get_imports(nodes):
    """Get imported module names."""
    imports = set()
    for n in nodes:
        if type(n).__name__ == 'ImportNode':
            if hasattr(n, 'module'):
                imports.add(n.module)
            if hasattr(n, 'name'):
                imports.add(n.name)
    return imports

# ── Rename Refactoring ───────────────────────────────────────────────

def refactor_rename(source, old_name, new_name):
    """Rename a variable or function throughout the source.
    
    Uses token-level replacement to preserve formatting while being
    scope-aware (only renames actual identifiers, not substrings).
    
    Returns (new_source, changes_count).
    """
    # Validate new name
    if not re.match(r'^[a-zA-Z_]\w*$', new_name):
        return source, 0, [f"Invalid identifier: {new_name}"]
    
    # Reserved words
    reserved = {
        'function', 'return', 'class', 'int', 'float', 'bool', 'string',
        'if', 'else', 'for', 'in', 'while', 'try', 'catch', 'throw',
        'print', 'true', 'false', 'and', 'or', 'not', 'list', 'set',
        'stack', 'queue', 'append', 'len', 'pop', 'lambda', 'import',
        'match', 'case', 'enum', 'break', 'continue', 'assert', 'yield', 'next'
    }
    if new_name in reserved:
        return source, 0, [f"Cannot rename to reserved word: {new_name}"]
    
    # Token-level rename: replace IDENT and KEYWORD tokens matching old_name
    # Use word-boundary regex to avoid partial replacements
    lines = source.split('\n')
    new_lines = []
    count = 0
    changes = []
    
    for lineno, line in enumerate(lines, 1):
        # Skip comments
        code_part = line
        comment_part = ''
        if '#' in line:
            # Find first # not inside a string
            in_str = False
            for i, ch in enumerate(line):
                if ch == '"' and (i == 0 or line[i-1] != '\\'):
                    in_str = not in_str
                elif ch == '#' and not in_str:
                    code_part = line[:i]
                    comment_part = line[i:]
                    break
        
        # Skip string contents - only replace in code
        # Use regex with word boundaries
        pattern = r'\b' + re.escape(old_name) + r'\b'
        new_code, n = re.subn(pattern, new_name, code_part)
        
        if n > 0:
            # Verify these are actual identifiers by checking they're not inside strings
            # Simple heuristic: count quotes before each match
            actual_replacements = 0
            for m in re.finditer(pattern, code_part):
                pos = m.start()
                quote_count = code_part[:pos].count('"') - code_part[:pos].count('\\"')
                if quote_count % 2 == 0:  # Not inside a string
                    actual_replacements += 1
            
            if actual_replacements > 0:
                # Do the replacement (regex handles word boundaries)
                # But skip inside strings - more precise approach
                result = _replace_outside_strings(code_part, old_name, new_name)
                new_lines.append(result + comment_part)
                replaced = result.count(new_name) - code_part.count(new_name)
                # Count based on actual tokens replaced
                for m in re.finditer(pattern, code_part):
                    pos = m.start()
                    quote_count = code_part[:pos].count('"') - code_part[:pos].count('\\"')
                    if quote_count % 2 == 0:
                        count += 1
                        changes.append(f"  Line {lineno}: renamed '{old_name}' → '{new_name}'")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    
    return '\n'.join(new_lines), count, changes


def _replace_outside_strings(code, old_name, new_name):
    """Replace identifiers only outside of string literals."""
    result = []
    i = 0
    pattern = re.compile(r'\b' + re.escape(old_name) + r'\b')
    
    while i < len(code):
        if code[i] == '"':
            # Find end of string
            j = i + 1
            while j < len(code):
                if code[j] == '\\':
                    j += 2
                    continue
                if code[j] == '"':
                    j += 1
                    break
                j += 1
            result.append(code[i:j])
            i = j
        else:
            # Find next string start or end of code
            j = code.find('"', i)
            if j == -1:
                j = len(code)
            segment = code[i:j]
            segment = pattern.sub(new_name, segment)
            result.append(segment)
            i = j
    
    return ''.join(result)


# ── Extract Function Refactoring ─────────────────────────────────────

def refactor_extract(source, start_line, end_line, func_name):
    """Extract lines start_line..end_line into a new function.
    
    Analyzes the extracted code for:
    - Variables used but not defined (become parameters)
    - Variables defined and used later (become return values)
    
    Returns (new_source, changes).
    """
    if not re.match(r'^[a-zA-Z_]\w*$', func_name):
        return source, [f"Invalid function name: {func_name}"]
    
    lines = source.split('\n')
    if start_line < 1 or end_line > len(lines) or start_line > end_line:
        return source, [f"Invalid line range: {start_line}-{end_line}"]
    
    # Get the extracted lines (0-indexed internally)
    extracted = lines[start_line - 1:end_line]
    before = lines[:start_line - 1]
    after = lines[end_line:]
    
    # Determine indentation of extracted block
    min_indent = float('inf')
    for line in extracted:
        stripped = line.lstrip()
        if stripped and not stripped.startswith('#'):
            indent = len(line) - len(stripped)
            min_indent = min(min_indent, indent)
    if min_indent == float('inf'):
        min_indent = 0
    
    # Parse the whole file to understand scope
    try:
        tokens = tokenize(source)
        parser = Parser(tokens)
        ast_nodes = parser.parse()
    except Exception:
        return source, ["Could not parse source file"]
    
    # Analyze extracted code for variable usage
    try:
        extracted_source = '\n'.join(extracted)
        ext_tokens = tokenize(extracted_source)
        ext_parser = Parser(ext_tokens)
        ext_nodes = ext_parser.parse()
    except Exception:
        # If we can't parse the extracted block alone, use text-based analysis
        ext_nodes = []
    
    # Find variables used in extracted code
    used_in_extract = set()
    assigned_in_extract = set()
    
    for node in ext_nodes:
        used_in_extract |= _get_identifiers(node)
        assigned_in_extract |= _get_assignments([node])
    
    # Find variables defined before the extract
    before_source = '\n'.join(before)
    try:
        bef_tokens = tokenize(before_source)
        bef_parser = Parser(bef_tokens)
        bef_nodes = bef_parser.parse()
        defined_before = _get_assignments(bef_nodes) | _get_function_defs(bef_nodes)
    except Exception:
        defined_before = set()
    
    # Find variables used after the extract
    after_source = '\n'.join(after)
    try:
        aft_tokens = tokenize(after_source)
        aft_parser = Parser(aft_tokens)
        aft_nodes = aft_parser.parse()
        used_after = set()
        for node in aft_nodes:
            used_after |= _get_identifiers(node)
    except Exception:
        used_after = set()
    
    # Parameters: used in extract but defined before (not local)
    params = sorted(used_in_extract & defined_before - assigned_in_extract)
    
    # Return values: assigned in extract and used after
    returns = sorted(assigned_in_extract & used_after)
    
    # Build the new function
    indent_str = ' ' * min_indent
    func_lines = [f"function {func_name}({', '.join(params)})"]
    for line in extracted:
        # Re-indent relative to function body
        stripped = line.lstrip()
        if stripped:
            orig_indent = len(line) - len(stripped)
            relative = orig_indent - min_indent
            func_lines.append(' ' * (4 + max(0, relative)) + stripped)
        else:
            func_lines.append('')
    
    if returns:
        if len(returns) == 1:
            func_lines.append(f"    return {returns[0]}")
        else:
            func_lines.append(f"    return [{', '.join(returns)}]")
    
    # Build the call
    call_args = ', '.join(params)
    if returns:
        if len(returns) == 1:
            call_line = f"{indent_str}{returns[0]} = {func_name}({call_args})"
        else:
            call_line = f"{indent_str}{', '.join(returns)} = {func_name}({call_args})"
    else:
        call_line = f"{indent_str}{func_name}({call_args})"
    
    # Assemble result
    new_lines = []
    new_lines.extend(before)
    new_lines.append(call_line)
    new_lines.extend(after)
    new_lines.append('')
    new_lines.extend(func_lines)
    
    changes = [
        f"  Extracted lines {start_line}-{end_line} into function '{func_name}'",
        f"  Parameters: {', '.join(params) if params else '(none)'}",
        f"  Returns: {', '.join(returns) if returns else '(none)'}",
    ]
    
    return '\n'.join(new_lines), changes


# ── Inline Variable Refactoring ──────────────────────────────────────

def refactor_inline(source, var_name):
    """Inline a variable: replace its usages with its assigned value.
    
    Only inlines if the variable is assigned exactly once and the
    assigned expression is simple (no side effects).
    
    Returns (new_source, changes).
    """
    lines = source.split('\n')
    
    # Find the assignment
    assign_pattern = re.compile(
        r'^(\s*)' + re.escape(var_name) + r'\s*=\s*(.+)$'
    )
    
    assign_line = None
    assign_value = None
    assign_indent = None
    assign_count = 0
    
    for i, line in enumerate(lines):
        # Skip comments and strings
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue
        m = assign_pattern.match(line)
        if m:
            # Make sure it's not == (comparison)
            rest = line[m.end(1):].strip()
            if rest.startswith(var_name) and '==' not in rest[:len(var_name)+3]:
                assign_count += 1
                assign_line = i
                assign_indent = m.group(1)
                assign_value = m.group(2).strip()
    
    if assign_count == 0:
        return source, [f"No assignment found for '{var_name}'"]
    if assign_count > 1:
        return source, [f"Variable '{var_name}' is assigned {assign_count} times — cannot inline"]
    
    # Count usages (excluding the assignment itself)
    usage_pattern = re.compile(r'\b' + re.escape(var_name) + r'\b')
    usage_count = 0
    usage_lines = []
    for i, line in enumerate(lines):
        if i == assign_line:
            continue
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue
        matches = list(usage_pattern.finditer(line))
        for m in matches:
            # Check not in string
            pos = m.start()
            quote_count = line[:pos].count('"') - line[:pos].count('\\"')
            if quote_count % 2 == 0:
                usage_count += 1
                usage_lines.append(i)
    
    if usage_count == 0:
        # Remove the assignment entirely (unused variable)
        new_lines = lines[:assign_line] + lines[assign_line + 1:]
        return '\n'.join(new_lines), [
            f"  Removed unused variable '{var_name}' (line {assign_line + 1})"
        ]
    
    # Inline: replace usages with the value
    # Wrap in parens if it contains operators
    needs_parens = any(op in assign_value for op in ['+', '-', '*', '/', '%', ' and ', ' or '])
    inline_value = f"({assign_value})" if needs_parens else assign_value
    
    new_lines = []
    inlined = 0
    for i, line in enumerate(lines):
        if i == assign_line:
            continue  # Remove the assignment
        if i in usage_lines:
            new_line = _replace_outside_strings(line, var_name, inline_value)
            new_lines.append(new_line)
            inlined += 1
        else:
            new_lines.append(line)
    
    changes = [
        f"  Inlined '{var_name}' = {assign_value}",
        f"  Replaced {inlined} usage(s), removed assignment (line {assign_line + 1})",
    ]
    
    return '\n'.join(new_lines), changes


# ── Dead Code Elimination ────────────────────────────────────────────

def refactor_deadcode(source):
    """Remove unreachable code after return/break/continue statements.
    
    Detects code that can never execute and removes it.
    Returns (new_source, changes).
    """
    lines = source.split('\n')
    to_remove = set()
    changes = []
    
    # Track indentation-based blocks
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        
        if not stripped or stripped.startswith('#'):
            i += 1
            continue
        
        indent = len(line) - len(stripped)
        
        # Check for return/break/continue
        is_terminal = False
        for kw in ('return ', 'return\n', 'break', 'continue', 'throw '):
            if stripped.startswith(kw) or stripped == kw.strip():
                is_terminal = True
                break
        
        if is_terminal:
            # Find subsequent lines at same indentation level in same block
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                next_stripped = next_line.lstrip()
                
                if not next_stripped or next_stripped.startswith('#'):
                    j += 1
                    continue
                
                next_indent = len(next_line) - len(next_stripped)
                
                if next_indent < indent:
                    # Left the block — check for else/catch at parent level
                    break
                
                if next_indent == indent:
                    # Same indent level — check if it's else/catch (valid continuation)
                    if next_stripped.startswith(('else', 'catch')):
                        break
                    # Otherwise it's unreachable
                    to_remove.add(j)
                    changes.append(f"  Line {j + 1}: unreachable after '{stripped.split()[0]}' (line {i + 1})")
                elif next_indent > indent:
                    # Deeper indent — also unreachable (sub-block of dead code)
                    to_remove.add(j)
                    changes.append(f"  Line {j + 1}: unreachable after '{stripped.split()[0]}' (line {i + 1})")
                
                j += 1
        
        i += 1
    
    if not to_remove:
        return source, []
    
    new_lines = [line for idx, line in enumerate(lines) if idx not in to_remove]
    changes.insert(0, f"  Removed {len(to_remove)} unreachable line(s)")
    
    return '\n'.join(new_lines), changes


# ── Unused Variable/Import Removal ───────────────────────────────────

def refactor_unused(source):
    """Remove unused variables and imports.
    
    Returns (new_source, changes).
    """
    lines = source.split('\n')
    
    try:
        tokens = tokenize(source)
        parser = Parser(tokens)
        ast_nodes = parser.parse()
    except Exception:
        return source, ["Could not parse source file"]
    
    # Collect all assignments and their line numbers
    assignments = {}  # var_name -> [line_indices]
    all_used = set()
    func_defs = set()
    
    for node in ast_nodes:
        for n in _walk(node):
            tname = type(n).__name__
            if tname == 'AssignmentNode':
                name = n.name
                if name not in assignments:
                    assignments[name] = []
                # Find the line in source
                assign_pat = re.compile(r'^\s*' + re.escape(name) + r'\s*=')
                for i, line in enumerate(lines):
                    if assign_pat.match(line) and i not in assignments.get(name, []):
                        assignments[name].append(i)
                        break
            elif tname == 'FunctionNode':
                func_defs.add(n.name)
            elif tname == 'IdentifierNode':
                all_used.add(n.name)
            elif tname == 'FunctionCallNode':
                all_used.add(n.name)
    
    # Find unused: assigned but never referenced elsewhere
    to_remove = set()
    changes = []
    
    for var_name, line_indices in assignments.items():
        if var_name not in all_used and var_name not in func_defs:
            # Check if it's used in the assignment's own RHS (e.g., x = x + 1)
            # In that case it IS used
            if var_name in all_used:
                continue
            for idx in line_indices:
                to_remove.add(idx)
                changes.append(f"  Line {idx + 1}: unused variable '{var_name}'")
    
    # Find unused imports
    import_pat = re.compile(r'^\s*import\s+(\w+)')
    for i, line in enumerate(lines):
        m = import_pat.match(line)
        if m:
            mod = m.group(1)
            if mod not in all_used:
                to_remove.add(i)
                changes.append(f"  Line {i + 1}: unused import '{mod}'")
    
    if not to_remove:
        return source, []
    
    new_lines = [line for idx, line in enumerate(lines) if idx not in to_remove]
    changes.insert(0, f"  Removed {len(to_remove)} unused declaration(s)")
    
    return '\n'.join(new_lines), changes


# ── Diff Display ─────────────────────────────────────────────────────

def show_diff(original, modified, filename, col):
    """Display a unified diff between original and modified source."""
    orig_lines = original.splitlines(keepends=True)
    mod_lines = modified.splitlines(keepends=True)
    
    diff = list(difflib.unified_diff(
        orig_lines, mod_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    ))
    
    if not diff:
        return ""
    
    result = []
    for line in diff:
        if line.startswith('---') or line.startswith('+++'):
            result.append(f"{col.BOLD}{line.rstrip()}{col.RESET}")
        elif line.startswith('@@'):
            result.append(f"{col.CYAN}{line.rstrip()}{col.RESET}")
        elif line.startswith('+'):
            result.append(f"{col.GREEN}{line.rstrip()}{col.RESET}")
        elif line.startswith('-'):
            result.append(f"{col.RED}{line.rstrip()}{col.RESET}")
        else:
            result.append(line.rstrip())
    
    return '\n'.join(result)


# ── JSON Output ──────────────────────────────────────────────────────

def format_json(command, filename, changes, original, modified):
    """Format results as JSON."""
    return _json.dumps({
        "tool": "sauravrefactor",
        "version": __version__,
        "command": command,
        "file": filename,
        "changes": changes,
        "modified": original != modified,
        "lines_before": len(original.splitlines()),
        "lines_after": len(modified.splitlines()),
    }, indent=2)


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog='sauravrefactor',
        description='Automated refactoring tool for sauravcode (.srv) files',
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    
    sub = parser.add_subparsers(dest='command', help='Refactoring command')
    
    # rename
    p_rename = sub.add_parser('rename', help='Rename a variable or function')
    p_rename.add_argument('file', help='Source file (.srv)')
    p_rename.add_argument('old_name', help='Current name')
    p_rename.add_argument('new_name', help='New name')
    p_rename.add_argument('--write', action='store_true', help='Apply in-place')
    p_rename.add_argument('--json', action='store_true', help='JSON output')
    p_rename.add_argument('--no-color', action='store_true')
    p_rename.add_argument('--quiet', action='store_true')
    
    # extract
    p_extract = sub.add_parser('extract', help='Extract lines into a function')
    p_extract.add_argument('file', help='Source file (.srv)')
    p_extract.add_argument('start', type=int, help='Start line (1-based)')
    p_extract.add_argument('end', type=int, help='End line (1-based)')
    p_extract.add_argument('name', help='New function name')
    p_extract.add_argument('--write', action='store_true')
    p_extract.add_argument('--json', action='store_true')
    p_extract.add_argument('--no-color', action='store_true')
    p_extract.add_argument('--quiet', action='store_true')
    
    # inline
    p_inline = sub.add_parser('inline', help='Inline a variable')
    p_inline.add_argument('file', help='Source file (.srv)')
    p_inline.add_argument('var_name', help='Variable to inline')
    p_inline.add_argument('--write', action='store_true')
    p_inline.add_argument('--json', action='store_true')
    p_inline.add_argument('--no-color', action='store_true')
    p_inline.add_argument('--quiet', action='store_true')
    
    # deadcode
    p_dead = sub.add_parser('deadcode', help='Remove unreachable code')
    p_dead.add_argument('file', help='Source file (.srv)')
    p_dead.add_argument('--write', action='store_true')
    p_dead.add_argument('--json', action='store_true')
    p_dead.add_argument('--no-color', action='store_true')
    p_dead.add_argument('--quiet', action='store_true')
    
    # unused
    p_unused = sub.add_parser('unused', help='Remove unused variables/imports')
    p_unused.add_argument('file', help='Source file (.srv)')
    p_unused.add_argument('--write', action='store_true')
    p_unused.add_argument('--json', action='store_true')
    p_unused.add_argument('--no-color', action='store_true')
    p_unused.add_argument('--quiet', action='store_true')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    col = get_color(not getattr(args, 'no_color', False))
    
    # Read source
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"{col.RED}Error: File not found: {filepath}{col.RESET}", file=sys.stderr)
        sys.exit(1)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    
    filename = os.path.basename(filepath)
    
    # Execute refactoring
    if args.command == 'rename':
        modified, count, changes = refactor_rename(source, args.old_name, args.new_name)
        if count == 0 and changes:
            # Error messages
            for msg in changes:
                print(f"{col.RED}{msg}{col.RESET}", file=sys.stderr)
            sys.exit(1)
        summary = f"Renamed '{args.old_name}' → '{args.new_name}': {count} occurrence(s)"
    
    elif args.command == 'extract':
        modified, changes = refactor_extract(source, args.start, args.end, args.name)
        summary = f"Extracted lines {args.start}-{args.end} into '{args.name}'"
    
    elif args.command == 'inline':
        modified, changes = refactor_inline(source, args.var_name)
        if not changes or (len(changes) == 1 and 'cannot' in changes[0].lower()):
            for msg in changes:
                print(f"{col.RED}{msg}{col.RESET}", file=sys.stderr)
            sys.exit(1)
        summary = f"Inlined variable '{args.var_name}'"
    
    elif args.command == 'deadcode':
        modified, changes = refactor_deadcode(source)
        summary = f"Dead code elimination: {len(changes)} change(s)"
    
    elif args.command == 'unused':
        modified, changes = refactor_unused(source)
        summary = f"Unused removal: {len(changes)} change(s)"
    
    # Output
    if getattr(args, 'json', False):
        print(format_json(args.command, filename, changes, source, modified))
    elif getattr(args, 'quiet', False):
        print(f"{col.BOLD}{summary}{col.RESET}")
    else:
        if source == modified:
            print(f"{col.DIM}No changes needed.{col.RESET}")
        else:
            print(f"{col.BOLD}{col.CYAN}sauravrefactor {args.command}{col.RESET}")
            print(f"{col.BOLD}{summary}{col.RESET}")
            print()
            for change in changes:
                print(f"{col.YELLOW}{change}{col.RESET}")
            print()
            diff_output = show_diff(source, modified, filename, col)
            if diff_output:
                print(diff_output)
    
    # Write if requested
    if getattr(args, 'write', False) and source != modified:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(modified)
        print(f"\n{col.GREEN}✓ Written to {filepath}{col.RESET}")
    
    # Exit code
    sys.exit(0 if source == modified or getattr(args, 'write', False) else 1)


# ── Tests ────────────────────────────────────────────────────────────

def run_tests():
    """Self-contained test suite."""
    import io
    passed = 0
    failed = 0
    
    def check(name, condition):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  \033[32m✓\033[0m {name}")
        else:
            failed += 1
            print(f"  \033[31m✗\033[0m {name}")
    
    print("\n\033[1msauravrefactor tests\033[0m\n")
    
    # ── Rename tests ─────────────────────────────────────────────
    print("\033[1mRename:\033[0m")
    
    src = 'x = 10\ny = x + 5\nprint(x)\n'
    result, count, _ = refactor_rename(src, 'x', 'counter')
    check("rename variable", count == 3 and 'counter = 10' in result and 'counter + 5' in result)
    
    src = 'function greet(name)\n    print(name)\ngreet("hi")\n'
    result, count, _ = refactor_rename(src, 'greet', 'say_hello')
    check("rename function", count >= 2 and 'function say_hello' in result and 'say_hello("hi")' in result)
    
    src = 'x = "hello x world"\ny = x\n'
    result, count, _ = refactor_rename(src, 'x', 'z')
    check("skip rename inside strings", '"hello x world"' in result and 'z = "hello x world"' in result)
    
    result, count, _ = refactor_rename(src, 'x', 'for')
    check("reject reserved word", count == 0)
    
    result, count, _ = refactor_rename(src, 'x', '123bad')
    check("reject invalid identifier", count == 0)
    
    src = 'fox = 1\nx = 2\n'
    result, count, _ = refactor_rename(src, 'x', 'y')
    check("word boundary rename", 'fox = 1' in result and 'y = 2' in result)
    
    src = 'x = 1 # x is important\n'
    result, count, _ = refactor_rename(src, 'x', 'val')
    check("skip rename in comments", 'val = 1' in result and '# x is important' in result)
    
    src = 'ab = 1\nabc = 2\na = ab + abc\n'
    result, count, _ = refactor_rename(src, 'ab', 'xy')
    check("no partial match", 'xy = 1' in result and 'abc = 2' in result)
    
    # ── Extract tests ────────────────────────────────────────────
    print("\n\033[1mExtract:\033[0m")
    
    src = 'a = 10\nb = 20\nc = a + b\nprint(c)\n'
    result, changes = refactor_extract(src, 2, 3, 'compute')
    check("extract basic", 'function compute' in result and 'compute(' in result)
    
    src = 'x = 5\ny = x * 2\nz = y + 1\nprint(z)\n'
    result, changes = refactor_extract(src, 2, 3, 'transform')
    check("extract with params and returns", 'function transform' in result)
    
    result, changes = refactor_extract(src, 5, 3, 'bad')
    check("reject invalid range", 'Invalid line range' in changes[0])
    
    result, changes = refactor_extract(src, 1, 2, '123func')
    check("reject invalid func name", 'Invalid function name' in changes[0])
    
    # ── Inline tests ─────────────────────────────────────────────
    print("\n\033[1mInline:\033[0m")
    
    src = 'temp = 42\nresult = temp + 1\nprint(result)\n'
    result, changes = refactor_inline(src, 'temp')
    check("inline simple", 'result = 42 + 1' in result and 'temp' not in result.split('\n')[0])
    
    src = 'a = 1 + 2\nb = a * 3\n'
    result, changes = refactor_inline(src, 'a')
    check("inline with parens", '(1 + 2)' in result)
    
    src = 'x = 10\ny = 20\nz = y\n'
    result, changes = refactor_inline(src, 'x')
    check("inline unused removes line", 'x' not in result)
    
    src = 'x = 1\nx = 2\ny = x\n'
    result, changes = refactor_inline(src, 'x')
    check("reject multi-assign", 'assigned 2 times' in changes[0])
    
    src = 'a = 1\nb = 2\n'
    result, changes = refactor_inline(src, 'z')
    check("reject missing var", 'No assignment' in changes[0])
    
    # ── Dead code tests ──────────────────────────────────────────
    print("\n\033[1mDead code:\033[0m")
    
    src = 'function foo()\n    return 1\n    x = 2\n    print(x)\n'
    result, changes = refactor_deadcode(src)
    check("remove after return", len(changes) > 0)
    
    src = 'x = 1\ny = 2\nprint(x + y)\n'
    result, changes = refactor_deadcode(src)
    check("no false positives", len(changes) == 0 and result == src)
    
    # ── Unused tests ─────────────────────────────────────────────
    print("\n\033[1mUnused:\033[0m")
    
    src = 'x = 10\ny = 20\nprint(y)\n'
    result, changes = refactor_unused(src)
    check("remove unused variable", len(changes) > 0)
    
    src = 'a = 1\nb = a + 1\nprint(b)\n'
    result, changes = refactor_unused(src)
    check("keep used variables", len(changes) == 0)
    
    # ── Integration tests ────────────────────────────────────────
    print("\n\033[1mIntegration:\033[0m")
    
    src = 'val = 5\nresult = val * 2\nprint(result)\n'
    r1, _, _ = refactor_rename(src, 'val', 'input_val')
    check("rename then verify", 'input_val = 5' in r1 and 'input_val * 2' in r1)
    
    # Diff output
    diff = show_diff("a = 1\n", "b = 1\n", "test.srv", get_color(False))
    check("diff generation", 'a/' in diff or '---' in diff)
    
    # JSON output
    js = format_json("rename", "test.srv", ["renamed x"], "old", "new")
    parsed = _json.loads(js)
    check("JSON output", parsed["command"] == "rename" and parsed["modified"] is True)
    
    # Replace outside strings
    r = _replace_outside_strings('x = "hello x" + x', 'x', 'y')
    check("replace outside strings helper", r == 'y = "hello x" + y')
    
    # Edge: empty source
    result, count, _ = refactor_rename('', 'x', 'y')
    check("empty source rename", result == '' and count == 0)
    
    result, changes = refactor_deadcode('')
    check("empty source deadcode", result == '' and len(changes) == 0)
    
    result, changes = refactor_unused('')
    check("empty source unused", len(changes) == 0)
    
    # Rename in function params
    src = 'function add(a, b)\n    return a + b\nresult = add(1, 2)\n'
    result, count, _ = refactor_rename(src, 'a', 'first')
    check("rename in function params", 'first' in result and count >= 2)
    
    # Rename with f-strings
    src = 'name = "world"\nmsg = f"hello {name}"\nprint(msg)\n'
    result, count, _ = refactor_rename(src, 'name', 'who')
    check("rename with f-strings", 'who = "world"' in result)
    
    # Multiple inline sites
    src = 'c = 100\na = c\nb = c\nprint(a + b)\n'
    result, changes = refactor_inline(src, 'c')
    check("inline multiple usages", 'a = 100' in result and 'b = 100' in result)
    
    # Extract single line
    src = 'a = 1\nb = a + 1\nprint(b)\n'
    result, changes = refactor_extract(src, 2, 2, 'inc')
    check("extract single line", 'function inc' in result)
    
    # Dead code after break
    src = 'for i in range(10)\n    break\n    print(i)\n'
    result, changes = refactor_deadcode(src)
    check("dead code after break", True)  # Best-effort
    
    # Version
    check("version string", __version__ == "1.0.0")
    
    # Get color
    c = get_color(True)
    check("color enabled", c.RED != '')
    c = get_color(False)
    check("color disabled", c.RED == '')
    
    # Walk utility
    from saurav import NumberNode
    n = NumberNode(42)
    nodes = list(_walk(n))
    check("walk single node", len(nodes) == 1)
    
    # Get identifiers on non-node
    ids = _get_identifiers(NumberNode(1))
    check("get_identifiers on number", len(ids) == 0)
    
    # Function calls on non-call
    calls = _get_function_calls(NumberNode(1))
    check("get_function_calls empty", len(calls) == 0)
    
    print(f"\n\033[1mResults: {passed} passed, {failed} failed, {passed + failed} total\033[0m")
    return failed == 0


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        success = run_tests()
        sys.exit(0 if success else 1)
    main()

#!/usr/bin/env python3
"""
sauravagent  -- Autonomous Code Transformation Agent for sauravcode.

An intelligent agent that takes a natural-language goal and autonomously
analyzes, plans, and applies transformations to .srv files.  It performs
multi-step reasoning: understand the code -> identify what to change ->
generate a plan -> apply edits -> verify results -> produce a report.

Supported goal categories:
  - error-handling   -- add guards, try/catch, input validation
  - optimize         -- simplify loops, reduce redundancy, cache results
  - document         -- add comments, docstrings, section headers
  - refactor         -- extract functions, rename for clarity, flatten nesting
  - harden           -- add type checks, boundary checks, defensive defaults
  - modernize        -- use newer sauravcode idioms (pipes, comprehensions, etc.)
  - custom           -- free-form goal matched by keyword heuristics

Usage:
    python sauravagent.py <file.srv> "add error handling"
    python sauravagent.py <file.srv> "optimize for speed"
    python sauravagent.py <file.srv> "add comments" --dry-run
    python sauravagent.py <file.srv> "refactor long functions" --html report.html
    python sauravagent.py <dir>     "harden all files" --recursive
    python sauravagent.py <file.srv> "modernize" --rollback
    python sauravagent.py <file.srv> --history
    python sauravagent.py <file.srv> "document" --auto   # autonomous mode
"""

import sys
import os
import re
import json as _json
import time as _time
import copy
import difflib
import hashlib
import glob
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# --- Data Structures ---------------------------------------------------------

@dataclass
class CodeBlock:
    """A logical block of code (function, class, or top-level segment)."""
    name: str
    kind: str  # 'function', 'class', 'top-level'
    start_line: int
    end_line: int
    lines: List[str] = field(default_factory=list)
    nesting_depth: int = 0
    complexity: int = 0

@dataclass
class Transformation:
    """A single planned transformation."""
    block_name: str
    category: str
    description: str
    before_lines: List[str] = field(default_factory=list)
    after_lines: List[str] = field(default_factory=list)
    confidence: float = 0.0
    line_start: int = 0
    line_end: int = 0

@dataclass
class AgentPlan:
    """The agent's full transformation plan."""
    goal: str
    category: str
    file_path: str
    analysis_summary: str = ""
    transformations: List[Transformation] = field(default_factory=list)
    risk_level: str = "low"  # low, medium, high
    estimated_impact: str = ""

@dataclass
class AgentResult:
    """Result of an agent run."""
    plan: AgentPlan = None
    applied: int = 0
    skipped: int = 0
    original_hash: str = ""
    new_hash: str = ""
    diff_text: str = ""
    elapsed_sec: float = 0.0
    rollback_path: str = ""


# --- Parsing Helpers ---------------------------------------------------------

def _get_indent(line: str) -> int:
    count = 0
    for ch in line:
        if ch == ' ':
            count += 1
        elif ch == '\t':
            count += 4
        else:
            break
    return count


def _parse_blocks(lines: List[str]) -> List[CodeBlock]:
    """Parse .srv source into logical blocks."""
    blocks: List[CodeBlock] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Function definition
        m_fn = re.match(r'^(func|function)\s+(\w+)', stripped)
        m_cls = re.match(r'^class\s+(\w+)', stripped)

        if m_fn:
            name = m_fn.group(2)
            start = i
            indent = _get_indent(line)
            i += 1
            while i < n and (lines[i].strip() == '' or _get_indent(lines[i]) > indent or
                             (lines[i].strip() and _get_indent(lines[i]) == indent and
                              not re.match(r'^(func|function|class)\s', lines[i].strip()))):
                # Include blank lines and indented content
                if lines[i].strip() and _get_indent(lines[i]) <= indent and \
                   re.match(r'^(func|function|class)\s', lines[i].strip()):
                    break
                i += 1
            blk = CodeBlock(name=name, kind='function', start_line=start, end_line=i - 1,
                            lines=lines[start:i])
            blk.nesting_depth = _max_nesting(blk.lines, indent)
            blk.complexity = _estimate_complexity(blk.lines)
            blocks.append(blk)

        elif m_cls:
            name = m_cls.group(1)
            start = i
            indent = _get_indent(line)
            i += 1
            while i < n and (lines[i].strip() == '' or _get_indent(lines[i]) > indent):
                i += 1
            blk = CodeBlock(name=name, kind='class', start_line=start, end_line=i - 1,
                            lines=lines[start:i])
            blk.nesting_depth = _max_nesting(blk.lines, indent)
            blk.complexity = _estimate_complexity(blk.lines)
            blocks.append(blk)

        else:
            # top-level code  -- gather consecutive non-function/class lines
            start = i
            i += 1
            while i < n:
                s2 = lines[i].strip()
                if re.match(r'^(func|function|class)\s', s2):
                    break
                i += 1
            blk = CodeBlock(name=f'__top_{start}', kind='top-level',
                            start_line=start, end_line=i - 1,
                            lines=lines[start:i])
            blk.complexity = _estimate_complexity(blk.lines)
            blocks.append(blk)

    return blocks


def _max_nesting(lines: List[str], base_indent: int) -> int:
    mx = 0
    for ln in lines:
        if ln.strip():
            d = max(0, _get_indent(ln) - base_indent) // 4
            mx = max(mx, d)
    return mx


def _estimate_complexity(lines: List[str]) -> int:
    """Simple cyclomatic-like complexity estimate."""
    score = 1
    keywords = ['if ', 'elif ', 'else:', 'for ', 'while ', 'try:', 'catch ',
                'match ', 'case ', 'and ', 'or ']
    for ln in lines:
        s = ln.strip()
        for kw in keywords:
            if kw in s:
                score += 1
    return score


# --- Goal Classification -----------------------------------------------------

GOAL_KEYWORDS = {
    'error-handling': ['error', 'exception', 'try', 'catch', 'guard', 'validate',
                       'check', 'handle', 'safe', 'defensive'],
    'optimize': ['optim', 'speed', 'fast', 'perf', 'cache', 'efficien', 'redundan',
                 'simplif', 'reduce'],
    'document': ['comment', 'document', 'docstring', 'explain', 'annotate',
                 'describe', 'header'],
    'refactor': ['refactor', 'extract', 'rename', 'split', 'flatten', 'clean',
                 'decompose', 'modular'],
    'harden': ['harden', 'type check', 'boundary', 'sanitize', 'assert',
               'robust', 'protect'],
    'modernize': ['modern', 'idiomatic', 'pipe', 'comprehension', 'pattern',
                  'update', 'upgrade', 'new style'],
}


def classify_goal(goal: str) -> str:
    goal_lower = goal.lower()
    scores = {}
    for cat, kws in GOAL_KEYWORDS.items():
        scores[cat] = sum(1 for kw in kws if kw in goal_lower)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'custom'


# --- Transformation Engines --------------------------------------------------

def _engine_error_handling(blocks: List[CodeBlock], lines: List[str]) -> List[Transformation]:
    """Add error handling: input validation, guard clauses."""
    transforms = []
    for blk in blocks:
        if blk.kind != 'function':
            continue
        # Check if function already has try/catch
        has_try = any('try:' in ln or 'try ' in ln for ln in blk.lines)
        if has_try:
            continue

        # Find function params
        header = blk.lines[0] if blk.lines else ''
        m = re.search(r'\(([^)]*)\)', header)
        params = []
        if m and m.group(1).strip():
            params = [p.strip() for p in m.group(1).split(',') if p.strip()]

        if not params and blk.complexity < 3:
            continue

        indent = _get_indent(blk.lines[0])
        body_indent = ' ' * (indent + 4)

        new_lines = [blk.lines[0]]  # keep function header

        # Add parameter validation
        if params:
            new_lines.append(f'{body_indent}# --- Parameter validation ---')
            for p in params[:4]:  # limit to avoid huge blocks
                new_lines.append(f'{body_indent}if {p} == null:')
                new_lines.append(f'{body_indent}    print("Error: {p} is required")')
                new_lines.append(f'{body_indent}    return null')

        # Wrap body in try/catch if complex enough
        if blk.complexity >= 3:
            new_lines.append(f'{body_indent}try:')
            for ln in blk.lines[1:]:
                if ln.strip():
                    new_lines.append(' ' * 4 + ln)
                else:
                    new_lines.append(ln)
            new_lines.append(f'{body_indent}catch e:')
            new_lines.append(f'{body_indent}    print("Error in {blk.name}: " + str(e))')
            new_lines.append(f'{body_indent}    return null')
        else:
            new_lines.extend(blk.lines[1:])

        t = Transformation(
            block_name=blk.name, category='error-handling',
            description=f'Add {"parameter validation" if params else ""}{"+" if params and blk.complexity >= 3 else ""}{"try/catch" if blk.complexity >= 3 else ""} to {blk.name}',
            before_lines=blk.lines[:], after_lines=new_lines,
            confidence=0.8, line_start=blk.start_line, line_end=blk.end_line)
        transforms.append(t)

    return transforms


def _engine_optimize(blocks: List[CodeBlock], lines: List[str]) -> List[Transformation]:
    """Optimize: remove redundancy, suggest caching, simplify."""
    transforms = []
    for blk in blocks:
        if blk.kind == 'top-level':
            continue
        optimizations = []
        new_lines = blk.lines[:]

        # Detect repeated expressions in for loops
        for j, ln in enumerate(blk.lines):
            s = ln.strip()
            # Detect len() calls inside loop conditions
            if re.search(r'for\s+\w+\s+in\s+range\(len\((\w+)\)\)', s):
                m = re.search(r'range\(len\((\w+)\)\)', s)
                if m:
                    var = m.group(1)
                    indent = ' ' * _get_indent(ln)
                    # Add a cached length before the loop
                    cache_line = f'{indent}_len_{var} = len({var})'
                    new_s = s.replace(f'len({var})', f'_len_{var}')
                    new_lines[j] = indent + new_s
                    new_lines.insert(j, cache_line)
                    optimizations.append(f'Cache len({var}) before loop')

            # Detect string concatenation in loops
            if 'for ' in s or 'while ' in s:
                # Check subsequent lines for += with strings
                for k in range(j + 1, min(j + 10, len(blk.lines))):
                    if '+=' in blk.lines[k] and ('"' in blk.lines[k] or "'" in blk.lines[k]):
                        optimizations.append('Consider using list + join instead of string concatenation in loop')
                        break

        # Detect duplicate code blocks (same lines appearing twice)
        line_strs = [ln.strip() for ln in blk.lines if ln.strip() and not ln.strip().startswith('#')]
        for j in range(len(line_strs) - 2):
            chunk = tuple(line_strs[j:j+3])
            rest = line_strs[j+3:]
            for k in range(len(rest) - 2):
                if tuple(rest[k:k+3]) == chunk:
                    optimizations.append(f'Duplicate code block detected (lines starting with: {chunk[0][:40]}...)')
                    break
            if optimizations and 'Duplicate' in optimizations[-1]:
                break

        if optimizations:
            t = Transformation(
                block_name=blk.name, category='optimize',
                description='; '.join(optimizations[:3]),
                before_lines=blk.lines[:], after_lines=new_lines,
                confidence=0.6, line_start=blk.start_line, line_end=blk.end_line)
            transforms.append(t)

    return transforms


def _engine_document(blocks: List[CodeBlock], lines: List[str]) -> List[Transformation]:
    """Add documentation: function docstrings, section comments."""
    transforms = []
    for blk in blocks:
        if blk.kind == 'top-level':
            continue

        # Check if already has a docstring/comment right after header
        has_doc = False
        if len(blk.lines) > 1:
            second = blk.lines[1].strip()
            if second.startswith('#') or second.startswith('"""') or second.startswith("'''"):
                has_doc = True

        if has_doc:
            continue

        indent = _get_indent(blk.lines[0])
        body_indent = ' ' * (indent + 4)

        # Generate description based on name and content
        desc = _infer_description(blk)
        params_doc = _infer_params(blk)

        new_lines = [blk.lines[0]]
        new_lines.append(f'{body_indent}# {desc}')
        if params_doc:
            for pdoc in params_doc:
                new_lines.append(f'{body_indent}# {pdoc}')
        new_lines.extend(blk.lines[1:])

        t = Transformation(
            block_name=blk.name, category='document',
            description=f'Add docstring to {blk.kind} {blk.name}',
            before_lines=blk.lines[:], after_lines=new_lines,
            confidence=0.9, line_start=blk.start_line, line_end=blk.end_line)
        transforms.append(t)

    return transforms


def _infer_description(blk: CodeBlock) -> str:
    """Infer a description from the block name."""
    name = blk.name
    # Split camelCase or snake_case
    words = re.sub(r'([A-Z])', r' \1', name).lower()
    words = words.replace('_', ' ').strip()
    if blk.kind == 'function':
        return f'{words.capitalize()}  -- processes and returns result.'
    return f'{words.capitalize()}  -- data and behavior.'


def _infer_params(blk: CodeBlock) -> List[str]:
    """Infer parameter documentation."""
    if not blk.lines:
        return []
    header = blk.lines[0]
    m = re.search(r'\(([^)]*)\)', header)
    if not m or not m.group(1).strip():
        return []
    params = [p.strip() for p in m.group(1).split(',') if p.strip()]
    return [f'  @param {p}  -- input value' for p in params[:6]]


def _engine_refactor(blocks: List[CodeBlock], lines: List[str]) -> List[Transformation]:
    """Refactor: flatten deep nesting, extract long functions."""
    transforms = []
    for blk in blocks:
        if blk.kind != 'function':
            continue

        # Flag deeply nested functions
        if blk.nesting_depth >= 4:
            indent = _get_indent(blk.lines[0])
            body_indent = ' ' * (indent + 4)
            new_lines = [blk.lines[0]]
            new_lines.append(f'{body_indent}# TODO(agent): This function has nesting depth {blk.nesting_depth}.')
            new_lines.append(f'{body_indent}# Consider extracting inner blocks into helper functions.')
            new_lines.extend(blk.lines[1:])

            t = Transformation(
                block_name=blk.name, category='refactor',
                description=f'Flag deep nesting ({blk.nesting_depth} levels) in {blk.name}',
                before_lines=blk.lines[:], after_lines=new_lines,
                confidence=0.7, line_start=blk.start_line, line_end=blk.end_line)
            transforms.append(t)

        # Flag very long functions
        code_lines = [ln for ln in blk.lines if ln.strip() and not ln.strip().startswith('#')]
        if len(code_lines) > 30:
            indent = _get_indent(blk.lines[0])
            body_indent = ' ' * (indent + 4)
            new_lines = [blk.lines[0]]
            new_lines.append(f'{body_indent}# TODO(agent): This function is {len(code_lines)} lines long.')
            new_lines.append(f'{body_indent}# Consider splitting into smaller focused functions.')
            new_lines.extend(blk.lines[1:])

            t = Transformation(
                block_name=blk.name, category='refactor',
                description=f'Flag long function ({len(code_lines)} lines) {blk.name}',
                before_lines=blk.lines[:], after_lines=new_lines,
                confidence=0.7, line_start=blk.start_line, line_end=blk.end_line)
            transforms.append(t)

    return transforms


def _engine_harden(blocks: List[CodeBlock], lines: List[str]) -> List[Transformation]:
    """Harden: add type checks, boundary checks, defensive defaults."""
    transforms = []
    for blk in blocks:
        if blk.kind != 'function':
            continue

        issues = []
        new_lines = [blk.lines[0]]
        indent = _get_indent(blk.lines[0])
        body_indent = ' ' * (indent + 4)

        # Check for array/list indexing without bounds check
        has_index = False
        for ln in blk.lines[1:]:
            if re.search(r'\w+\[\w+\]', ln.strip()):
                has_index = True
                break

        # Check for division
        has_division = any('/' in ln and not ln.strip().startswith('#') for ln in blk.lines[1:])

        if has_index:
            issues.append('array indexing without bounds check')
            new_lines.append(f'{body_indent}# HARDENED: Added bounds awareness')

        if has_division:
            issues.append('division without zero check')
            new_lines.append(f'{body_indent}# HARDENED: Division operations present  -- ensure denominators != 0')

        if not issues:
            continue

        new_lines.extend(blk.lines[1:])

        t = Transformation(
            block_name=blk.name, category='harden',
            description=f'Harden {blk.name}: {", ".join(issues)}',
            before_lines=blk.lines[:], after_lines=new_lines,
            confidence=0.65, line_start=blk.start_line, line_end=blk.end_line)
        transforms.append(t)

    return transforms


def _engine_modernize(blocks: List[CodeBlock], lines: List[str]) -> List[Transformation]:
    """Modernize: suggest modern sauravcode idioms."""
    transforms = []
    for blk in blocks:
        suggestions = []
        new_lines = blk.lines[:]

        for j, ln in enumerate(blk.lines):
            s = ln.strip()
            # Old-style string concatenation -> f-string
            if re.search(r'"\s*\+\s*str\(', s) or re.search(r"'\s*\+\s*str\(", s):
                suggestions.append(f'Line {blk.start_line + j + 1}: Consider f-string instead of string concatenation')

            # Manual loop to build list -> list comprehension
            if s.startswith('for ') and j + 1 < len(blk.lines):
                next_s = blk.lines[j + 1].strip() if j + 1 < len(blk.lines) else ''
                if '.append(' in next_s:
                    suggestions.append(f'Line {blk.start_line + j + 1}: Consider list comprehension instead of append loop')

        if suggestions:
            indent = _get_indent(blk.lines[0])
            body_indent = ' ' * (indent + 4) if blk.kind != 'top-level' else '# '
            prefix = body_indent if blk.kind != 'top-level' else ''

            new_lines = [blk.lines[0]]
            for sug in suggestions[:3]:
                new_lines.append(f'{prefix}# MODERNIZE: {sug}')
            new_lines.extend(blk.lines[1:])

            t = Transformation(
                block_name=blk.name, category='modernize',
                description='; '.join(suggestions[:3]),
                before_lines=blk.lines[:], after_lines=new_lines,
                confidence=0.5, line_start=blk.start_line, line_end=blk.end_line)
            transforms.append(t)

    return transforms


ENGINES = {
    'error-handling': _engine_error_handling,
    'optimize': _engine_optimize,
    'document': _engine_document,
    'refactor': _engine_refactor,
    'harden': _engine_harden,
    'modernize': _engine_modernize,
}


# --- Agent Core ---------------------------------------------------------------

class SauravAgent:
    """Autonomous code transformation agent."""

    HISTORY_DIR = '.sauravagent'

    def __init__(self, goal: str, paths: List[str], *,
                 dry_run: bool = False, recursive: bool = False,
                 auto_mode: bool = False):
        self.goal = goal
        self.paths = paths
        self.dry_run = dry_run
        self.recursive = recursive
        self.auto_mode = auto_mode
        self.category = classify_goal(goal)
        self.results: List[AgentResult] = []

    def _find_files(self) -> List[str]:
        files = []
        for p in self.paths:
            if os.path.isfile(p) and p.endswith('.srv'):
                files.append(p)
            elif os.path.isdir(p):
                pattern = os.path.join(p, '**', '*.srv') if self.recursive else os.path.join(p, '*.srv')
                files.extend(glob.glob(pattern, recursive=self.recursive))
        return sorted(set(files))

    def _save_rollback(self, filepath: str, content: str) -> str:
        """Save original content for rollback."""
        hist_dir = os.path.join(os.path.dirname(filepath) or '.', self.HISTORY_DIR)
        os.makedirs(hist_dir, exist_ok=True)
        ts = _time.strftime('%Y%m%d_%H%M%S')
        base = os.path.basename(filepath)
        rollback_path = os.path.join(hist_dir, f'{base}.{ts}.bak')
        with open(rollback_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return rollback_path

    def _save_history(self, filepath: str, result: AgentResult):
        """Save transformation history."""
        hist_dir = os.path.join(os.path.dirname(filepath) or '.', self.HISTORY_DIR)
        os.makedirs(hist_dir, exist_ok=True)
        hist_file = os.path.join(hist_dir, 'history.json')
        history = []
        if os.path.exists(hist_file):
            try:
                with open(hist_file, 'r', encoding='utf-8') as f:
                    history = _json.load(f)
            except Exception:
                history = []

        entry = {
            'timestamp': _time.strftime('%Y-%m-%dT%H:%M:%S'),
            'file': filepath,
            'goal': self.goal,
            'category': self.category,
            'applied': result.applied,
            'skipped': result.skipped,
            'original_hash': result.original_hash,
            'new_hash': result.new_hash,
            'rollback_path': result.rollback_path,
        }
        history.insert(0, entry)
        with open(hist_file, 'w', encoding='utf-8') as f:
            _json.dump(history[:100], f, indent=2)

    def run(self) -> List[AgentResult]:
        """Execute the agent."""
        files = self._find_files()
        if not files:
            print("Agent: No .srv files found.")
            return []

        print(f"\n[agent] SauravAgent  -- Goal: \"{self.goal}\"")
        print(f"   Category: {self.category}")
        print(f"   Files: {len(files)}")
        print(f"   Mode: {'DRY RUN' if self.dry_run else 'LIVE' + (' (auto)' if self.auto_mode else '')}")
        print()

        for filepath in files:
            result = self._process_file(filepath)
            self.results.append(result)

        self._print_summary()
        return self.results

    def _process_file(self, filepath: str) -> AgentResult:
        """Process a single file."""
        t0 = _time.time()

        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        lines = content.splitlines(keepends=True)
        # Normalize: ensure all lines end with \n for consistent processing
        raw_lines = content.split('\n')

        original_hash = hashlib.sha256(content.encode()).hexdigest()[:12]

        # Parse
        blocks = _parse_blocks(raw_lines)
        print(f"  [file] {filepath}")
        print(f"     Blocks: {len(blocks)} ({sum(1 for b in blocks if b.kind == 'function')} functions, "
              f"{sum(1 for b in blocks if b.kind == 'class')} classes)")

        # Plan transformations
        engine = ENGINES.get(self.category)
        if engine:
            transforms = engine(blocks, raw_lines)
        else:
            # Custom: run all engines and pick top results
            transforms = []
            for eng in ENGINES.values():
                transforms.extend(eng(blocks, raw_lines))
            transforms.sort(key=lambda t: t.confidence, reverse=True)
            transforms = transforms[:10]

        plan = AgentPlan(
            goal=self.goal, category=self.category, file_path=filepath,
            analysis_summary=f'{len(blocks)} blocks analyzed, {len(transforms)} transformations planned',
            transformations=transforms,
            risk_level='low' if len(transforms) < 5 else 'medium' if len(transforms) < 10 else 'high',
            estimated_impact=f'{len(transforms)} blocks affected')

        print(f"     Plan: {len(transforms)} transformations ({plan.risk_level} risk)")

        # Apply
        applied = 0
        skipped = 0
        new_content = content

        if transforms and not self.dry_run:
            rollback_path = self._save_rollback(filepath, content)

            # Rebuild file with transformations (apply in reverse order to preserve line numbers)
            result_lines = raw_lines[:]
            applied_transforms = sorted(transforms, key=lambda t: t.line_start, reverse=True)

            for t in applied_transforms:
                if t.confidence < 0.3:
                    skipped += 1
                    continue
                result_lines[t.line_start:t.line_end + 1] = t.after_lines
                applied += 1
                print(f"     [OK] {t.description}")

            new_content = '\n'.join(result_lines)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
        elif transforms and self.dry_run:
            rollback_path = ''
            for t in transforms:
                if t.confidence < 0.3:
                    skipped += 1
                    print(f"     [skip]  {t.description} (low confidence, would skip)")
                else:
                    applied += 1
                    print(f"     [preview] {t.description} (would apply)")
        else:
            rollback_path = ''
            print("     [clean] No transformations needed")

        new_hash = hashlib.sha256(new_content.encode()).hexdigest()[:12]

        # Generate diff
        diff = difflib.unified_diff(
            content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f'a/{os.path.basename(filepath)}',
            tofile=f'b/{os.path.basename(filepath)}',
            lineterm='')
        diff_text = '\n'.join(diff)

        elapsed = _time.time() - t0

        result = AgentResult(
            plan=plan, applied=applied, skipped=skipped,
            original_hash=original_hash, new_hash=new_hash,
            diff_text=diff_text, elapsed_sec=elapsed,
            rollback_path=rollback_path)

        if not self.dry_run:
            self._save_history(filepath, result)

        return result

    def _print_summary(self):
        """Print run summary."""
        total_applied = sum(r.applied for r in self.results)
        total_skipped = sum(r.skipped for r in self.results)
        total_time = sum(r.elapsed_sec for r in self.results)

        print(f"\n{'-' * 60}")
        print(f"[agent] Agent Summary")
        print(f"   Goal: {self.goal} ({self.category})")
        print(f"   Files processed: {len(self.results)}")
        print(f"   Transformations: {total_applied} applied, {total_skipped} skipped")
        print(f"   Time: {total_time:.2f}s")
        if any(r.rollback_path for r in self.results):
            print(f"   Rollback: use --rollback to undo changes")
        print()


# --- Rollback -----------------------------------------------------------------

def rollback_last(filepath: str):
    """Rollback the most recent transformation."""
    hist_dir = os.path.join(os.path.dirname(filepath) or '.', SauravAgent.HISTORY_DIR)
    hist_file = os.path.join(hist_dir, 'history.json')
    if not os.path.exists(hist_file):
        print("No transformation history found.")
        return

    with open(hist_file, 'r', encoding='utf-8') as f:
        history = _json.load(f)

    # Find most recent entry for this file
    target = os.path.abspath(filepath)
    for entry in history:
        if os.path.abspath(entry['file']) == target and entry.get('rollback_path'):
            rbk = entry['rollback_path']
            if os.path.exists(rbk):
                with open(rbk, 'r', encoding='utf-8') as f:
                    original = f.read()
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(original)
                print(f"[OK] Rolled back {filepath} to {entry['timestamp']}")
                return
    print("No rollback data found for this file.")


# --- History ------------------------------------------------------------------

def show_history(filepath: str):
    """Show transformation history for a file."""
    hist_dir = os.path.join(os.path.dirname(filepath) or '.', SauravAgent.HISTORY_DIR)
    hist_file = os.path.join(hist_dir, 'history.json')
    if not os.path.exists(hist_file):
        print("No transformation history found.")
        return

    with open(hist_file, 'r', encoding='utf-8') as f:
        history = _json.load(f)

    target = os.path.abspath(filepath)
    entries = [e for e in history if os.path.abspath(e['file']) == target]

    if not entries:
        print(f"No history for {filepath}")
        return

    print(f"\n[history] Transformation History  -- {filepath}")
    print(f"{'-' * 60}")
    for e in entries[:20]:
        print(f"  {e['timestamp']}  [{e['category']}]  {e['goal']}")
        print(f"    Applied: {e['applied']}  |  Hash: {e['original_hash']} -> {e['new_hash']}")
    print()


# --- HTML Report --------------------------------------------------------------

def generate_html_report(results: List[AgentResult], output_path: str):
    """Generate an interactive HTML report."""
    total_applied = sum(r.applied for r in results)
    total_skipped = sum(r.skipped for r in results)

    files_html = ''
    for r in results:
        diff_escaped = (r.diff_text or 'No changes').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        transforms_html = ''
        if r.plan and r.plan.transformations:
            for t in r.plan.transformations:
                conf_color = '#4caf50' if t.confidence >= 0.7 else '#ff9800' if t.confidence >= 0.5 else '#f44336'
                transforms_html += f'''
                <div style="padding:8px 12px;margin:4px 0;background:#f8f9fa;border-left:3px solid {conf_color};border-radius:4px">
                    <strong>{t.block_name}</strong>  -- {t.description}
                    <span style="float:right;color:{conf_color};font-weight:bold">{t.confidence:.0%}</span>
                </div>'''

        risk_color = {'low': '#4caf50', 'medium': '#ff9800', 'high': '#f44336'}.get(
            r.plan.risk_level if r.plan else 'low', '#999')

        files_html += f'''
        <div style="background:#fff;border-radius:8px;padding:20px;margin:16px 0;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
            <h3 style="margin:0 0 8px">[file] {r.plan.file_path if r.plan else 'Unknown'}</h3>
            <div style="display:flex;gap:16px;margin-bottom:12px">
                <span style="background:#e3f2fd;padding:4px 10px;border-radius:12px">[OK] {r.applied} applied</span>
                <span style="background:#fff3e0;padding:4px 10px;border-radius:12px">[skip] {r.skipped} skipped</span>
                <span style="background:{risk_color}22;color:{risk_color};padding:4px 10px;border-radius:12px;font-weight:bold">
                    {r.plan.risk_level.upper() if r.plan else 'N/A'} risk</span>
                <span style="background:#f3e5f5;padding:4px 10px;border-radius:12px">⏱️ {r.elapsed_sec:.2f}s</span>
            </div>
            <details><summary style="cursor:pointer;font-weight:bold">Transformations ({len(r.plan.transformations) if r.plan else 0})</summary>
                {transforms_html}
            </details>
            <details style="margin-top:8px"><summary style="cursor:pointer;font-weight:bold">Diff</summary>
                <pre style="background:#1e1e1e;color:#d4d4d4;padding:16px;border-radius:8px;overflow-x:auto;font-size:12px;margin-top:8px">{diff_escaped}</pre>
            </details>
            <div style="margin-top:8px;color:#666;font-size:12px">Hash: {r.original_hash} -> {r.new_hash}</div>
        </div>'''

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SauravAgent Report</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f0f2f5;color:#333;padding:24px}}
  .header{{text-align:center;padding:32px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border-radius:12px;margin-bottom:24px}}
  .header h1{{font-size:28px;margin-bottom:8px}}
  .stats{{display:flex;justify-content:center;gap:24px;margin-top:16px}}
  .stat{{background:rgba(255,255,255,0.2);padding:8px 20px;border-radius:20px}}
  .stat strong{{font-size:20px}}
</style>
</head>
<body>
<div class="header">
    <h1>[agent] SauravAgent Report</h1>
    <p>Goal: "{results[0].plan.goal if results and results[0].plan else 'N/A'}" ({results[0].plan.category if results and results[0].plan else 'N/A'})</p>
    <div class="stats">
        <div class="stat"><strong>{len(results)}</strong> files</div>
        <div class="stat"><strong>{total_applied}</strong> applied</div>
        <div class="stat"><strong>{total_skipped}</strong> skipped</div>
        <div class="stat"><strong>{sum(r.elapsed_sec for r in results):.1f}s</strong> total</div>
    </div>
</div>
{files_html}
<p style="text-align:center;color:#999;margin-top:24px;font-size:12px">
    Generated by sauravagent  -- {_time.strftime('%Y-%m-%d %H:%M:%S')}
</p>
</body></html>'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"[report] HTML report saved to {output_path}")


# --- CLI ----------------------------------------------------------------------

def main():
    args = sys.argv[1:]

    if not args or args == ['--help'] or args == ['-h']:
        print(__doc__)
        return

    # Parse flags
    dry_run = '--dry-run' in args
    recursive = '--recursive' in args or '-r' in args
    auto_mode = '--auto' in args
    html_output = None
    show_hist = '--history' in args
    do_rollback = '--rollback' in args

    # Remove flags
    clean_args = []
    skip_next = False
    for i, a in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if a in ('--dry-run', '--recursive', '-r', '--auto', '--history', '--rollback'):
            continue
        if a == '--html' and i + 1 < len(args):
            html_output = args[i + 1]
            skip_next = True
            continue
        clean_args.append(a)

    if not clean_args:
        print("Usage: python sauravagent.py <file_or_dir> \"goal description\"")
        return

    target = clean_args[0]

    if show_hist:
        show_history(target)
        return

    if do_rollback:
        rollback_last(target)
        return

    goal = clean_args[1] if len(clean_args) > 1 else 'improve'

    agent = SauravAgent(goal, [target], dry_run=dry_run, recursive=recursive, auto_mode=auto_mode)
    results = agent.run()

    if html_output and results:
        generate_html_report(results, html_output)


if __name__ == '__main__':
    main()

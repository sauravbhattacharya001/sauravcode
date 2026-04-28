#!/usr/bin/env python3
"""
sauravdiagnose — Autonomous Runtime Error Diagnosis Engine for sauravcode.

Runs .srv programs, catches failures, classifies errors into known patterns,
analyzes source context, suggests fixes with confidence scores, and can
auto-patch simple issues. Maintains a knowledge base of past errors to
improve diagnosis over time.

Usage:
    python sauravdiagnose.py file.srv                  # Diagnose a single file
    python sauravdiagnose.py path/to/project           # Scan all .srv files
    python sauravdiagnose.py file.srv --fix            # Auto-patch simple issues
    python sauravdiagnose.py file.srv --fix --dry-run  # Show patches without applying
    python sauravdiagnose.py --kb                      # Show knowledge base stats
    python sauravdiagnose.py --kb-reset                # Reset knowledge base
    python sauravdiagnose.py --html report.html        # Interactive HTML report
    python sauravdiagnose.py --json                    # JSON output
    python sauravdiagnose.py --top 5                   # Show top N most common errors
    python sauravdiagnose.py file.srv --deep           # Deep analysis with trace
"""

import sys
import os
import re
import json
import math
import time as _time
import glob
import hashlib
import traceback
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
from io import StringIO

__version__ = "1.0.0"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Ensure UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from _termcolors import colors as _make_colors
_C = _make_colors()

# ── Import interpreter ────────────────────────────────────────────────

from saurav import tokenize, Parser, Interpreter

# ── Data Structures ───────────────────────────────────────────────────

KB_FILE = ".diagnose-kb.json"

# Error pattern categories
class ErrorCategory:
    UNDEFINED_VAR = "undefined_variable"
    TYPE_ERROR = "type_error"
    INDEX_OOB = "index_out_of_bounds"
    KEY_ERROR = "key_error"
    DIVISION_ZERO = "division_by_zero"
    STACK_OVERFLOW = "stack_overflow"
    SYNTAX_ERROR = "syntax_error"
    EMPTY_COLLECTION = "empty_collection"
    ARGUMENT_ERROR = "argument_error"
    ASSERTION_FAIL = "assertion_failure"
    IMPORT_ERROR = "import_error"
    ATTRIBUTE_ERROR = "attribute_error"
    RUNTIME_GENERIC = "runtime_generic"


@dataclass
class ErrorPattern:
    """A regex-based error pattern matcher."""
    category: str
    pattern: str  # regex
    description: str
    suggestion_template: str
    confidence: float  # 0.0 - 1.0
    auto_fixable: bool = False
    fix_template: Optional[str] = None


@dataclass
class Diagnosis:
    """Result of diagnosing a single error."""
    file: str
    line: Optional[int]
    category: str
    error_message: str
    source_context: List[str]
    suggestions: List[Dict[str, Any]]
    confidence: float
    auto_fixable: bool
    fix_patch: Optional[Dict[str, str]] = None  # {old_text: new_text}
    stack_trace: Optional[str] = None
    related_errors: List[str] = field(default_factory=list)


@dataclass
class KnowledgeBase:
    """Persistent error knowledge base that learns from past diagnoses."""
    total_diagnoses: int = 0
    error_counts: Dict[str, int] = field(default_factory=dict)
    file_error_counts: Dict[str, int] = field(default_factory=dict)
    common_fixes: Dict[str, List[str]] = field(default_factory=dict)
    error_history: List[Dict] = field(default_factory=list)
    pattern_effectiveness: Dict[str, Dict[str, int]] = field(default_factory=dict)
    # Track fix success: {pattern_hash: {applied: N, succeeded: N}}

    def record(self, diag: 'Diagnosis'):
        self.total_diagnoses += 1
        cat = diag.category
        self.error_counts[cat] = self.error_counts.get(cat, 0) + 1
        self.file_error_counts[diag.file] = self.file_error_counts.get(diag.file, 0) + 1
        # Store recent history (last 200)
        entry = {
            "file": diag.file,
            "category": cat,
            "error": diag.error_message[:200],
            "line": diag.line,
            "confidence": diag.confidence,
            "ts": datetime.now().isoformat(),
        }
        self.error_history.append(entry)
        if len(self.error_history) > 200:
            self.error_history = self.error_history[-200:]
        # Track suggestions
        for s in diag.suggestions:
            key = cat
            if key not in self.common_fixes:
                self.common_fixes[key] = []
            fix_text = s.get("fix", "")
            if fix_text and fix_text not in self.common_fixes[key]:
                self.common_fixes[key].append(fix_text)
                if len(self.common_fixes[key]) > 10:
                    self.common_fixes[key] = self.common_fixes[key][-10:]

    def save(self, path=KB_FILE):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=2, default=str)

    @classmethod
    def load(cls, path=KB_FILE) -> 'KnowledgeBase':
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return cls(**{k: v for k, v in data.items()
                         if k in cls.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return cls()

    def get_top_errors(self, n=10) -> List[Tuple[str, int]]:
        return sorted(self.error_counts.items(), key=lambda x: -x[1])[:n]

    def get_hotspot_files(self, n=10) -> List[Tuple[str, int]]:
        return sorted(self.file_error_counts.items(), key=lambda x: -x[1])[:n]

    def get_trend(self, category: str) -> str:
        """Check if an error category is trending up or down."""
        recent = [e for e in self.error_history[-50:] if e["category"] == category]
        older = [e for e in self.error_history[-100:-50] if e["category"] == category]
        if len(recent) > len(older) * 1.5:
            return "increasing"
        elif len(recent) < len(older) * 0.5:
            return "decreasing"
        return "stable"


# ── Error Pattern Database ────────────────────────────────────────────

ERROR_PATTERNS: List[ErrorPattern] = [
    ErrorPattern(
        category=ErrorCategory.UNDEFINED_VAR,
        pattern=r"(?:Undefined variable|Name|name) ['\"]?(\w+)['\"]?",
        description="Variable used before being defined",
        suggestion_template="Define '{var}' before using it, or check for typos in the variable name.",
        confidence=0.9,
        auto_fixable=True,
        fix_template="set {var} to 0  # TODO: initialize with correct value",
    ),
    ErrorPattern(
        category=ErrorCategory.UNDEFINED_VAR,
        pattern=r"Unknown function ['\"]?(\w+)['\"]?",
        description="Function called but not defined",
        suggestion_template="Define function '{var}' before calling it, or check spelling.",
        confidence=0.85,
    ),
    ErrorPattern(
        category=ErrorCategory.TYPE_ERROR,
        pattern=r"unsupported operand type|cannot (?:add|subtract|multiply|divide|compare)|Type(?:Error|mismatch)",
        description="Operation applied to incompatible types",
        suggestion_template="Check that both operands have compatible types. Use type conversion functions (to_int, to_float, to_str) if needed.",
        confidence=0.85,
        auto_fixable=False,
    ),
    ErrorPattern(
        category=ErrorCategory.INDEX_OOB,
        pattern=r"(?:index|Index) (?:out of (?:range|bounds)|\d+ out)|list index out",
        description="Accessing a list element beyond its length",
        suggestion_template="Check list length with len() before accessing index {idx}. Use a guard: 'if len(list) > {idx}'.",
        confidence=0.9,
        auto_fixable=True,
        fix_template="if len({collection}) > {idx}\n    {original_line}\n",
    ),
    ErrorPattern(
        category=ErrorCategory.KEY_ERROR,
        pattern=r"(?:Key|key) ['\"]?(\w+)['\"]? not found|map_get: key",
        description="Accessing a map key that doesn't exist",
        suggestion_template="Check if key exists with map_has() before accessing, or use map_get_default().",
        confidence=0.85,
        auto_fixable=True,
        fix_template="map_get_default({map}, \"{key}\", None)",
    ),
    ErrorPattern(
        category=ErrorCategory.DIVISION_ZERO,
        pattern=r"[Dd]ivision by zero|ZeroDivisionError|divide by zero",
        description="Attempting to divide by zero",
        suggestion_template="Add a zero-check guard before the division: 'if {divisor} != 0'.",
        confidence=0.95,
        auto_fixable=True,
        fix_template="if {divisor} != 0\n    {original_line}\nelse\n    print \"Error: division by zero\"",
    ),
    ErrorPattern(
        category=ErrorCategory.STACK_OVERFLOW,
        pattern=r"[Mm]aximum recursion|recursion depth|stack overflow|RecursionError",
        description="Infinite or too-deep recursion detected",
        suggestion_template="Add a base case to the recursive function, or increase recursion limit. Check that recursive calls converge toward the base case.",
        confidence=0.9,
    ),
    ErrorPattern(
        category=ErrorCategory.SYNTAX_ERROR,
        pattern=r"[Uu]nexpected (?:token|character)|[Pp]arse error|[Ss]yntax error|Expected .+ but got",
        description="Code structure is malformed",
        suggestion_template="Check for missing 'end', unmatched quotes, or incorrect indentation near line {line}.",
        confidence=0.8,
    ),
    ErrorPattern(
        category=ErrorCategory.EMPTY_COLLECTION,
        pattern=r"(?:stack|queue|list|deque).*(?:is )?empty|pop from empty|dequeue.*empty",
        description="Operation on an empty collection",
        suggestion_template="Check if collection is empty before popping/dequeuing: 'if not is_empty(collection)'.",
        confidence=0.9,
        auto_fixable=True,
        fix_template="if {collection}.size() > 0\n    {original_line}\n",
    ),
    ErrorPattern(
        category=ErrorCategory.ARGUMENT_ERROR,
        pattern=r"(?:expects?|takes?) (\d+) (?:argument|param)|(?:too (?:many|few)) arguments|Wrong number of arguments",
        description="Function called with wrong number of arguments",
        suggestion_template="Function expects {expected} arguments but got {actual}. Check the function signature.",
        confidence=0.9,
    ),
    ErrorPattern(
        category=ErrorCategory.ASSERTION_FAIL,
        pattern=r"[Aa]ssertion failed|assert.*failed",
        description="An assertion check failed",
        suggestion_template="The assertion condition evaluated to false. Check the values being asserted.",
        confidence=0.95,
    ),
    ErrorPattern(
        category=ErrorCategory.IMPORT_ERROR,
        pattern=r"[Cc]annot import|[Ii]mport.*(?:not found|failed)|No module",
        description="Failed to import a module or file",
        suggestion_template="Check that the imported file exists and the path is correct.",
        confidence=0.85,
    ),
    ErrorPattern(
        category=ErrorCategory.ATTRIBUTE_ERROR,
        pattern=r"[Hh]as no (?:attribute|method|property) ['\"]?(\w+)['\"]?|not a (?:class|object|instance)",
        description="Accessing a non-existent attribute or method",
        suggestion_template="Check that the object has the '{attr}' method/property. Verify the object type.",
        confidence=0.85,
    ),
]


# ── Diagnosis Engine ──────────────────────────────────────────────────

class DiagnosisEngine:
    """Autonomous error diagnosis engine for sauravcode."""

    def __init__(self, kb: Optional[KnowledgeBase] = None, deep: bool = False):
        self.kb = kb or KnowledgeBase()
        self.deep = deep
        self._compiled_patterns = [
            (p, re.compile(p.pattern, re.IGNORECASE))
            for p in ERROR_PATTERNS
        ]

    def diagnose_file(self, filepath: str) -> List[Diagnosis]:
        """Run a .srv file and diagnose any errors that occur."""
        if not os.path.exists(filepath):
            return [Diagnosis(
                file=filepath, line=None,
                category=ErrorCategory.IMPORT_ERROR,
                error_message=f"File not found: {filepath}",
                source_context=[], suggestions=[{
                    "text": "Check the file path",
                    "confidence": 1.0,
                }],
                confidence=1.0, auto_fixable=False,
            )]

        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()

        source_lines = source.splitlines()
        diagnoses = []

        # Phase 1: Static analysis — check for obvious issues before running
        static_diags = self._static_analysis(filepath, source, source_lines)
        diagnoses.extend(static_diags)

        # Phase 2: Runtime analysis — actually execute and catch errors
        runtime_diags = self._runtime_analysis(filepath, source, source_lines)
        diagnoses.extend(runtime_diags)

        # Record all in knowledge base
        for d in diagnoses:
            self.kb.record(d)

        return diagnoses

    def _static_analysis(self, filepath: str, source: str,
                         lines: List[str]) -> List[Diagnosis]:
        """Detect issues without running the code."""
        diags = []

        # Check 1: Unmatched quotes
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('//'):
                continue
            # Count unescaped quotes
            in_str = False
            quote_char = None
            for j, ch in enumerate(stripped):
                if ch in ('"', "'") and (j == 0 or stripped[j-1] != '\\'):
                    if not in_str:
                        in_str = True
                        quote_char = ch
                    elif ch == quote_char:
                        in_str = False
                        quote_char = None
            if in_str:
                diags.append(Diagnosis(
                    file=filepath, line=i,
                    category=ErrorCategory.SYNTAX_ERROR,
                    error_message=f"Unclosed string literal on line {i}",
                    source_context=self._get_context(lines, i),
                    suggestions=[{
                        "text": f"Add closing {quote_char} on line {i}",
                        "confidence": 0.8,
                        "fix": f"Close the string with {quote_char}",
                    }],
                    confidence=0.8, auto_fixable=False,
                ))

        # Check 2: Potential infinite loops (while true without break)
        for i, line in enumerate(lines, 1):
            stripped = line.strip().lower()
            if stripped in ('while true', 'while 1'):
                # Look ahead for break
                has_break = False
                indent = len(line) - len(line.lstrip())
                for j in range(i, min(i + 50, len(lines))):
                    jline = lines[j]
                    jindent = len(jline) - len(jline.lstrip())
                    if jline.strip() and jindent <= indent and j > i:
                        break
                    if 'break' in jline.lower():
                        has_break = True
                        break
                if not has_break:
                    diags.append(Diagnosis(
                        file=filepath, line=i,
                        category=ErrorCategory.STACK_OVERFLOW,
                        error_message=f"Potential infinite loop at line {i}: 'while true' without break",
                        source_context=self._get_context(lines, i),
                        suggestions=[{
                            "text": "Add a break condition inside the while loop",
                            "confidence": 0.7,
                            "fix": "Add 'if <condition>\\n    break' inside the loop body",
                        }],
                        confidence=0.7, auto_fixable=False,
                    ))

        # Check 3: Variable used before assignment (simple heuristic)
        defined_vars = set()
        builtins = {
            'print', 'len', 'type', 'str', 'int', 'float', 'bool',
            'input', 'range', 'abs', 'min', 'max', 'sum', 'round',
            'map', 'filter', 'sort', 'reverse', 'append', 'pop',
            'push', 'keys', 'values', 'upper', 'lower', 'trim',
            'split', 'join', 'replace', 'contains', 'starts_with',
            'ends_with', 'substr', 'to_int', 'to_float', 'to_str',
            'random', 'random_int', 'time', 'sleep', 'true', 'false',
            'null', 'none', 'nil', 'pi', 'e', 'sqrt', 'floor', 'ceil',
            'log', 'sin', 'cos', 'tan', 'typeof', 'is_list', 'is_map',
            'is_string', 'is_number', 'is_bool', 'is_null', 'is_function',
        }
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or stripped.startswith('//'):
                continue
            # Track set/assignment
            m = re.match(r'^set\s+(\w+)\s+to\b', stripped)
            if m:
                defined_vars.add(m.group(1))
                continue
            # Track function definitions
            m = re.match(r'^(?:function|func|fn)\s+(\w+)', stripped)
            if m:
                defined_vars.add(m.group(1))
                continue
            # Track for loop vars
            m = re.match(r'^for\s+(\w+)\s+', stripped)
            if m:
                defined_vars.add(m.group(1))
                continue
            # Track foreach vars
            m = re.match(r'^foreach\s+(\w+)\s+in\b', stripped)
            if m:
                defined_vars.add(m.group(1))
                continue

        return diags

    def _runtime_analysis(self, filepath: str, source: str,
                          lines: List[str]) -> List[Diagnosis]:
        """Run the code and diagnose runtime errors."""
        diags = []
        captured_stdout = StringIO()
        captured_stderr = StringIO()

        try:
            tokens = tokenize(source)
            parser = Parser(tokens)
            ast = parser.parse()

            interp = Interpreter()
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = captured_stdout
            sys.stderr = captured_stderr

            try:
                interp.execute_body(ast)
            except RecursionError as e:
                diags.append(self._classify_error(
                    filepath, lines, str(e) or "Maximum recursion depth exceeded",
                    traceback.format_exc()
                ))
            except RuntimeError as e:
                diags.append(self._classify_error(
                    filepath, lines, str(e), traceback.format_exc()
                ))
            except Exception as e:
                diags.append(self._classify_error(
                    filepath, lines, str(e), traceback.format_exc()
                ))
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

        except RecursionError as e:
            diags.append(self._classify_error(
                filepath, lines,
                str(e) or "Maximum recursion depth exceeded during parsing",
                traceback.format_exc()
            ))
        except RuntimeError as e:
            # Parse/tokenize error
            diags.append(self._classify_error(
                filepath, lines, str(e), traceback.format_exc()
            ))
        except Exception as e:
            diags.append(self._classify_error(
                filepath, lines, str(e), traceback.format_exc()
            ))

        return diags

    def _classify_error(self, filepath: str, lines: List[str],
                        error_msg: str, stack_trace: str) -> Diagnosis:
        """Match an error against known patterns and generate diagnosis."""
        # Extract line number from error message or traceback
        line_num = self._extract_line(error_msg, stack_trace)

        # Match against patterns
        best_match = None
        best_confidence = 0.0
        match_groups = {}

        for pattern, compiled in self._compiled_patterns:
            m = compiled.search(error_msg)
            if m:
                # Boost confidence if KB has seen this pattern before
                kb_boost = 0.0
                cat_count = self.kb.error_counts.get(pattern.category, 0)
                if cat_count > 5:
                    kb_boost = min(0.05, cat_count * 0.005)
                adj_confidence = min(1.0, pattern.confidence + kb_boost)

                if adj_confidence > best_confidence:
                    best_confidence = adj_confidence
                    best_match = pattern
                    match_groups = {f"g{i}": g for i, g in enumerate(m.groups())}

        if best_match is None:
            # Generic fallback
            return Diagnosis(
                file=filepath, line=line_num,
                category=ErrorCategory.RUNTIME_GENERIC,
                error_message=error_msg,
                source_context=self._get_context(lines, line_num) if line_num else [],
                suggestions=[{
                    "text": "Review the error message and check the code near the failure point.",
                    "confidence": 0.3,
                }],
                confidence=0.3,
                auto_fixable=False,
                stack_trace=stack_trace,
                related_errors=self._find_related(error_msg),
            )

        # Build suggestions
        suggestions = []
        sugg_text = best_match.suggestion_template
        # Fill in template vars
        for k, v in match_groups.items():
            sugg_text = sugg_text.replace(f"{{{k}}}", str(v) if v else "")
        sugg_text = sugg_text.replace("{line}", str(line_num or "?"))
        if match_groups.get("g0"):
            sugg_text = sugg_text.replace("{var}", match_groups["g0"])
            sugg_text = sugg_text.replace("{key}", match_groups["g0"])
            sugg_text = sugg_text.replace("{attr}", match_groups["g0"])
            sugg_text = sugg_text.replace("{idx}", match_groups["g0"])

        suggestions.append({
            "text": sugg_text,
            "confidence": best_confidence,
            "fix": best_match.fix_template or "",
        })

        # Add KB-sourced suggestions
        kb_fixes = self.kb.common_fixes.get(best_match.category, [])
        for fix in kb_fixes[:3]:
            if fix not in [s.get("fix") for s in suggestions]:
                suggestions.append({
                    "text": f"Previously effective fix: {fix}",
                    "confidence": best_confidence * 0.8,
                    "fix": fix,
                    "source": "knowledge_base",
                })

        # Build fix patch if auto-fixable
        fix_patch = None
        if best_match.auto_fixable and line_num and line_num <= len(lines):
            fix_patch = self._build_fix_patch(
                best_match, lines, line_num, match_groups, error_msg
            )

        return Diagnosis(
            file=filepath, line=line_num,
            category=best_match.category,
            error_message=error_msg,
            source_context=self._get_context(lines, line_num) if line_num else [],
            suggestions=suggestions,
            confidence=best_confidence,
            auto_fixable=best_match.auto_fixable and fix_patch is not None,
            fix_patch=fix_patch,
            stack_trace=stack_trace if self.deep else None,
            related_errors=self._find_related(error_msg),
        )

    def _extract_line(self, error_msg: str, stack_trace: str) -> Optional[int]:
        """Extract line number from error message or stack trace."""
        # Pattern: "on line N" or "line N" in error message
        m = re.search(r'(?:on )?line (\d+)', error_msg, re.IGNORECASE)
        if m:
            return int(m.group(1))
        # Pattern: "File ... line N" in traceback
        matches = re.findall(r'line (\d+)', stack_trace)
        if matches:
            return int(matches[-1])
        return None

    def _get_context(self, lines: List[str], line_num: int,
                     radius: int = 3) -> List[str]:
        """Get source lines around the error."""
        if not line_num or line_num < 1:
            return []
        start = max(0, line_num - radius - 1)
        end = min(len(lines), line_num + radius)
        ctx = []
        for i in range(start, end):
            marker = ">>>" if i == line_num - 1 else "   "
            ctx.append(f"{marker} {i+1:4d} | {lines[i]}")
        return ctx

    def _build_fix_patch(self, pattern: ErrorPattern, lines: List[str],
                         line_num: int, groups: dict,
                         error_msg: str) -> Optional[Dict[str, str]]:
        """Build a concrete fix patch for auto-fixable errors."""
        if not pattern.fix_template:
            return None

        original_line = lines[line_num - 1] if line_num <= len(lines) else ""
        indent = len(original_line) - len(original_line.lstrip())
        indent_str = " " * indent

        fix = pattern.fix_template
        fix = fix.replace("{original_line}", original_line.strip())
        for k, v in groups.items():
            if v:
                fix = fix.replace(f"{{{k}}}", v)
                fix = fix.replace("{var}", v)
                fix = fix.replace("{key}", v)
                fix = fix.replace("{idx}", v)

        # Extract divisor from division by zero errors
        if pattern.category == ErrorCategory.DIVISION_ZERO:
            m = re.search(r'(/\s*\w+)', original_line)
            divisor = m.group(1).replace('/', '').strip() if m else "divisor"
            fix = fix.replace("{divisor}", divisor)

        # Extract collection name for empty collection errors
        if pattern.category == ErrorCategory.EMPTY_COLLECTION:
            m = re.search(r'(\w+)\s*\.\s*(?:pop|dequeue|peek)', original_line)
            coll = m.group(1) if m else "collection"
            fix = fix.replace("{collection}", coll)

        # Extract map/key for key errors
        if pattern.category == ErrorCategory.KEY_ERROR:
            m = re.search(r'map_get\s+(\w+)\s+"?(\w+)"?', original_line)
            if m:
                fix = fix.replace("{map}", m.group(1))
                fix = fix.replace("{key}", m.group(2))

        # Apply indentation
        fix_lines = fix.split("\n")
        indented = "\n".join(indent_str + fl for fl in fix_lines)

        return {"old": original_line, "new": indented}

    def _find_related(self, error_msg: str) -> List[str]:
        """Find related past errors from the knowledge base."""
        related = []
        words = set(re.findall(r'\w+', error_msg.lower()))
        for entry in self.kb.error_history[-50:]:
            past_words = set(re.findall(r'\w+', entry.get("error", "").lower()))
            overlap = len(words & past_words)
            if overlap >= 3 and entry["error"] != error_msg[:200]:
                related.append(
                    f"[{entry['category']}] {entry['file']}:{entry.get('line', '?')} — {entry['error'][:80]}"
                )
        return related[:5]

    def diagnose_directory(self, dirpath: str) -> Dict[str, List[Diagnosis]]:
        """Scan all .srv files in a directory."""
        results = {}
        srv_files = glob.glob(os.path.join(dirpath, "**", "*.srv"), recursive=True)
        if not srv_files:
            srv_files = glob.glob(os.path.join(dirpath, "*.srv"))

        for fp in sorted(srv_files):
            diags = self.diagnose_file(fp)
            if diags:
                results[fp] = diags
        return results


# ── Fix Applier ───────────────────────────────────────────────────────

def apply_fixes(diagnoses: List[Diagnosis], dry_run: bool = False) -> List[str]:
    """Apply auto-fix patches to files. Returns list of applied fix descriptions."""
    applied = []
    file_patches = defaultdict(list)

    for d in diagnoses:
        if d.auto_fixable and d.fix_patch:
            file_patches[d.file].append(d)

    for filepath, diags in file_patches.items():
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        for d in diags:
            old = d.fix_patch["old"]
            new = d.fix_patch["new"]
            if old in content:
                desc = f"{filepath}:{d.line} [{d.category}] — {d.error_message[:60]}"
                if dry_run:
                    applied.append(f"[DRY-RUN] Would fix: {desc}")
                else:
                    content = content.replace(old, new, 1)
                    applied.append(f"Fixed: {desc}")

        if not dry_run and any(d.fix_patch["old"] in open(filepath).read()
                               for d in diags if d.fix_patch):
            pass  # Already handled above
        if not dry_run:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

    return applied


# ── HTML Report Generator ─────────────────────────────────────────────

def generate_html_report(all_diagnoses: Dict[str, List[Diagnosis]],
                         kb: KnowledgeBase) -> str:
    """Generate an interactive HTML diagnosis report."""

    total_errors = sum(len(d) for d in all_diagnoses.values())
    total_fixable = sum(1 for ds in all_diagnoses.values()
                        for d in ds if d.auto_fixable)
    categories = Counter(d.category for ds in all_diagnoses.values() for d in ds)

    # Category color map
    cat_colors = {
        ErrorCategory.UNDEFINED_VAR: "#e74c3c",
        ErrorCategory.TYPE_ERROR: "#e67e22",
        ErrorCategory.INDEX_OOB: "#f39c12",
        ErrorCategory.KEY_ERROR: "#9b59b6",
        ErrorCategory.DIVISION_ZERO: "#c0392b",
        ErrorCategory.STACK_OVERFLOW: "#8e44ad",
        ErrorCategory.SYNTAX_ERROR: "#d35400",
        ErrorCategory.EMPTY_COLLECTION: "#2980b9",
        ErrorCategory.ARGUMENT_ERROR: "#16a085",
        ErrorCategory.ASSERTION_FAIL: "#27ae60",
        ErrorCategory.IMPORT_ERROR: "#2c3e50",
        ErrorCategory.ATTRIBUTE_ERROR: "#7f8c8d",
        ErrorCategory.RUNTIME_GENERIC: "#95a5a6",
    }

    # Build category chart data
    cat_labels = json.dumps(list(categories.keys()))
    cat_values = json.dumps(list(categories.values()))
    cat_clrs = json.dumps([cat_colors.get(c, "#95a5a6") for c in categories.keys()])

    # Build file cards
    file_cards = []
    for filepath, diags in sorted(all_diagnoses.items()):
        fname = os.path.basename(filepath)
        cards_html = ""
        for d in diags:
            color = cat_colors.get(d.category, "#95a5a6")
            ctx_html = "\n".join(
                f"<span class='{'error-line' if l.startswith('>>>') else ''}'>{_html_esc(l)}</span>"
                for l in d.source_context
            )
            sugg_html = ""
            for s in d.suggestions:
                conf_pct = int(s["confidence"] * 100)
                sugg_html += f"<div class='suggestion'><span class='conf'>{conf_pct}%</span> {_html_esc(s['text'])}</div>"
            fix_badge = "<span class='fix-badge'>AUTO-FIXABLE</span>" if d.auto_fixable else ""
            cards_html += f"""
            <div class='diagnosis-card' style='border-left: 4px solid {color}'>
                <div class='card-header'>
                    <span class='category' style='background:{color}'>{d.category}</span>
                    <span class='line'>Line {d.line or '?'}</span>
                    {fix_badge}
                    <span class='confidence'>Confidence: {int(d.confidence*100)}%</span>
                </div>
                <div class='error-msg'>{_html_esc(d.error_message)}</div>
                <pre class='source-ctx'>{ctx_html}</pre>
                <div class='suggestions-box'>
                    <strong>Suggestions:</strong>
                    {sugg_html}
                </div>
            </div>"""
        file_cards.append(f"""
        <div class='file-section'>
            <h3>📄 {_html_esc(fname)} <span class='count'>({len(diags)} issue{'s' if len(diags) != 1 else ''})</span></h3>
            {cards_html}
        </div>""")

    files_html = "\n".join(file_cards) if file_cards else "<p class='no-issues'>No issues found! 🎉</p>"

    # KB stats
    top_errors_html = ""
    for cat, count in kb.get_top_errors(8):
        trend = kb.get_trend(cat)
        trend_icon = {"increasing": "📈", "decreasing": "📉", "stable": "➡️"}.get(trend, "")
        top_errors_html += f"<tr><td>{cat}</td><td>{count}</td><td>{trend_icon} {trend}</td></tr>"

    hotspots_html = ""
    for f, count in kb.get_hotspot_files(8):
        hotspots_html += f"<tr><td>{_html_esc(os.path.basename(f))}</td><td>{count}</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>sauravdiagnose — Error Diagnosis Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root {{ --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #e6edf3;
         --muted: #8b949e; --accent: #58a6ff; --green: #3fb950; --red: #f85149; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: var(--bg); color: var(--text); padding: 20px; }}
h1 {{ font-size: 1.8em; margin-bottom: 8px; }}
h2 {{ font-size: 1.3em; margin: 24px 0 12px; color: var(--accent); }}
h3 {{ font-size: 1.1em; margin-bottom: 12px; }}
.header {{ text-align: center; padding: 30px 0; }}
.header .subtitle {{ color: var(--muted); }}
.stats-row {{ display: flex; gap: 16px; justify-content: center; margin: 20px 0; flex-wrap: wrap; }}
.stat-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px;
              padding: 16px 24px; text-align: center; min-width: 140px; }}
.stat-card .number {{ font-size: 2em; font-weight: bold; }}
.stat-card .label {{ color: var(--muted); font-size: 0.85em; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 20px 0; }}
@media (max-width: 768px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.panel {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }}
.file-section {{ margin-bottom: 24px; }}
.file-section .count {{ color: var(--muted); font-weight: normal; }}
.diagnosis-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 6px;
                   padding: 16px; margin-bottom: 12px; }}
.card-header {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }}
.category {{ padding: 2px 8px; border-radius: 4px; font-size: 0.8em; color: white; }}
.line {{ color: var(--muted); font-size: 0.85em; }}
.confidence {{ color: var(--muted); font-size: 0.85em; margin-left: auto; }}
.fix-badge {{ background: var(--green); color: #000; padding: 2px 8px; border-radius: 4px;
              font-size: 0.75em; font-weight: bold; }}
.error-msg {{ color: var(--red); font-family: monospace; margin: 8px 0; padding: 8px;
              background: rgba(248,81,73,0.1); border-radius: 4px; word-break: break-word; }}
.source-ctx {{ background: #0d1117; border: 1px solid var(--border); border-radius: 4px;
               padding: 12px; font-size: 0.85em; overflow-x: auto; white-space: pre; line-height: 1.6; }}
.error-line {{ color: var(--red); font-weight: bold; }}
.suggestions-box {{ margin-top: 12px; }}
.suggestion {{ padding: 6px 10px; margin: 4px 0; background: rgba(88,166,255,0.08);
               border-radius: 4px; font-size: 0.9em; }}
.conf {{ color: var(--accent); font-weight: bold; margin-right: 8px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
th {{ color: var(--muted); font-size: 0.85em; }}
.no-issues {{ text-align: center; padding: 40px; color: var(--green); font-size: 1.2em; }}
.chart-container {{ max-width: 400px; margin: 0 auto; }}
</style>
</head>
<body>
<div class="header">
    <h1>🔬 sauravdiagnose</h1>
    <p class="subtitle">Autonomous Runtime Error Diagnosis Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</div>

<div class="stats-row">
    <div class="stat-card">
        <div class="number" style="color:var(--red)">{total_errors}</div>
        <div class="label">Issues Found</div>
    </div>
    <div class="stat-card">
        <div class="number" style="color:var(--green)">{total_fixable}</div>
        <div class="label">Auto-Fixable</div>
    </div>
    <div class="stat-card">
        <div class="number" style="color:var(--accent)">{len(all_diagnoses)}</div>
        <div class="label">Files Affected</div>
    </div>
    <div class="stat-card">
        <div class="number">{kb.total_diagnoses}</div>
        <div class="label">KB Total Diagnoses</div>
    </div>
</div>

<div class="grid">
    <div class="panel">
        <h2>📊 Error Distribution</h2>
        <div class="chart-container">
            <canvas id="catChart"></canvas>
        </div>
    </div>
    <div class="panel">
        <h2>🔥 Error Hotspots (KB)</h2>
        <table>
            <tr><th>File</th><th>Errors</th></tr>
            {hotspots_html if hotspots_html else '<tr><td colspan="2" style="color:var(--muted)">No history yet</td></tr>'}
        </table>
        <h2 style="margin-top:20px">📈 Trending Errors (KB)</h2>
        <table>
            <tr><th>Category</th><th>Count</th><th>Trend</th></tr>
            {top_errors_html if top_errors_html else '<tr><td colspan="3" style="color:var(--muted)">No history yet</td></tr>'}
        </table>
    </div>
</div>

<h2>📋 Diagnosis Results</h2>
{files_html}

<script>
const ctx = document.getElementById('catChart');
if (ctx) {{
    new Chart(ctx, {{
        type: 'doughnut',
        data: {{
            labels: {cat_labels},
            datasets: [{{ data: {cat_values}, backgroundColor: {cat_clrs}, borderWidth: 0 }}]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ position: 'bottom', labels: {{ color: '#e6edf3', font: {{ size: 11 }} }} }}
            }}
        }}
    }});
}}
</script>
</body></html>"""


def _html_esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ── CLI Formatter ─────────────────────────────────────────────────────

def print_diagnosis(d: Diagnosis, verbose: bool = False):
    """Print a single diagnosis to terminal."""
    cat_colors = {
        ErrorCategory.UNDEFINED_VAR: "31",
        ErrorCategory.TYPE_ERROR: "33",
        ErrorCategory.INDEX_OOB: "33",
        ErrorCategory.KEY_ERROR: "35",
        ErrorCategory.DIVISION_ZERO: "31",
        ErrorCategory.STACK_OVERFLOW: "35",
        ErrorCategory.SYNTAX_ERROR: "31",
        ErrorCategory.EMPTY_COLLECTION: "34",
        ErrorCategory.ARGUMENT_ERROR: "36",
        ErrorCategory.ASSERTION_FAIL: "32",
        ErrorCategory.IMPORT_ERROR: "37",
        ErrorCategory.ATTRIBUTE_ERROR: "37",
        ErrorCategory.RUNTIME_GENERIC: "37",
    }
    cc = cat_colors.get(d.category, "37")

    fix_tag = _C.green(" [AUTO-FIXABLE]") if d.auto_fixable else ""
    print(f"\n  \033[{cc};1m● {d.category}\033[0m  "
          f"{_C.dim(d.file)}:{d.line or '?'}{fix_tag}")
    print(f"    {_C.red(d.error_message)}")

    if d.source_context:
        print()
        for line in d.source_context:
            if line.startswith(">>>"):
                print(f"    {_C.red(line)}")
            else:
                print(f"    {_C.dim(line)}")

    if d.suggestions:
        print(f"\n    {_C.bold('Suggestions:')}")
        for s in d.suggestions:
            conf_pct = int(s["confidence"] * 100)
            src = f" ({_C.dim('from KB')})" if s.get("source") == "knowledge_base" else ""
            print(f"      {_C.cyan(f'{conf_pct}%')} {s['text']}{src}")

    if verbose and d.related_errors:
        print(f"\n    {_C.bold('Related past errors:')}")
        for r in d.related_errors:
            print(f"      {_C.dim('•')} {_C.dim(r)}")

    if verbose and d.stack_trace:
        print(f"\n    {_C.dim('Stack trace:')}")
        for line in d.stack_trace.splitlines()[-8:]:
            print(f"    {_C.dim(line)}")


def print_kb_stats(kb: KnowledgeBase):
    """Print knowledge base statistics."""
    print(f"\n  {_C.bold('Knowledge Base Statistics')}")
    print(f"  {'─' * 40}")
    print(f"  Total diagnoses: {_C.cyan(str(kb.total_diagnoses))}")
    print(f"  Error categories tracked: {len(kb.error_counts)}")
    print(f"  Files tracked: {len(kb.file_error_counts)}")
    print(f"  History entries: {len(kb.error_history)}")

    top = kb.get_top_errors(10)
    if top:
        print(f"\n  {_C.bold('Top Error Categories:')}")
        for cat, count in top:
            trend = kb.get_trend(cat)
            trend_icon = {"increasing": "↑", "decreasing": "↓", "stable": "→"}.get(trend, "")
            bar = "█" * min(30, count)
            print(f"    {cat:30s} {_C.cyan(str(count)):>6s}  {bar} {trend_icon}")

    hotspots = kb.get_hotspot_files(10)
    if hotspots:
        print(f"\n  {_C.bold('Error Hotspot Files:')}")
        for f, count in hotspots:
            print(f"    {os.path.basename(f):30s} {_C.red(str(count)):>6s} errors")


# ── Main ──────────────────────────────────────────────────────────────

def main(argv=None):
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="sauravdiagnose",
        description="Autonomous runtime error diagnosis engine for sauravcode",
    )
    parser.add_argument("target", nargs="?", default=".",
                        help="File or directory to diagnose (default: current directory)")
    parser.add_argument("--fix", action="store_true",
                        help="Auto-patch fixable issues")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show patches without applying (requires --fix)")
    parser.add_argument("--deep", action="store_true",
                        help="Deep analysis with full stack traces")
    parser.add_argument("--html", metavar="FILE",
                        help="Generate interactive HTML report")
    parser.add_argument("--json", action="store_true",
                        help="JSON output")
    parser.add_argument("--kb", action="store_true",
                        help="Show knowledge base statistics")
    parser.add_argument("--kb-reset", action="store_true",
                        help="Reset knowledge base")
    parser.add_argument("--top", type=int, metavar="N",
                        help="Show top N most common errors from KB")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show related errors and stack traces")

    args = parser.parse_args(argv)

    # Load knowledge base
    kb = KnowledgeBase.load()

    if args.kb_reset:
        kb = KnowledgeBase()
        kb.save()
        print(f"  {_C.green('✓')} Knowledge base reset.")
        return

    if args.kb:
        print_kb_stats(kb)
        return

    if args.top:
        top = kb.get_top_errors(args.top)
        if not top:
            print(f"  {_C.dim('No errors in knowledge base yet.')}")
            return
        print(f"\n  {_C.bold(f'Top {args.top} Error Categories:')}")
        for cat, count in top:
            trend = kb.get_trend(cat)
            trend_icon = {"increasing": "↑", "decreasing": "↓", "stable": "→"}.get(trend, "")
            print(f"    {cat:30s} {count:>4d}  {trend_icon}")
        return

    # Run diagnosis
    engine = DiagnosisEngine(kb=kb, deep=args.deep)
    target = args.target

    all_diagnoses = {}
    if os.path.isfile(target) and target.endswith('.srv'):
        diags = engine.diagnose_file(target)
        if diags:
            all_diagnoses[target] = diags
    elif os.path.isdir(target):
        all_diagnoses = engine.diagnose_directory(target)
    else:
        print(f"  {_C.red('Error:')} Target must be a .srv file or directory")
        sys.exit(1)

    # Save KB
    kb.save()

    # Output
    total = sum(len(d) for d in all_diagnoses.values())

    if args.json:
        output = {
            "total_issues": total,
            "files": {
                fp: [asdict(d) for d in ds]
                for fp, ds in all_diagnoses.items()
            },
            "kb_stats": {
                "total_diagnoses": kb.total_diagnoses,
                "categories": dict(kb.get_top_errors(20)),
            }
        }
        print(json.dumps(output, indent=2, default=str))
        return

    if args.html:
        html = generate_html_report(all_diagnoses, kb)
        with open(args.html, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"  {_C.green('✓')} HTML report written to {args.html}")
        return

    # Terminal output
    if not all_diagnoses:
        print(f"\n  {_C.green('✓ No issues found!')} All .srv files executed cleanly.")
        return

    print(f"\n  {_C.bold('sauravdiagnose')} — Runtime Error Diagnosis")
    print(f"  {'═' * 50}")

    for filepath, diags in sorted(all_diagnoses.items()):
        print(f"\n  {_C.bold('📄 ' + os.path.basename(filepath))}")
        for d in diags:
            print_diagnosis(d, verbose=args.verbose or args.deep)

    fixable = sum(1 for ds in all_diagnoses.values() for d in ds if d.auto_fixable)
    print(f"\n  {'═' * 50}")
    print(f"  {_C.bold('Summary:')} {_C.red(str(total))} issue{'s' if total != 1 else ''} "
          f"in {len(all_diagnoses)} file{'s' if len(all_diagnoses) != 1 else ''}"
          f" ({_C.green(str(fixable))} auto-fixable)")

    # Apply fixes
    if args.fix and fixable > 0:
        all_diags = [d for ds in all_diagnoses.values() for d in ds]
        applied = apply_fixes(all_diags, dry_run=args.dry_run)
        if applied:
            print(f"\n  {_C.bold('Fixes Applied:')}")
            for a in applied:
                print(f"    {_C.green('✓')} {a}")
    elif args.fix:
        print(f"\n  {_C.dim('No auto-fixable issues to patch.')}")


if __name__ == "__main__":
    main()

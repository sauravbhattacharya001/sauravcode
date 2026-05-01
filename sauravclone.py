#!/usr/bin/env python3
"""
sauravclone - Autonomous Code Clone Detector for sauravcode programs.

Detects duplicated code fragments across .srv files using AST-based
structural comparison. Classifies clones into types (exact, renamed,
near-miss), calculates a DRY score, and suggests refactoring opportunities
to eliminate redundancy.

Usage:
    python sauravclone.py program.srv                 # Detect clones in a file
    python sauravclone.py src/ --recursive            # Scan entire directory
    python sauravclone.py program.srv --min-tokens 20 # Minimum clone size (tokens)
    python sauravclone.py program.srv --threshold 0.8 # Similarity threshold (0-1)
    python sauravclone.py program.srv --json          # JSON output
    python sauravclone.py program.srv --html report   # Interactive HTML dashboard
    python sauravclone.py program.srv --refactor      # Show refactoring suggestions
    python sauravclone.py program.srv --dry-score     # Show DRY score only
    python sauravclone.py program.srv --type exact    # Only show exact clones
    python sauravclone.py program.srv --type renamed  # Only renamed-variable clones
    python sauravclone.py program.srv --type gapped   # Only near-miss clones

Clone Types:
    Type 1 (Exact)   - Identical code fragments (ignoring whitespace/comments)
    Type 2 (Renamed) - Structurally identical but with renamed variables/functions
    Type 3 (Gapped)  - Similar structure with small insertions/deletions/modifications

Agentic Features:
    - Autonomous redundancy detection without configuration
    - Refactoring suggestions with confidence scores
    - DRY (Don't Repeat Yourself) health score 0-100
    - Trend detection when run over time
    - Priority ranking by clone severity and fix effort
"""

import sys
import os
import json as _json
import argparse
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Set

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, ASTNode


# ── AST Utilities ────────────────────────────────────────────────────────────

_NODE_CHILD_ATTRS: dict = {}


def _child_attrs(node):
    """Return cached tuple of child-bearing attribute names for node's type."""
    cls = type(node)
    attrs = _NODE_CHILD_ATTRS.get(cls)
    if attrs is not None:
        return attrs
    attrs = tuple(
        a for a in sorted(vars(node))
        if not a.startswith('_') and a != 'line_num'
    )
    _NODE_CHILD_ATTRS[cls] = attrs
    return attrs


def walk_ast(nodes, depth=0):
    """Yield (node, depth) for every ASTNode in the tree."""
    if isinstance(nodes, list):
        for node in nodes:
            yield from walk_ast(node, depth)
    elif isinstance(nodes, ASTNode):
        yield (nodes, depth)
        for attr in _child_attrs(nodes):
            val = getattr(nodes, attr)
            if isinstance(val, ASTNode):
                yield from walk_ast(val, depth + 1)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, ASTNode):
                        yield from walk_ast(item, depth + 1)


def node_size(node):
    """Count the number of AST nodes in a subtree."""
    count = 0
    for _ in walk_ast(node):
        count += 1
    return count


def node_fingerprint(node, normalize_names=False):
    """Generate a structural fingerprint for an AST node.
    
    If normalize_names=True, all identifiers are replaced with positional
    placeholders, enabling detection of renamed clones.
    """
    name_map = {}
    name_counter = [0]

    def _normalize(name):
        if name not in name_map:
            name_map[name] = f"$V{name_counter[0]}"
            name_counter[0] += 1
        return name_map[name]

    def _fp(n):
        if isinstance(n, ASTNode):
            type_name = type(n).__name__
            parts = [type_name]
            for attr in _child_attrs(n):
                val = getattr(n, attr)
                if normalize_names and isinstance(val, str) and attr in ('name', 'var_name', 'func_name', 'target'):
                    parts.append(f"{attr}={_normalize(val)}")
                elif isinstance(val, ASTNode):
                    parts.append(_fp(val))
                elif isinstance(val, list):
                    sub = [_fp(item) if isinstance(item, ASTNode) else repr(item) for item in val]
                    parts.append(f"[{','.join(sub)}]")
                elif isinstance(val, str) and normalize_names:
                    parts.append(f"{attr}={_normalize(val)}")
                else:
                    parts.append(f"{attr}={repr(val)}")
            return f"({' '.join(parts)})"
        return repr(n)

    return _fp(node)


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class CodeFragment:
    """A parseable code fragment from a source file."""
    file: str
    start_line: int
    end_line: int
    node: object  # ASTNode
    size: int  # number of AST nodes
    fingerprint: str = ""
    normalized_fingerprint: str = ""


@dataclass
class CloneGroup:
    """A group of code fragments that are clones of each other."""
    clone_type: str  # 'exact', 'renamed', 'gapped'
    fragments: List[CodeFragment] = field(default_factory=list)
    similarity: float = 1.0
    size: int = 0  # AST nodes in each fragment
    refactoring: Optional[str] = None
    confidence: float = 0.0
    severity: str = "low"  # low, medium, high, critical


@dataclass
class CloneReport:
    """Full clone detection report."""
    files_scanned: int = 0
    total_fragments: int = 0
    clone_groups: List[CloneGroup] = field(default_factory=list)
    dry_score: float = 100.0
    total_lines: int = 0
    cloned_lines: int = 0
    insights: List[str] = field(default_factory=list)


# ── File Parsing ─────────────────────────────────────────────────────────────

def parse_file(path):
    """Parse a .srv file and return its AST."""
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        source = f.read()
    tokens = tokenize(source)
    parser = Parser(tokens)
    return parser.parse()


def collect_files(path, recursive=False):
    """Collect .srv files from a path."""
    files = []
    if os.path.isfile(path):
        if path.endswith('.srv'):
            files.append(path)
    elif os.path.isdir(path):
        if recursive:
            for root, dirs, fnames in os.walk(path):
                for fname in fnames:
                    if fname.endswith('.srv'):
                        files.append(os.path.join(root, fname))
        else:
            for fname in os.listdir(path):
                if fname.endswith('.srv'):
                    files.append(os.path.join(path, fname))
    return sorted(files)


# ── Fragment Extraction ──────────────────────────────────────────────────────

def extract_fragments(ast, filename, min_size=5):
    """Extract meaningful code fragments from an AST.
    
    Extracts function bodies, top-level statements, loop bodies, and
    conditional branches as individual fragments for comparison.
    """
    fragments = []
    
    # Extract top-level function definitions
    for node, depth in walk_ast(ast):
        type_name = type(node).__name__
        
        # Skip trivially small nodes
        size = node_size(node)
        if size < min_size:
            continue
        
        # Only extract meaningful structural units
        if type_name in ('FunctionNode', 'FunctionDef', 'ForLoop', 'WhileLoop',
                         'ForEachLoop', 'ForNode', 'WhileNode', 'ForEachNode',
                         'IfStatement', 'IfNode', 'TryCatch', 'TryNode',
                         'MatchStatement', 'MatchNode'):
            line = getattr(node, 'line_num', 0) or 0
            frag = CodeFragment(
                file=filename,
                start_line=line,
                end_line=line,  # Approximate; we use AST size instead
                node=node,
                size=size,
            )
            # For functions, fingerprint the body to detect same-body clones
            if type_name in ('FunctionNode', 'FunctionDef') and hasattr(node, 'body'):
                body = getattr(node, 'body')
                if isinstance(body, list) and body:
                    body_fp_parts = [node_fingerprint(b, False) for b in body if isinstance(b, ASTNode)]
                    body_norm_parts = [node_fingerprint(b, True) for b in body if isinstance(b, ASTNode)]
                    frag.fingerprint = f"BODY[{';'.join(body_fp_parts)}]"
                    frag.normalized_fingerprint = f"BODY[{';'.join(body_norm_parts)}]"
                else:
                    frag.fingerprint = node_fingerprint(node, normalize_names=False)
                    frag.normalized_fingerprint = node_fingerprint(node, normalize_names=True)
            else:
                frag.fingerprint = node_fingerprint(node, normalize_names=False)
                frag.normalized_fingerprint = node_fingerprint(node, normalize_names=True)
            fragments.append(frag)
    
    # Also extract sequences of consecutive statements (sliding window)
    if isinstance(ast, list) and len(ast) >= 2:
        for window_size in range(2, min(6, len(ast) + 1)):
            for i in range(len(ast) - window_size + 1):
                window = ast[i:i + window_size]
                total_size = sum(node_size(n) for n in window if isinstance(n, ASTNode))
                if total_size < min_size:
                    continue
                # Use a wrapper fingerprint for sequences
                fps = [node_fingerprint(n, False) for n in window if isinstance(n, ASTNode)]
                norm_fps = [node_fingerprint(n, True) for n in window if isinstance(n, ASTNode)]
                line = getattr(window[0], 'line_num', 0) or 0
                frag = CodeFragment(
                    file=filename,
                    start_line=line,
                    end_line=line,
                    node=window,
                    size=total_size,
                    fingerprint="SEQ[" + ";".join(fps) + "]",
                    normalized_fingerprint="SEQ[" + ";".join(norm_fps) + "]",
                )
                fragments.append(frag)
    
    return fragments


# ── Clone Detection Engines ──────────────────────────────────────────────────

def detect_exact_clones(fragments):
    """Type 1: Find fragments with identical fingerprints."""
    by_fp = defaultdict(list)
    for frag in fragments:
        if frag.fingerprint:
            by_fp[frag.fingerprint].append(frag)
    
    groups = []
    for fp, frags in by_fp.items():
        if len(frags) < 2:
            continue
        # Deduplicate: don't report same-file overlapping fragments
        unique = _deduplicate_fragments(frags)
        if len(unique) < 2:
            continue
        group = CloneGroup(
            clone_type='exact',
            fragments=unique,
            similarity=1.0,
            size=unique[0].size,
        )
        groups.append(group)
    return groups


def detect_renamed_clones(fragments):
    """Type 2: Find fragments identical after normalizing identifiers."""
    by_norm = defaultdict(list)
    for frag in fragments:
        if frag.normalized_fingerprint:
            by_norm[frag.normalized_fingerprint].append(frag)
    
    # Exclude those already caught as exact clones
    exact_fps = set()
    for frag in fragments:
        exact_fps.add(frag.fingerprint)
    
    groups = []
    for norm_fp, frags in by_norm.items():
        if len(frags) < 2:
            continue
        # Check that they're NOT all exact (already reported)
        fps_in_group = set(f.fingerprint for f in frags)
        if len(fps_in_group) == 1:
            continue  # All exact - skip (caught by Type 1)
        unique = _deduplicate_fragments(frags)
        if len(unique) < 2:
            continue
        group = CloneGroup(
            clone_type='renamed',
            fragments=unique,
            similarity=0.95,
            size=unique[0].size,
        )
        groups.append(group)
    return groups


def detect_gapped_clones(fragments, threshold=0.8):
    """Type 3: Find fragments with high structural similarity but not identical."""
    # Use fingerprint token-based similarity
    groups = []
    checked = set()
    
    for i, frag_a in enumerate(fragments):
        if frag_a.size < 8:  # Only check substantial fragments
            continue
        for j, frag_b in enumerate(fragments):
            if j <= i:
                continue
            if (i, j) in checked:
                continue
            checked.add((i, j))
            
            # Skip if same file and overlapping
            if frag_a.file == frag_b.file and frag_a.start_line == frag_b.start_line:
                continue
            
            # Skip if already exact or renamed match
            if frag_a.fingerprint == frag_b.fingerprint:
                continue
            if frag_a.normalized_fingerprint == frag_b.normalized_fingerprint:
                continue
            
            # Compute similarity
            sim = _fingerprint_similarity(frag_a.normalized_fingerprint,
                                         frag_b.normalized_fingerprint)
            if sim >= threshold:
                group = CloneGroup(
                    clone_type='gapped',
                    fragments=[frag_a, frag_b],
                    similarity=sim,
                    size=max(frag_a.size, frag_b.size),
                )
                groups.append(group)
    
    return groups


def _deduplicate_fragments(frags):
    """Remove fragments from same location."""
    seen = set()
    unique = []
    for f in frags:
        key = (f.file, f.start_line, f.size)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def _fingerprint_similarity(fp_a, fp_b):
    """Compute Jaccard similarity between fingerprint token sets."""
    tokens_a = set(fp_a.split())
    tokens_b = set(fp_b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) if union else 0.0


# ── Scoring & Analysis ───────────────────────────────────────────────────────

def compute_dry_score(report):
    """Compute DRY health score 0-100.
    
    100 = perfectly DRY (no clones)
    0 = extremely wet (massive duplication)
    """
    if report.total_fragments == 0:
        return 100.0
    
    # Weight by clone severity
    penalty = 0.0
    for group in report.clone_groups:
        # Larger clones and more instances = higher penalty
        instance_count = len(group.fragments)
        size_factor = min(group.size / 20.0, 3.0)  # Cap at 3x
        type_weight = {'exact': 1.5, 'renamed': 1.2, 'gapped': 0.8}.get(group.clone_type, 1.0)
        penalty += instance_count * size_factor * type_weight
    
    # Normalize: each penalty point reduces score
    raw_score = max(0.0, 100.0 - penalty * 3.0)
    return round(raw_score, 1)


def classify_severity(group):
    """Classify clone group severity based on size and count."""
    n = len(group.fragments)
    size = group.size
    
    if size >= 30 and n >= 3:
        return "critical"
    elif size >= 20 or (size >= 10 and n >= 3):
        return "high"
    elif size >= 10 or n >= 3:
        return "medium"
    return "low"


def suggest_refactoring(group):
    """Generate refactoring suggestions for a clone group."""
    n = len(group.fragments)
    size = group.size
    clone_type = group.clone_type
    
    # Check if fragments come from function bodies
    has_functions = any(
        type(f.node).__name__ == 'FunctionDef' for f in group.fragments
    )
    
    if clone_type == 'exact':
        if has_functions:
            return "Extract duplicate logic into a shared helper function"
        elif size >= 15:
            return "Extract repeated code block into a new function"
        else:
            return "Consider extracting into a reusable variable or expression"
    elif clone_type == 'renamed':
        if size >= 15:
            return "Parameterize the differing names and extract a generic function"
        else:
            return "Use a parameterized helper to handle both cases"
    else:  # gapped
        if size >= 20:
            return "Extract shared structure into a template function with callbacks"
        else:
            return "Consider a higher-order function to capture the common pattern"


def generate_insights(report):
    """Generate autonomous insights about the codebase's duplication."""
    insights = []
    
    if not report.clone_groups:
        insights.append("No significant code duplication detected - excellent DRY discipline!")
        return insights
    
    # Count by type
    type_counts = defaultdict(int)
    for g in report.clone_groups:
        type_counts[g.clone_type] += 1
    
    total = len(report.clone_groups)
    
    if type_counts['exact'] > total * 0.5:
        insights.append(
            f"Copy-paste hotspot: {type_counts['exact']} exact clone groups detected. "
            "These are low-hanging fruit for refactoring."
        )
    
    if type_counts['renamed'] > 3:
        insights.append(
            f"Pattern: {type_counts['renamed']} renamed clones suggest repeated patterns "
            "that could be parameterized into generic functions."
        )
    
    if type_counts['gapped'] > 5:
        insights.append(
            "High structural similarity across fragments suggests the codebase would "
            "benefit from higher-order functions or template patterns."
        )
    
    # Severity distribution
    severities = defaultdict(int)
    for g in report.clone_groups:
        severities[g.severity] += 1
    
    if severities['critical'] > 0:
        insights.append(
            f"URGENT: {severities['critical']} critical duplication clusters need "
            "immediate refactoring attention."
        )
    
    if severities['high'] > 2:
        insights.append(
            f"{severities['high']} high-severity clone groups are inflating maintenance cost."
        )
    
    # Cross-file clones
    cross_file = sum(1 for g in report.clone_groups
                     if len(set(f.file for f in g.fragments)) > 1)
    if cross_file > 0:
        insights.append(
            f"{cross_file} clone groups span multiple files - consider a shared module."
        )
    
    # DRY score commentary
    if report.dry_score >= 90:
        insights.append("DRY score is healthy. Minor cleanup opportunities exist.")
    elif report.dry_score >= 70:
        insights.append("DRY score is fair. Targeted refactoring would improve maintainability.")
    elif report.dry_score >= 50:
        insights.append("DRY score is concerning. Significant duplication is accumulating.")
    else:
        insights.append("DRY score is critical. The codebase urgently needs deduplication.")
    
    return insights


# ── Main Detection Pipeline ──────────────────────────────────────────────────

def detect_clones(paths, recursive=False, min_size=5, threshold=0.8,
                  type_filter=None):
    """Run the full clone detection pipeline."""
    # Collect files
    all_files = []
    for path in paths:
        all_files.extend(collect_files(path, recursive))
    
    if not all_files:
        return CloneReport()
    
    # Parse and extract fragments
    all_fragments = []
    total_lines = 0
    
    for filepath in all_files:
        try:
            ast = parse_file(filepath)
            frags = extract_fragments(ast, filepath, min_size)
            all_fragments.extend(frags)
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                total_lines += sum(1 for _ in f)
        except Exception:
            continue  # Skip unparseable files
    
    # Detect clones by type
    clone_groups = []
    
    if type_filter is None or type_filter == 'exact':
        clone_groups.extend(detect_exact_clones(all_fragments))
    
    if type_filter is None or type_filter == 'renamed':
        clone_groups.extend(detect_renamed_clones(all_fragments))
    
    if type_filter is None or type_filter == 'gapped':
        # Limit gapped detection to avoid O(n^2) blowup on large codebases
        substantial = [f for f in all_fragments if f.size >= 8][:200]
        clone_groups.extend(detect_gapped_clones(substantial, threshold))
    
    # Annotate groups
    for group in clone_groups:
        group.severity = classify_severity(group)
        group.refactoring = suggest_refactoring(group)
        group.confidence = _refactoring_confidence(group)
    
    # Sort by severity then size
    severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    clone_groups.sort(key=lambda g: (severity_order.get(g.severity, 9), -g.size))
    
    # Build report
    report = CloneReport(
        files_scanned=len(all_files),
        total_fragments=len(all_fragments),
        clone_groups=clone_groups,
        total_lines=total_lines,
    )
    report.dry_score = compute_dry_score(report)
    report.insights = generate_insights(report)
    
    return report


def _refactoring_confidence(group):
    """Estimate confidence that the suggested refactoring is safe."""
    size = group.size
    n = len(group.fragments)
    
    # Higher confidence for larger, more repeated clones
    size_conf = min(size / 30.0, 1.0)
    count_conf = min(n / 4.0, 1.0)
    type_conf = {'exact': 0.95, 'renamed': 0.85, 'gapped': 0.65}.get(group.clone_type, 0.5)
    
    return round(size_conf * 0.3 + count_conf * 0.3 + type_conf * 0.4, 2)


# ── Output Formatters ────────────────────────────────────────────────────────

def format_text(report):
    """Format report as human-readable text."""
    lines = []
    lines.append("=" * 70)
    lines.append("  SAURAVCLONE - Autonomous Code Clone Detector")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"  Files scanned:     {report.files_scanned}")
    lines.append(f"  Total lines:       {report.total_lines}")
    lines.append(f"  Fragments checked: {report.total_fragments}")
    lines.append(f"  Clone groups:      {len(report.clone_groups)}")
    lines.append(f"  DRY Score:         {report.dry_score}/100")
    lines.append("")
    
    if not report.clone_groups:
        lines.append("  No clones detected. Code is DRY!")
        lines.append("")
        return "\n".join(lines)
    
    # Summary by type
    type_counts = defaultdict(int)
    for g in report.clone_groups:
        type_counts[g.clone_type] += 1
    
    lines.append("  Clone Distribution:")
    for ct in ['exact', 'renamed', 'gapped']:
        if type_counts[ct]:
            label = {'exact': 'Type 1 (Exact)', 'renamed': 'Type 2 (Renamed)',
                     'gapped': 'Type 3 (Gapped)'}[ct]
            lines.append(f"    {label}: {type_counts[ct]} groups")
    lines.append("")
    
    # Detailed groups
    lines.append("-" * 70)
    lines.append("  CLONE GROUPS (sorted by severity)")
    lines.append("-" * 70)
    
    for i, group in enumerate(report.clone_groups[:20], 1):
        sev_icon = {'critical': '!!!', 'high': '!! ', 'medium': '!  ', 'low': '   '}
        icon = sev_icon.get(group.severity, '   ')
        lines.append("")
        lines.append(f"  [{icon}] Group {i} | {group.clone_type.upper()} | "
                     f"size={group.size} nodes | similarity={group.similarity:.0%} | "
                     f"severity={group.severity}")
        
        for frag in group.fragments:
            fname = os.path.basename(frag.file)
            lines.append(f"        -> {fname}:{frag.start_line} ({frag.size} nodes)")
        
        if group.refactoring:
            lines.append(f"        Suggestion: {group.refactoring} "
                         f"(confidence: {group.confidence:.0%})")
    
    if len(report.clone_groups) > 20:
        lines.append(f"\n  ... and {len(report.clone_groups) - 20} more clone groups")
    
    # Insights
    lines.append("")
    lines.append("-" * 70)
    lines.append("  AUTONOMOUS INSIGHTS")
    lines.append("-" * 70)
    for insight in report.insights:
        lines.append(f"  * {insight}")
    
    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)


def format_json(report):
    """Format report as JSON."""
    data = {
        "files_scanned": report.files_scanned,
        "total_lines": report.total_lines,
        "total_fragments": report.total_fragments,
        "dry_score": report.dry_score,
        "clone_groups": [
            {
                "clone_type": g.clone_type,
                "similarity": g.similarity,
                "size": g.size,
                "severity": g.severity,
                "confidence": g.confidence,
                "refactoring": g.refactoring,
                "fragments": [
                    {
                        "file": f.file,
                        "start_line": f.start_line,
                        "size": f.size,
                    }
                    for f in g.fragments
                ],
            }
            for g in report.clone_groups
        ],
        "insights": report.insights,
    }
    return _json.dumps(data, indent=2)


def generate_html(report, output_path):
    """Generate an interactive HTML dashboard."""
    # Severity colors
    sev_colors = {
        'critical': '#dc3545',
        'high': '#fd7e14',
        'medium': '#ffc107',
        'low': '#28a745',
    }
    
    # Build clone group rows
    rows_html = ""
    for i, group in enumerate(report.clone_groups, 1):
        color = sev_colors.get(group.severity, '#6c757d')
        locations = "<br>".join(
            f"{os.path.basename(f.file)}:{f.start_line} ({f.size} nodes)"
            for f in group.fragments
        )
        rows_html += f"""
        <tr>
            <td>{i}</td>
            <td><span style="color:{color};font-weight:bold">{group.severity.upper()}</span></td>
            <td>{group.clone_type}</td>
            <td>{group.size}</td>
            <td>{group.similarity:.0%}</td>
            <td style="font-size:0.85em">{locations}</td>
            <td style="font-size:0.85em">{group.refactoring or '-'}</td>
        </tr>"""
    
    # Insights list
    insights_html = "".join(f"<li>{ins}</li>" for ins in report.insights)
    
    # DRY score gauge color
    if report.dry_score >= 80:
        gauge_color = '#28a745'
    elif report.dry_score >= 60:
        gauge_color = '#ffc107'
    elif report.dry_score >= 40:
        gauge_color = '#fd7e14'
    else:
        gauge_color = '#dc3545'
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>sauravclone - Clone Detection Report</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #1a1a2e; color: #e0e0e0; padding: 2rem; }}
  h1 {{ color: #00d4ff; margin-bottom: 0.5rem; }}
  .subtitle {{ color: #888; margin-bottom: 2rem; }}
  .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
              gap: 1rem; margin-bottom: 2rem; }}
  .metric {{ background: #16213e; border-radius: 12px; padding: 1.5rem; text-align: center; }}
  .metric .value {{ font-size: 2.5rem; font-weight: bold; color: #00d4ff; }}
  .metric .label {{ font-size: 0.85rem; color: #888; margin-top: 0.3rem; }}
  .gauge {{ font-size: 3rem; font-weight: bold; color: {gauge_color}; }}
  .section {{ background: #16213e; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; }}
  .section h2 {{ color: #00d4ff; margin-bottom: 1rem; font-size: 1.2rem; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid #2a2a4a; }}
  th {{ color: #00d4ff; font-size: 0.85rem; text-transform: uppercase; }}
  tr:hover {{ background: #1a1a3e; }}
  ul {{ list-style: none; }}
  ul li {{ padding: 0.5rem 0; border-bottom: 1px solid #2a2a4a; }}
  ul li:before {{ content: "\\2022"; color: #00d4ff; margin-right: 0.5rem; }}
</style>
</head>
<body>
<h1>sauravclone</h1>
<p class="subtitle">Autonomous Code Clone Detection Report</p>

<div class="metrics">
  <div class="metric">
    <div class="value gauge">{report.dry_score}</div>
    <div class="label">DRY Score (0-100)</div>
  </div>
  <div class="metric">
    <div class="value">{len(report.clone_groups)}</div>
    <div class="label">Clone Groups</div>
  </div>
  <div class="metric">
    <div class="value">{report.files_scanned}</div>
    <div class="label">Files Scanned</div>
  </div>
  <div class="metric">
    <div class="value">{report.total_lines}</div>
    <div class="label">Total Lines</div>
  </div>
</div>

<div class="section">
  <h2>Clone Groups</h2>
  <table>
    <thead>
      <tr><th>#</th><th>Severity</th><th>Type</th><th>Size</th><th>Similarity</th><th>Locations</th><th>Refactoring</th></tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</div>

<div class="section">
  <h2>Autonomous Insights</h2>
  <ul>{insights_html}</ul>
</div>
</body>
</html>"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    return output_path


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='sauravclone - Autonomous Code Clone Detector for sauravcode')
    parser.add_argument('paths', nargs='+', help='.srv files or directories to scan')
    parser.add_argument('--recursive', '-r', action='store_true',
                        help='Recursively scan directories')
    parser.add_argument('--min-tokens', type=int, default=5,
                        help='Minimum AST node count for a fragment (default: 5)')
    parser.add_argument('--threshold', type=float, default=0.8,
                        help='Similarity threshold for gapped clones (default: 0.8)')
    parser.add_argument('--json', action='store_true', help='Output JSON report')
    parser.add_argument('--html', metavar='PATH', help='Generate HTML dashboard')
    parser.add_argument('--refactor', action='store_true',
                        help='Show detailed refactoring suggestions')
    parser.add_argument('--dry-score', action='store_true',
                        help='Show DRY score only')
    parser.add_argument('--type', choices=['exact', 'renamed', 'gapped'],
                        help='Filter by clone type')
    
    args = parser.parse_args()
    
    report = detect_clones(
        args.paths,
        recursive=args.recursive,
        min_size=args.min_tokens,
        threshold=args.threshold,
        type_filter=args.type,
    )
    
    if args.dry_score:
        print(f"{report.dry_score}")
        return
    
    if args.json:
        print(format_json(report))
    elif args.html:
        path = generate_html(report, args.html)
        print(f"HTML report written to: {path}")
    else:
        print(format_text(report))
    
    # Exit code: 1 if critical clones found
    if any(g.severity == 'critical' for g in report.clone_groups):
        sys.exit(1)


if __name__ == '__main__':
    main()

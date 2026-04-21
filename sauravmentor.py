"""sauravmentor — Autonomous Code Review Mentor for sauravcode.

Analyzes .srv source files for code quality, detects anti-patterns,
tracks improvement over time, and proactively suggests refactorings.

Usage:
    python sauravmentor.py <file.srv>              Review single file
    python sauravmentor.py <file.srv> --history    Show improvement trend
    python sauravmentor.py <dir>                   Review all .srv files
    python sauravmentor.py <file.srv> --report     HTML report with charts
    python sauravmentor.py <file.srv> --json       JSON output
    python sauravmentor.py --dashboard             Project health dashboard
    python sauravmentor.py <file.srv> --watch      Auto-review on change
"""

import sys
import os
import re
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime

HISTORY_FILE = ".sauravmentor_history.json"

# Pre-compiled regexes for .srv function detection
_FUNC_DEF_RE = re.compile(r'^function\s+\w+')
_FUNC_NAME_RE = re.compile(r'^function\s+(\w+)')

# ─── Smell Detectors ───────────────────────────────────────────────────────────

class Smell:
    def __init__(self, name, severity, line, message, suggestion=""):
        self.name = name
        self.severity = severity  # 1=info, 2=warning, 3=error
        self.line = line
        self.message = message
        self.suggestion = suggestion

    def to_dict(self):
        return {"name": self.name, "severity": self.severity, "line": self.line,
                "message": self.message, "suggestion": self.suggestion}


def _detect_long_functions(lines):
    """Functions longer than 30 lines."""
    smells = []
    func_start = None
    func_name = ""
    depth = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _FUNC_DEF_RE.match(stripped):
            if func_start is not None and (i - func_start) > 30:
                smells.append(Smell("long_function", 2, func_start + 1,
                    f"Function '{func_name}' is {i - func_start} lines long (>30)",
                    "Break into smaller helper functions"))
            func_start = i
            func_name = _FUNC_NAME_RE.match(stripped).group(1)
        elif stripped == "end" and func_start is not None:
            length = i - func_start
            if length > 30:
                smells.append(Smell("long_function", 2, func_start + 1,
                    f"Function '{func_name}' is {length} lines long (>30)",
                    "Break into smaller helper functions"))
            func_start = None
    return smells


def _detect_deep_nesting(lines):
    """Blocks nested deeper than 4 levels."""
    smells = []
    indent_stack = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        level = indent // 4 if indent > 0 else 0
        if level > 4:
            smells.append(Smell("deep_nesting", 2, i + 1,
                f"Nesting depth {level} (>4 levels)",
                "Extract inner logic into separate functions"))
    return smells


def _detect_magic_numbers(lines):
    """Numeric literals not in obvious assignments."""
    smells = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        # Skip simple assignments like x = 0, x = 1, loop ranges
        if re.match(r'^\w+\s*=\s*\d+$', stripped):
            continue
        if re.match(r'^(for|while|if|elif|return)\b', stripped):
            nums = re.findall(r'\b(\d{2,})\b', stripped)
            for n in nums:
                if int(n) not in (0, 1, 2, 10, 100):
                    smells.append(Smell("magic_number", 1, i + 1,
                        f"Magic number {n} — consider naming it",
                        "Extract to a named constant"))
                    break
    return smells


def _detect_unused_variables(lines):
    """Variables assigned but never referenced again."""
    smells = []
    assignments = {}
    source = "\n".join(lines)
    for i, line in enumerate(lines):
        m = re.match(r'^\s*(\w+)\s*=\s*.+', line)
        if m:
            name = m.group(1)
            if name.startswith("_") or name in ("self", "cls"):
                continue
            assignments[name] = i
    for name, line_num in assignments.items():
        # Count occurrences (must appear more than just the assignment)
        count = len(re.findall(r'\b' + re.escape(name) + r'\b', source))
        if count <= 1:
            smells.append(Smell("unused_variable", 2, line_num + 1,
                f"Variable '{name}' appears unused",
                "Remove or use the variable"))
    return smells


def _detect_duplicate_strings(lines):
    """String literals appearing more than 2 times."""
    smells = []
    strings = {}
    for i, line in enumerate(lines):
        for m in re.finditer(r'"([^"]{3,})"', line):
            s = m.group(1)
            strings.setdefault(s, []).append(i + 1)
    for s, locs in strings.items():
        if len(locs) > 2:
            smells.append(Smell("duplicate_string", 1, locs[0],
                f'String "{s[:30]}" repeated {len(locs)} times',
                "Extract to a named constant"))
    return smells


def _detect_empty_catch(lines):
    """Empty catch/except blocks."""
    smells = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("catch") or stripped.startswith("except"):
            # Check if next non-empty line is end/another block
            for j in range(i + 1, min(i + 3, len(lines))):
                next_s = lines[j].strip()
                if next_s and next_s in ("end", "pass", ""):
                    smells.append(Smell("empty_catch", 3, i + 1,
                        "Empty catch block swallows errors",
                        "Log the error or handle it explicitly"))
                    break
                elif next_s:
                    break
    return smells


def _detect_too_many_params(lines):
    """Functions with more than 5 parameters."""
    smells = []
    for i, line in enumerate(lines):
        m = re.match(r'^\s*func\s+(\w+)\s*\(([^)]*)\)', line)
        if m:
            params = [p.strip() for p in m.group(2).split(",") if p.strip()]
            if len(params) > 5:
                smells.append(Smell("too_many_params", 2, i + 1,
                    f"Function '{m.group(1)}' has {len(params)} parameters (>5)",
                    "Group related params into an object"))
    return smells


def _detect_missing_docstrings(lines):
    """Functions without a preceding comment."""
    smells = []
    for i, line in enumerate(lines):
        if re.match(r'^\s*func\s+\w+', line):
            has_doc = False
            if i > 0 and lines[i - 1].strip().startswith("#"):
                has_doc = True
            if not has_doc:
                name = re.match(r'^\s*func\s+(\w+)', line).group(1)
                smells.append(Smell("missing_docstring", 1, i + 1,
                    f"Function '{name}' has no documentation comment",
                    "Add a # comment above explaining purpose"))
    return smells


def _detect_long_lines(lines):
    """Lines exceeding 100 characters."""
    smells = []
    for i, line in enumerate(lines):
        if len(line.rstrip()) > 100:
            smells.append(Smell("long_line", 1, i + 1,
                f"Line is {len(line.rstrip())} chars (>100)",
                "Break into multiple lines"))
    return smells


def _detect_excessive_globals(lines):
    """More than 10 top-level variable assignments."""
    smells = []
    globals_count = 0
    for i, line in enumerate(lines):
        if re.match(r'^[a-zA-Z_]\w*\s*=\s*.+', line) and not line.startswith(" "):
            globals_count += 1
    if globals_count > 10:
        smells.append(Smell("excessive_globals", 2, 1,
            f"{globals_count} global variables (>10)",
            "Encapsulate related globals in a class or config object"))
    return smells


def _detect_complex_conditionals(lines):
    """If statements with more than 3 conditions."""
    smells = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r'^(if|elif)\b', stripped):
            conds = len(re.findall(r'\b(and|or|&&|\|\|)\b', stripped))
            if conds >= 3:
                smells.append(Smell("complex_conditional", 2, i + 1,
                    f"Conditional has {conds + 1} conditions",
                    "Extract into a named boolean function"))
    return smells


def _detect_dead_code(lines):
    """Code after return statements within same block."""
    smells = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("return ") or stripped == "return":
            indent = len(line) - len(line.lstrip())
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                next_stripped = next_line.strip()
                if next_stripped and not next_stripped.startswith("#"):
                    next_indent = len(next_line) - len(next_line.lstrip())
                    if next_indent >= indent and next_stripped not in ("end", "else", "elif", "catch"):
                        smells.append(Smell("dead_code", 3, i + 2,
                            "Unreachable code after return",
                            "Remove dead code"))
    return smells


ALL_DETECTORS = [
    _detect_long_functions, _detect_deep_nesting, _detect_magic_numbers,
    _detect_unused_variables, _detect_duplicate_strings, _detect_empty_catch,
    _detect_too_many_params, _detect_missing_docstrings, _detect_long_lines,
    _detect_excessive_globals, _detect_complex_conditionals, _detect_dead_code,
]

# ─── Skill Assessment ──────────────────────────────────────────────────────────

def assess_skills(lines):
    """Rate coding across 5 dimensions (1-5 stars)."""
    source = "\n".join(lines)
    total = len(lines) or 1

    # Organization: functions & classes
    funcs = len(re.findall(r'^\s*func\s+', source, re.M))
    classes = len(re.findall(r'^\s*class\s+', source, re.M))
    org = min(5, 1 + funcs // 3 + classes * 2)

    # Error handling
    tries = len(re.findall(r'^\s*try\b', source, re.M))
    err = min(5, 1 + tries * 2)

    # Data structure variety
    ds_keywords = ["list", "map", "set", "stack", "queue", "deque", "heap", "graph"]
    ds_count = sum(1 for k in ds_keywords if k in source.lower())
    ds = min(5, 1 + ds_count)

    # Algorithm complexity
    loops = len(re.findall(r'^\s*(for|while)\b', source, re.M))
    recursion = 1 if re.search(r'func\s+(\w+).*\b\1\(', source) else 0
    alg = min(5, 1 + loops // 5 + recursion * 2)

    # Documentation
    comments = len(re.findall(r'^\s*#', source, re.M))
    doc_ratio = comments / total
    doc = min(5, 1 + int(doc_ratio * 20))

    return {"organization": org, "error_handling": err, "data_structures": ds,
            "algorithms": alg, "documentation": doc}


# ─── History & Tracking ────────────────────────────────────────────────────────

def _load_history(base_dir="."):
    path = os.path.join(base_dir, HISTORY_FILE)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {"entries": []}


def _save_history(history, base_dir="."):
    path = os.path.join(base_dir, HISTORY_FILE)
    with open(path, "w") as f:
        json.dump(history, f, indent=2)


def _record_review(filepath, smells, skills, base_dir="."):
    history = _load_history(base_dir)
    entry = {
        "file": filepath,
        "timestamp": datetime.now().isoformat(),
        "smell_count": len(smells),
        "smell_breakdown": {},
        "skills": skills,
        "health_score": _calc_health(smells, skills),
    }
    for s in smells:
        entry["smell_breakdown"][s.name] = entry["smell_breakdown"].get(s.name, 0) + 1
    history["entries"].append(entry)
    # Keep last 500 entries
    history["entries"] = history["entries"][-500:]
    _save_history(history, base_dir)
    return history


def _calc_health(smells, skills):
    """Health score 0-100."""
    penalty = sum(s.severity * 3 for s in smells)
    skill_bonus = sum(skills.values()) * 2
    return max(0, min(100, 80 - penalty + skill_bonus))


def _get_trend(history, filepath):
    """Get improvement trend for a file."""
    entries = [e for e in history.get("entries", []) if e["file"] == filepath]
    if len(entries) < 2:
        return "insufficient_data"
    recent = entries[-3:]
    older = entries[-6:-3] if len(entries) >= 6 else entries[:len(entries)//2]
    if not older:
        return "insufficient_data"
    recent_avg = sum(e["smell_count"] for e in recent) / len(recent)
    older_avg = sum(e["smell_count"] for e in older) / len(older)
    if recent_avg < older_avg * 0.8:
        return "improving"
    elif recent_avg > older_avg * 1.2:
        return "declining"
    return "stable"


# ─── Recommendations ───────────────────────────────────────────────────────────

def generate_recommendations(smells, skills):
    """Proactive action items."""
    recs = []
    smell_names = [s.name for s in smells]

    if "long_function" in smell_names:
        recs.append({"priority": 1, "action": "Refactor long functions into smaller units",
                     "exercise": "Try `python sauravkata.py` decomposition katas"})
    if "magic_number" in smell_names:
        recs.append({"priority": 2, "action": "Extract magic numbers into named constants",
                     "exercise": "Try `python sauravgolf.py` for concise naming practice"})
    if "deep_nesting" in smell_names:
        recs.append({"priority": 1, "action": "Flatten nested code with early returns or guard clauses",
                     "exercise": "Try `python sauravkata.py` for refactoring exercises"})
    if "unused_variable" in smell_names:
        recs.append({"priority": 2, "action": "Remove unused variables or prefix with _",
                     "exercise": "Run `python sauravlint.py` for detailed analysis"})
    if "complex_conditional" in smell_names:
        recs.append({"priority": 2, "action": "Extract complex conditions into well-named booleans",
                     "exercise": "Practice readable conditionals in sauravkata"})
    if "dead_code" in smell_names:
        recs.append({"priority": 3, "action": "Remove unreachable code after return",
                     "exercise": "Use `python sauravguard.py` for runtime verification"})
    if skills.get("error_handling", 0) < 3:
        recs.append({"priority": 2, "action": "Add try/catch blocks for error-prone operations",
                     "exercise": "Study error handling patterns in sauravtutorial.py"})
    if skills.get("documentation", 0) < 3:
        recs.append({"priority": 3, "action": "Add comments before functions explaining their purpose",
                     "exercise": "Run `python sauravdoc.py` for documentation generation"})

    recs.sort(key=lambda r: r["priority"])
    return recs


# ─── Output Formats ────────────────────────────────────────────────────────────

def _print_review(filepath, smells, skills, health, trend, recs):
    """Terminal output."""
    print(f"\n{'=' * 60}")
    print(f"  SAURAVMENTOR - Code Review: {os.path.basename(filepath)}")
    print(f"{'=' * 60}")
    print(f"\n  Health Score: {health}/100  |  Trend: {trend}")
    print(f"\n  --- Skills ---")
    for dim, score in skills.items():
        stars = "*" * score + "." * (5 - score)
        print(f"    {dim:20s} [{stars}]")

    if smells:
        print(f"\n  --- Code Smells ({len(smells)}) ---")
        sev_map = {1: "INFO", 2: "WARN", 3: "ERR "}
        for s in smells[:20]:
            print(f"    {sev_map[s.severity]} L{s.line:>4d}: {s.message}")
        if len(smells) > 20:
            print(f"    ... and {len(smells) - 20} more")
    else:
        print(f"\n  No code smells detected! Clean code.")

    if recs:
        print(f"\n  --- Recommendations ---")
        for i, r in enumerate(recs[:5], 1):
            print(f"    {i}. [P{r['priority']}] {r['action']}")
            if r.get("exercise"):
                print(f"       -> {r['exercise']}")

    print(f"\n{'=' * 60}\n")


def _json_output(filepath, smells, skills, health, trend, recs):
    """JSON output."""
    result = {
        "file": filepath,
        "timestamp": datetime.now().isoformat(),
        "health_score": health,
        "trend": trend,
        "skills": skills,
        "smells": [s.to_dict() for s in smells],
        "recommendations": recs,
    }
    print(json.dumps(result, indent=2))


def _html_report(filepath, smells, skills, health, trend, recs):
    """Self-contained HTML report."""
    smell_data = json.dumps({s.name: sum(1 for x in smells if x.name == s.name) for s in smells})
    skill_labels = json.dumps(list(skills.keys()))
    skill_values = json.dumps(list(skills.values()))

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Mentor Report: {os.path.basename(filepath)}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 2rem; background: #1a1a2e; color: #eee; }}
  h1 {{ color: #e94560; }} h2 {{ color: #0f3460; background: #16213e; padding: 0.5rem 1rem; border-radius: 6px; color: #e94560; }}
  .score {{ font-size: 3rem; text-align: center; padding: 1rem; }}
  .score span {{ background: linear-gradient(135deg, #e94560, #0f3460); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
  .smell {{ padding: 0.5rem; margin: 0.3rem 0; border-left: 3px solid; border-radius: 3px; background: #16213e; }}
  .sev-1 {{ border-color: #53a8b6; }} .sev-2 {{ border-color: #f5a623; }} .sev-3 {{ border-color: #e94560; }}
  canvas {{ max-width: 100%; }}
  .rec {{ padding: 0.5rem 1rem; margin: 0.3rem 0; background: #16213e; border-radius: 4px; }}
  table {{ width: 100%; border-collapse: collapse; }} th, td {{ padding: 0.5rem; border-bottom: 1px solid #333; text-align: left; }}
</style></head><body>
<h1>🎓 Mentor Report</h1>
<p><strong>{filepath}</strong> — {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
<div class="score"><span>{health}/100</span> health | Trend: {trend}</div>

<h2>Skills Assessment</h2>
<canvas id="radar" width="400" height="400"></canvas>

<h2>Code Smells ({len(smells)})</h2>
{''.join(f'<div class="smell sev-{s.severity}"><strong>L{s.line}</strong> [{s.name}] {s.message}</div>' for s in smells[:30])}

<h2>Recommendations</h2>
{''.join(f'<div class="rec"><strong>P{r["priority"]}</strong> {r["action"]}</div>' for r in recs)}

<script>
(function() {{
  const canvas = document.getElementById('radar');
  const ctx = canvas.getContext('2d');
  const labels = {skill_labels};
  const values = {skill_values};
  const cx = 200, cy = 200, r = 150;
  const n = labels.length;
  ctx.strokeStyle = '#333'; ctx.fillStyle = '#16213e';
  for (let ring = 1; ring <= 5; ring++) {{
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {{
      const angle = (Math.PI * 2 * i / n) - Math.PI / 2;
      const x = cx + Math.cos(angle) * (r * ring / 5);
      const y = cy + Math.sin(angle) * (r * ring / 5);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }}
    ctx.stroke();
  }}
  // Data
  ctx.beginPath(); ctx.fillStyle = 'rgba(233,69,96,0.3)'; ctx.strokeStyle = '#e94560'; ctx.lineWidth = 2;
  values.forEach((v, i) => {{
    const angle = (Math.PI * 2 * i / n) - Math.PI / 2;
    const x = cx + Math.cos(angle) * (r * v / 5);
    const y = cy + Math.sin(angle) * (r * v / 5);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }});
  ctx.closePath(); ctx.fill(); ctx.stroke();
  // Labels
  ctx.fillStyle = '#eee'; ctx.font = '12px sans-serif'; ctx.textAlign = 'center';
  labels.forEach((lbl, i) => {{
    const angle = (Math.PI * 2 * i / n) - Math.PI / 2;
    const x = cx + Math.cos(angle) * (r + 25);
    const y = cy + Math.sin(angle) * (r + 25);
    ctx.fillText(lbl, x, y);
  }});
}})();
</script></body></html>"""
    out_path = filepath.replace(".srv", "_mentor_report.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  📄 Report saved: {out_path}")


# ─── Review Engine ─────────────────────────────────────────────────────────────

def review_file(filepath, base_dir="."):
    """Run all detectors on a file."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()

    smells = []
    for detector in ALL_DETECTORS:
        smells.extend(detector(lines))

    smells.sort(key=lambda s: (s.severity * -1, s.line))
    skills = assess_skills(lines)
    health = _calc_health(smells, skills)
    history = _record_review(filepath, smells, skills, base_dir)
    trend = _get_trend(history, filepath)
    recs = generate_recommendations(smells, skills)

    return smells, skills, health, trend, recs


# ─── Dashboard ─────────────────────────────────────────────────────────────────

def dashboard(directory="."):
    """Project-wide health dashboard."""
    srv_files = list(Path(directory).rglob("*.srv"))
    if not srv_files:
        print("  No .srv files found.")
        return

    print(f"\n{'=' * 60}")
    print(f"  SAURAVMENTOR - Project Dashboard")
    print(f"  {os.path.abspath(directory)} ({len(srv_files)} files)")
    print(f"{'=' * 60}\n")

    total_smells = 0
    total_health = 0
    file_results = []

    for fp in sorted(srv_files)[:50]:
        try:
            smells, skills, health, trend, _ = review_file(str(fp), directory)
            total_smells += len(smells)
            total_health += health
            file_results.append((str(fp.name), len(smells), health, trend))
        except Exception:
            pass

    if file_results:
        avg_health = total_health // len(file_results)
        print(f"  Overall Health: {avg_health}/100  |  Total Smells: {total_smells}")
        print(f"\n  {'File':<30s} {'Smells':>7s} {'Health':>7s} {'Trend':<12s}")
        print(f"  {'-' * 58}")
        for name, sc, h, t in sorted(file_results, key=lambda x: x[2]):
            print(f"  {name:<30s} {sc:>7d} {h:>7d} {t:<12s}")
    print()


# ─── Watch Mode ────────────────────────────────────────────────────────────────

def watch_file(filepath):
    """Auto-review on file change."""
    print(f"  Watching {filepath} (Ctrl+C to stop)...")
    last_hash = ""
    while True:
        try:
            with open(filepath, "rb") as f:
                h = hashlib.md5(f.read()).hexdigest()
            if h != last_hash:
                last_hash = h
                smells, skills, health, trend, recs = review_file(filepath)
                _print_review(filepath, smells, skills, health, trend, recs)
            time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Stopped watching.")
            break
        except Exception as e:
            print(f"  Error: {e}")
            time.sleep(2)


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    flags = [a for a in args if a.startswith("--")]
    positional = [a for a in args if not a.startswith("--")]

    if "--dashboard" in flags:
        directory = positional[0] if positional else "."
        dashboard(directory)
        return

    if not positional:
        print("Error: provide a file or directory path")
        sys.exit(1)

    target = positional[0]

    if os.path.isdir(target):
        dashboard(target)
        return

    if not os.path.exists(target):
        print(f"Error: {target} not found")
        sys.exit(1)

    if "--watch" in flags:
        watch_file(target)
        return

    base_dir = os.path.dirname(os.path.abspath(target)) or "."
    smells, skills, health, trend, recs = review_file(target, base_dir)

    if "--json" in flags:
        _json_output(target, smells, skills, health, trend, recs)
    elif "--report" in flags:
        _html_report(target, smells, skills, health, trend, recs)
        _print_review(target, smells, skills, health, trend, recs)
    elif "--history" in flags:
        history = _load_history(base_dir)
        entries = [e for e in history.get("entries", []) if e["file"] == target]
        print(f"\n  📈 History for {os.path.basename(target)} ({len(entries)} reviews)")
        print(f"  Trend: {trend}\n")
        for e in entries[-10:]:
            print(f"    {e['timestamp'][:16]}  smells={e['smell_count']:>3d}  health={e['health_score']:>3d}")
        print()
    else:
        _print_review(target, smells, skills, health, trend, recs)


if __name__ == "__main__":
    main()

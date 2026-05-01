---
hide:
  - footer
---

# Autonomous Engineering Tools

> Three tools for autonomous code quality: clone detection, dead-code archaeology, and self-healing patching. Zero configuration required — point at your `.srv` files and let the engines do the work.

!!! info "New in the Toolchain"
    These tools extend the [autonomous analysis suite](autonomous-analysis.md) with
    production-grade clone elimination, fossil excavation, and self-healing capabilities.

---

## Quick Reference

| Tool | Command | Purpose |
|------|---------|---------|
| **sauravclone** | `python sauravclone.py file.srv` | Code clone detection with DRY scoring |
| **sauravfossil** | `python sauravfossil.py file.srv` | Dead-code archaeology & excavation planning |
| **sauravautopatch** | `python sauravautopatch.py file.srv` | Autonomous bug detection & self-healing |

---

## Code Clone Detector (`sauravclone`)

Detects duplicated code fragments across `.srv` files using AST-based structural comparison. Classifies clones by type, calculates a DRY health score, and suggests refactoring opportunities.

### Clone Types

| Type | Name | Description |
|------|------|-------------|
| **Type 1** | Exact | Identical fragments (ignoring whitespace and comments) |
| **Type 2** | Renamed | Structurally identical with renamed variables/functions |
| **Type 3** | Gapped | Similar structure with small insertions, deletions, or modifications |

### Usage

```bash
python sauravclone.py program.srv                 # Detect clones in a file
python sauravclone.py src/ --recursive            # Scan entire directory
python sauravclone.py program.srv --min-tokens 20 # Minimum clone size (tokens)
python sauravclone.py program.srv --threshold 0.8 # Similarity threshold (0-1)
python sauravclone.py program.srv --json          # JSON output
python sauravclone.py program.srv --html report   # Interactive HTML dashboard
python sauravclone.py program.srv --refactor      # Show refactoring suggestions
python sauravclone.py program.srv --dry-score     # Show DRY score only
python sauravclone.py program.srv --type exact    # Only exact clones
python sauravclone.py program.srv --type renamed  # Only renamed-variable clones
python sauravclone.py program.srv --type gapped   # Only near-miss clones
```

### Agentic Features

- **Autonomous redundancy detection** — no configuration needed
- **Refactoring suggestions** with confidence scores and priority ranking
- **DRY health score** (0–100) for tracking code hygiene over time
- **Trend detection** when run repeatedly on the same codebase

### Example Output

```
🔍 sauravclone — Code Clone Detector

Scanning: calculator.srv (342 tokens)

Clone Group #1 [Type 2 — Renamed] (similarity: 0.94)
  ├─ lines 12-18: fn calculate_sum(items)
  └─ lines 45-51: fn calculate_avg(values)
  💡 Refactor: Extract shared iteration logic into a helper function

DRY Score: 72/100 (Good — minor duplication detected)
```

---

## Code Fossil Analyzer (`sauravfossil`)

Examines `.srv` programs like geological strata: identifies dead code, orphaned functions, vestigial logic, and evolutionary layers. Produces excavation plans for safe removal.

### Analysis Engines (8)

| ID | Engine | Description |
|----|--------|-------------|
| F001 | Dead Function Detector | Functions never called anywhere |
| F002 | Orphaned Variable Finder | Variables assigned but never read |
| F003 | Vestigial Branch Detector | Conditions that are always true/false |
| F004 | Unreachable Code Scanner | Code after return/break/continue |
| F005 | Redundant Import Finder | Imports whose exports aren't used |
| F006 | Code Layer Dating | Groups code into evolutionary epochs |
| F007 | Fossil Dependency Mapper | Dead code that references other dead code |
| F008 | Excavation Planner | Safe removal plan with risk assessment |

### Usage

```bash
python sauravfossil.py target.srv                     # Full fossil analysis
python sauravfossil.py . --recursive                  # Deep scan all .srv files
python sauravfossil.py target.srv --html report.html  # Interactive HTML dashboard
python sauravfossil.py target.srv --json              # JSON output
python sauravfossil.py . --excavate                   # Show safe removal plan
python sauravfossil.py . --layers                     # Show evolutionary layers
python sauravfossil.py . --summary                    # Summary only
```

### Example Output

```
🦴 sauravfossil — Code Fossil Record Analyzer

Scanning: legacy_app.srv (847 lines)

Layer 1 — Primordial (lines 1-120)
  High complexity, dense variable usage. Likely the original codebase.

Layer 2 — Cambrian Explosion (lines 121-450)
  Rapid feature additions with inconsistent naming.

Fossils Found: 12
  F001  fn old_handler()          lines 67-89    ☠ Dead — never called
  F002  var temp_flag              line 203       ☠ Orphaned — written, never read
  F004  lines 512-518             after return    ☠ Unreachable code

Excavation Plan: 3 safe removals (−42 lines, risk: LOW)
```

---

## Self-Healing Engine (`sauravautopatch`)

Scans `.srv` programs for bugs, anti-patterns, and code smells, then autonomously generates, validates, and applies patches. Operates at four autonomy levels.

### Detection Engines (10)

| ID | Engine | Description |
|----|--------|-------------|
| P001 | Uninitialized Variable Use | Variables read before assignment |
| P002 | Dead Code Eliminator | Unreachable code after return/break |
| P003 | Infinite Loop Guard | Loops without exit conditions |
| P004 | Unused Parameter Cleanup | Function params never referenced |
| P005 | Missing Return Path | Functions with inconsistent returns |
| P006 | Duplicate Branch Detector | Identical if/else bodies |
| P007 | Off-by-One Guard | Common loop boundary mistakes |
| P008 | Resource Leak Patcher | Open-without-close patterns |
| P009 | Type Coercion Fixer | Implicit coercion in comparisons |
| P010 | Idempotency Enforcer | Non-idempotent operations in retry loops |

### Autonomy Levels

| Level | Flag | Behavior |
|-------|------|----------|
| 0 | `--scan` | Detect issues, report only |
| 1 | `--suggest` | Generate patch diffs, don't apply |
| 2 | `--heal` | Apply safe patches (confidence ≥ 0.8) |
| 3 | `--heal-all` | Apply all patches regardless of confidence |

### Usage

```bash
python sauravautopatch.py program.srv                # Scan (level 0)
python sauravautopatch.py program.srv --suggest      # Generate patch suggestions
python sauravautopatch.py program.srv --heal         # Auto-fix safe issues
python sauravautopatch.py program.srv --heal-all     # Fix everything
python sauravautopatch.py program.srv --json         # JSON output
python sauravautopatch.py program.srv --html report  # HTML dashboard
python sauravautopatch.py src/ --recursive --heal    # Heal entire project
```

### Example Output

```
🩹 sauravautopatch — Self-Healing Engine

Scanning: server.srv (523 lines)

Issues Found: 4
  P001  Uninitialized 'count' at line 45    confidence: 0.95  🩹 PATCHED
  P003  Infinite loop at line 112           confidence: 0.87  🩹 PATCHED
  P005  Missing return in fn validate()     confidence: 0.72  📋 Suggested
  P008  Unclosed resource at line 301       confidence: 0.91  🩹 PATCHED

Healed: 3/4 issues (1 below confidence threshold)
Backup saved: server.srv.bak
```

---

## Combining the Tools

These three tools form a powerful autonomous pipeline for code maintenance:

```bash
# 1. Find and remove dead code
python sauravfossil.py src/ --recursive --excavate

# 2. Eliminate duplication
python sauravclone.py src/ --recursive --refactor

# 3. Auto-fix remaining issues
python sauravautopatch.py src/ --recursive --heal
```

!!! tip "CI Integration"
    Add all three to your CI pipeline for continuous code hygiene:
    
    - `sauravclone --dry-score` — fail if DRY score drops below threshold
    - `sauravfossil --summary --json` — track fossil count over time
    - `sauravautopatch --scan` — zero-tolerance for detectable bugs

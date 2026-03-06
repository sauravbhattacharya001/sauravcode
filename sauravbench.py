#!/usr/bin/env python3
"""sauravbench -- Benchmarking tool for sauravcode (.srv) programs.

Runs programs multiple times and reports statistical timing analysis.
Supports warmup rounds, comparison mode, baseline saving/checking,
and multiple output formats.

Usage:
    python sauravbench.py fib.srv                       # Basic benchmark (10 runs)
    python sauravbench.py fib.srv -n 50                 # 50 iterations
    python sauravbench.py fib.srv --warmup 3            # 3 warmup rounds
    python sauravbench.py fib.srv --json                # JSON output
    python sauravbench.py fib.srv --save                # Save baseline
    python sauravbench.py fib.srv --check               # Compare against baseline
    python sauravbench.py fib.srv sort.srv --compare    # Compare two programs
    python sauravbench.py fib.srv -n 30 --percentiles   # Show p50/p90/p95/p99
"""

import sys
import os
import time
import json
import math
import argparse
import io
from contextlib import redirect_stdout, redirect_stderr

# Import the sauravcode interpreter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from saurav import tokenize, Parser, Interpreter, FunctionCallNode


# -- Constants ----------------------------------------------------

BASELINE_DIR = ".sauravbench"
BASELINE_FILE = "baselines.json"
DEFAULT_ITERATIONS = 10
DEFAULT_WARMUP = 2
REGRESSION_THRESHOLD = 0.10  # 10% slower = regression


# -- Core benchmark runner ----------------------------------------

def run_once(code, filename):
    """Execute a sauravcode program once, returning elapsed seconds.

    Captures stdout/stderr to avoid cluttering benchmark output.
    Returns (elapsed_seconds, success, error_message).
    """
    tokens = list(tokenize(code))
    parser = Parser(tokens)
    ast_nodes = parser.parse()

    interpreter = Interpreter()
    abs_filename = os.path.abspath(filename)
    interpreter._source_dir = os.path.dirname(abs_filename)
    interpreter._imported_modules.add(abs_filename)

    buf_out = io.StringIO()
    buf_err = io.StringIO()

    start = time.perf_counter()
    try:
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            for node in ast_nodes:
                if isinstance(node, FunctionCallNode):
                    interpreter.execute_function(node)
                else:
                    interpreter.interpret(node)
        elapsed = time.perf_counter() - start
        return elapsed, True, None
    except Exception as e:
        elapsed = time.perf_counter() - start
        return elapsed, False, str(e)


def benchmark(code, filename, iterations, warmup):
    """Run a benchmark suite: warmup + measured iterations.

    Returns dict with timing statistics.
    """
    # Warmup phase
    for _ in range(warmup):
        _, ok, err = run_once(code, filename)
        if not ok:
            return {"error": f"Warmup failed: {err}"}

    # Measured runs
    times = []
    errors = 0
    for _ in range(iterations):
        elapsed, ok, err = run_once(code, filename)
        if ok:
            times.append(elapsed)
        else:
            errors += 1

    if not times:
        return {"error": "All iterations failed"}

    return compute_stats(times, errors, iterations, warmup, filename)


def compute_stats(times, errors, iterations, warmup, filename):
    """Compute statistical summary from timing samples."""
    times_sorted = sorted(times)
    n = len(times_sorted)

    mean = sum(times_sorted) / n
    variance = sum((t - mean) ** 2 for t in times_sorted) / n if n > 1 else 0
    stddev = math.sqrt(variance)

    # Coefficient of variation (relative stddev)
    cv = (stddev / mean * 100) if mean > 0 else 0

    return {
        "file": os.path.basename(filename),
        "iterations": iterations,
        "warmup": warmup,
        "successful": n,
        "errors": errors,
        "min_ms": times_sorted[0] * 1000,
        "max_ms": times_sorted[-1] * 1000,
        "mean_ms": mean * 1000,
        "median_ms": percentile(times_sorted, 50) * 1000,
        "stddev_ms": stddev * 1000,
        "cv_percent": round(cv, 2),
        "p50_ms": percentile(times_sorted, 50) * 1000,
        "p90_ms": percentile(times_sorted, 90) * 1000,
        "p95_ms": percentile(times_sorted, 95) * 1000,
        "p99_ms": percentile(times_sorted, 99) * 1000,
        "total_ms": sum(times_sorted) * 1000,
        "raw_times_ms": [t * 1000 for t in times_sorted],
    }


def percentile(sorted_data, p):
    """Calculate the p-th percentile of sorted data."""
    if not sorted_data:
        return 0
    k = (len(sorted_data) - 1) * (p / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[int(f)] * (c - k) + sorted_data[int(c)] * (k - f)


# -- Output formatters -------------------------------------------

def format_time(ms):
    """Format milliseconds for display."""
    if ms < 1:
        return f"{ms * 1000:.1f}us"
    if ms < 1000:
        return f"{ms:.2f}ms"
    return f"{ms / 1000:.3f}s"


def print_table(stats, show_percentiles=False):
    """Print a human-readable benchmark results table."""
    if "error" in stats:
        print(f"\n  [FAIL] {stats.get('file', '?')}: {stats['error']}")
        return

    w = 50
    print(f"\n  +{'=' * w}+")
    print(f"  | Benchmark: {stats['file']:<{w - 13}s}|")
    print(f"  +{'-' * w}+")
    print(f"  | Iterations : {stats['successful']:>6d} / {stats['iterations']:<6d}{' ' * 20}|")
    print(f"  | Warmup     : {stats['warmup']:>6d}{' ' * 28}|")
    print(f"  +{'-' * w}+")
    print(f"  | Min        : {format_time(stats['min_ms']):>12s}{' ' * 24}|")
    print(f"  | Max        : {format_time(stats['max_ms']):>12s}{' ' * 24}|")
    print(f"  | Mean       : {format_time(stats['mean_ms']):>12s}{' ' * 24}|")
    print(f"  | Median     : {format_time(stats['median_ms']):>12s}{' ' * 24}|")
    print(f"  | Std Dev    : {format_time(stats['stddev_ms']):>12s}{' ' * 24}|")
    print(f"  | CV         : {stats['cv_percent']:>10.1f}%{' ' * 25}|")

    if show_percentiles:
        print(f"  +{'-' * w}+")
        print(f"  | p50        : {format_time(stats['p50_ms']):>12s}{' ' * 24}|")
        print(f"  | p90        : {format_time(stats['p90_ms']):>12s}{' ' * 24}|")
        print(f"  | p95        : {format_time(stats['p95_ms']):>12s}{' ' * 24}|")
        print(f"  | p99        : {format_time(stats['p99_ms']):>12s}{' ' * 24}|")

    print(f"  | Total      : {format_time(stats['total_ms']):>12s}{' ' * 24}|")
    print(f"  +{'=' * w}+")

    if stats['cv_percent'] > 20:
        print(f"  WARNING: High variance (CV={stats['cv_percent']:.1f}%) -- results may be noisy.")
        print(f"    Try more iterations (-n) or check for I/O in your program.")


def print_comparison(stats_a, stats_b):
    """Print side-by-side comparison of two benchmark results."""
    if "error" in stats_a or "error" in stats_b:
        print("\n  Cannot compare -- one or both benchmarks failed.")
        if "error" in stats_a:
            print(f"    A ({stats_a.get('file', '?')}): {stats_a['error']}")
        if "error" in stats_b:
            print(f"    B ({stats_b.get('file', '?')}): {stats_b['error']}")
        return

    a_name = stats_a['file']
    b_name = stats_b['file']

    diff_pct = ((stats_b['mean_ms'] - stats_a['mean_ms']) / stats_a['mean_ms']) * 100 if stats_a['mean_ms'] > 0 else 0

    w = 64
    print(f"\n  +{'=' * w}+")
    print(f"  | {'Comparison':<{w - 1}s}|")
    print(f"  +{'-' * w}+")
    print(f"  | {'Metric':<12s} | {'A: ' + a_name:<20s} | {'B: ' + b_name:<20s}   |")
    print(f"  +{'-' * w}+")

    rows = [
        ("Min",    stats_a['min_ms'],    stats_b['min_ms']),
        ("Max",    stats_a['max_ms'],    stats_b['max_ms']),
        ("Mean",   stats_a['mean_ms'],   stats_b['mean_ms']),
        ("Median", stats_a['median_ms'], stats_b['median_ms']),
        ("Std Dev", stats_a['stddev_ms'], stats_b['stddev_ms']),
    ]

    for label, va, vb in rows:
        print(f"  | {label:<12s} | {format_time(va):>20s} | {format_time(vb):>20s}   |")

    print(f"  +{'-' * w}+")

    if diff_pct > 0:
        ratio = stats_b['mean_ms'] / stats_a['mean_ms'] if stats_a['mean_ms'] > 0 else float('inf')
        verdict = f"A is {ratio:.2f}x faster (B is {diff_pct:+.1f}% slower)"
    elif diff_pct < 0:
        ratio = stats_a['mean_ms'] / stats_b['mean_ms'] if stats_b['mean_ms'] > 0 else float('inf')
        verdict = f"B is {ratio:.2f}x faster (A is {-diff_pct:.1f}% slower)"
    else:
        verdict = "Identical performance"

    print(f"  | Result: {verdict:<{w - 10}s}|")
    print(f"  +{'=' * w}+")


# -- Baseline management -----------------------------------------

def baselines_path():
    """Return path to baselines JSON file."""
    return os.path.join(BASELINE_DIR, BASELINE_FILE)


def load_baselines():
    """Load saved baselines from disk."""
    path = baselines_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_baseline(stats):
    """Save benchmark stats as baseline for the file."""
    os.makedirs(BASELINE_DIR, exist_ok=True)
    baselines = load_baselines()
    baselines[stats['file']] = {
        "mean_ms": stats['mean_ms'],
        "median_ms": stats['median_ms'],
        "min_ms": stats['min_ms'],
        "stddev_ms": stats['stddev_ms'],
        "iterations": stats['iterations'],
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(baselines_path(), 'w', encoding='utf-8') as f:
        json.dump(baselines, f, indent=2)
    print(f"  [OK] Baseline saved for {stats['file']}")


def check_baseline(stats, threshold=REGRESSION_THRESHOLD):
    """Compare current stats against saved baseline.

    Returns (passed, message).
    """
    baselines = load_baselines()
    key = stats['file']
    if key not in baselines:
        return None, f"No baseline found for {key}. Run with --save first."

    baseline = baselines[key]
    old_mean = baseline['mean_ms']
    new_mean = stats['mean_ms']
    change = (new_mean - old_mean) / old_mean if old_mean > 0 else 0

    saved_at = baseline.get('saved_at', 'unknown')

    if change > threshold:
        return False, (
            f"REGRESSION in {key}: "
            f"{format_time(old_mean)} -> {format_time(new_mean)} "
            f"({change * 100:+.1f}%, threshold {threshold * 100:.0f}%) "
            f"[baseline from {saved_at}]"
        )
    elif change < -threshold:
        return True, (
            f"IMPROVEMENT in {key}: "
            f"{format_time(old_mean)} -> {format_time(new_mean)} "
            f"({change * 100:+.1f}%) "
            f"[baseline from {saved_at}]"
        )
    else:
        return True, (
            f"OK {key}: "
            f"{format_time(old_mean)} -> {format_time(new_mean)} "
            f"({change * 100:+.1f}%, within +/-{threshold * 100:.0f}%) "
            f"[baseline from {saved_at}]"
        )


# -- Histogram ----------------------------------------------------

def print_histogram(stats, width=40):
    """Print a simple ASCII histogram of run times."""
    if "error" in stats:
        return

    times = stats['raw_times_ms']
    if len(times) < 3:
        return

    # Create 10 buckets
    lo, hi = min(times), max(times)
    if hi == lo:
        print(f"\n  All runs: {format_time(lo)}")
        return

    n_buckets = min(10, len(times))
    bucket_width = (hi - lo) / n_buckets
    buckets = [0] * n_buckets

    for t in times:
        idx = min(int((t - lo) / bucket_width), n_buckets - 1)
        buckets[idx] += 1

    max_count = max(buckets)

    print(f"\n  Distribution:")
    for i, count in enumerate(buckets):
        edge = lo + i * bucket_width
        bar_len = int(count / max_count * width) if max_count > 0 else 0
        bar = "#" * bar_len
        print(f"    {format_time(edge):>10s} | {bar} ({count})")


# -- Main ---------------------------------------------------------

def load_file(filename):
    """Read and validate a .srv file."""
    if not filename.endswith('.srv'):
        print(f"Error: {filename} must have a .srv extension.")
        sys.exit(1)
    if not os.path.isfile(filename):
        print(f"Error: File '{filename}' not found.")
        sys.exit(1)
    with open(filename, 'r', encoding='utf-8') as f:
        return f.read()


def main():
    parser = argparse.ArgumentParser(
        prog="sauravbench",
        description="Benchmark runner for sauravcode (.srv) programs.",
        epilog="Examples:\n"
               "  python sauravbench.py fib.srv -n 50\n"
               "  python sauravbench.py fib.srv sort.srv --compare\n"
               "  python sauravbench.py fib.srv --save --check\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("files", nargs="+", metavar="FILE",
                        help=".srv file(s) to benchmark")
    parser.add_argument("-n", "--iterations", type=int, default=DEFAULT_ITERATIONS,
                        help=f"Number of measured iterations (default: {DEFAULT_ITERATIONS})")
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP,
                        help=f"Warmup iterations before measurement (default: {DEFAULT_WARMUP})")
    parser.add_argument("--compare", action="store_true",
                        help="Compare two files side-by-side (requires exactly 2 files)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--save", action="store_true",
                        help="Save results as baseline")
    parser.add_argument("--check", action="store_true",
                        help="Compare against saved baseline")
    parser.add_argument("--threshold", type=float, default=REGRESSION_THRESHOLD,
                        help=f"Regression threshold as decimal (default: {REGRESSION_THRESHOLD})")
    parser.add_argument("--percentiles", action="store_true",
                        help="Show p50/p90/p95/p99 percentiles")
    parser.add_argument("--histogram", action="store_true",
                        help="Show distribution histogram")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress progress output")

    args = parser.parse_args()

    if args.compare and len(args.files) != 2:
        print("Error: --compare requires exactly 2 files.")
        sys.exit(1)

    # Run benchmarks
    results = []
    for filename in args.files:
        code = load_file(filename)
        if not args.quiet:
            print(f"  Benchmarking {filename}... ", end="", flush=True)
        stats = benchmark(code, filename, args.iterations, args.warmup)
        if not args.quiet:
            if "error" in stats:
                print(f"FAILED: {stats['error']}")
            else:
                print(f"done ({format_time(stats['mean_ms'])} mean)")
        results.append(stats)

    # JSON output
    if args.json:
        # Strip raw_times for cleaner JSON unless only 1 file
        output = []
        for r in results:
            clean = {k: v for k, v in r.items() if k != 'raw_times_ms'}
            output.append(clean)
        print(json.dumps(output if len(output) > 1 else output[0], indent=2))
        return

    # Table output
    if args.compare:
        print_comparison(results[0], results[1])
    else:
        for stats in results:
            print_table(stats, show_percentiles=args.percentiles)
            if args.histogram:
                print_histogram(stats)

    # Baseline operations
    exit_code = 0
    for stats in results:
        if "error" in stats:
            continue
        if args.save:
            save_baseline(stats)
        if args.check:
            passed, msg = check_baseline(stats, args.threshold)
            if passed is None:
                print(f"  [!] {msg}")
            elif passed:
                print(f"  [OK] {msg}")
            else:
                print(f"  [FAIL] {msg}")
                exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

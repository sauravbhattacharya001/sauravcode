#!/usr/bin/env python3
"""
sauravbench - Benchmark runner for sauravcode programs.

Runs .srv programs multiple times, measures execution time and memory,
and produces comparative benchmark reports.

Usage:
    python sauravbench.py program.srv                    # Benchmark a single file
    python sauravbench.py prog1.srv prog2.srv            # Compare multiple files
    python sauravbench.py program.srv -n 50              # 50 iterations (default: 10)
    python sauravbench.py program.srv --warmup 3         # 3 warmup runs (default: 2)
    python sauravbench.py program.srv --json              # JSON output
    python sauravbench.py program.srv --csv               # CSV output
    python sauravbench.py program.srv --baseline b.json   # Compare against baseline
    python sauravbench.py program.srv --save result.json  # Save results as baseline
    python sauravbench.py program.srv --quiet             # Suppress program output
"""

import json
import math
import os
import sys
import time
import tracemalloc
import importlib.util

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_saurav_cache = None

def _resolve_saurav():
    """Import the saurav interpreter module from the project root."""
    global _saurav_cache
    if _saurav_cache is not None:
        return _saurav_cache
    root = os.path.dirname(os.path.abspath(__file__))
    saurav_path = os.path.join(root, "saurav.py")
    if not os.path.isfile(saurav_path):
        raise FileNotFoundError(f"Cannot find saurav.py at {saurav_path}")
    spec = importlib.util.spec_from_file_location("saurav_interp", saurav_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _saurav_cache = mod
    return mod


def _suppress_stdout(func, *args, **kwargs):
    """Run *func* while suppressing stdout."""
    import io
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        return func(*args, **kwargs)
    finally:
        sys.stdout = old


def _run_program(saurav_mod, code, quiet=True):
    """Parse + interpret *code* once.  Returns (duration_s, peak_mem_bytes, error)."""
    tracemalloc.start()
    start = time.perf_counter()
    error = None
    try:
        tokens = list(saurav_mod.tokenize(code))
        parser = saurav_mod.Parser(tokens)
        ast_nodes = parser.parse()
        interp = saurav_mod.Interpreter()
        if quiet:
            _suppress_stdout(lambda: [interp.interpret(node) for node in ast_nodes])
        else:
            for node in ast_nodes:
                interp.interpret(node)
    except Exception as e:
        error = str(e)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, peak, error


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

class BenchStats:
    """Compute descriptive statistics from a list of measurements."""

    def __init__(self, values):
        self.values = sorted(values)
        self.n = len(values)

    @property
    def mean(self):
        return sum(self.values) / self.n if self.n else 0.0

    @property
    def median(self):
        if not self.n:
            return 0.0
        mid = self.n // 2
        if self.n % 2 == 0:
            return (self.values[mid - 1] + self.values[mid]) / 2
        return self.values[mid]

    @property
    def std(self):
        if self.n < 2:
            return 0.0
        m = self.mean
        return math.sqrt(sum((v - m) ** 2 for v in self.values) / (self.n - 1))

    @property
    def min(self):
        return self.values[0] if self.n else 0.0

    @property
    def max(self):
        return self.values[-1] if self.n else 0.0

    @property
    def cv(self):
        """Coefficient of variation (%)."""
        m = self.mean
        return (self.std / m * 100) if m else 0.0

    def percentile(self, p):
        if not self.n:
            return 0.0
        k = (self.n - 1) * (p / 100)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return self.values[int(k)]
        return self.values[f] * (c - k) + self.values[c] * (k - f)

    def to_dict(self):
        return {
            "n": self.n,
            "mean": round(self.mean, 9),
            "median": round(self.median, 9),
            "std": round(self.std, 9),
            "min": round(self.min, 9),
            "max": round(self.max, 9),
            "cv_percent": round(self.cv, 2),
            "p5": round(self.percentile(5), 9),
            "p95": round(self.percentile(95), 9),
        }


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

class BenchmarkResult:
    """Results for a single file benchmark."""

    def __init__(self, filename, iterations, warmup, time_stats, mem_stats, errors):
        self.filename = filename
        self.iterations = iterations
        self.warmup = warmup
        self.time_stats = time_stats
        self.mem_stats = mem_stats
        self.errors = errors

    def to_dict(self):
        return {
            "file": self.filename,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "errors": self.errors,
            "time_seconds": self.time_stats.to_dict(),
            "peak_memory_bytes": self.mem_stats.to_dict(),
        }


def benchmark_file(filepath, iterations=10, warmup=2, quiet=True, on_progress=None):
    """Benchmark a .srv file.  Returns a BenchmarkResult."""
    saurav = _resolve_saurav()

    with open(filepath, "r") as f:
        code = f.read()

    # Warmup runs (not measured)
    for i in range(warmup):
        _run_program(saurav, code, quiet=True)
        if on_progress:
            on_progress("warmup", i + 1, warmup)

    # Measured runs
    times = []
    mems = []
    errors = 0
    for i in range(iterations):
        t, m, err = _run_program(saurav, code, quiet=quiet)
        if err:
            errors += 1
        else:
            times.append(t)
            mems.append(m)
        if on_progress:
            on_progress("bench", i + 1, iterations)

    if not times:
        times = [0.0]
        mems = [0]

    return BenchmarkResult(
        filename=os.path.basename(filepath),
        iterations=iterations,
        warmup=warmup,
        time_stats=BenchStats(times),
        mem_stats=BenchStats(mems),
        errors=errors,
    )


def compare_to_baseline(result, baseline):
    """Compare a BenchmarkResult dict against a baseline dict."""
    r_time = result["time_seconds"]["mean"]
    b_time = baseline["time_seconds"]["mean"]
    r_mem = result["peak_memory_bytes"]["mean"]
    b_mem = baseline["peak_memory_bytes"]["mean"]

    time_delta = ((r_time - b_time) / b_time * 100) if b_time else 0
    mem_delta = ((r_mem - b_mem) / b_mem * 100) if b_mem else 0

    def assess_time(delta):
        if delta < -5:
            return "FASTER"
        elif delta > 5:
            return "SLOWER"
        return "SAME"

    def assess_mem(delta):
        if delta < -5:
            return "LESS_MEMORY"
        elif delta > 5:
            return "MORE_MEMORY"
        return "SAME"

    return {
        "file": result["file"],
        "time_delta_percent": round(time_delta, 2),
        "time_assessment": assess_time(time_delta),
        "mem_delta_percent": round(mem_delta, 2),
        "mem_assessment": assess_mem(mem_delta),
        "baseline_time": b_time,
        "current_time": r_time,
        "baseline_mem": b_mem,
        "current_mem": r_mem,
    }


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _fmt_time(seconds):
    """Format seconds in human-friendly units."""
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.1f} us"
    if seconds < 1:
        return f"{seconds * 1000:.2f} ms"
    return f"{seconds:.4f} s"


def _fmt_mem(bytes_val):
    """Format bytes in human-friendly units."""
    if bytes_val < 1024:
        return f"{bytes_val:.0f} B"
    if bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    return f"{bytes_val / (1024 * 1024):.2f} MB"


def format_text_report(results, comparisons=None):
    """Format a human-readable benchmark report."""
    lines = []
    lines.append("=" * 70)
    lines.append("  SAURAVCODE BENCHMARK REPORT")
    lines.append("=" * 70)
    lines.append("")

    for r in results:
        d = r.to_dict()
        ts = d["time_seconds"]
        ms = d["peak_memory_bytes"]

        lines.append(f"  File: {d['file']}")
        lines.append(f"  Iterations: {d['iterations']} (+ {d['warmup']} warmup)")
        if d["errors"]:
            lines.append(f"  Errors: {d['errors']}")
        lines.append("")

        lines.append("  Execution Time:")
        lines.append(f"    Mean:     {_fmt_time(ts['mean'])}")
        lines.append(f"    Median:   {_fmt_time(ts['median'])}")
        lines.append(f"    Std Dev:  {_fmt_time(ts['std'])}")
        lines.append(f"    Min:      {_fmt_time(ts['min'])}")
        lines.append(f"    Max:      {_fmt_time(ts['max'])}")
        lines.append(f"    CV:       {ts['cv_percent']:.1f}%")
        lines.append(f"    P5-P95:   {_fmt_time(ts['p5'])} - {_fmt_time(ts['p95'])}")
        lines.append("")

        lines.append("  Peak Memory:")
        lines.append(f"    Mean:     {_fmt_mem(ms['mean'])}")
        lines.append(f"    Median:   {_fmt_mem(ms['median'])}")
        lines.append(f"    Min:      {_fmt_mem(ms['min'])}")
        lines.append(f"    Max:      {_fmt_mem(ms['max'])}")
        lines.append("")

        # Sparkline-style bar of run times
        if r.time_stats.n > 1:
            times = r.time_stats.values
            mn, mx = min(times), max(times)
            span = mx - mn if mx > mn else 1
            bars = "_.-=*#@"
            spark = ""
            for t in times:
                idx = int((t - mn) / span * (len(bars) - 1))
                spark += bars[idx]
            lines.append(f"  Time Distribution: [{spark}]")
            lines.append("")

        lines.append("-" * 70)
        lines.append("")

    # Comparison table if multiple files
    if len(results) > 1:
        lines.append("  COMPARISON")
        lines.append("")
        ranked = sorted(results, key=lambda r: r.time_stats.mean)
        fastest = ranked[0].time_stats.mean
        hdr = "  {:<30} {:>12} {:>12} {:>12}".format("File", "Mean Time", "vs Fastest", "Memory")
        lines.append(hdr)
        sep = "  {} {} {} {}".format("-" * 30, "-" * 12, "-" * 12, "-" * 12)
        lines.append(sep)
        for r in ranked:
            delta = ((r.time_stats.mean - fastest) / fastest * 100) if fastest else 0
            delta_str = f"+{delta:.1f}%" if delta > 0 else "baseline"
            row = "  {:<30} {:>12} {:>12} {:>12}".format(
                r.filename, _fmt_time(r.time_stats.mean), delta_str, _fmt_mem(r.mem_stats.mean)
            )
            lines.append(row)
        lines.append("")

    # Baseline comparisons
    if comparisons:
        lines.append("  BASELINE COMPARISON")
        lines.append("")
        for c in comparisons:
            time_label = c["time_assessment"]
            mem_label = c["mem_assessment"]
            lines.append(f"  {c['file']}:")
            lines.append(f"    Time: {time_label} {c['time_delta_percent']:+.1f}% ({_fmt_time(c['baseline_time'])} -> {_fmt_time(c['current_time'])})")
            lines.append(f"    Mem:  {mem_label} {c['mem_delta_percent']:+.1f}% ({_fmt_mem(c['baseline_mem'])} -> {_fmt_mem(c['current_mem'])})")
        lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


def format_csv(results):
    """Format results as CSV."""
    lines = ["file,iterations,warmup,errors,time_mean_s,time_median_s,time_std_s,time_min_s,time_max_s,time_cv_pct,mem_mean_bytes,mem_median_bytes,mem_min_bytes,mem_max_bytes"]
    for r in results:
        d = r.to_dict()
        ts = d["time_seconds"]
        ms = d["peak_memory_bytes"]
        lines.append(
            f"{d['file']},{d['iterations']},{d['warmup']},{d['errors']},"
            f"{ts['mean']},{ts['median']},{ts['std']},{ts['min']},{ts['max']},{ts['cv_percent']},"
            f"{ms['mean']},{ms['median']},{ms['min']},{ms['max']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    """Parse CLI arguments. Returns (files, options)."""
    args = argv if argv is not None else sys.argv[1:]
    files = []
    options = {
        "iterations": 10,
        "warmup": 2,
        "json": False,
        "csv": False,
        "quiet": False,
        "baseline": None,
        "save": None,
    }
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-n", "--iterations"):
            i += 1
            options["iterations"] = int(args[i])
        elif a == "--warmup":
            i += 1
            options["warmup"] = int(args[i])
        elif a == "--json":
            options["json"] = True
        elif a == "--csv":
            options["csv"] = True
        elif a == "--quiet":
            options["quiet"] = True
        elif a == "--baseline":
            i += 1
            options["baseline"] = args[i]
        elif a == "--save":
            i += 1
            options["save"] = args[i]
        elif a in ("-h", "--help"):
            print(__doc__.strip())
            sys.exit(0)
        elif a.startswith("-"):
            print(f"Unknown option: {a}", file=sys.stderr)
            sys.exit(1)
        else:
            files.append(a)
        i += 1

    return files, options


def main(argv=None):
    files, opts = parse_args(argv)

    if not files:
        print("Error: No .srv files specified.", file=sys.stderr)
        print("Usage: python sauravbench.py <file.srv> [file2.srv ...] [options]")
        sys.exit(1)

    for f in files:
        if not os.path.isfile(f):
            print(f"Error: File '{f}' not found.", file=sys.stderr)
            sys.exit(1)
        if not f.endswith(".srv"):
            print(f"Error: File '{f}' must have .srv extension.", file=sys.stderr)
            sys.exit(1)

    results = []
    for filepath in files:
        name = os.path.basename(filepath)
        if not opts["json"] and not opts["csv"]:
            print(f"\n  Benchmarking {name}...", end="", flush=True)

        def progress(phase, cur, total):
            if not opts["json"] and not opts["csv"]:
                if phase == "warmup":
                    print(f"\r  Warming up {name}... {cur}/{total}", end="", flush=True)
                else:
                    print(f"\r  Benchmarking {name}... {cur}/{total}  ", end="", flush=True)

        r = benchmark_file(
            filepath,
            iterations=opts["iterations"],
            warmup=opts["warmup"],
            quiet=opts.get("quiet", True),
            on_progress=progress,
        )
        results.append(r)
        if not opts["json"] and not opts["csv"]:
            print(f"\r  Benchmarking {name}... done.         ")

    comparisons = None
    if opts["baseline"]:
        with open(opts["baseline"], "r") as f:
            baseline_data = json.load(f)
        baseline_map = {b["file"]: b for b in baseline_data.get("results", [])}
        comparisons = []
        for r in results:
            rd = r.to_dict()
            if rd["file"] in baseline_map:
                comparisons.append(compare_to_baseline(rd, baseline_map[rd["file"]]))

    if opts["json"]:
        output = {"results": [r.to_dict() for r in results]}
        if comparisons:
            output["comparisons"] = comparisons
        print(json.dumps(output, indent=2))
    elif opts["csv"]:
        print(format_csv(results))
    else:
        print(format_text_report(results, comparisons))

    if opts["save"]:
        output = {"results": [r.to_dict() for r in results]}
        with open(opts["save"], "w") as f:
            json.dump(output, f, indent=2)
        print(f"  Results saved to {opts['save']}")


if __name__ == "__main__":
    main()

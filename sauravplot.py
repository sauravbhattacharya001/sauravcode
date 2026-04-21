#!/usr/bin/env python3
"""sauravplot — ASCII data plotting for sauravcode.

Create bar charts, line charts, scatter plots, and histograms right in
the terminal.  Works standalone or with .srv scripts via built-in
plot_* functions.

Usage (CLI):
    python sauravplot.py bar   "Apples:5,Bananas:8,Cherries:3"
    python sauravplot.py line  "1:2,2:5,3:3,4:7,5:4"
    python sauravplot.py scatter "1:2,2:5,3:3,4:7,5:4"
    python sauravplot.py hist  "1,2,2,3,3,3,4,4,5" --bins 5
    python sauravplot.py spark "3,1,4,1,5,9,2,6,5,3,5"
    python sauravplot.py pie   "Apples:5,Bananas:8,Cherries:3"
    python sauravplot.py --help

Options:
    --width  N    Chart width in columns (default: 60)
    --height N    Chart height in rows (default: 20, line/scatter)
    --title  TEXT Chart title
    --color       Enable ANSI colors
    --bins   N    Number of histogram bins (default: 10)
"""

import sys

# ── ANSI colors ──────────────────────────────────────────────────────
COLORS = [
    "\033[36m",   # cyan
    "\033[32m",   # green
    "\033[33m",   # yellow
    "\033[35m",   # magenta
    "\033[31m",   # red
    "\033[34m",   # blue
    "\033[37m",   # white
]
RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"


def _c(text, idx, use_color):
    if not use_color:
        return str(text)
    return f"{COLORS[idx % len(COLORS)]}{text}{RESET}"


# ── Bar Chart ────────────────────────────────────────────────────────
def bar_chart(labels, values, width=60, title=None, color=False):
    """Horizontal bar chart."""
    lines = []
    if title:
        lines.append(f"\n  {BOLD}{title}{RESET}" if color else f"\n  {title}")
        lines.append("")

    max_val = max(values) if values else 1
    max_label = max(len(str(l)) for l in labels) if labels else 1

    for i, (label, val) in enumerate(zip(labels, values)):
        bar_len = int((val / max_val) * width) if max_val else 0
        bar = "█" * bar_len
        lbl = str(label).rjust(max_label)
        bar_text = _c(bar, i, color)
        lines.append(f"  {lbl} │ {bar_text} {val}")

    lines.append(f"  {''.rjust(max_label)} └{'─' * (width + 2)}")
    return "\n".join(lines)


# ── Sparkline ────────────────────────────────────────────────────────
SPARKS = "▁▂▃▄▅▆▇█"

def sparkline(values, title=None, color=False):
    """Single-line sparkline."""
    if not values:
        return ""
    mn, mx = min(values), max(values)
    rng = mx - mn if mx != mn else 1
    chars = []
    for v in values:
        idx = int((v - mn) / rng * (len(SPARKS) - 1))
        chars.append(SPARKS[idx])
    spark = "".join(chars)
    prefix = f"{title}: " if title else ""
    if color:
        spark = f"{COLORS[0]}{spark}{RESET}"
    mn_s = f"{DIM}(min={mn:.4g} max={mx:.4g}){RESET}" if color else f"(min={mn:.4g} max={mx:.4g})"
    return f"  {prefix}{spark} {mn_s}"


# ── Line Chart ───────────────────────────────────────────────────────
def line_chart(xs, ys, width=60, height=20, title=None, color=False):
    """ASCII line chart on a grid."""
    lines = []
    if title:
        lines.append(f"\n  {BOLD}{title}{RESET}" if color else f"\n  {title}")

    min_y, max_y = min(ys), max(ys)
    min_x, max_x = min(xs), max(xs)
    y_range = max_y - min_y if max_y != min_y else 1
    x_range = max_x - min_x if max_x != min_x else 1

    grid = [[" " for _ in range(width)] for _ in range(height)]

    # plot points and connect
    points = []
    for x, y in zip(xs, ys):
        col = int((x - min_x) / x_range * (width - 1))
        row = height - 1 - int((y - min_y) / y_range * (height - 1))
        points.append((row, col))

    # draw lines between consecutive points
    for i in range(len(points) - 1):
        r0, c0 = points[i]
        r1, c1 = points[i + 1]
        steps = max(abs(r1 - r0), abs(c1 - c0), 1)
        for s in range(steps + 1):
            t = s / steps
            r = int(r0 + (r1 - r0) * t)
            c = int(c0 + (c1 - c0) * t)
            if 0 <= r < height and 0 <= c < width:
                grid[r][c] = "·"

    # mark actual points
    for r, c in points:
        if 0 <= r < height and 0 <= c < width:
            grid[r][c] = "●"

    # render with y-axis labels
    y_label_w = max(len(f"{max_y:.4g}"), len(f"{min_y:.4g}"))
    for row_idx in range(height):
        y_val = max_y - (row_idx / (height - 1)) * y_range
        label = f"{y_val:.4g}".rjust(y_label_w)
        row_str = "".join(grid[row_idx])
        if color:
            row_str = f"{COLORS[0]}{row_str}{RESET}"
        sep = "┤" if row_idx < height - 1 else "┘"
        lines.append(f"  {label} {sep}{row_str}")

    # x-axis
    x_axis = f"  {''.rjust(y_label_w)} └{'─' * width}"
    lines.append(x_axis)
    x_min_s = f"{min_x:.4g}"
    x_max_s = f"{max_x:.4g}"
    pad = width - len(x_min_s) - len(x_max_s)
    lines.append(f"  {''.rjust(y_label_w)}  {x_min_s}{' ' * max(pad, 1)}{x_max_s}")

    return "\n".join(lines)


# ── Scatter Plot ─────────────────────────────────────────────────────
def scatter_plot(xs, ys, width=60, height=20, title=None, color=False):
    """ASCII scatter plot."""
    lines = []
    if title:
        lines.append(f"\n  {BOLD}{title}{RESET}" if color else f"\n  {title}")

    min_y, max_y = min(ys), max(ys)
    min_x, max_x = min(xs), max(xs)
    y_range = max_y - min_y if max_y != min_y else 1
    x_range = max_x - min_x if max_x != min_x else 1

    grid = [[" " for _ in range(width)] for _ in range(height)]

    for x, y in zip(xs, ys):
        col = int((x - min_x) / x_range * (width - 1))
        row = height - 1 - int((y - min_y) / y_range * (height - 1))
        if 0 <= row < height and 0 <= col < width:
            grid[row][col] = "◆"

    y_label_w = max(len(f"{max_y:.4g}"), len(f"{min_y:.4g}"))
    for row_idx in range(height):
        y_val = max_y - (row_idx / (height - 1)) * y_range
        label = f"{y_val:.4g}".rjust(y_label_w)
        row_str = "".join(grid[row_idx])
        if color:
            row_str = f"{COLORS[1]}{row_str}{RESET}"
        sep = "┤" if row_idx < height - 1 else "┘"
        lines.append(f"  {label} {sep}{row_str}")

    x_axis = f"  {''.rjust(y_label_w)} └{'─' * width}"
    lines.append(x_axis)
    x_min_s = f"{min_x:.4g}"
    x_max_s = f"{max_x:.4g}"
    pad = width - len(x_min_s) - len(x_max_s)
    lines.append(f"  {''.rjust(y_label_w)}  {x_min_s}{' ' * max(pad, 1)}{x_max_s}")

    return "\n".join(lines)


# ── Histogram ────────────────────────────────────────────────────────
def histogram(values, bins=10, width=60, title=None, color=False):
    """ASCII histogram."""
    mn, mx = min(values), max(values)
    rng = mx - mn if mx != mn else 1
    bin_width = rng / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - mn) / bin_width), bins - 1)
        counts[idx] += 1

    labels = []
    for i in range(bins):
        lo = mn + i * bin_width
        hi = lo + bin_width
        labels.append(f"{lo:.3g}-{hi:.3g}")

    return bar_chart(labels, counts, width=width, title=title or "Histogram", color=color)


# ── Pie Chart (ASCII) ────────────────────────────────────────────────
PIE_CHARS = "░▒▓█▚▞●◆"

def pie_chart(labels, values, title=None, color=False):
    """ASCII pie chart as percentage bar + legend."""
    total = sum(values) if values else 1
    lines = []
    if title:
        lines.append(f"\n  {BOLD}{title}{RESET}" if color else f"\n  {title}")
        lines.append("")

    # percentage bar (50 chars wide)
    bar_w = 50
    bar_parts = []
    for i, (label, val) in enumerate(zip(labels, values)):
        pct = val / total
        seg_len = max(1, round(pct * bar_w))
        ch = PIE_CHARS[i % len(PIE_CHARS)]
        segment = ch * seg_len
        bar_parts.append(_c(segment, i, color))

    lines.append("  [" + "".join(bar_parts) + "]")
    lines.append("")

    # legend
    max_lbl = max(len(str(l)) for l in labels) if labels else 1
    for i, (label, val) in enumerate(zip(labels, values)):
        pct = val / total * 100
        ch = PIE_CHARS[i % len(PIE_CHARS)]
        indicator = _c(ch * 2, i, color)
        lines.append(f"  {indicator} {str(label).ljust(max_lbl)}  {val} ({pct:.1f}%)")

    return "\n".join(lines)


# ── Multi-series support ─────────────────────────────────────────────
def multi_bar(series_dict, width=60, title=None, color=False):
    """Grouped bar chart. series_dict = {series_name: {label: value}}."""
    lines = []
    if title:
        lines.append(f"\n  {BOLD}{title}{RESET}" if color else f"\n  {title}")
        lines.append("")

    all_labels = []
    for sd in series_dict.values():
        for l in sd:
            if l not in all_labels:
                all_labels.append(l)

    all_vals = [v for sd in series_dict.values() for v in sd.values()]
    max_val = max(all_vals) if all_vals else 1
    max_label = max(len(str(l)) for l in all_labels) if all_labels else 1
    series_names = list(series_dict.keys())

    for label in all_labels:
        for si, sname in enumerate(series_names):
            val = series_dict[sname].get(label, 0)
            bar_len = int((val / max_val) * width) if max_val else 0
            bar = "█" * bar_len
            bar_text = _c(bar, si, color)
            lbl = str(label).rjust(max_label) if si == 0 else "".rjust(max_label)
            tag = f" [{sname}]" if len(series_names) > 1 else ""
            lines.append(f"  {lbl} │ {bar_text} {val}{tag}")
        lines.append(f"  {''.rjust(max_label)} │")

    lines.append(f"  {''.rjust(max_label)} └{'─' * (width + 2)}")
    return "\n".join(lines)


# ── Sauravcode integration ───────────────────────────────────────────
def register_plot_builtins(builtins_dict):
    """Register plot_* functions into a sauravcode interpreter builtins dict."""

    def _plot_bar(args):
        labels, values = args[0], args[1]
        title = args[2] if len(args) > 2 else None
        print(bar_chart(labels, values, title=title, color=True))
        return None

    def _plot_line(args):
        xs, ys = args[0], args[1]
        title = args[2] if len(args) > 2 else None
        print(line_chart(xs, ys, title=title, color=True))
        return None

    def _plot_scatter(args):
        xs, ys = args[0], args[1]
        title = args[2] if len(args) > 2 else None
        print(scatter_plot(xs, ys, title=title, color=True))
        return None

    def _plot_hist(args):
        values = args[0]
        bins = int(args[1]) if len(args) > 1 else 10
        title = args[2] if len(args) > 2 else None
        print(histogram(values, bins=bins, title=title, color=True))
        return None

    def _plot_spark(args):
        values = args[0]
        title = args[1] if len(args) > 1 else None
        print(sparkline(values, title=title, color=True))
        return None

    def _plot_pie(args):
        labels, values = args[0], args[1]
        title = args[2] if len(args) > 2 else None
        print(pie_chart(labels, values, title=title, color=True))
        return None

    builtins_dict["plot_bar"] = _plot_bar
    builtins_dict["plot_line"] = _plot_line
    builtins_dict["plot_scatter"] = _plot_scatter
    builtins_dict["plot_hist"] = _plot_hist
    builtins_dict["plot_spark"] = _plot_spark
    builtins_dict["plot_pie"] = _plot_pie


# ── CLI ──────────────────────────────────────────────────────────────
def _parse_kv(s):
    """Parse 'A:1,B:2' into (labels, values)."""
    labels, values = [], []
    for pair in s.split(","):
        parts = pair.strip().split(":")
        if len(parts) == 2:
            labels.append(parts[0].strip())
            values.append(float(parts[1].strip()))
    return labels, values


def _parse_xy(s):
    """Parse '1:2,3:4' into (xs, ys)."""
    xs, ys = [], []
    for pair in s.split(","):
        parts = pair.strip().split(":")
        if len(parts) == 2:
            xs.append(float(parts[0].strip()))
            ys.append(float(parts[1].strip()))
    return xs, ys


def _parse_values(s):
    """Parse '1,2,3,4' into list of floats."""
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return

    chart_type = args[0].lower()
    data_str = args[1] if len(args) > 1 else ""

    # parse optional flags
    width = 60
    height = 20
    title = None
    use_color = False
    bins = 10

    i = 2
    while i < len(args):
        if args[i] == "--width" and i + 1 < len(args):
            width = int(args[i + 1]); i += 2
        elif args[i] == "--height" and i + 1 < len(args):
            height = int(args[i + 1]); i += 2
        elif args[i] == "--title" and i + 1 < len(args):
            title = args[i + 1]; i += 2
        elif args[i] == "--color":
            use_color = True; i += 1
        elif args[i] == "--bins" and i + 1 < len(args):
            bins = int(args[i + 1]); i += 2
        else:
            i += 1

    if chart_type == "bar":
        labels, values = _parse_kv(data_str)
        print(bar_chart(labels, values, width=width, title=title, color=use_color))
    elif chart_type == "line":
        xs, ys = _parse_xy(data_str)
        print(line_chart(xs, ys, width=width, height=height, title=title, color=use_color))
    elif chart_type == "scatter":
        xs, ys = _parse_xy(data_str)
        print(scatter_plot(xs, ys, width=width, height=height, title=title, color=use_color))
    elif chart_type == "hist":
        values = _parse_values(data_str)
        print(histogram(values, bins=bins, width=width, title=title, color=use_color))
    elif chart_type == "spark":
        values = _parse_values(data_str)
        print(sparkline(values, title=title, color=use_color))
    elif chart_type == "pie":
        labels, values = _parse_kv(data_str)
        print(pie_chart(labels, values, title=title, color=use_color))
    else:
        print(f"Unknown chart type: {chart_type}")
        print("Supported: bar, line, scatter, hist, spark, pie")
        sys.exit(1)


if __name__ == "__main__":
    main()

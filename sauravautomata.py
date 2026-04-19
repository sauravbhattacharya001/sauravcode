#!/usr/bin/env python3
"""sauravautomata — Interactive Cellular Automata Simulator & Explorer.

Simulate 1D elementary cellular automata (Wolfram rules 0-255) and
Conway's Game of Life in the terminal.  Features proactive pattern
detection, auto-classification, and smart recommendations.

Usage (CLI):
    python sauravautomata.py rule 30 --generations 40 --width 80
    python sauravautomata.py rule 110 --generations 60 --color
    python sauravautomata.py life --preset glider --generations 50
    python sauravautomata.py life --random --density 0.3 --generations 100
    python sauravautomata.py life --width 40 --height 20 --generations 80
    python sauravautomata.py repl
    python sauravautomata.py classify 0 255
    python sauravautomata.py --help

Options:
    --width  N      Grid width in columns (default: 60)
    --height N      Grid height in rows (default: 20, life only)
    --generations N Number of generations (default: 40)
    --density F     Random fill density 0.0-1.0 (default: 0.3)
    --color         Enable ANSI colors
    --preset NAME   Life preset: glider, blinker, pulsar, gun, rpentomino
"""

import sys
import math
import random
import os
import io

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower().replace('-','') != 'utf8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ── ANSI colors ──────────────────────────────────────────────────────
COLORS = [
    "\033[36m", "\033[32m", "\033[33m", "\033[35m",
    "\033[31m", "\033[34m", "\033[37m",
]
RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"

def _c(text, color_idx, use_color):
    if not use_color:
        return str(text)
    return f"{COLORS[color_idx % len(COLORS)]}{text}{RESET}"

def _bold(text, use_color):
    return f"{BOLD}{text}{RESET}" if use_color else str(text)

# ── Sparkline ────────────────────────────────────────────────────────
SPARK_CHARS = "▁▂▃▄▅▆▇█"

def sparkline(values):
    if not values:
        return ""
    lo, hi = min(values), max(values)
    rng = hi - lo if hi != lo else 1
    return "".join(SPARK_CHARS[min(int((v - lo) / rng * 7), 7)] for v in values)

# ── Shannon entropy ──────────────────────────────────────────────────
def shannon_entropy(cells):
    n = len(cells)
    if n == 0:
        return 0.0
    ones = sum(cells)
    zeros = n - ones
    ent = 0.0
    for count in (zeros, ones):
        if count > 0:
            p = count / n
            ent -= p * math.log2(p)
    return ent

# ═════════════════════════════════════════════════════════════════════
#  1D ELEMENTARY CELLULAR AUTOMATA
# ═════════════════════════════════════════════════════════════════════

def rule_to_table(rule_num):
    """Convert rule number (0-255) to lookup table."""
    return {(i >> 2 & 1, i >> 1 & 1, i & 1): (rule_num >> i) & 1
            for i in range(8)}

def step_1d(cells, table):
    n = len(cells)
    new = [0] * n
    for i in range(n):
        l = cells[(i - 1) % n]
        c = cells[i]
        r = cells[(i + 1) % n]
        new[i] = table[(l, c, r)]
    return new

def render_1d_row(cells, color=False, gen=0):
    chars = []
    for c in cells:
        if c:
            chars.append(_c("█", gen % len(COLORS), color))
        else:
            chars.append(" ")
    return "".join(chars)

def run_1d(rule_num, width=60, generations=40, color=False):
    """Run 1D elementary CA and return history + stats."""
    table = rule_to_table(rule_num)
    cells = [0] * width
    cells[width // 2] = 1  # single seed

    history = [cells[:]]
    populations = [sum(cells)]
    entropies = [shannon_entropy(cells)]
    lines = []
    lines.append(render_1d_row(cells, color, 0))

    for g in range(1, generations):
        cells = step_1d(cells, table)
        history.append(cells[:])
        populations.append(sum(cells))
        entropies.append(shannon_entropy(cells))
        lines.append(render_1d_row(cells, color, g))

    return lines, history, populations, entropies

def classify_1d_rule(rule_num, width=80, generations=100):
    """Auto-classify a 1D rule into Wolfram Class I-IV."""
    _, history, pops, ents = run_1d(rule_num, width, generations)

    # Check stabilization (Class I)
    last = history[-1]
    stable_count = 0
    for i in range(len(history) - 1, max(0, len(history) - 20), -1):
        if history[i] == last:
            stable_count += 1
        else:
            break
    if stable_count >= 15:
        return "I", "Stable (uniform/fixed)"

    # Check oscillation (Class II)
    tail = history[generations // 2:]
    for period in range(1, min(20, len(tail) // 2)):
        is_periodic = True
        for i in range(len(tail) - period):
            if tail[i] != tail[i + period]:
                is_periodic = False
                break
        if is_periodic:
            return "II", f"Periodic (period {period})"

    # Check entropy for chaos vs complexity
    avg_ent = sum(ents[generations // 2:]) / max(1, len(ents[generations // 2:]))
    ent_var = sum((e - avg_ent) ** 2 for e in ents[generations // 2:]) / max(1, len(ents[generations // 2:]))

    if avg_ent > 0.8 and ent_var < 0.01:
        return "III", "Chaotic (high entropy, low variance)"

    return "IV", "Complex (edge of chaos)"

# ═════════════════════════════════════════════════════════════════════
#  CONWAY'S GAME OF LIFE (2D)
# ═════════════════════════════════════════════════════════════════════

PRESETS = {
    "glider":     {"cells": [(0,1),(1,2),(2,0),(2,1),(2,2)], "desc": "Classic glider"},
    "blinker":    {"cells": [(1,0),(1,1),(1,2)], "desc": "Period-2 oscillator"},
    "pulsar":     {"cells": [], "desc": "Period-3 oscillator"},
    "rpentomino": {"cells": [(0,1),(0,2),(1,0),(1,1),(2,1)], "desc": "R-pentomino (long-lived)"},
    "gun":        {"cells": [], "desc": "Gosper glider gun"},
}

def _init_pulsar():
    cells = []
    offsets = [
        (2,4),(2,5),(2,6),(2,10),(2,11),(2,12),
        (4,2),(4,7),(4,9),(4,14),
        (5,2),(5,7),(5,9),(5,14),
        (6,2),(6,7),(6,9),(6,14),
        (7,4),(7,5),(7,6),(7,10),(7,11),(7,12),
    ]
    for r, c in offsets:
        cells.append((r, c))
        cells.append((14 - r, c))
    return list(set(cells))

PRESETS["pulsar"]["cells"] = _init_pulsar()

def _init_gun():
    raw = [
        (5,1),(5,2),(6,1),(6,2),
        (3,13),(3,14),(4,12),(4,16),(5,11),(5,17),(6,11),(6,15),(6,17),(6,18),
        (7,11),(7,17),(8,12),(8,16),(9,13),(9,14),
        (1,25),(2,23),(2,25),(3,21),(3,22),(4,21),(4,22),(5,21),(5,22),
        (6,23),(6,25),(7,25),
        (3,35),(3,36),(4,35),(4,36),
    ]
    return raw

PRESETS["gun"]["cells"] = _init_gun()

def make_life_grid(width, height, preset=None, density=0.3):
    grid = [[0]*width for _ in range(height)]
    if preset and preset in PRESETS:
        off_r = height // 4
        off_c = width // 4
        for r, c in PRESETS[preset]["cells"]:
            rr, cc = r + off_r, c + off_c
            if 0 <= rr < height and 0 <= cc < width:
                grid[rr][cc] = 1
    else:
        for r in range(height):
            for c in range(width):
                grid[r][c] = 1 if random.random() < density else 0
    return grid

def step_life(grid):
    h = len(grid)
    w = len(grid[0])
    new = [[0]*w for _ in range(h)]
    births = deaths = 0
    for r in range(h):
        for c in range(w):
            n = 0
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = (r + dr) % h, (c + dc) % w
                    n += grid[nr][nc]
            if grid[r][c]:
                if n in (2, 3):
                    new[r][c] = 1
                else:
                    deaths += 1
            else:
                if n == 3:
                    new[r][c] = 1
                    births += 1
    return new, births, deaths

def render_life(grid, color=False, gen=0):
    lines = []
    for r, row in enumerate(grid):
        chars = []
        for c, cell in enumerate(row):
            if cell:
                chars.append(_c("█", (r + c) % len(COLORS), color))
            else:
                chars.append(_c("·", 6, color) if color else "·")
        lines.append("".join(chars))
    return lines

def grid_hash(grid):
    return tuple(tuple(row) for row in grid)

def run_life(width=40, height=20, generations=100, preset=None, density=0.3, color=False):
    """Run Game of Life and return stats."""
    grid = make_life_grid(width, height, preset, density)
    populations = [sum(sum(row) for row in grid)]
    seen_hashes = {grid_hash(grid): 0}
    all_frames = [render_life(grid, color, 0)]
    alerts = []
    oscillation_period = None

    for g in range(1, generations):
        grid, births, deaths = step_life(grid)
        pop = sum(sum(row) for row in grid)
        populations.append(pop)
        all_frames.append(render_life(grid, color, g))

        h = grid_hash(grid)
        if h in seen_hashes:
            period = g - seen_hashes[h]
            if period == 0:
                alerts.append(f"⚠  Pattern stabilized at generation {g} (no changes)")
                oscillation_period = 0
                break
            else:
                alerts.append(f"🔄 Oscillation detected at generation {g}: period {period}")
                oscillation_period = period
                break
        seen_hashes[h] = g

        if pop == 0:
            alerts.append(f"💀 Population extinct at generation {g}")
            break

    # Growth analysis
    if len(populations) > 10:
        early = sum(populations[:5]) / 5
        late = sum(populations[-5:]) / 5
        if early > 0 and late / max(early, 1) > 3:
            alerts.append("📈 Significant population growth detected")

    return all_frames, populations, alerts, oscillation_period

# ── Smart Recommendations ────────────────────────────────────────────

INTERESTING_RULES = [30, 54, 60, 90, 110, 150, 184, 105, 73, 45, 75, 89, 101, 135, 169]

def recommend_after_1d(rule_num):
    suggestions = []
    cls, _ = classify_1d_rule(rule_num, 60, 60)
    if cls in ("I", "II"):
        suggestions.append(f"Try chaotic Rule 30 or complex Rule 110 for more action")
    elif cls == "III":
        suggestions.append(f"Try Rule 110 (Class IV — edge of chaos) for emergent structures")
    elif cls == "IV":
        suggestions.append(f"Try Rule 90 (Sierpinski triangle) for beautiful fractal patterns")

    neighbors = [r for r in (rule_num - 1, rule_num + 1, rule_num ^ 0xFF) if 0 <= r <= 255 and r != rule_num]
    if neighbors:
        suggestions.append(f"Explore neighbors: Rule {', '.join(str(n) for n in neighbors[:3])}")
    return suggestions

def recommend_after_life(preset):
    presets = list(PRESETS.keys())
    others = [p for p in presets if p != preset]
    if others:
        pick = random.choice(others)
        return [f"Try preset '{pick}': {PRESETS[pick]['desc']}",
                "Try --random --density 0.15 for sparse emergent life"]
    return ["Try --random mode with different densities"]

# ═════════════════════════════════════════════════════════════════════
#  REPL
# ═════════════════════════════════════════════════════════════════════

REPL_HELP = """
Commands:
  rule <N>               Set 1D rule (0-255) and show 40 generations
  life                   Start Game of Life (random)
  preset <name>          Start Life with preset (glider/blinker/pulsar/rpentomino/gun)
  step                   Advance one generation
  run <N>                Run N generations
  reset                  Reset current automaton
  random [density]       Random Life grid (density 0.0-1.0)
  stats                  Show population sparkline and entropy
  classify [start] [end] Classify 1D rules in range
  export <file>          Export current state to text file
  help                   Show this help
  quit / exit            Exit REPL
""".strip()

def repl():
    """Interactive REPL mode."""
    print(_bold("╔═══════════════════════════════════════╗", True))
    print(_bold("║   sauravautomata — Interactive REPL   ║", True))
    print(_bold("╚═══════════════════════════════════════╝", True))
    print("Type 'help' for commands.\n")

    mode = None  # '1d' or 'life'
    cells_1d = None
    table_1d = None
    grid = None
    gen = 0
    rule_num = 0
    populations = []
    entropies = []
    w, h = 60, 20
    color = True

    while True:
        try:
            line = input("automata> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        if cmd in ("quit", "exit"):
            print("Bye!")
            break

        elif cmd == "help":
            print(REPL_HELP)

        elif cmd == "rule":
            if len(parts) < 2:
                print("Usage: rule <0-255>")
                continue
            try:
                rule_num = int(parts[1])
                assert 0 <= rule_num <= 255
            except (ValueError, AssertionError):
                print("Rule must be 0-255")
                continue
            mode = "1d"
            table_1d = rule_to_table(rule_num)
            cells_1d = [0] * w
            cells_1d[w // 2] = 1
            gen = 0
            populations = [sum(cells_1d)]
            entropies = [shannon_entropy(cells_1d)]
            lines, hist, pops, ents = run_1d(rule_num, w, 40, color)
            for l in lines:
                print(l)
            populations = pops
            entropies = ents
            cells_1d = hist[-1]
            gen = len(hist) - 1
            cls, desc = classify_1d_rule(rule_num, w, 80)
            print(f"\n🏷  Rule {rule_num} → Wolfram Class {cls}: {desc}")
            for rec in recommend_after_1d(rule_num):
                print(f"  💡 {rec}")

        elif cmd == "life":
            mode = "life"
            grid = make_life_grid(w, h, density=0.3)
            gen = 0
            pop = sum(sum(row) for row in grid)
            populations = [pop]
            entropies = []
            for l in render_life(grid, color, 0):
                print(l)
            print(f"Gen 0 | Pop: {pop}")

        elif cmd == "preset":
            if len(parts) < 2 or parts[1] not in PRESETS:
                print(f"Available: {', '.join(PRESETS.keys())}")
                continue
            mode = "life"
            grid = make_life_grid(w, h, preset=parts[1])
            gen = 0
            pop = sum(sum(row) for row in grid)
            populations = [pop]
            print(f"Loaded preset '{parts[1]}': {PRESETS[parts[1]]['desc']}")
            for l in render_life(grid, color, 0):
                print(l)
            print(f"Gen 0 | Pop: {pop}")

        elif cmd == "step":
            if mode == "1d" and cells_1d:
                cells_1d = step_1d(cells_1d, table_1d)
                gen += 1
                pop = sum(cells_1d)
                populations.append(pop)
                entropies.append(shannon_entropy(cells_1d))
                print(render_1d_row(cells_1d, color, gen))
                print(f"Gen {gen} | Pop: {pop}")
            elif mode == "life" and grid:
                grid, births, deaths = step_life(grid)
                gen += 1
                pop = sum(sum(row) for row in grid)
                populations.append(pop)
                for l in render_life(grid, color, gen):
                    print(l)
                print(f"Gen {gen} | Pop: {pop} | +{births} -{deaths}")
            else:
                print("No automaton active. Use 'rule <N>' or 'life' first.")

        elif cmd == "run":
            n = int(parts[1]) if len(parts) > 1 else 20
            if mode == "1d" and cells_1d:
                for _ in range(n):
                    cells_1d = step_1d(cells_1d, table_1d)
                    gen += 1
                    populations.append(sum(cells_1d))
                    entropies.append(shannon_entropy(cells_1d))
                    print(render_1d_row(cells_1d, color, gen))
                print(f"Gen {gen} | Pop: {populations[-1]}")
            elif mode == "life" and grid:
                seen = {grid_hash(grid): gen}
                for _ in range(n):
                    grid, births, deaths = step_life(grid)
                    gen += 1
                    pop = sum(sum(row) for row in grid)
                    populations.append(pop)
                    gh = grid_hash(grid)
                    if gh in seen:
                        period = gen - seen[gh]
                        if period == 0:
                            print(f"⚠  Stabilized at generation {gen}")
                        else:
                            print(f"🔄 Oscillation: period {period} (gen {gen})")
                        break
                    seen[gh] = gen
                    if pop == 0:
                        print(f"💀 Extinct at generation {gen}")
                        break
                for l in render_life(grid, color, gen):
                    print(l)
                print(f"Gen {gen} | Pop: {populations[-1]}")
            else:
                print("No automaton active.")

        elif cmd == "reset":
            if mode == "1d":
                cells_1d = [0] * w
                cells_1d[w // 2] = 1
                gen = 0
                populations = [sum(cells_1d)]
                entropies = [shannon_entropy(cells_1d)]
                print("Reset 1D automaton.")
            elif mode == "life":
                grid = make_life_grid(w, h, density=0.3)
                gen = 0
                populations = [sum(sum(row) for row in grid)]
                print("Reset Life grid.")
            else:
                print("Nothing to reset.")

        elif cmd == "random":
            density = float(parts[1]) if len(parts) > 1 else 0.3
            mode = "life"
            grid = make_life_grid(w, h, density=density)
            gen = 0
            pop = sum(sum(row) for row in grid)
            populations = [pop]
            for l in render_life(grid, color, 0):
                print(l)
            print(f"Gen 0 | Pop: {pop} | Density: {density:.1%}")

        elif cmd == "stats":
            if not populations:
                print("No data yet.")
                continue
            print(f"Generations: {gen}")
            print(f"Population:  {sparkline(populations[-60:])}")
            print(f"  current={populations[-1]}, min={min(populations)}, max={max(populations)}, avg={sum(populations)/len(populations):.1f}")
            if entropies:
                print(f"Entropy:     {sparkline(entropies[-60:])}")
                print(f"  current={entropies[-1]:.3f}")

        elif cmd == "classify":
            start = int(parts[1]) if len(parts) > 1 else 0
            end = int(parts[2]) if len(parts) > 2 else 255
            counts = {"I": 0, "II": 0, "III": 0, "IV": 0}
            for r in range(start, min(end + 1, 256)):
                cls, desc = classify_1d_rule(r, 60, 60)
                counts[cls] += 1
                print(f"  Rule {r:>3d} → Class {cls}: {desc}")
            print(f"\nSummary: I={counts['I']} II={counts['II']} III={counts['III']} IV={counts['IV']}")

        elif cmd == "export":
            if len(parts) < 2:
                print("Usage: export <filename>")
                continue
            fname = parts[1]
            try:
                with open(fname, "w") as f:
                    if mode == "1d" and cells_1d:
                        f.write(f"Rule {rule_num} | Gen {gen}\n")
                        f.write("".join("█" if c else " " for c in cells_1d) + "\n")
                    elif mode == "life" and grid:
                        f.write(f"Game of Life | Gen {gen}\n")
                        for row in grid:
                            f.write("".join("█" if c else "·" for c in row) + "\n")
                    f.write(f"\nPopulation: {', '.join(str(p) for p in populations)}\n")
                print(f"Exported to {fname}")
            except IOError as e:
                print(f"Error: {e}")

        else:
            print(f"Unknown command: {cmd}. Type 'help'.")

# ═════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═════════════════════════════════════════════════════════════════════

def _get_arg(args, name, default=None, type_fn=str):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return type_fn(args[i + 1])
    return default

def _has_flag(args, name):
    return name in args

def print_help():
    print(__doc__)

def main():
    args = sys.argv[1:]

    if not args or args[0] in ("--help", "-h", "help"):
        print_help()
        return

    color = _has_flag(args, "--color")
    width = _get_arg(args, "--width", 60, int)
    height = _get_arg(args, "--height", 20, int)
    generations = _get_arg(args, "--generations", 40, int)
    density = _get_arg(args, "--density", 0.3, float)
    preset = _get_arg(args, "--preset", None)

    cmd = args[0].lower()

    if cmd == "repl":
        repl()

    elif cmd == "rule":
        if len(args) < 2:
            print("Usage: sauravautomata.py rule <0-255>")
            return
        rule_num = int(args[1])
        if not 0 <= rule_num <= 255:
            print("Rule must be 0-255")
            return

        print(_bold(f"═══ Rule {rule_num} ═══", color))
        lines, history, pops, ents = run_1d(rule_num, width, generations, color)
        for l in lines:
            print(l)

        # Stats
        print(f"\n📊 Population: {sparkline(pops)}")
        print(f"   min={min(pops)}, max={max(pops)}, final={pops[-1]}")
        print(f"📊 Entropy:    {sparkline(ents)}")

        # Auto-classify
        cls, desc = classify_1d_rule(rule_num, width, min(generations, 100))
        print(f"\n🏷  Wolfram Class {cls}: {desc}")

        # Recommendations
        print("\n💡 Suggestions:")
        for rec in recommend_after_1d(rule_num):
            print(f"   {rec}")

    elif cmd == "life":
        print(_bold("═══ Conway's Game of Life ═══", color))
        if preset:
            print(f"Preset: {preset} — {PRESETS.get(preset, {}).get('desc', '?')}")

        frames, pops, alerts, osc = run_life(width, height, generations, preset, density, color)

        # Show last frame
        for l in frames[-1]:
            print(l)

        print(f"\n📊 Population: {sparkline(pops)}")
        print(f"   gens={len(pops)}, final={pops[-1]}, peak={max(pops)}")

        # Alerts
        for a in alerts:
            print(f"   {a}")

        # Recommendations
        print("\n💡 Suggestions:")
        for rec in recommend_after_life(preset):
            print(f"   {rec}")

    elif cmd == "classify":
        start = int(args[1]) if len(args) > 1 else 0
        end = int(args[2]) if len(args) > 2 else 255
        print(_bold("═══ Wolfram Rule Classification ═══", color))
        counts = {"I": 0, "II": 0, "III": 0, "IV": 0}
        for r in range(start, min(end + 1, 256)):
            cls, desc = classify_1d_rule(r, 60, 60)
            counts[cls] += 1
            c_idx = {"I": 4, "II": 1, "III": 3, "IV": 0}[cls]
            print(f"  Rule {r:>3d} → {_c(f'Class {cls}', c_idx, color)}: {desc}")
        print(f"\n  Summary: I={counts['I']}  II={counts['II']}  III={counts['III']}  IV={counts['IV']}")
        total = sum(counts.values())
        if total > 0:
            print(f"  Distribution: I={counts['I']/total:.0%} II={counts['II']/total:.0%} III={counts['III']/total:.0%} IV={counts['IV']/total:.0%}")

    else:
        print(f"Unknown command: {cmd}")
        print_help()

if __name__ == "__main__":
    main()

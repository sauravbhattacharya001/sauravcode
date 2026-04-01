#!/usr/bin/env python3
"""sauravcanvas — Turtle graphics for sauravcode.

Write .srv programs using turtle-like drawing commands and generate
SVG output.  The tool injects drawing built-in functions into the
sauravcode interpreter so you can mix regular sauravcode logic with
graphics commands.

Usage:
    python sauravcanvas.py drawing.srv                  # write SVG to stdout
    python sauravcanvas.py drawing.srv -o out.svg       # write to file
    python sauravcanvas.py drawing.srv --html            # wrap in HTML viewer
    python sauravcanvas.py drawing.srv --html -o out.html
    python sauravcanvas.py --gallery                     # show built-in examples

Drawing commands available inside .srv files:
    forward N          — move forward N pixels, drawing a line
    back N             — move backward N pixels
    turn_right D       — turn right D degrees
    turn_left D        — turn left D degrees
    pen_up             — stop drawing (move without lines)
    pen_down           — start drawing again
    pen_color C        — set stroke color (CSS name or hex)
    pen_width W        — set stroke width in pixels
    goto_xy X Y        — move to absolute position
    circle R           — draw a circle with radius R
    fill_color C       — set fill color for circles/shapes
    save_pos           — push current position/heading to stack
    restore_pos        — pop position/heading from stack
    canvas_size W H    — set canvas dimensions (default 800×600)
    canvas_bg C        — set canvas background color

Example .srv file:
    pen_color "royalblue"
    pen_width 2
    for i in range 0 4
        forward 100
        turn_right 90

    # Draws a blue square!
"""

import sys
import os
import math
import copy
import argparse


class TurtleState:
    """Track the turtle's position, heading, pen state, and drawn paths."""

    def __init__(self):
        self.x = 400.0
        self.y = 300.0
        self.heading = -90.0  # degrees, 0 = right, -90 = up
        self.pen_down = True
        self.color = "black"
        self.width = 2
        self.fill = "none"
        self.canvas_w = 800
        self.canvas_h = 600
        self.canvas_bg = "white"
        self.elements = []  # SVG elements (lines, circles)
        self.pos_stack = []
        self._current_path = []  # points for current polyline

    def _flush_path(self):
        if len(self._current_path) >= 2:
            pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in self._current_path)
            self.elements.append(
                f'<polyline points="{pts}" fill="none" '
                f'stroke="{self.color}" stroke-width="{self.width}" '
                f'stroke-linecap="round" stroke-linejoin="round"/>'
            )
        self._current_path = []

    def forward(self, dist):
        rad = math.radians(self.heading)
        nx = self.x + dist * math.cos(rad)
        ny = self.y + dist * math.sin(rad)
        if self.pen_down:
            if not self._current_path:
                self._current_path.append((self.x, self.y))
            self._current_path.append((nx, ny))
        else:
            self._flush_path()
        self.x, self.y = nx, ny

    def back(self, dist):
        self.forward(-dist)

    def right(self, deg):
        self._flush_path()
        self.heading = (self.heading + deg) % 360

    def left(self, deg):
        self._flush_path()
        self.heading = (self.heading - deg) % 360

    def set_pen_up(self):
        self._flush_path()
        self.pen_down = False

    def set_pen_down(self):
        self.pen_down = True

    def set_color(self, c):
        self._flush_path()
        self.color = str(c)

    def set_width(self, w):
        self._flush_path()
        self.width = max(0.1, float(w))

    def set_fill(self, c):
        self.fill = str(c)

    def goto(self, x, y):
        if self.pen_down:
            if not self._current_path:
                self._current_path.append((self.x, self.y))
            self._current_path.append((float(x), float(y)))
        else:
            self._flush_path()
        self.x, self.y = float(x), float(y)

    def draw_circle(self, r):
        self._flush_path()
        self.elements.append(
            f'<circle cx="{self.x:.2f}" cy="{self.y:.2f}" r="{abs(float(r)):.2f}" '
            f'fill="{self.fill}" stroke="{self.color}" stroke-width="{self.width}"/>'
        )

    def save(self):
        self.pos_stack.append((self.x, self.y, self.heading))

    def restore(self):
        if self.pos_stack:
            self._flush_path()
            self.x, self.y, self.heading = self.pos_stack.pop()

    def to_svg(self):
        self._flush_path()
        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{self.canvas_w}" height="{self.canvas_h}" '
            f'viewBox="0 0 {self.canvas_w} {self.canvas_h}">',
            f'  <rect width="100%" height="100%" fill="{self.canvas_bg}"/>',
        ]
        for el in self.elements:
            lines.append(f"  {el}")
        lines.append("</svg>")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gallery examples
# ---------------------------------------------------------------------------
GALLERY = {
    "square": (
        "Simple Square",
        'pen_color "royalblue"\npen_width 3\nfor i in range 0 4\n    forward 100\n    turn_right 90\n',
    ),
    "star": (
        "Five-Pointed Star",
        'pen_color "gold"\npen_width 2\nfor i in range 0 5\n    forward 150\n    turn_right 144\n',
    ),
    "spiral": (
        "Rainbow Spiral",
        'set colors to ["red", "orange", "gold", "green", "blue", "purple"]\n'
        "pen_width 2\n"
        "for i in range 0 72\n"
        "    pen_color colors[i % 6]\n"
        "    forward i * 3\n"
        "    turn_right 61\n",
    ),
    "tree": (
        "Fractal Tree",
        'function tree size depth\n'
        '    if depth == 0\n'
        '        return 0\n'
        '    forward size\n'
        '    save_pos\n'
        '    turn_left 30\n'
        '    tree size * 0.7 depth - 1\n'
        '    restore_pos\n'
        '    save_pos\n'
        '    turn_right 30\n'
        '    tree size * 0.7 depth - 1\n'
        '    restore_pos\n'
        '    back size\n'
        '\n'
        'goto_xy 400 550\n'
        'pen_color "forestgreen"\n'
        'pen_width 2\n'
        'tree 120 7\n',
    ),
    "snowflake": (
        "Koch Snowflake",
        'function koch len depth\n'
        '    if depth == 0\n'
        '        forward len\n'
        '        return 0\n'
        '    koch len / 3 depth - 1\n'
        '    turn_left 60\n'
        '    koch len / 3 depth - 1\n'
        '    turn_right 120\n'
        '    koch len / 3 depth - 1\n'
        '    turn_left 60\n'
        '    koch len / 3 depth - 1\n'
        '\n'
        'goto_xy 200 200\n'
        'pen_color "steelblue"\n'
        'pen_width 1\n'
        'for i in range 0 3\n'
        '    koch 400 4\n'
        '    turn_right 120\n',
    ),
    "circles": (
        "Concentric Circles",
        'set colors to ["#264653", "#2a9d8f", "#e9c46a", "#f4a261", "#e76f51"]\n'
        'fill_color "none"\n'
        'pen_width 3\n'
        'goto_xy 400 300\n'
        'for i in range 1 11\n'
        '    pen_color colors[i % 5]\n'
        '    circle i * 25\n',
    ),
}


def print_gallery():
    """Print all gallery examples to stdout."""
    print("=== sauravcanvas Gallery ===\n")
    for key, (title, code) in GALLERY.items():
        print(f"--- {title} ({key}) ---")
        print(code)
        print()


# ---------------------------------------------------------------------------
# Interpreter integration
# ---------------------------------------------------------------------------

def inject_canvas_builtins(interpreter, turtle):
    """Add turtle graphics built-in functions to a sauravcode interpreter."""

    def _forward(args):
        turtle.forward(float(args[0]))
        return 0

    def _back(args):
        turtle.back(float(args[0]))
        return 0

    def _turn_right(args):
        turtle.right(float(args[0]))
        return 0

    def _turn_left(args):
        turtle.left(float(args[0]))
        return 0

    def _pen_up(args):
        turtle.set_pen_up()
        return 0

    def _pen_down(args):
        turtle.set_pen_down()
        return 0

    def _pen_color(args):
        turtle.set_color(args[0])
        return 0

    def _pen_width(args):
        turtle.set_width(args[0])
        return 0

    def _fill_color(args):
        turtle.set_fill(args[0])
        return 0

    def _goto_xy(args):
        turtle.goto(args[0], args[1])
        return 0

    def _circle(args):
        turtle.draw_circle(args[0])
        return 0

    def _save_pos(args):
        turtle.save()
        return 0

    def _restore_pos(args):
        turtle.restore()
        return 0

    def _canvas_size(args):
        turtle.canvas_w = int(args[0])
        turtle.canvas_h = int(args[1])
        turtle.x = turtle.canvas_w / 2
        turtle.y = turtle.canvas_h / 2
        return 0

    def _canvas_bg(args):
        turtle.canvas_bg = str(args[0])
        return 0

    canvas_builtins = {
        "forward": _forward,
        "back": _back,
        "turn_right": _turn_right,
        "turn_left": _turn_left,
        "pen_up": _pen_up,
        "pen_down": _pen_down,
        "pen_color": _pen_color,
        "pen_width": _pen_width,
        "fill_color": _fill_color,
        "goto_xy": _goto_xy,
        "circle": _circle,
        "save_pos": _save_pos,
        "restore_pos": _restore_pos,
        "canvas_size": _canvas_size,
        "canvas_bg": _canvas_bg,
    }

    interpreter.builtins.update(canvas_builtins)


def wrap_html(svg_str, title="sauravcanvas"):
    """Wrap SVG in a minimal HTML viewer with zoom controls."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #1a1a2e; display: flex; flex-direction: column;
         align-items: center; justify-content: center; min-height: 100vh;
         font-family: 'Segoe UI', system-ui, sans-serif; color: #e0e0e0; }}
  h1 {{ margin: 1rem 0 0.5rem; font-size: 1.4rem; color: #7fdbca; }}
  .toolbar {{ margin-bottom: 0.75rem; display: flex; gap: 0.5rem; }}
  .toolbar button {{ background: #16213e; border: 1px solid #0f3460;
         color: #e0e0e0; padding: 0.35rem 0.9rem; border-radius: 4px;
         cursor: pointer; font-size: 0.9rem; }}
  .toolbar button:hover {{ background: #0f3460; }}
  .canvas-wrap {{ background: #fff; border-radius: 8px;
         box-shadow: 0 4px 24px rgba(0,0,0,0.4); overflow: hidden;
         transition: transform 0.2s; }}
  .info {{ margin-top: 0.75rem; font-size: 0.8rem; color: #888; }}
</style>
</head>
<body>
<h1>🐢 sauravcanvas</h1>
<div class="toolbar">
  <button onclick="zoom(1.2)">🔍+</button>
  <button onclick="zoom(1/1.2)">🔍−</button>
  <button onclick="resetZoom()">Reset</button>
  <button onclick="downloadSVG()">⬇ SVG</button>
</div>
<div class="canvas-wrap" id="wrap">
{svg_str}
</div>
<div class="info">Generated by sauravcanvas — turtle graphics for sauravcode</div>
<script>
let scale = 1;
const wrap = document.getElementById('wrap');
function zoom(f) {{ scale *= f; wrap.style.transform = 'scale('+scale+')'; }}
function resetZoom() {{ scale = 1; wrap.style.transform = ''; }}
function downloadSVG() {{
  const svg = wrap.querySelector('svg').outerHTML;
  const blob = new Blob([svg], {{type:'image/svg+xml'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'sauravcanvas.svg';
  a.click();
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Turtle graphics for sauravcode — generate SVG from .srv drawing programs"
    )
    parser.add_argument("file", nargs="?", help=".srv file to execute")
    parser.add_argument("-o", "--output", help="output file (default: stdout)")
    parser.add_argument("--html", action="store_true", help="wrap output in HTML viewer")
    parser.add_argument("--gallery", action="store_true", help="print built-in example programs")
    args = parser.parse_args()

    if args.gallery:
        print_gallery()
        return

    if not args.file:
        parser.print_help()
        sys.exit(1)

    if not os.path.isfile(args.file):
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    # Import the sauravcode interpreter
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    try:
        from saurav import Parser, Interpreter
    except ImportError:
        print("Error: cannot import saurav.py — ensure it is in the same directory",
              file=sys.stderr)
        sys.exit(1)

    # Read source
    with open(args.file, "r", encoding="utf-8") as f:
        source = f.read()

    # Parse
    parser_obj = Parser(source)

    # Add canvas function names to BUILTIN_FUNCTIONS so the parser recognizes them
    canvas_names = {
        "forward", "back", "turn_right", "turn_left",
        "pen_up", "pen_down", "pen_color", "pen_width",
        "fill_color", "goto_xy", "circle",
        "save_pos", "restore_pos", "canvas_size", "canvas_bg",
    }
    parser_obj.BUILTIN_FUNCTIONS = parser_obj.BUILTIN_FUNCTIONS | canvas_names
    # Zero-arg builtins
    zero_arg_canvas = {"pen_up", "pen_down", "save_pos", "restore_pos"}
    parser_obj.ZERO_ARG_BUILTINS = parser_obj.ZERO_ARG_BUILTINS | zero_arg_canvas

    ast = parser_obj.parse()

    # Interpret with canvas builtins
    turtle = TurtleState()
    interp = Interpreter()
    # Patch parser builtins on the interpreter's parser reference too
    interp.builtins  # ensure _init_builtins ran
    inject_canvas_builtins(interp, turtle)

    # Run
    try:
        interp.run(ast)
    except Exception as e:
        print(f"Runtime error: {e}", file=sys.stderr)
        sys.exit(1)

    # Output
    svg = turtle.to_svg()
    output = wrap_html(svg) if args.html else svg

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()

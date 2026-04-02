"""Tests for sauravcanvas — turtle graphics SVG generator."""

import math
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sauravcanvas import TurtleState, wrap_html, inject_canvas_builtins, GALLERY, print_gallery


# ---------------------------------------------------------------------------
# TurtleState — initialization
# ---------------------------------------------------------------------------

class TestTurtleStateInit:
    def test_default_position(self):
        t = TurtleState()
        assert t.x == 400.0
        assert t.y == 300.0

    def test_default_heading(self):
        t = TurtleState()
        assert t.heading == -90.0

    def test_default_pen_state(self):
        t = TurtleState()
        assert t.pen_down is True
        assert t.color == "black"
        assert t.width == 2
        assert t.fill == "none"

    def test_default_canvas(self):
        t = TurtleState()
        assert t.canvas_w == 800
        assert t.canvas_h == 600
        assert t.canvas_bg == "white"

    def test_empty_elements(self):
        t = TurtleState()
        assert t.elements == []
        assert t.pos_stack == []
        assert t._current_path == []


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------

class TestForward:
    def test_forward_up(self):
        """Default heading is -90° (up), so forward should decrease y."""
        t = TurtleState()
        t.forward(100)
        assert abs(t.x - 400.0) < 1e-6
        assert abs(t.y - 200.0) < 1e-6

    def test_forward_draws_path(self):
        t = TurtleState()
        t.forward(50)
        assert len(t._current_path) == 2
        assert t._current_path[0] == (400.0, 300.0)

    def test_forward_extends_path(self):
        t = TurtleState()
        t.forward(50)
        t.forward(50)
        assert len(t._current_path) == 3

    def test_forward_pen_up_no_path(self):
        t = TurtleState()
        t.set_pen_up()
        t.forward(100)
        assert t._current_path == []

    def test_forward_zero(self):
        t = TurtleState()
        t.forward(0)
        assert abs(t.x - 400.0) < 1e-6
        assert abs(t.y - 300.0) < 1e-6

    def test_forward_negative(self):
        """Negative forward goes backward."""
        t = TurtleState()
        t.forward(-100)
        assert abs(t.y - 400.0) < 1e-6


class TestBack:
    def test_back_goes_opposite(self):
        t = TurtleState()
        t.back(100)
        assert abs(t.y - 400.0) < 1e-6


# ---------------------------------------------------------------------------
# Turning
# ---------------------------------------------------------------------------

class TestTurning:
    def test_right_90(self):
        t = TurtleState()
        t.right(90)
        assert t.heading == 0.0

    def test_left_90(self):
        t = TurtleState()
        t.left(90)
        expected = (-90.0 - 90.0) % 360
        assert t.heading == expected

    def test_full_rotation(self):
        t = TurtleState()
        for _ in range(4):
            t.right(90)
        assert abs(t.heading - (-90.0 % 360)) < 1e-6

    def test_turn_flushes_path(self):
        t = TurtleState()
        t.forward(50)
        assert len(t._current_path) == 2
        t.right(45)
        # Path should be flushed to elements
        assert t._current_path == []
        assert len(t.elements) == 1

    def test_turn_right_heading_wraps(self):
        t = TurtleState()
        t.right(450)
        assert t.heading == ((-90 + 450) % 360)

    def test_turn_left_heading_wraps(self):
        t = TurtleState()
        t.left(450)
        assert t.heading == ((-90 - 450) % 360)


# ---------------------------------------------------------------------------
# Pen state
# ---------------------------------------------------------------------------

class TestPenState:
    def test_pen_up(self):
        t = TurtleState()
        t.set_pen_up()
        assert t.pen_down is False

    def test_pen_down(self):
        t = TurtleState()
        t.set_pen_up()
        t.set_pen_down()
        assert t.pen_down is True

    def test_set_color(self):
        t = TurtleState()
        t.set_color("red")
        assert t.color == "red"

    def test_set_color_hex(self):
        t = TurtleState()
        t.set_color("#ff0000")
        assert t.color == "#ff0000"

    def test_set_width(self):
        t = TurtleState()
        t.set_width(5)
        assert t.width == 5

    def test_set_width_minimum(self):
        t = TurtleState()
        t.set_width(-1)
        assert t.width == 0.1

    def test_set_width_zero(self):
        t = TurtleState()
        t.set_width(0)
        assert t.width == 0.1

    def test_set_fill(self):
        t = TurtleState()
        t.set_fill("blue")
        assert t.fill == "blue"

    def test_color_change_flushes_path(self):
        t = TurtleState()
        t.forward(50)
        t.set_color("red")
        assert t._current_path == []
        assert len(t.elements) == 1

    def test_width_change_flushes_path(self):
        t = TurtleState()
        t.forward(50)
        t.set_width(5)
        assert t._current_path == []


# ---------------------------------------------------------------------------
# Goto
# ---------------------------------------------------------------------------

class TestGoto:
    def test_goto_with_pen_down(self):
        t = TurtleState()
        t.goto(100, 200)
        assert t.x == 100.0
        assert t.y == 200.0
        assert len(t._current_path) == 2

    def test_goto_pen_up_no_path(self):
        t = TurtleState()
        t.set_pen_up()
        t.goto(100, 200)
        assert t._current_path == []
        assert t.x == 100.0


# ---------------------------------------------------------------------------
# Circle
# ---------------------------------------------------------------------------

class TestCircle:
    def test_draw_circle(self):
        t = TurtleState()
        t.draw_circle(50)
        assert len(t.elements) == 1
        assert 'circle' in t.elements[0]
        assert 'r="50.00"' in t.elements[0]

    def test_circle_negative_radius(self):
        t = TurtleState()
        t.draw_circle(-30)
        assert 'r="30.00"' in t.elements[0]

    def test_circle_uses_fill(self):
        t = TurtleState()
        t.set_fill("red")
        t.draw_circle(10)
        assert 'fill="red"' in t.elements[0]

    def test_circle_uses_stroke(self):
        t = TurtleState()
        t.set_color("green")
        t.draw_circle(10)
        assert 'stroke="green"' in t.elements[0]


# ---------------------------------------------------------------------------
# Position stack
# ---------------------------------------------------------------------------

class TestPositionStack:
    def test_save_restore(self):
        t = TurtleState()
        t.forward(100)
        t.save()
        t.forward(100)
        t.restore()
        assert abs(t.x - 400.0) < 1e-6
        assert abs(t.y - 200.0) < 1e-6

    def test_restore_heading(self):
        t = TurtleState()
        t.right(45)
        t.save()
        t.right(90)
        t.restore()
        assert t.heading == ((-90 + 45) % 360)

    def test_restore_empty_stack(self):
        """Restore with empty stack should be a no-op."""
        t = TurtleState()
        t.forward(50)
        x, y = t.x, t.y
        t.restore()
        assert t.x == x
        assert t.y == y

    def test_nested_save_restore(self):
        t = TurtleState()
        t.save()  # (400, 300, -90)
        t.forward(100)
        t.save()  # (400, 200, -90)
        t.forward(100)
        t.restore()
        assert abs(t.y - 200.0) < 1e-6
        t.restore()
        assert abs(t.y - 300.0) < 1e-6


# ---------------------------------------------------------------------------
# SVG output
# ---------------------------------------------------------------------------

class TestSVGOutput:
    def test_empty_svg(self):
        t = TurtleState()
        svg = t.to_svg()
        assert '<svg' in svg
        assert '</svg>' in svg
        assert 'width="800"' in svg
        assert 'height="600"' in svg

    def test_svg_background(self):
        t = TurtleState()
        t.canvas_bg = "#1a1a2e"
        svg = t.to_svg()
        assert 'fill="#1a1a2e"' in svg

    def test_svg_with_line(self):
        t = TurtleState()
        t.forward(100)
        svg = t.to_svg()
        assert '<polyline' in svg

    def test_svg_with_circle(self):
        t = TurtleState()
        t.draw_circle(50)
        svg = t.to_svg()
        assert '<circle' in svg

    def test_custom_canvas_size(self):
        t = TurtleState()
        t.canvas_w = 1024
        t.canvas_h = 768
        svg = t.to_svg()
        assert 'width="1024"' in svg
        assert 'height="768"' in svg

    def test_to_svg_flushes_current_path(self):
        t = TurtleState()
        t.forward(50)
        assert len(t._current_path) > 0
        t.to_svg()
        assert t._current_path == []

    def test_polyline_attributes(self):
        t = TurtleState()
        t.set_color("blue")
        t.set_width(3)
        t.forward(100)
        svg = t.to_svg()
        assert 'stroke="blue"' in svg
        assert 'stroke-width="3' in svg

    def test_square_draws_four_lines(self):
        t = TurtleState()
        for _ in range(4):
            t.forward(100)
            t.right(90)
        svg = t.to_svg()
        # Each right() flushes the path, so we get 4 polylines
        assert svg.count('<polyline') == 4


# ---------------------------------------------------------------------------
# HTML wrapper
# ---------------------------------------------------------------------------

class TestWrapHtml:
    def test_contains_svg(self):
        html = wrap_html('<svg></svg>')
        assert '<svg></svg>' in html
        assert '<!DOCTYPE html>' in html

    def test_custom_title(self):
        html = wrap_html('<svg></svg>', title="My Drawing")
        assert '<title>My Drawing</title>' in html

    def test_has_zoom_controls(self):
        html = wrap_html('<svg></svg>')
        assert 'zoom' in html.lower()
        assert 'downloadSVG' in html

    def test_default_title(self):
        html = wrap_html('<svg></svg>')
        assert '<title>sauravcanvas</title>' in html


# ---------------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------------

class TestGallery:
    def test_gallery_has_examples(self):
        assert len(GALLERY) >= 5

    def test_gallery_entries_have_title_and_code(self):
        for key, (title, code) in GALLERY.items():
            assert isinstance(title, str) and len(title) > 0
            assert isinstance(code, str) and len(code) > 0

    def test_gallery_keys(self):
        assert "square" in GALLERY
        assert "star" in GALLERY
        assert "spiral" in GALLERY

    def test_print_gallery(self, capsys):
        print_gallery()
        captured = capsys.readouterr()
        assert "Gallery" in captured.out
        assert "Square" in captured.out


# ---------------------------------------------------------------------------
# Canvas size command
# ---------------------------------------------------------------------------

class TestCanvasSize:
    def test_canvas_size_changes_dimensions(self):
        t = TurtleState()
        t.canvas_w = 1024
        t.canvas_h = 768
        assert t.canvas_w == 1024
        assert t.canvas_h == 768

    def test_canvas_bg(self):
        t = TurtleState()
        t.canvas_bg = "#000"
        assert t.canvas_bg == "#000"


# ---------------------------------------------------------------------------
# inject_canvas_builtins
# ---------------------------------------------------------------------------

class TestInjectBuiltins:
    def test_inject_adds_all_commands(self):
        class FakeInterp:
            builtins = {}
        interp = FakeInterp()
        turtle = TurtleState()
        inject_canvas_builtins(interp, turtle)

        expected = {
            "forward", "back", "turn_right", "turn_left",
            "pen_up", "pen_down", "pen_color", "pen_width",
            "fill_color", "goto_xy", "circle",
            "save_pos", "restore_pos", "canvas_size", "canvas_bg",
        }
        assert expected == set(interp.builtins.keys())

    def test_injected_forward_moves_turtle(self):
        class FakeInterp:
            builtins = {}
        interp = FakeInterp()
        turtle = TurtleState()
        inject_canvas_builtins(interp, turtle)
        result = interp.builtins["forward"]([100])
        assert result == 0
        assert abs(turtle.y - 200.0) < 1e-6

    def test_injected_pen_color(self):
        class FakeInterp:
            builtins = {}
        interp = FakeInterp()
        turtle = TurtleState()
        inject_canvas_builtins(interp, turtle)
        interp.builtins["pen_color"](["red"])
        assert turtle.color == "red"

    def test_injected_circle(self):
        class FakeInterp:
            builtins = {}
        interp = FakeInterp()
        turtle = TurtleState()
        inject_canvas_builtins(interp, turtle)
        interp.builtins["circle"]([50])
        assert len(turtle.elements) == 1

    def test_injected_canvas_size(self):
        class FakeInterp:
            builtins = {}
        interp = FakeInterp()
        turtle = TurtleState()
        inject_canvas_builtins(interp, turtle)
        interp.builtins["canvas_size"]([1024, 768])
        assert turtle.canvas_w == 1024
        assert turtle.canvas_h == 768
        # Center position should update
        assert turtle.x == 512.0
        assert turtle.y == 384.0

    def test_injected_canvas_bg(self):
        class FakeInterp:
            builtins = {}
        interp = FakeInterp()
        turtle = TurtleState()
        inject_canvas_builtins(interp, turtle)
        interp.builtins["canvas_bg"](["#000"])
        assert turtle.canvas_bg == "#000"

    def test_injected_save_restore(self):
        class FakeInterp:
            builtins = {}
        interp = FakeInterp()
        turtle = TurtleState()
        inject_canvas_builtins(interp, turtle)
        interp.builtins["save_pos"]([])
        interp.builtins["forward"]([100])
        interp.builtins["restore_pos"]([])
        assert abs(turtle.y - 300.0) < 1e-6

    def test_injected_pen_up_down(self):
        class FakeInterp:
            builtins = {}
        interp = FakeInterp()
        turtle = TurtleState()
        inject_canvas_builtins(interp, turtle)
        interp.builtins["pen_up"]([])
        assert turtle.pen_down is False
        interp.builtins["pen_down"]([])
        assert turtle.pen_down is True

    def test_injected_goto_xy(self):
        class FakeInterp:
            builtins = {}
        interp = FakeInterp()
        turtle = TurtleState()
        inject_canvas_builtins(interp, turtle)
        interp.builtins["goto_xy"]([100, 200])
        assert turtle.x == 100.0
        assert turtle.y == 200.0

    def test_injected_fill_color(self):
        class FakeInterp:
            builtins = {}
        interp = FakeInterp()
        turtle = TurtleState()
        inject_canvas_builtins(interp, turtle)
        interp.builtins["fill_color"](["gold"])
        assert turtle.fill == "gold"

    def test_all_builtins_return_zero(self):
        class FakeInterp:
            builtins = {}
        interp = FakeInterp()
        turtle = TurtleState()
        inject_canvas_builtins(interp, turtle)
        for name, fn in interp.builtins.items():
            if name in ("pen_up", "pen_down", "save_pos", "restore_pos"):
                assert fn([]) == 0
            elif name in ("goto_xy", "canvas_size"):
                assert fn([100, 100]) == 0
            else:
                assert fn([10]) == 0


# ---------------------------------------------------------------------------
# Flush path
# ---------------------------------------------------------------------------

class TestFlushPath:
    def test_flush_single_point_no_element(self):
        t = TurtleState()
        t._current_path = [(0, 0)]
        t._flush_path()
        assert len(t.elements) == 0

    def test_flush_two_points_creates_polyline(self):
        t = TurtleState()
        t._current_path = [(0, 0), (100, 100)]
        t._flush_path()
        assert len(t.elements) == 1
        assert '<polyline' in t.elements[0]

    def test_flush_clears_path(self):
        t = TurtleState()
        t._current_path = [(0, 0), (100, 100)]
        t._flush_path()
        assert t._current_path == []

    def test_flush_empty_no_op(self):
        t = TurtleState()
        t._flush_path()
        assert len(t.elements) == 0


# ---------------------------------------------------------------------------
# Complex drawing scenarios
# ---------------------------------------------------------------------------

class TestComplexDrawing:
    def test_triangle(self):
        t = TurtleState()
        for _ in range(3):
            t.forward(100)
            t.right(120)
        svg = t.to_svg()
        assert svg.count('<polyline') == 3

    def test_pen_up_gap(self):
        """Two separate line segments with a gap."""
        t = TurtleState()
        t.forward(50)
        t.set_pen_up()
        t.forward(50)
        t.set_pen_down()
        t.forward(50)
        svg = t.to_svg()
        assert svg.count('<polyline') == 2

    def test_direction_after_right_turn(self):
        t = TurtleState()
        t.right(90)  # now heading 0 (right)
        t.forward(100)
        assert abs(t.x - 500.0) < 1e-6
        assert abs(t.y - 300.0) < 1e-6

    def test_mixed_circles_and_lines(self):
        t = TurtleState()
        t.forward(50)
        t.draw_circle(30)
        t.forward(50)
        svg = t.to_svg()
        assert '<circle' in svg
        assert '<polyline' in svg

#!/usr/bin/env python3
"""sauravscaffold -- Project scaffolding & template generator for sauravcode.

Quickly create new sauravcode projects from built-in templates or custom ones.

Usage:
    python sauravscaffold.py new myproject                  # basic project
    python sauravscaffold.py new myproject --template cli    # CLI app
    python sauravscaffold.py new myproject --template lib    # library
    python sauravscaffold.py new myproject --template web    # web API
    python sauravscaffold.py new myproject --template game   # text game
    python sauravscaffold.py new myproject --template data   # data pipeline
    python sauravscaffold.py list                            # list templates
    python sauravscaffold.py info cli                        # template details
    python sauravscaffold.py new myapp -d output/            # custom dir
    python sauravscaffold.py new myapp --var author=Alice    # template vars

Templates:
    basic   - Simple starter with main.srv and README
    cli     - Command-line application with arg parsing and help
    lib     - Reusable library with imports, tests, and docs
    web     - REST API server using sauravapi
    game    - Text-based adventure game scaffold
    data    - Data processing pipeline with CSV/JSON I/O
"""

import sys
import os
import json
import time
import re

# ── Template Definitions ───────────────────────────────────────────

TEMPLATES = {
    "basic": {
        "name": "Basic Project",
        "description": "Simple sauravcode starter project with a main file and README.",
        "files": {
            "main.srv": '''\
# {project_name} — Main Entry Point
# Run: python saurav.py main.srv

print "Welcome to {project_name}!"

fn greet name
    print "Hello, " + name + "!"

greet "{author}"
''',
            "README.md": '''\
# {project_name}

A sauravcode project.

## Quick Start

```bash
python saurav.py main.srv
```

## Author

{author}
''',
            ".gitignore": '''\
__pycache__/
*.pyc
*.srvpkg
.saurav_history
''',
        },
        "tags": ["starter", "minimal"],
    },

    "cli": {
        "name": "CLI Application",
        "description": "Command-line application with argument parsing, help display, and subcommands.",
        "files": {
            "main.srv": '''\
# {project_name} — CLI Application
# Run: python saurav.py main.srv

import "cli_utils.srv"

print "{project_name} v0.1.0"
print "A command-line tool built with sauravcode"
print ""

fn show_help
    print "Usage: {project_name} <command> [options]"
    print ""
    print "Commands:"
    print "  greet <name>   Greet someone by name"
    print "  count <n>      Count from 1 to n"
    print "  info           Show project information"
    print "  help           Show this help message"

fn cmd_greet name
    print "Hello, " + name + "! Welcome to {project_name}."

fn cmd_count n
    i = 1
    while i <= n
        print i
        i = i + 1

fn cmd_info
    print "Project: {project_name}"
    print "Author:  {author}"
    print "Version: 0.1.0"
    print "Built with sauravcode"

# Default action
show_help
''',
            "cli_utils.srv": '''\
# CLI utility functions for {project_name}

fn pad_right text width
    result = text
    while len result < width
        result = result + " "
    return result

fn print_table header rows
    print header
    print "---"
    for row in rows
        print row

fn confirm prompt
    print prompt + " [y/n]"
    return true
''',
            "tests/test_cli.srv": '''\
# Tests for {project_name} CLI

import "../cli_utils.srv"

# Test pad_right
result = pad_right "hi" 5
assert len result == 5

# Test basic functions
print "All CLI tests passed!"
''',
            "README.md": '''\
# {project_name}

A command-line application built with sauravcode.

## Usage

```bash
python saurav.py main.srv
```

## Commands

| Command | Description |
|---------|-------------|
| `greet <name>` | Greet someone |
| `count <n>` | Count to n |
| `info` | Project info |
| `help` | Show help |

## Author

{author}
''',
            ".gitignore": '''\
__pycache__/
*.pyc
*.srvpkg
.saurav_history
''',
        },
        "tags": ["cli", "tool", "application"],
    },

    "lib": {
        "name": "Library",
        "description": "Reusable library with importable modules, unit tests, and documentation.",
        "files": {
            "src/lib.srv": '''\
# {project_name} — Core Library
# Import this module in your projects:
#   import "src/lib.srv"

fn {short_name}_add a b
    return a + b

fn {short_name}_multiply a b
    return a * b

fn {short_name}_max a b
    if a > b
        return a
    return b

fn {short_name}_min a b
    if a < b
        return a
    return b

fn {short_name}_clamp value lo hi
    if value < lo
        return lo
    if value > hi
        return hi
    return value

fn {short_name}_abs n
    if n < 0
        return 0 - n
    return n

fn {short_name}_factorial n
    if n <= 1
        return 1
    return n * {short_name}_factorial (n - 1)
''',
            "src/strings.srv": '''\
# {project_name} — String Utilities

fn repeat_str text count
    result = ""
    i = 0
    while i < count
        result = result + text
        i = i + 1
    return result

fn starts_with text prefix
    if len text < len prefix
        return false
    i = 0
    while i < len prefix
        if text[i] != prefix[i]
            return false
        i = i + 1
    return true

fn is_empty text
    return len text == 0
''',
            "tests/test_lib.srv": '''\
# Tests for {project_name} core library

import "../src/lib.srv"

# Test add
assert {short_name}_add 2 3 == 5
assert {short_name}_add -1 1 == 0

# Test multiply
assert {short_name}_multiply 3 4 == 12
assert {short_name}_multiply 0 100 == 0

# Test max/min
assert {short_name}_max 5 3 == 5
assert {short_name}_min 5 3 == 3

# Test clamp
assert {short_name}_clamp 15 0 10 == 10
assert {short_name}_clamp -5 0 10 == 0
assert {short_name}_clamp 5 0 10 == 5

# Test abs
assert {short_name}_abs -7 == 7
assert {short_name}_abs 7 == 7

# Test factorial
assert {short_name}_factorial 5 == 120
assert {short_name}_factorial 0 == 1

print "All library tests passed! (12 assertions)"
''',
            "tests/test_strings.srv": '''\
# Tests for string utilities

import "../src/strings.srv"

# Test repeat_str
assert repeat_str "ab" 3 == "ababab"
assert repeat_str "x" 1 == "x"

# Test is_empty
assert is_empty "" == true
assert is_empty "hello" == false

print "All string tests passed! (4 assertions)"
''',
            "example.srv": '''\
# Example: Using the {project_name} library

import "src/lib.srv"
import "src/strings.srv"

print "Library Demo"
print "============"

result = {short_name}_add 10 20
print "10 + 20 = " + result

fact = {short_name}_factorial 6
print "6! = " + fact

line = repeat_str "=-" 20
print line
''',
            "README.md": '''\
# {project_name}

A reusable sauravcode library.

## Installation

Copy the `src/` directory into your project, then:

```srv
import "src/lib.srv"
import "src/strings.srv"
```

## API

### Core (`src/lib.srv`)
- `{short_name}_add a b` — Addition
- `{short_name}_multiply a b` — Multiplication
- `{short_name}_max a b` / `{short_name}_min a b` — Comparisons
- `{short_name}_clamp value lo hi` — Clamp to range
- `{short_name}_abs n` — Absolute value
- `{short_name}_factorial n` — Factorial

### Strings (`src/strings.srv`)
- `repeat_str text count` — Repeat a string
- `starts_with text prefix` — Check prefix
- `is_empty text` — Check if empty

## Running Tests

```bash
python saurav.py tests/test_lib.srv
python saurav.py tests/test_strings.srv
```

## Author

{author}
''',
            ".gitignore": '''\
__pycache__/
*.pyc
*.srvpkg
.saurav_history
''',
        },
        "tags": ["library", "module", "reusable"],
    },

    "web": {
        "name": "Web API Server",
        "description": "REST API project using sauravapi with routes, models, and sample endpoints.",
        "files": {
            "api.srv": '''\
# {project_name} — Web API
# Run: python sauravapi.py api.srv
# Then visit http://localhost:8000

import "models.srv"
import "handlers.srv"

print "Starting {project_name} API server..."

# Define your data
items = []

fn handle_root
    return "{project_name} API v0.1.0 — Welcome!"

fn handle_status
    return "OK"

fn handle_items
    if len items == 0
        return "No items yet. POST to /items to add one."
    result = ""
    for item in items
        result = result + item + "\\n"
    return result

print "Routes:"
print "  GET  /        — Welcome message"
print "  GET  /status  — Health check"
print "  GET  /items   — List items"
''',
            "models.srv": '''\
# {project_name} — Data Models

fn create_item name category
    return name + " [" + category + "]"

fn validate_item name
    if len name < 1
        return false
    if len name > 100
        return false
    return true
''',
            "handlers.srv": '''\
# {project_name} — Request Handlers

fn format_json key value
    return "{\\"" + key + "\\": \\"" + value + "\\"}"

fn format_error message
    return format_json "error" message

fn format_success message
    return format_json "status" message
''',
            "README.md": '''\
# {project_name}

A REST API built with sauravcode and sauravapi.

## Quick Start

```bash
python sauravapi.py api.srv
```

Then open http://localhost:8000

## Endpoints

- `GET /` — Welcome message
- `GET /status` — Health check
- `GET /items` — List items

## Author

{author}
''',
            ".gitignore": '''\
__pycache__/
*.pyc
*.srvpkg
.saurav_history
''',
        },
        "tags": ["web", "api", "server"],
    },

    "game": {
        "name": "Text Adventure Game",
        "description": "Text-based adventure game with rooms, inventory, and game loop.",
        "files": {
            "game.srv": '''\
# {project_name} — Text Adventure Game
# Run: python saurav.py game.srv

import "world.srv"
import "player.srv"

print "================================"
print "  {project_name}"
print "  A Text Adventure"
print "================================"
print ""

# Game state
current_room = "entrance"
game_over = false
turns = 0

fn describe_room room
    if room == "entrance"
        print "You stand at the entrance of a dark cave."
        print "A faint light glows to the NORTH."
        print "A narrow path leads EAST."
    if room == "cavern"
        print "A vast cavern opens before you."
        print "Crystals shimmer on the walls."
        print "The entrance is to the SOUTH."
        print "A wooden door is to the EAST."
    if room == "passage"
        print "A narrow passage stretches ahead."
        print "You hear water dripping."
        print "The entrance is to the WEST."
        print "Stairs go DOWN."
    if room == "treasure"
        print "A small room filled with golden light!"
        print "A treasure chest sits in the center."
        print "The cavern is to the WEST."
    if room == "underground"
        print "An underground lake stretches before you."
        print "The water is perfectly still."
        print "Stairs go UP."

print "Type commands: go north/south/east/west, look, inventory, quit"
print ""
describe_room current_room

# Simple game loop demo (runs a few turns)
print ""
print "--- Demo Mode ---"
print "Exploring automatically..."
print ""

describe_room "cavern"
print ""
describe_room "treasure"
print ""
print "You found the treasure! Game complete in demo mode."
print "Extend game.srv with a real input loop for full gameplay."
''',
            "world.srv": '''\
# {project_name} — World Definition

# Room connections map
# Format: room -> direction -> destination

fn can_move room direction
    if room == "entrance" and direction == "north"
        return true
    if room == "entrance" and direction == "east"
        return true
    if room == "cavern" and direction == "south"
        return true
    if room == "cavern" and direction == "east"
        return true
    if room == "passage" and direction == "west"
        return true
    if room == "passage" and direction == "down"
        return true
    if room == "treasure" and direction == "west"
        return true
    if room == "underground" and direction == "up"
        return true
    return false

fn get_destination room direction
    if room == "entrance" and direction == "north"
        return "cavern"
    if room == "entrance" and direction == "east"
        return "passage"
    if room == "cavern" and direction == "south"
        return "entrance"
    if room == "cavern" and direction == "east"
        return "treasure"
    if room == "passage" and direction == "west"
        return "entrance"
    if room == "passage" and direction == "down"
        return "underground"
    if room == "treasure" and direction == "west"
        return "cavern"
    if room == "underground" and direction == "up"
        return "passage"
    return room
''',
            "player.srv": '''\
# {project_name} — Player State

inventory = []
health = 100
score = 0

fn add_item item
    append inventory item
    print "Picked up: " + item

fn has_item item
    for i in inventory
        if i == item
            return true
    return false

fn show_inventory
    if len inventory == 0
        print "Your inventory is empty."
    else
        print "Inventory:"
        for item in inventory
            print "  - " + item

fn show_stats
    print "Health: " + health
    print "Score:  " + score
    print "Items:  " + len inventory
''',
            "README.md": '''\
# {project_name}

A text adventure game built with sauravcode.

## Play

```bash
python saurav.py game.srv
```

## Extending

- Edit `world.srv` to add rooms and connections
- Edit `player.srv` to add inventory items and stats
- Edit `game.srv` to add game logic and puzzles

## Author

{author}
''',
            ".gitignore": '''\
__pycache__/
*.pyc
*.srvpkg
.saurav_history
''',
        },
        "tags": ["game", "interactive", "adventure"],
    },

    "data": {
        "name": "Data Pipeline",
        "description": "Data processing pipeline with parsing, transformation, and output stages.",
        "files": {
            "pipeline.srv": '''\
# {project_name} — Data Pipeline
# Run: python saurav.py pipeline.srv

import "transforms.srv"

print "{project_name} Data Pipeline"
print "========================="
print ""

# Sample data
data = [10 25 3 47 12 8 36 19 42 5]
print "Input data: " + data
print "Count: " + len data

# Transform
total = sum_list data
avg = total / len data
print ""
print "Sum: " + total
print "Average: " + avg

# Find extremes
mx = max_list data
mn = min_list data
print "Max: " + mx
print "Min: " + mn
print "Range: " + (mx - mn)

# Filter
big = filter_above data 20
print ""
print "Values above 20: " + big
print "Count above 20: " + len big

# Sort (bubble)
sorted = sort_list data
print "Sorted: " + sorted

print ""
print "Pipeline complete!"
''',
            "transforms.srv": '''\
# {project_name} — Data Transformations

fn sum_list data
    total = 0
    for item in data
        total = total + item
    return total

fn max_list data
    result = data[0]
    for item in data
        if item > result
            result = item
    return result

fn min_list data
    result = data[0]
    for item in data
        if item < result
            result = item
    return result

fn filter_above data threshold
    result = []
    for item in data
        if item > threshold
            append result item
    return result

fn filter_below data threshold
    result = []
    for item in data
        if item < threshold
            append result item
    return result

fn sort_list data
    result = []
    for item in data
        append result item
    n = len result
    i = 0
    while i < n
        j = 0
        while j < n - i - 1
            if result[j] > result[j + 1]
                temp = result[j]
                result[j] = result[j + 1]
                result[j + 1] = temp
            j = j + 1
        i = i + 1
    return result

fn scale_list data factor
    result = []
    for item in data
        append result (item * factor)
    return result

fn normalize data
    mn = min_list data
    mx = max_list data
    rng = mx - mn
    if rng == 0
        return data
    result = []
    for item in data
        append result ((item - mn) / rng)
    return result
''',
            "tests/test_transforms.srv": '''\
# Tests for data transforms

import "../transforms.srv"

data = [5 3 8 1 9 2]

# Test sum
assert sum_list data == 28

# Test max/min
assert max_list data == 9
assert min_list data == 1

# Test filter
big = filter_above data 4
assert len big == 3

small = filter_below data 4
assert len small == 2

# Test sort
sorted = sort_list data
assert sorted[0] == 1
assert sorted[5] == 9

# Test scale
scaled = scale_list [1 2 3] 10
assert scaled[0] == 10
assert scaled[2] == 30

print "All transform tests passed! (10 assertions)"
''',
            "README.md": '''\
# {project_name}

A data processing pipeline built with sauravcode.

## Run

```bash
python saurav.py pipeline.srv
```

## Run Tests

```bash
python saurav.py tests/test_transforms.srv
```

## Transforms Available

- `sum_list` / `max_list` / `min_list`
- `filter_above` / `filter_below`
- `sort_list` — Bubble sort
- `scale_list` — Multiply by factor
- `normalize` — Scale to 0..1

## Author

{author}
''',
            ".gitignore": '''\
__pycache__/
*.pyc
*.srvpkg
.saurav_history
''',
        },
        "tags": ["data", "pipeline", "processing"],
    },
}

# ── Scaffold Engine ────────────────────────────────────────────────

def render_template(text, variables):
    """Replace {variable} placeholders in template text."""
    result = text
    for key, value in variables.items():
        result = result.replace("{" + key + "}", value)
    return result


def create_project(project_name, template_name, output_dir, extra_vars):
    """Create a new project from a template."""
    if template_name not in TEMPLATES:
        print(f"Error: Unknown template '{template_name}'.")
        print(f"Available templates: {', '.join(TEMPLATES.keys())}")
        return False

    template = TEMPLATES[template_name]

    # Build project directory
    project_dir = os.path.join(output_dir, project_name)
    if os.path.exists(project_dir):
        print(f"Error: Directory '{project_dir}' already exists.")
        return False

    # Template variables
    short_name = re.sub(r'[^a-z0-9]', '', project_name.lower())[:8] or "lib"
    variables = {
        "project_name": project_name,
        "short_name": short_name,
        "author": extra_vars.get("author", "developer"),
        "year": str(time.localtime().tm_year),
        "date": time.strftime("%Y-%m-%d"),
    }
    variables.update(extra_vars)

    # Create files
    files_created = 0
    for rel_path, content in template["files"].items():
        full_path = os.path.join(project_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        rendered = render_template(content, variables)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(rendered)
        files_created += 1
        print(f"  ✓ {rel_path}")

    # Create saurav.pkg.json manifest
    manifest = {
        "name": project_name,
        "version": "0.1.0",
        "description": f"{template['name']} created with sauravscaffold",
        "author": variables["author"],
        "template": template_name,
        "created": variables["date"],
        "main": list(template["files"].keys())[0],
        "scripts": {},
        "dependencies": {},
    }
    # Add run script
    main_file = manifest["main"]
    manifest["scripts"]["start"] = f"python saurav.py {main_file}"

    # Add test script if tests exist
    test_files = [f for f in template["files"] if f.startswith("tests/")]
    if test_files:
        manifest["scripts"]["test"] = f"python saurav.py {test_files[0]}"

    manifest_path = os.path.join(project_dir, "saurav.pkg.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    files_created += 1
    print(f"  ✓ saurav.pkg.json")

    print()
    print(f"✨ Created '{project_name}' from '{template_name}' template ({files_created} files)")
    print(f"   cd {project_dir}")
    print(f"   python saurav.py {main_file}")
    return True


def list_templates():
    """List all available templates."""
    print("Available templates:")
    print()
    for key, tmpl in TEMPLATES.items():
        tag_str = ", ".join(tmpl["tags"])
        file_count = len(tmpl["files"])
        print(f"  {key:8s}  {tmpl['name']:25s}  ({file_count} files)  [{tag_str}]")
    print()
    print(f"Usage: python sauravscaffold.py new <project> --template <name>")


def show_info(template_name):
    """Show detailed info about a template."""
    if template_name not in TEMPLATES:
        print(f"Error: Unknown template '{template_name}'.")
        print(f"Available: {', '.join(TEMPLATES.keys())}")
        return

    tmpl = TEMPLATES[template_name]
    print(f"Template: {tmpl['name']}")
    print(f"Key:      {template_name}")
    print(f"Tags:     {', '.join(tmpl['tags'])}")
    print()
    print(f"Description:")
    print(f"  {tmpl['description']}")
    print()
    print(f"Files generated:")
    for rel_path in tmpl["files"]:
        lines = tmpl["files"][rel_path].count("\n") + 1
        print(f"  {rel_path:30s}  ({lines} lines)")
    print(f"  {'saurav.pkg.json':30s}  (auto-generated)")
    print()
    print(f"Variables:")
    print(f"  {{project_name}}  — Project name (from command)")
    print(f"  {{short_name}}    — Short alphanumeric prefix (auto)")
    print(f"  {{author}}        — Author name (--var author=NAME)")
    print(f"  {{year}}          — Current year (auto)")
    print(f"  {{date}}          — Current date (auto)")


def parse_args(argv):
    """Parse command-line arguments."""
    if len(argv) < 2:
        print_usage()
        return None

    command = argv[1]

    if command == "list":
        return {"command": "list"}

    if command == "info":
        if len(argv) < 3:
            print("Usage: python sauravscaffold.py info <template>")
            return None
        return {"command": "info", "template": argv[2]}

    if command == "new":
        if len(argv) < 3:
            print("Usage: python sauravscaffold.py new <project_name> [--template <name>] [--var key=val] [-d dir]")
            return None
        result = {
            "command": "new",
            "project_name": argv[2],
            "template": "basic",
            "output_dir": ".",
            "vars": {},
        }
        i = 3
        while i < len(argv):
            if argv[i] in ("--template", "-t") and i + 1 < len(argv):
                result["template"] = argv[i + 1]
                i += 2
            elif argv[i] in ("--var", "-v") and i + 1 < len(argv):
                if "=" in argv[i + 1]:
                    k, v = argv[i + 1].split("=", 1)
                    result["vars"][k] = v
                i += 2
            elif argv[i] in ("-d", "--dir") and i + 1 < len(argv):
                result["output_dir"] = argv[i + 1]
                i += 2
            else:
                print(f"Unknown option: {argv[i]}")
                return None
        return result

    if command in ("--help", "-h", "help"):
        print_usage()
        return None

    print(f"Unknown command: {command}")
    print_usage()
    return None


def print_usage():
    """Print usage information."""
    print("sauravscaffold — Project scaffolding for sauravcode")
    print()
    print("Usage:")
    print("  python sauravscaffold.py new <name> [--template <t>] [--var k=v] [-d dir]")
    print("  python sauravscaffold.py list")
    print("  python sauravscaffold.py info <template>")
    print()
    print("Templates: basic, cli, lib, web, game, data")
    print()
    print("Examples:")
    print("  python sauravscaffold.py new myapp")
    print("  python sauravscaffold.py new mylib --template lib --var author=Alice")
    print("  python sauravscaffold.py new mygame -t game -d ~/projects")


# ── Tests ──────────────────────────────────────────────────────────

def run_tests():
    """Run self-tests for the scaffold engine."""
    import tempfile
    import shutil

    passed = 0
    failed = 0

    def check(name, condition):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  ✓ {name}")
        else:
            failed += 1
            print(f"  ✗ {name}")

    print("Running sauravscaffold tests...")
    print()

    # Test 1: render_template
    result = render_template("Hello {name}!", {"name": "World"})
    check("render_template basic", result == "Hello World!")

    # Test 2: render multiple vars
    result = render_template("{a} + {b}", {"a": "1", "b": "2"})
    check("render_template multi", result == "1 + 2")

    # Test 3: all templates exist and have required keys
    for key in TEMPLATES:
        tmpl = TEMPLATES[key]
        check(f"template '{key}' has name", "name" in tmpl)
        check(f"template '{key}' has files", len(tmpl["files"]) > 0)
        check(f"template '{key}' has tags", len(tmpl["tags"]) > 0)
        check(f"template '{key}' has description", len(tmpl.get("description", "")) > 0)

    # Test 4: create each template in temp dir
    for tmpl_name in TEMPLATES:
        tmpdir = tempfile.mkdtemp(prefix="sauravscaffold_test_")
        try:
            ok = create_project(f"test_{tmpl_name}", tmpl_name, tmpdir, {"author": "tester"})
            check(f"create '{tmpl_name}' project", ok)

            proj_dir = os.path.join(tmpdir, f"test_{tmpl_name}")
            check(f"'{tmpl_name}' dir exists", os.path.isdir(proj_dir))

            # Check manifest
            manifest_path = os.path.join(proj_dir, "saurav.pkg.json")
            check(f"'{tmpl_name}' has manifest", os.path.isfile(manifest_path))

            if os.path.isfile(manifest_path):
                with open(manifest_path) as f:
                    manifest = json.load(f)
                check(f"'{tmpl_name}' manifest has name", manifest.get("name") == f"test_{tmpl_name}")
                check(f"'{tmpl_name}' manifest has template", manifest.get("template") == tmpl_name)

            # Check all template files exist
            for rel_path in TEMPLATES[tmpl_name]["files"]:
                fp = os.path.join(proj_dir, rel_path)
                check(f"'{tmpl_name}' file {rel_path}", os.path.isfile(fp))

            # Check no unresolved placeholders
            for rel_path in TEMPLATES[tmpl_name]["files"]:
                fp = os.path.join(proj_dir, rel_path)
                if os.path.isfile(fp):
                    with open(fp) as f:
                        content = f.read()
                    has_unresolved = "{project_name}" in content or "{author}" in content
                    check(f"'{tmpl_name}' {rel_path} no unresolved vars", not has_unresolved)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # Test 5: duplicate dir prevention
    tmpdir = tempfile.mkdtemp(prefix="sauravscaffold_test_")
    try:
        create_project("dup_test", "basic", tmpdir, {})
        ok2 = create_project("dup_test", "basic", tmpdir, {})
        check("duplicate project prevented", not ok2)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Test 6: unknown template
    tmpdir = tempfile.mkdtemp(prefix="sauravscaffold_test_")
    try:
        ok = create_project("bad", "nonexistent", tmpdir, {})
        check("unknown template rejected", not ok)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Test 7: parse_args
    args = parse_args(["prog", "new", "myapp", "--template", "cli", "--var", "author=Bob"])
    check("parse_args new", args is not None and args["command"] == "new")
    check("parse_args template", args is not None and args["template"] == "cli")
    check("parse_args var", args is not None and args["vars"].get("author") == "Bob")

    args = parse_args(["prog", "list"])
    check("parse_args list", args is not None and args["command"] == "list")

    args = parse_args(["prog", "info", "game"])
    check("parse_args info", args is not None and args["template"] == "game")

    # Test 8: short_name generation
    # Creating a project with special chars in name
    tmpdir = tempfile.mkdtemp(prefix="sauravscaffold_test_")
    try:
        ok = create_project("my-cool-app", "basic", tmpdir, {"author": "dev"})
        check("project with hyphens", ok)
        manifest_path = os.path.join(tmpdir, "my-cool-app", "saurav.pkg.json")
        if os.path.isfile(manifest_path):
            with open(manifest_path) as f:
                m = json.load(f)
            check("manifest name preserved", m["name"] == "my-cool-app")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    return failed == 0


# ── Main ───────────────────────────────────────────────────────────

def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--test":
        success = run_tests()
        sys.exit(0 if success else 1)

    args = parse_args(sys.argv)
    if args is None:
        sys.exit(1)

    if args["command"] == "list":
        list_templates()
    elif args["command"] == "info":
        show_info(args["template"])
    elif args["command"] == "new":
        ok = create_project(
            args["project_name"],
            args["template"],
            args["output_dir"],
            args["vars"],
        )
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

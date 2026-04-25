#!/usr/bin/env python3
"""sauravquest.py - RPG-style coding quest system for sauravcode.

An interactive adventure where users solve progressively harder sauravcode
programming challenges, earn XP, level up, and unlock achievements.

Usage::

    python sauravquest.py                # Start / resume adventure
    python sauravquest.py --new          # New game
    python sauravquest.py --status       # Character sheet
    python sauravquest.py --achievements # List achievements
    python sauravquest.py --report       # HTML quest log
    python sauravquest.py --leaderboard  # Local scores
"""

import json, os, sys, time, subprocess, textwrap, tempfile, hashlib, math, re
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Terminal colours
# ---------------------------------------------------------------------------
try:
    from _termcolors import *
    _HAS_COLORS = True
except Exception:
    _HAS_COLORS = False

def _c(code, text):
    if not _HAS_COLORS and sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    if _HAS_COLORS:
        return f"\033[{code}m{text}\033[0m"
    return text

def bold(t): return _c("1", t)
def green(t): return _c("32", t)
def red(t): return _c("31", t)
def yellow(t): return _c("33", t)
def cyan(t): return _c("36", t)
def magenta(t): return _c("35", t)
def dim(t): return _c("2", t)

# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------
SAVE_DIR = Path.home() / ".sauravquest"
SAVE_FILE = SAVE_DIR / "save.json"
LEADERBOARD_FILE = SAVE_DIR / "leaderboard.json"

def _default_save():
    return {
        "name": "",
        "char_class": "",
        "xp": 0,
        "level": 1,
        "completed": [],       # list of quest ids
        "failures": {},        # quest_id -> count
        "streak": 0,
        "max_streak": 0,
        "total_time": 0.0,
        "achievements": [],
        "quest_times": {},     # quest_id -> seconds
        "started_at": datetime.now().isoformat(),
        "classes_played": [],
    }

def load_save():
    if SAVE_FILE.exists():
        try:
            return json.loads(SAVE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None

def save_game(data):
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    SAVE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def load_leaderboard():
    if LEADERBOARD_FILE.exists():
        try:
            return json.loads(LEADERBOARD_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

def save_leaderboard(lb):
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    LEADERBOARD_FILE.write_text(json.dumps(lb, indent=2), encoding="utf-8")

# ---------------------------------------------------------------------------
# XP / Leveling
# ---------------------------------------------------------------------------
def xp_for_level(lvl):
    return int(100 * (1.3 ** (lvl - 1)))

def check_level_up(save):
    changed = False
    while save["xp"] >= xp_for_level(save["level"]):
        save["xp"] -= xp_for_level(save["level"])
        save["level"] += 1
        changed = True
        print(bold(yellow(f"\n⭐ LEVEL UP! You are now level {save['level']}!")))
    return changed

# ---------------------------------------------------------------------------
# Character classes
# ---------------------------------------------------------------------------
CLASSES = {
    "warrior": {"desc": "Brute Force - bonus XP for solutions that just work", "bonus_style": "brute"},
    "mage":    {"desc": "Elegant Coder - bonus XP for short, clean solutions", "bonus_style": "elegant"},
    "rogue":   {"desc": "Clever Trickster - bonus XP for creative/unusual approaches", "bonus_style": "clever"},
}

def class_bonus_xp(save, solution_code, base_xp):
    """Return bonus XP based on class and solution style."""
    cls = save.get("char_class", "warrior")
    lines = [l for l in solution_code.strip().split("\n") if l.strip()]
    bonus = 0
    if cls == "mage" and len(lines) <= 3:
        bonus = int(base_xp * 0.25)
    elif cls == "warrior" and len(lines) >= 6:
        bonus = int(base_xp * 0.15)
    elif cls == "rogue":
        # Bonus for using uncommon builtins
        unusual = ["map", "filter", "reduce", "lambda", "comprehension", "zip"]
        if any(u in solution_code.lower() for u in unusual):
            bonus = int(base_xp * 0.20)
    return bonus

# ---------------------------------------------------------------------------
# Quest definitions
# ---------------------------------------------------------------------------
QUESTS = []

def quest(id, chapter, title, story, task, template, expected_output, hints, xp, optimal_lines=None):
    QUESTS.append({
        "id": id, "chapter": chapter, "title": title, "story": story,
        "task": task, "template": template, "expected": expected_output.strip(),
        "hints": hints, "xp": xp, "optimal_lines": optimal_lines,
    })

# Chapter 1: The Awakening
quest("c1q1", 1, "First Words",
      "You awaken in a strange land made of code. A glowing terminal floats before you.\n"
      "To prove you are real, you must speak the ancient greeting...",
      "Write a program that prints exactly: Hello, Adventurer!",
      'print "Hello, Adventurer!"',
      "Hello, Adventurer!",
      ["Use the print statement", 'The syntax is: print "text"'],
      50, optimal_lines=1)

quest("c1q2", 1, "The Number Stone",
      "A stone tablet blocks your path. It demands you perform a calculation.\n"
      "Inscribed: 'What is 42 multiplied by 13, added to 7?'",
      "Print the result of 42 * 13 + 7",
      'print 42 * 13 + 7',
      "553",
      ["Use arithmetic operators", "print can evaluate expressions"],
      60, optimal_lines=1)

quest("c1q3", 1, "The Variable Vault",
      "A vault door has two dials. You must set them correctly.\n"
      "Set x to your lucky number 7, y to 3, and reveal their sum.",
      "Create variables x=7 and y=3, then print their sum.",
      'x = 7\ny = 3\nprint x + y',
      "10",
      ["Assign with: x = 7", "Print the sum with: print x + y"],
      70, optimal_lines=3)

# Chapter 2: The Forest of Logic
quest("c2q1", 2, "The Guardian's Riddle",
      "A forest guardian blocks the path. 'Tell me,' it says,\n"
      "'if 15 is greater than 10, say YES. Otherwise, say NO.'",
      "Use an if statement to print YES if 15 > 10, else print NO.",
      'if 15 > 10\n  print "YES"\nelse\n  print "NO"\nend',
      "YES",
      ["if condition ... end", "Use if 15 > 10"],
      80, optimal_lines=4)

quest("c2q2", 2, "The Counting Trees",
      "The enchanted trees demand you count them.\n"
      "There are exactly 5 trees. Count from 1 to 5, one per line.",
      "Use a loop to print numbers 1 through 5, each on its own line.",
      'i = 1\nwhile i <= 5\n  print i\n  i = i + 1\nend',
      "1\n2\n3\n4\n5",
      ["Use a while loop", "Initialize a counter variable", "Increment inside the loop"],
      90, optimal_lines=5)

quest("c2q3", 2, "The Function Bridge",
      "A magical bridge asks for a password function.\n"
      "'Create a function that doubles a number. Call it with 21.'",
      "Define a function 'double' that returns its argument times 2. Call it with 21 and print the result.",
      'fun double(n)\n  return n * 2\nend\nprint double(21)',
      "42",
      ["Define functions with: fun name(args) ... end", "Use return to send back a value"],
      100, optimal_lines=4)

# Chapter 3: The Data Caverns
quest("c3q1", 3, "The Crystal Array",
      "Deep in the caverns, crystals are arranged in a row.\n"
      "You must list them: ruby, emerald, sapphire.",
      "Create a list with three items: ruby, emerald, sapphire. Print each on its own line.",
      'gems = ["ruby", "emerald", "sapphire"]\nfor g in gems\n  print g\nend',
      "ruby\nemerald\nsapphire",
      ["Lists use square brackets", "Use a for loop to iterate"],
      100, optimal_lines=3)

quest("c3q2", 3, "The Map Chamber",
      "An ancient map chamber has hero stats carved in stone.\n"
      "Record: hp=100, mp=50, attack=25. Report the attack value.",
      "Create a map with hp, mp, attack keys and print the attack value.",
      'hero = {"hp": 100, "mp": 50, "attack": 25}\nprint hero["attack"]',
      "25",
      ["Maps use curly braces", "Access values with map[\"key\"]"],
      110, optimal_lines=2)

quest("c3q3", 3, "The String Puzzle",
      "A locked chest has a string puzzle: reverse the word 'DRAGON'.",
      "Print the reverse of the string 'DRAGON'.",
      'word = "DRAGON"\nrev = ""\ni = len(word) - 1\nwhile i >= 0\n  rev = rev + word[i]\n  i = i - 1\nend\nprint rev',
      "NOGARD",
      ["You can index strings with word[i]", "Build the result character by character", "Use len() to get string length"],
      120, optimal_lines=5)

# Chapter 4: The Tower of Algorithms
quest("c4q1", 4, "The Sorting Hat",
      "The tower's sorting hat demands you sort 5 numbers.\n"
      "Given: 5, 2, 8, 1, 9 - print them sorted ascending, one per line.",
      "Sort the numbers [5, 2, 8, 1, 9] and print each on its own line.",
      'nums = [5, 2, 8, 1, 9]\nn = len(nums)\ni = 0\nwhile i < n\n  j = 0\n  while j < n - 1 - i\n    if nums[j] > nums[j+1]\n      tmp = nums[j]\n      nums[j] = nums[j+1]\n      nums[j+1] = tmp\n    end\n    j = j + 1\n  end\n  i = i + 1\nend\nfor x in nums\n  print x\nend',
      "1\n2\n5\n8\n9",
      ["Use bubble sort: compare adjacent elements", "Swap when left > right", "Repeat until sorted"],
      150, optimal_lines=10)

quest("c4q2", 4, "The Search Spiral",
      "A spiral staircase has 7 steps numbered 10,20,30,40,50,60,70.\n"
      "Find which step holds the value 40. Print its index (0-based).",
      "Search for 40 in the list [10,20,30,40,50,60,70] and print its 0-based index.",
      'steps = [10, 20, 30, 40, 50, 60, 70]\ni = 0\nwhile i < len(steps)\n  if steps[i] == 40\n    print i\n  end\n  i = i + 1\nend',
      "3",
      ["Iterate through the list with an index", "Check each element against 40"],
      130, optimal_lines=6)

quest("c4q3", 4, "The Recursive Dragon",
      "The dragon demands you compute factorial of 6 using recursion.",
      "Write a recursive function to compute factorial(6) and print the result.",
      'fun factorial(n)\n  if n <= 1\n    return 1\n  end\n  return n * factorial(n - 1)\nend\nprint factorial(6)',
      "720",
      ["Base case: factorial(0) = factorial(1) = 1", "Recursive case: n * factorial(n-1)"],
      160, optimal_lines=6)

# Chapter 5: The Final Frontier
quest("c5q1", 5, "The Fibonacci Gate",
      "The final gate opens only with the first 10 Fibonacci numbers.\n"
      "Print them, one per line: 0, 1, 1, 2, 3, 5, 8, 13, 21, 34.",
      "Print the first 10 Fibonacci numbers, each on its own line.",
      'a = 0\nb = 1\ni = 0\nwhile i < 10\n  print a\n  tmp = a + b\n  a = b\n  b = tmp\n  i = i + 1\nend',
      "0\n1\n1\n2\n3\n5\n8\n13\n21\n34",
      ["Start with a=0, b=1", "Each step: next = a + b, then shift"],
      170, optimal_lines=8)

quest("c5q2", 5, "The Prime Fortress",
      "The fortress requires all prime numbers up to 20 as a password.\n"
      "Print each prime on its own line.",
      "Print all prime numbers from 2 to 20, each on its own line.",
      'n = 2\nwhile n <= 20\n  is_prime = 1\n  d = 2\n  while d * d <= n\n    if n % d == 0\n      is_prime = 0\n    end\n    d = d + 1\n  end\n  if is_prime == 1\n    print n\n  end\n  n = n + 1\nend',
      "2\n3\n5\n7\n11\n13\n17\n19",
      ["Check divisibility from 2 to sqrt(n)", "If no divisors found, it's prime"],
      180, optimal_lines=10)

quest("c5q3", 5, "The Final Boss",
      "The Dark Compiler challenges you to a final test!\n"
      "'Create a program that computes the sum of squares from 1 to 10\n"
      "and print the result. Prove your mastery!'",
      "Compute and print the sum of 1² + 2² + 3² + ... + 10².",
      'total = 0\ni = 1\nwhile i <= 10\n  total = total + i * i\n  i = i + 1\nend\nprint total',
      "385",
      ["Sum of i*i for i from 1 to 10", "Use an accumulator variable"],
      200, optimal_lines=5)

CHAPTERS = {
    1: {"name": "The Awakening", "desc": "Basic syntax: variables, print, arithmetic"},
    2: {"name": "The Forest of Logic", "desc": "Conditionals, loops, functions"},
    3: {"name": "The Data Caverns", "desc": "Lists, maps, strings"},
    4: {"name": "The Tower of Algorithms", "desc": "Sorting, searching, recursion"},
    5: {"name": "The Final Frontier", "desc": "Advanced: Fibonacci, primes, complex programs"},
}

# ---------------------------------------------------------------------------
# Achievements
# ---------------------------------------------------------------------------
ACHIEVEMENT_DEFS = {
    "first_blood":    ("🗡️  First Blood",       "Complete your first quest"),
    "speed_demon":    ("⚡ Speed Demon",         "Complete a quest in under 60 seconds"),
    "perfect_streak": ("🔥 Perfect Streak",      "5 quests in a row without failures"),
    "chapter_master": ("📖 Chapter Master",      "Complete all quests in a chapter"),
    "legendary":      ("👑 Legendary",           "Complete all 15 quests"),
    "overachiever":   ("🏆 Overachiever",        "Reach level 15"),
    "perfectionist":  ("💎 Perfectionist",       "Complete all quests with optimal solutions"),
    "explorer":       ("🧭 Explorer",            "Play all 3 character classes"),
    "persistent":     ("🪨  Persistent",          "Fail 10 times but keep going"),
    "speedrunner":    ("🏃 Speedrunner",         "Complete all quests in under 30 minutes total"),
}

def check_achievements(save):
    new = []
    a = save["achievements"]
    completed = set(save["completed"])
    total_failures = sum(save.get("failures", {}).values())

    checks = {
        "first_blood": len(completed) >= 1,
        "speed_demon": any(t < 60 for t in save.get("quest_times", {}).values()),
        "perfect_streak": save.get("max_streak", 0) >= 5,
        "chapter_master": any(
            all(q["id"] in completed for q in QUESTS if q["chapter"] == ch)
            for ch in CHAPTERS
        ),
        "legendary": len(completed) == len(QUESTS),
        "overachiever": save["level"] >= 15,
        "persistent": total_failures >= 10,
        "speedrunner": (
            len(completed) == len(QUESTS) and
            save.get("total_time", 9999) < 1800
        ),
        "explorer": len(save.get("classes_played", [])) >= 3,
    }

    # Perfectionist: all quests done with <= optimal_lines
    all_optimal = True
    for q in QUESTS:
        if q["id"] not in completed:
            all_optimal = False
            break
    checks["perfectionist"] = all_optimal  # simplified - we track completion

    for key, cond in checks.items():
        if cond and key not in a:
            a.append(key)
            new.append(key)

    return new

def print_achievement(key):
    name, desc = ACHIEVEMENT_DEFS.get(key, ("?", "?"))
    print(bold(yellow(f"\n🎖️  ACHIEVEMENT UNLOCKED: {name}")))
    print(f"   {desc}\n")

# ---------------------------------------------------------------------------
# Difficulty scaling
# ---------------------------------------------------------------------------
def get_difficulty_multiplier(save):
    """Adaptive difficulty based on success rate."""
    completed = len(save["completed"])
    total_failures = sum(save.get("failures", {}).values())
    total_attempts = completed + total_failures
    if total_attempts < 3:
        return 1.0
    success_rate = completed / total_attempts
    if success_rate > 0.8:
        return 1.2  # harder = more XP
    elif success_rate < 0.4:
        return 0.8  # easier = less XP but more hints
    return 1.0

# ---------------------------------------------------------------------------
# Judge: run .srv solution
# ---------------------------------------------------------------------------
def run_srv(code):
    """Run sauravcode source and return (stdout, stderr, returncode)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    interpreter = os.path.join(script_dir, "saurav.py")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".srv", delete=False, encoding="utf-8") as f:
        f.write(code)
        f.flush()
        tmp = f.name
    try:
        result = subprocess.run(
            [sys.executable, interpreter, tmp],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT: program took too long", 1
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

# ---------------------------------------------------------------------------
# Interactive quest runner
# ---------------------------------------------------------------------------
def run_quest(quest_def, save):
    qid = quest_def["id"]
    ch = CHAPTERS[quest_def["chapter"]]

    print("\n" + bold(cyan("=" * 60)))
    print(bold(cyan(f"  Chapter {quest_def['chapter']}: {ch['name']}")))
    print(bold(cyan(f"  Quest: {quest_def['title']}")))
    print(bold(cyan("=" * 60)))
    print()
    for line in quest_def["story"].split("\n"):
        print(f"  {dim(line)}")
    print()
    print(bold(f"📋 Task: {quest_def['task']}"))
    print()
    print(dim("  Tip: Write your solution and press Enter twice (empty line) to submit."))
    print(dim("  Type 'hint' for a hint, 'skip' to skip, 'quit' to save & exit."))
    print()

    attempts = 0
    hint_idx = 0
    start_time = time.time()

    while True:
        print(bold("Your solution:"))
        lines = []
        try:
            while True:
                line = input("  ")
                if line.strip().lower() == "quit":
                    return "quit"
                if line.strip().lower() == "skip":
                    print(yellow("\n⏭️  Quest skipped.\n"))
                    return "skip"
                if line.strip().lower() == "hint":
                    if hint_idx < len(quest_def["hints"]):
                        print(yellow(f"  💡 Hint: {quest_def['hints'][hint_idx]}"))
                        hint_idx += 1
                    else:
                        print(dim("  No more hints available."))
                    continue
                if line == "" and lines and lines[-1] == "":
                    lines.pop()
                    break
                lines.append(line)
        except EOFError:
            return "quit"
        except KeyboardInterrupt:
            print()
            return "quit"

        code = "\n".join(lines)
        if not code.strip():
            print(red("  Empty solution. Try again.\n"))
            continue

        attempts += 1
        stdout, stderr, rc = run_srv(code)

        if stdout == quest_def["expected"]:
            elapsed = time.time() - start_time
            base_xp = quest_def["xp"]
            mult = get_difficulty_multiplier(save)
            bonus = class_bonus_xp(save, code, base_xp)
            total_xp = int(base_xp * mult) + bonus

            print(bold(green(f"\n✅ QUEST COMPLETE: {quest_def['title']}")))
            print(green(f"   +{total_xp} XP (base {base_xp}, multiplier {mult:.1f}, class bonus {bonus})"))
            print(green(f"   Time: {elapsed:.1f}s"))

            save["xp"] += total_xp
            if qid not in save["completed"]:
                save["completed"].append(qid)
            save["quest_times"][qid] = elapsed
            save["total_time"] = save.get("total_time", 0) + elapsed
            save["streak"] = save.get("streak", 0) + 1
            save["max_streak"] = max(save.get("max_streak", 0), save["streak"])

            check_level_up(save)
            for ach in check_achievements(save):
                print_achievement(ach)

            save_game(save)
            return "done"
        else:
            save["failures"][qid] = save.get("failures", {}).get(qid, 0) + 1
            save["streak"] = 0
            print(red(f"\n❌ Incorrect output."))
            print(f"   Expected: {cyan(quest_def['expected'][:80])}")
            print(f"   Got:      {red(stdout[:80] if stdout else '(no output)')}")
            if stderr:
                print(f"   Error:    {red(stderr[:120])}")
            print()

            fail_count = save["failures"].get(qid, 0)
            if fail_count >= 5:
                print(yellow("  🤖 The oracle whispers: study the template solution pattern..."))
                print(dim(f"  Template:\n"))
                for tl in quest_def["template"].split("\n"):
                    print(dim(f"    {tl}"))
                print()
            elif fail_count >= 2 and hint_idx < len(quest_def["hints"]):
                print(yellow(f"  💡 Auto-hint: {quest_def['hints'][hint_idx]}"))
                hint_idx += 1

            check_achievements(save)
            save_game(save)

# ---------------------------------------------------------------------------
# Game flow
# ---------------------------------------------------------------------------
def new_game():
    print(bold(magenta("\n" + "=" * 60)))
    print(bold(magenta("  ⚔️  SAURAVQUEST - A Coding Adventure  ⚔️")))
    print(bold(magenta("=" * 60)))
    print()
    name = input("  Enter your hero name: ").strip() or "Hero"
    print()
    print(bold("  Choose your class:"))
    for key, val in CLASSES.items():
        print(f"    {bold(key.capitalize()):20s} - {val['desc']}")
    print()
    while True:
        cls = input("  Class (warrior/mage/rogue): ").strip().lower()
        if cls in CLASSES:
            break
        print(red("  Invalid class. Choose warrior, mage, or rogue."))

    save = _default_save()
    save["name"] = name
    save["char_class"] = cls
    save["classes_played"] = [cls]
    save_game(save)
    print(green(f"\n  Welcome, {name} the {cls.capitalize()}! Your quest begins...\n"))
    return save

def play(save):
    completed = set(save["completed"])
    for q in QUESTS:
        if q["id"] not in completed:
            result = run_quest(q, save)
            if result == "quit":
                print(dim("\n  Progress saved. See you next time, adventurer!\n"))
                return
            if result == "skip":
                continue
            # After completing, offer to continue
            ans = input("  Continue to next quest? (y/n): ").strip().lower()
            if ans != "y" and ans != "yes" and ans != "":
                print(dim("\n  Progress saved. See you next time!\n"))
                return

    print(bold(yellow("\n🎉 All quests completed! You are a Sauravcode Legend! 🎉\n")))

# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------
def show_status(save):
    print(bold(cyan("\n  ═══ CHARACTER SHEET ═══")))
    print(f"  Name:   {bold(save['name'])}")
    print(f"  Class:  {bold(save['char_class'].capitalize())}")
    print(f"  Level:  {bold(str(save['level']))}")
    xp_needed = xp_for_level(save["level"])
    bar_len = 20
    filled = min(bar_len, int(bar_len * save["xp"] / max(1, xp_needed)))
    bar = green("█" * filled) + dim("░" * (bar_len - filled))
    print(f"  XP:     [{bar}] {save['xp']}/{xp_needed}")
    print(f"  Quests: {len(save['completed'])}/{len(QUESTS)}")
    print(f"  Streak: {save.get('streak', 0)} (best: {save.get('max_streak', 0)})")
    print(f"  Time:   {save.get('total_time', 0):.0f}s total")
    print()

def show_achievements(save):
    print(bold(yellow("\n  ═══ ACHIEVEMENTS ═══")))
    for key, (name, desc) in ACHIEVEMENT_DEFS.items():
        status = green("✅") if key in save["achievements"] else dim("🔒")
        print(f"  {status} {name:25s} - {desc}")
    print()

def show_leaderboard():
    lb = load_leaderboard()
    print(bold(cyan("\n  ═══ LEADERBOARD ═══")))
    if not lb:
        print(dim("  No entries yet. Complete quests to get on the board!\n"))
        return
    for i, entry in enumerate(lb[:10], 1):
        print(f"  {i:2d}. {entry['name']:15s} Lvl {entry['level']:2d}  {entry['quests']}/{len(QUESTS)} quests  {entry['time']:.0f}s")
    print()

def update_leaderboard(save):
    lb = load_leaderboard()
    entry = {
        "name": save["name"],
        "level": save["level"],
        "quests": len(save["completed"]),
        "time": save.get("total_time", 0),
        "date": datetime.now().isoformat(),
    }
    # Update or append
    lb = [e for e in lb if e["name"] != save["name"]]
    lb.append(entry)
    lb.sort(key=lambda e: (-e["quests"], -e["level"], e["time"]))
    save_leaderboard(lb)

# ---------------------------------------------------------------------------
# HTML Report
# ---------------------------------------------------------------------------
def generate_report(save):
    completed = set(save["completed"])
    pct = len(completed) / len(QUESTS) * 100 if QUESTS else 0
    ch_rows = ""
    for ch_num, ch_info in CHAPTERS.items():
        ch_quests = [q for q in QUESTS if q["chapter"] == ch_num]
        ch_done = sum(1 for q in ch_quests if q["id"] in completed)
        status = "✅" if ch_done == len(ch_quests) else f"{ch_done}/{len(ch_quests)}"
        quest_list = ""
        for q in ch_quests:
            qstatus = "✅" if q["id"] in completed else "⬜"
            t = save.get("quest_times", {}).get(q["id"], None)
            time_str = f"{t:.1f}s" if t else "-"
            quest_list += f"<tr><td>{qstatus}</td><td>{q['title']}</td><td>{q['xp']} XP</td><td>{time_str}</td></tr>"
        ch_rows += f"""
        <tr class="chapter-row"><td colspan="4"><strong>Chapter {ch_num}: {ch_info['name']}</strong> — {status}</td></tr>
        {quest_list}"""

    ach_rows = ""
    for key, (name, desc) in ACHIEVEMENT_DEFS.items():
        s = "✅" if key in save["achievements"] else "🔒"
        ach_rows += f"<tr><td>{s}</td><td>{name}</td><td>{desc}</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>SauravQuest Report</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; max-width: 800px; margin: 2em auto; background: #1a1a2e; color: #e0e0e0; padding: 1em; }}
h1 {{ color: #e94560; text-align: center; }}
h2 {{ color: #0f3460; background: #16213e; padding: 0.5em; border-radius: 6px; }}
table {{ width: 100%; border-collapse: collapse; margin: 1em 0; }}
td, th {{ padding: 8px 12px; border-bottom: 1px solid #333; }}
.chapter-row {{ background: #16213e; }}
.progress-bar {{ background: #333; border-radius: 10px; overflow: hidden; height: 24px; }}
.progress-fill {{ background: linear-gradient(90deg, #e94560, #0f3460); height: 100%; border-radius: 10px; transition: width 0.3s; }}
.stat {{ display: inline-block; background: #16213e; padding: 1em; margin: 0.5em; border-radius: 8px; min-width: 120px; text-align: center; }}
.stat-value {{ font-size: 2em; font-weight: bold; color: #e94560; }}
</style></head><body>
<h1>⚔️ SauravQuest — Adventure Log</h1>
<div style="text-align:center;">
  <div class="stat"><div class="stat-value">{save['name']}</div><div>Hero</div></div>
  <div class="stat"><div class="stat-value">{save['char_class'].capitalize()}</div><div>Class</div></div>
  <div class="stat"><div class="stat-value">{save['level']}</div><div>Level</div></div>
  <div class="stat"><div class="stat-value">{len(completed)}/{len(QUESTS)}</div><div>Quests</div></div>
</div>
<h2>Progress</h2>
<div class="progress-bar"><div class="progress-fill" style="width:{pct:.0f}%"></div></div>
<p>{pct:.0f}% complete — {save.get('total_time',0):.0f}s total play time</p>
<h2>Quest Log</h2>
<table>{ch_rows}</table>
<h2>Achievements</h2>
<table>{ach_rows}</table>
<p style="text-align:center;color:#666;margin-top:2em;">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</body></html>"""
    out = Path("sauravquest_report.html")
    out.write_text(html, encoding="utf-8")
    print(green(f"\n  📊 Report saved to {out.resolve()}\n"))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = sys.argv[1:]

    if "--leaderboard" in args:
        show_leaderboard()
        return

    save = load_save()

    if "--new" in args or save is None:
        save = new_game()

    if save is None:
        print(red("No save file. Run with --new to start.\n"))
        return

    if "--status" in args:
        show_status(save)
        return

    if "--achievements" in args:
        show_achievements(save)
        return

    if "--report" in args:
        generate_report(save)
        return

    # Normal play
    show_status(save)
    play(save)
    update_leaderboard(save)
    save_game(save)


if __name__ == "__main__":
    main()

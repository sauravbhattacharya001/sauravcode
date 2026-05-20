#!/usr/bin/env python3
"""sauravver — Version & release management for sauravcode (.srv) projects.

Manages semantic versioning, generates changelogs from git commits,
creates release tags, validates version strings, and tracks release history.

Usage:
    python sauravver.py show                          # show current version
    python sauravver.py bump major|minor|patch        # bump version
    python sauravver.py bump prerelease [--pre alpha]  # bump prerelease
    python sauravver.py set 2.5.0                     # set explicit version
    python sauravver.py validate 1.2.3-beta.1         # validate semver
    python sauravver.py changelog                     # generate changelog from git
    python sauravver.py changelog --from v1.0 --to v2.0  # range changelog
    python sauravver.py changelog --format md|json|text  # output format
    python sauravver.py tag                           # create git tag for current version
    python sauravver.py tag --sign                    # signed tag
    python sauravver.py history                       # show version history from tags
    python sauravver.py compare 1.0.0 2.0.0           # compare two versions
    python sauravver.py next                          # suggest next version from commits
    python sauravver.py --json                        # JSON output for any command
    python sauravver.py --file VERSION                # use VERSION file instead of pyproject.toml
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple

__version__ = "1.0.0"

# ─── Semver parsing ──────────────────────────────────────────────

SEMVER_RE = re.compile(
    r'^v?(?P<major>0|[1-9]\d*)'
    r'\.(?P<minor>0|[1-9]\d*)'
    r'\.(?P<patch>0|[1-9]\d*)'
    r'(?:-(?P<pre>[0-9A-Za-z\-.]+))?'
    r'(?:\+(?P<build>[0-9A-Za-z\-.]+))?$'
)


@dataclass
class SemVer:
    """Parsed semantic-version value object.

    Holds the five SemVer 2.0.0 components (``major``, ``minor``, ``patch``,
    optional ``pre`` and ``build``) and provides comparison + bump helpers.

    Pre-release versions are ordered *below* the same MAJOR.MINOR.PATCH without
    a pre-release, per SemVer §11. The ``build`` metadata field is preserved
    in string form but ignored for ordering (per SemVer §10).
    """

    major: int
    minor: int
    patch: int
    pre: Optional[str] = None
    build: Optional[str] = None

    @classmethod
    def parse(cls, s: str) -> 'SemVer':
        """Parse a SemVer string (with optional leading ``v``) into a :class:`SemVer`.

        Args:
            s: Version string, e.g. ``"1.2.3"``, ``"v2.0.0-beta.1"``,
               ``"1.0.0+build.42"``. Leading/trailing whitespace is stripped.

        Returns:
            A new :class:`SemVer` instance.

        Raises:
            ValueError: If ``s`` does not match the SemVer 2.0.0 grammar.
        """
        m = SEMVER_RE.match(s.strip())
        if not m:
            raise ValueError(f"Invalid semver: {s}")
        return cls(
            major=int(m.group('major')),
            minor=int(m.group('minor')),
            patch=int(m.group('patch')),
            pre=m.group('pre'),
            build=m.group('build'),
        )

    def __str__(self):
        """Render the canonical SemVer string (no leading ``v``)."""
        s = f"{self.major}.{self.minor}.{self.patch}"
        if self.pre:
            s += f"-{self.pre}"
        if self.build:
            s += f"+{self.build}"
        return s

    def tuple(self):
        """Return ``(major, minor, patch, pre)`` for ad-hoc tuple comparisons.

        Note:
            This helper is **not** SemVer-correct for ordering pre-releases vs
            releases — use the rich-comparison operators for that. It is kept
            for callers that just need a hashable key.
        """
        return (self.major, self.minor, self.patch, self.pre or "")

    def __lt__(self, other):
        """SemVer §11 less-than comparison.

        A version *with* a pre-release is considered lower than the same
        MAJOR.MINOR.PATCH *without* a pre-release.
        """
        # Pre-release has lower precedence than release
        a = (self.major, self.minor, self.patch, 0 if self.pre is None else 1, self.pre or "")
        b = (other.major, other.minor, other.patch, 0 if other.pre is None else 1, other.pre or "")
        # No pre = higher than with pre for same version
        a_key = (self.major, self.minor, self.patch, 1 if self.pre is None else 0, self.pre or "")
        b_key = (other.major, other.minor, other.patch, 1 if other.pre is None else 0, other.pre or "")
        return a_key < b_key

    def __eq__(self, other):
        """Equality ignoring ``build`` metadata (per SemVer §10)."""
        return (self.major, self.minor, self.patch, self.pre) == (other.major, other.minor, other.patch, other.pre)

    def __le__(self, other):
        """``<=`` defined in terms of :meth:`__eq__` and :meth:`__lt__`."""
        return self == other or self < other

    def __gt__(self, other):
        """``>`` is the negation of :meth:`__le__`."""
        return not self <= other

    def __ge__(self, other):
        """``>=`` is the negation of :meth:`__lt__`."""
        return not self < other

    def bump(self, kind: str, pre_tag: str = "alpha") -> 'SemVer':
        """Return a new :class:`SemVer` advanced by ``kind``.

        Args:
            kind: One of ``"major"``, ``"minor"``, ``"patch"`` (resets lower
                components to ``0`` and drops any pre-release/build), or
                ``"prerelease"`` (increments the trailing numeric segment of
                the existing pre-release, or starts ``<patch+1>-<pre_tag>.0``
                on a release version).
            pre_tag: Identifier used when promoting a release into its first
                pre-release. Ignored when an existing pre-release is being
                incremented.

        Returns:
            A brand-new :class:`SemVer`; ``self`` is never mutated.

        Raises:
            ValueError: If ``kind`` is not one of the recognised values.
        """
        if kind == "major":
            return SemVer(self.major + 1, 0, 0)
        elif kind == "minor":
            return SemVer(self.major, self.minor + 1, 0)
        elif kind == "patch":
            return SemVer(self.major, self.minor, self.patch + 1)
        elif kind == "prerelease":
            if self.pre:
                # Increment numeric suffix
                parts = self.pre.split(".")
                if parts[-1].isdigit():
                    parts[-1] = str(int(parts[-1]) + 1)
                else:
                    parts.append("1")
                return SemVer(self.major, self.minor, self.patch, ".".join(parts))
            else:
                return SemVer(self.major, self.minor, self.patch + 1, f"{pre_tag}.0")
        else:
            raise ValueError(f"Unknown bump kind: {kind}")


# ─── Conventional Commit parsing ──────────────────────────────────

CONVENTIONAL_RE = re.compile(
    r'^(?P<type>feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)'
    r'(?:\((?P<scope>[^)]+)\))?'
    r'(?P<breaking>!)?'
    r':\s*(?P<desc>.+)$',
    re.IGNORECASE
)

COMMIT_CATEGORIES = {
    "feat":     "✨ Features",
    "fix":      "🐛 Bug Fixes",
    "docs":     "📖 Documentation",
    "style":    "💅 Style",
    "refactor": "♻️ Refactoring",
    "perf":     "⚡ Performance",
    "test":     "🧪 Tests",
    "build":    "📦 Build",
    "ci":       "🔄 CI",
    "chore":    "🔧 Chores",
    "revert":   "⏪ Reverts",
}


@dataclass
class Commit:
    """A parsed git commit, classified by Conventional Commits 1.0.0.

    Commits whose subject does not match the Conventional Commits grammar
    are still represented here with ``type == "other"`` so they can be shown
    in a generic "Other" changelog section rather than dropped silently.
    """

    hash: str
    short_hash: str
    type: str
    scope: Optional[str]
    description: str
    body: str
    breaking: bool
    author: str
    date: str
    raw_message: str

    @classmethod
    def from_git_line(cls, hash: str, message: str, author: str = "", date: str = "") -> 'Commit':
        """Build a :class:`Commit` from raw ``git log`` fields.

        Args:
            hash: Full commit SHA. May be empty for synthetic commits.
            message: First (subject) line of the commit message.
            author: Author name (``%an``); optional, defaults to empty.
            date: Author date in ISO-8601 (``%aI``); optional.

        Returns:
            A populated :class:`Commit`. If ``message`` does not match the
            Conventional Commits subject grammar, ``type`` is set to
            ``"other"`` and the original message is kept verbatim as the
            description.
        """
        short = hash[:7] if hash else ""
        m = CONVENTIONAL_RE.match(message.strip())
        if m:
            return cls(
                hash=hash, short_hash=short,
                type=m.group('type').lower(),
                scope=m.group('scope'),
                description=m.group('desc').strip(),
                body="", breaking=bool(m.group('breaking')),
                author=author, date=date, raw_message=message.strip()
            )
        else:
            return cls(
                hash=hash, short_hash=short,
                type="other", scope=None,
                description=message.strip(),
                body="", breaking=False,
                author=author, date=date, raw_message=message.strip()
            )


# ─── Git helpers ──────────────────────────────────────────────────

def run_git(args: List[str], cwd: Optional[str] = None) -> Tuple[int, str]:
    """Run ``git <args>`` and return ``(returncode, stdout_stripped)``.

    Captures stdout/stderr, uses a 30-second timeout, and converts
    ``FileNotFoundError`` / ``TimeoutExpired`` into a non-zero return code so
    callers can stay on the happy path with a simple ``rc != 0`` guard.

    Args:
        args: Arguments after ``git`` (e.g. ``["tag", "--sort=-v:refname"]``).
        cwd: Optional working directory; ``None`` uses the current directory.

    Returns:
        ``(returncode, stdout)`` — ``stdout`` is stripped of surrounding
        whitespace. ``returncode`` is ``1`` (and ``stdout`` is empty) when
        git is missing or the call timed out.
    """
    try:
        r = subprocess.run(
            ["git"] + args, capture_output=True, text=True,
            cwd=cwd, timeout=30
        )
        return r.returncode, r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 1, ""


def get_git_tags(cwd=None) -> List[str]:
    """Return all git tags in descending SemVer order.

    Args:
        cwd: Repository directory; ``None`` uses the current directory.

    Returns:
        Tag names (newest first by ``v:refname`` sort), or an empty list if
        the repo has no tags or git is unavailable.
    """
    rc, out = run_git(["tag", "--sort=-v:refname"], cwd)
    if rc != 0 or not out:
        return []
    return [t.strip() for t in out.split("\n") if t.strip()]


def get_commits(from_ref=None, to_ref="HEAD", cwd=None) -> List[Commit]:
    """Return :class:`Commit` objects for ``from_ref..to_ref`` (merges excluded).

    Args:
        from_ref: Inclusive-exclusive lower bound (any git rev). ``None``
            means "all reachable commits up to ``to_ref``".
        to_ref: Upper bound, defaults to ``HEAD``.
        cwd: Repository directory; ``None`` uses the current directory.

    Returns:
        Newest-first list of parsed commits. Returns ``[]`` if the range is
        empty, the refs are unknown, or git is unavailable.
    """
    fmt = "%H|%s|%an|%aI"
    if from_ref:
        range_spec = f"{from_ref}..{to_ref}"
    else:
        range_spec = to_ref
    rc, out = run_git(["log", range_spec, f"--format={fmt}", "--no-merges"], cwd)
    if rc != 0 or not out:
        return []
    commits = []
    for line in out.split("\n"):
        parts = line.split("|", 3)
        if len(parts) >= 4:
            commits.append(Commit.from_git_line(parts[0], parts[1], parts[2], parts[3]))
        elif len(parts) >= 2:
            commits.append(Commit.from_git_line(parts[0], parts[1]))
    return commits


# ─── Version file detection ──────────────────────────────────────

VERSION_FILE_PATTERNS = [
    ("pyproject.toml", r'version\s*=\s*"([^"]+)"', 'version = "{}"'),
    ("setup.py", r'version\s*=\s*["\']([^"\']+)["\']', 'version="{}"'),
    ("setup.cfg", r'version\s*=\s*(.+)', 'version = {}'),
    ("VERSION", r'^(.+)$', '{}'),
    ("version.txt", r'^(.+)$', '{}'),
    ("package.json", r'"version"\s*:\s*"([^"]+)"', '"version": "{}"'),
]


def find_version_file(project_dir: str, explicit: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """Returns (filepath, current_version) or None."""
    if explicit:
        fp = os.path.join(project_dir, explicit)
        if os.path.exists(fp):
            content = open(fp).read()
            if explicit.endswith(".json"):
                m = re.search(r'"version"\s*:\s*"([^"]+)"', content)
            else:
                m = re.search(r'^(.+)$', content.strip(), re.MULTILINE)
            if m:
                return fp, m.group(1).strip()
        return None

    for fname, pattern, _ in VERSION_FILE_PATTERNS:
        fp = os.path.join(project_dir, fname)
        if os.path.exists(fp):
            content = open(fp).read()
            m = re.search(pattern, content, re.MULTILINE)
            if m:
                return fp, m.group(1).strip()
    return None


def update_version_file(filepath: str, old_ver: str, new_ver: str):
    """Rewrite the version field in ``filepath`` from ``old_ver`` to ``new_ver``.

    Format-aware: looks up the file's regex from :data:`VERSION_FILE_PATTERNS`
    and rewrites *only* inside the matched version-field substring instead of
    blindly replacing the first textual occurrence of the version literal
    anywhere in the file.

    The old implementation used ``content.replace(old_ver, new_ver, 1)``,
    which corrupted unrelated content whenever the same numeric triple
    appeared earlier in the file (release-notes URLs, changelog refs,
    badges, etc.). See issue #129 for the full repro: a ``pyproject.toml``
    with ``description = "... /releases/1.2.3/notes"`` ahead of
    ``version = "1.2.3"`` would silently mutate the URL and leave the
    real version untouched.

    Also opens with explicit ``encoding="utf-8"`` (the previous default
    locale encoding was mojibake-prone on non-UTF-8 hosts) and preserves
    existing line endings via ``newline=""`` so repos that pin LF don't
    get silently rewritten to CRLF on Windows.

    Raises:
        ValueError: if the file's basename isn't in ``VERSION_FILE_PATTERNS``
            or the version field can't be located in the file.
    """
    fname = os.path.basename(filepath)
    pattern: Optional[str] = None
    for f, p, _t in VERSION_FILE_PATTERNS:
        if f.lower() == fname.lower():
            pattern = p
            break
    if pattern is None:
        # Fall back to a permissive single-line match (mirrors the
        # explicit-file branch of find_version_file).
        pattern = r'^(.+)$'

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    def _swap(match: "re.Match[str]") -> str:
        # Replace only inside the matched substring (the version field),
        # and only the first occurrence within it — group(1) is always
        # the version literal for the patterns we ship, so this is a
        # surgical edit.
        return match.group(0).replace(old_ver, new_ver, 1)

    new_content, n = re.subn(pattern, _swap, content, count=1, flags=re.MULTILINE)
    if n == 0:
        raise ValueError(
            f"version field not found in {filepath!r} (looked for old_ver={old_ver!r})"
        )

    with open(filepath, "w", encoding="utf-8", newline="") as f:
        f.write(new_content)


# ─── Changelog generation ────────────────────────────────────────

def generate_changelog_md(commits: List[Commit], version: str = "Unreleased",
                          date: str = None) -> str:
    """Render a Markdown changelog grouped by Conventional Commits type.

    Sections appear in a stable order (Features, Bug Fixes, …) regardless of
    commit ordering. Commits marked with ``!`` are *additionally* surfaced in
    a top-level "💥 Breaking Changes" block. Anything that did not parse as a
    Conventional Commit lands in a final "📋 Other" section.

    Args:
        commits: Commits to summarise, newest-first.
        version: Heading version string (e.g. ``"v1.2.0"`` or ``"Unreleased"``).
        date: ISO date string for the heading; defaults to today (UTC).

    Returns:
        A Markdown document (no trailing newline).
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    categorized = {}
    breaking = []
    for c in commits:
        cat = COMMIT_CATEGORIES.get(c.type, "📋 Other")
        categorized.setdefault(cat, []).append(c)
        if c.breaking:
            breaking.append(c)

    lines = [f"## [{version}] — {date}", ""]
    if breaking:
        lines.append("### 💥 Breaking Changes")
        lines.append("")
        for c in breaking:
            scope = f"**{c.scope}:** " if c.scope else ""
            lines.append(f"- {scope}{c.description} ({c.short_hash})")
        lines.append("")

    for cat in COMMIT_CATEGORIES.values():
        if cat in categorized:
            lines.append(f"### {cat}")
            lines.append("")
            for c in categorized[cat]:
                scope = f"**{c.scope}:** " if c.scope else ""
                lines.append(f"- {scope}{c.description} ({c.short_hash})")
            lines.append("")

    other = categorized.get("📋 Other", [])
    if other:
        lines.append("### 📋 Other")
        lines.append("")
        for c in other:
            lines.append(f"- {c.description} ({c.short_hash})")
        lines.append("")

    return "\n".join(lines)


def generate_changelog_json(commits: List[Commit], version: str = "Unreleased",
                            date: str = None) -> str:
    """Render a JSON-encoded changelog with per-commit fields and aggregate stats.

    Args:
        commits: Commits to encode.
        version: Version label included in the payload.
        date: ISO date; defaults to today (UTC).

    Returns:
        Indented JSON string with shape
        ``{"version", "date", "commits": [...], "stats": {"total", "breaking", "by_type"}}``.
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    entries = []
    for c in commits:
        entries.append({
            "hash": c.hash,
            "type": c.type,
            "scope": c.scope,
            "description": c.description,
            "breaking": c.breaking,
            "author": c.author,
            "date": c.date,
        })
    result = {
        "version": version,
        "date": date,
        "commits": entries,
        "stats": {
            "total": len(commits),
            "breaking": sum(1 for c in commits if c.breaking),
            "by_type": {},
        }
    }
    for c in commits:
        t = c.type
        result["stats"]["by_type"][t] = result["stats"]["by_type"].get(t, 0) + 1
    return json.dumps(result, indent=2)


def generate_changelog_text(commits: List[Commit], version: str = "Unreleased",
                            date: str = None) -> str:
    """Render a plain-text changelog suitable for terminals and release notes.

    Args:
        commits: Commits to summarise.
        version: Version label shown in the title line.
        date: ISO date; defaults to today (UTC).

    Returns:
        A multi-line string ending with a ``Total: N commits`` footer.
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"{version} ({date})", "=" * (len(version) + len(date) + 3), ""]
    for c in commits:
        prefix = "[BREAKING] " if c.breaking else ""
        scope = f"({c.scope}) " if c.scope else ""
        lines.append(f"  {prefix}{c.type}: {scope}{c.description}")
    lines.append("")
    lines.append(f"Total: {len(commits)} commits")
    return "\n".join(lines)


# ─── Suggest next version ────────────────────────────────────────

def suggest_next(current: SemVer, commits: List[Commit]) -> Tuple[SemVer, str]:
    """Recommend the next :class:`SemVer` based on Conventional Commit traffic.

    Decision rules (highest precedence first):

    * any ``!`` breaking change → **major** bump
    * any ``feat:`` commit → **minor** bump
    * any ``fix:`` or other non-empty change → **patch** bump
    * otherwise → no bump

    Args:
        current: Current released version.
        commits: Commits to weigh (typically since the last tag).

    Returns:
        ``(next_version, human_reason)`` — ``next_version`` equals ``current``
        when no bump is warranted.
    """
    has_breaking = any(c.breaking for c in commits)
    has_feat = any(c.type == "feat" for c in commits)
    has_fix = any(c.type == "fix" for c in commits)

    if has_breaking:
        return current.bump("major"), "major (breaking changes detected)"
    elif has_feat:
        return current.bump("minor"), "minor (new features detected)"
    elif has_fix or commits:
        return current.bump("patch"), "patch (fixes/other changes)"
    else:
        return current, "no changes detected"


# ─── Version history from tags ────────────────────────────────────

def get_version_history(cwd=None) -> List[Dict]:
    """Return release history derived from git tags that parse as SemVer.

    Tags that fail :meth:`SemVer.parse` are silently skipped so non-release
    tags (``"backup-2024"``, ``"old"``, …) don't pollute the output.

    Args:
        cwd: Repository directory; ``None`` uses the current directory.

    Returns:
        Newest-first list of ``{"tag", "version", "date", "author"}`` dicts.
        ``date``/``author`` fall back to ``"unknown"`` if git can't resolve them.
    """
    tags = get_git_tags(cwd)
    history = []
    for tag in tags:
        try:
            ver = SemVer.parse(tag)
        except ValueError:
            continue
        rc, date = run_git(["log", "-1", "--format=%aI", tag], cwd)
        rc2, author = run_git(["log", "-1", "--format=%an", tag], cwd)
        history.append({
            "tag": tag,
            "version": str(ver),
            "date": date if rc == 0 else "unknown",
            "author": author if rc2 == 0 else "unknown",
        })
    return history


# ─── Compare versions ────────────────────────────────────────────

def compare_versions(a: str, b: str) -> Dict:
    """Compare two SemVer strings and describe the relationship.

    Args:
        a: First version string.
        b: Second version string.

    Returns:
        A dict with keys ``a``, ``b`` (canonicalised), ``relationship``
        (human sentence), ``diff`` (per-component ``b - a``), and
        ``compatible`` (``True`` when both share the same MAJOR — i.e. they
        are SemVer API-compatible).

    Raises:
        ValueError: If either input fails :meth:`SemVer.parse`.
    """
    va = SemVer.parse(a)
    vb = SemVer.parse(b)
    if va < vb:
        rel = "older"
    elif va > vb:
        rel = "newer"
    else:
        rel = "equal"

    diff = {
        "major": vb.major - va.major,
        "minor": vb.minor - va.minor,
        "patch": vb.patch - va.patch,
    }

    return {
        "a": str(va), "b": str(vb),
        "relationship": f"{va} is {rel} than {vb}",
        "diff": diff,
        "compatible": va.major == vb.major,
    }


# ─── CLI ──────────────────────────────────────────────────────────

def build_parser():
    """Construct the top-level :class:`argparse.ArgumentParser`.

    Split out from :func:`main` so the parser can be reused by tests and by
    documentation tooling (e.g. ``sphinx-argparse``) without invoking the CLI.
    """
    p = argparse.ArgumentParser(
        prog="sauravver",
        description="Version & release management for sauravcode projects",
    )
    p.add_argument("--version", action="version", version=f"sauravver {__version__}")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--dir", default=".", help="Project directory")
    p.add_argument("--file", default=None, help="Explicit version file")

    sub = p.add_subparsers(dest="command")

    # show
    sub.add_parser("show", help="Show current version")

    # bump
    bp = sub.add_parser("bump", help="Bump version")
    bp.add_argument("kind", choices=["major", "minor", "patch", "prerelease"])
    bp.add_argument("--pre", default="alpha", help="Prerelease tag (default: alpha)")
    bp.add_argument("--dry-run", action="store_true", help="Don't write changes")

    # set
    sp = sub.add_parser("set", help="Set explicit version")
    sp.add_argument("version", help="Version string")
    sp.add_argument("--dry-run", action="store_true")

    # validate
    vp = sub.add_parser("validate", help="Validate semver string")
    vp.add_argument("version", help="Version to validate")

    # changelog
    cp = sub.add_parser("changelog", help="Generate changelog from git")
    cp.add_argument("--from", dest="from_ref", help="Start ref (tag/commit)")
    cp.add_argument("--to", default="HEAD", help="End ref")
    cp.add_argument("--format", dest="fmt", choices=["md", "json", "text"], default="md")

    # tag
    tp = sub.add_parser("tag", help="Create git tag for current version")
    tp.add_argument("--sign", action="store_true", help="GPG sign tag")
    tp.add_argument("--dry-run", action="store_true")
    tp.add_argument("--message", "-m", help="Tag message")

    # history
    sub.add_parser("history", help="Show version history from git tags")

    # compare
    cmp = sub.add_parser("compare", help="Compare two versions")
    cmp.add_argument("a", help="First version")
    cmp.add_argument("b", help="Second version")

    # next
    np_ = sub.add_parser("next", help="Suggest next version from commits")
    np_.add_argument("--from", dest="from_ref", help="Start ref")

    return p


def main(argv=None):
    """CLI entry point.

    Args:
        argv: Optional argument list; ``None`` uses ``sys.argv[1:]``.

    Returns:
        Process exit code — ``0`` on success, ``1`` on user/data errors,
        ``2`` for unparseable arguments (raised by :mod:`argparse`).
    """
    # Issue #129: the default Windows console is cp1252 and would raise
    # UnicodeEncodeError on the '→'/emoji output below — before the
    # version bump was written. Promote stdout/stderr to utf-8 with a
    # replacement fallback so non-ASCII output never crashes the bump.
    for _stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(_stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                # Best-effort; never let console encoding kill a bump.
                pass
    parser = build_parser()
    args = parser.parse_args(argv)

    project_dir = os.path.abspath(args.dir)
    use_json = args.json

    if not args.command:
        parser.print_help()
        return 0

    # ── show ──
    if args.command == "show":
        result = find_version_file(project_dir, args.file)
        if not result:
            print("Error: No version file found", file=sys.stderr)
            return 1
        fp, ver = result
        try:
            sv = SemVer.parse(ver)
        except ValueError:
            sv = None
        if use_json:
            print(json.dumps({
                "version": ver,
                "file": fp,
                "valid_semver": sv is not None,
                "parsed": {"major": sv.major, "minor": sv.minor, "patch": sv.patch,
                           "pre": sv.pre, "build": sv.build} if sv else None,
            }, indent=2))
        else:
            print(f"Version: {ver}")
            print(f"File:    {fp}")
            if sv:
                print(f"Semver:  {sv.major}.{sv.minor}.{sv.patch}" +
                      (f"-{sv.pre}" if sv.pre else "") +
                      (f"+{sv.build}" if sv.build else ""))
        return 0

    # ── bump ──
    if args.command == "bump":
        result = find_version_file(project_dir, args.file)
        if not result:
            print("Error: No version file found", file=sys.stderr)
            return 1
        fp, ver = result
        try:
            current = SemVer.parse(ver)
        except ValueError:
            print(f"Error: Current version '{ver}' is not valid semver", file=sys.stderr)
            return 1
        new = current.bump(args.kind, args.pre)
        if use_json:
            print(json.dumps({
                "previous": str(current),
                "new": str(new),
                "kind": args.kind,
                "file": fp,
                "dry_run": getattr(args, 'dry_run', False),
            }, indent=2))
        else:
            print(f"Bump {args.kind}: {current} → {new}")
            print(f"File: {fp}")
        if not getattr(args, 'dry_run', False):
            update_version_file(fp, ver, str(new))
            if not use_json:
                print("✅ Version updated")
        else:
            if not use_json:
                print("(dry run — no changes written)")
        return 0

    # ── set ──
    if args.command == "set":
        try:
            new = SemVer.parse(args.version)
        except ValueError:
            print(f"Error: '{args.version}' is not valid semver", file=sys.stderr)
            return 1
        result = find_version_file(project_dir, args.file)
        if not result:
            print("Error: No version file found", file=sys.stderr)
            return 1
        fp, ver = result
        if use_json:
            print(json.dumps({"previous": ver, "new": str(new), "file": fp,
                              "dry_run": getattr(args, 'dry_run', False)}, indent=2))
        else:
            print(f"Set version: {ver} → {new}")
        if not getattr(args, 'dry_run', False):
            update_version_file(fp, ver, str(new))
            if not use_json:
                print("✅ Version updated")
        return 0

    # ── validate ──
    if args.command == "validate":
        try:
            sv = SemVer.parse(args.version)
            if use_json:
                print(json.dumps({"input": args.version, "valid": True,
                                  "normalized": str(sv),
                                  "major": sv.major, "minor": sv.minor,
                                  "patch": sv.patch, "pre": sv.pre,
                                  "build": sv.build}, indent=2))
            else:
                print(f"✅ Valid semver: {sv}")
                if sv.pre:
                    print(f"   Pre-release: {sv.pre}")
                if sv.build:
                    print(f"   Build: {sv.build}")
        except ValueError as e:
            if use_json:
                print(json.dumps({"input": args.version, "valid": False,
                                  "error": str(e)}, indent=2))
            else:
                print(f"❌ Invalid: {e}")
            return 1
        return 0

    # ── changelog ──
    if args.command == "changelog":
        commits = get_commits(args.from_ref, args.to, project_dir)
        result = find_version_file(project_dir, args.file)
        ver = result[1] if result else "Unreleased"
        if args.fmt == "json":
            print(generate_changelog_json(commits, ver))
        elif args.fmt == "text":
            print(generate_changelog_text(commits, ver))
        else:
            print(generate_changelog_md(commits, ver))
        return 0

    # ── tag ──
    if args.command == "tag":
        result = find_version_file(project_dir, args.file)
        if not result:
            print("Error: No version file found", file=sys.stderr)
            return 1
        _, ver = result
        tag_name = f"v{ver}"
        msg = args.message or f"Release {tag_name}"
        if use_json:
            print(json.dumps({"tag": tag_name, "message": msg,
                              "sign": args.sign,
                              "dry_run": getattr(args, 'dry_run', False)}, indent=2))
        if getattr(args, 'dry_run', False):
            if not use_json:
                print(f"Would create tag: {tag_name}")
                print(f"Message: {msg}")
            return 0
        git_args = ["tag", "-a", tag_name, "-m", msg]
        if args.sign:
            git_args.insert(1, "-s")
        rc, out = run_git(git_args, project_dir)
        if rc != 0:
            print(f"Error creating tag: {out}", file=sys.stderr)
            return 1
        if not use_json:
            print(f"✅ Created tag: {tag_name}")
        return 0

    # ── history ──
    if args.command == "history":
        history = get_version_history(project_dir)
        if use_json:
            print(json.dumps(history, indent=2))
        else:
            if not history:
                print("No version tags found")
            else:
                print(f"{'Tag':<20} {'Date':<28} {'Author':<20}")
                print("─" * 68)
                for h in history:
                    print(f"{h['tag']:<20} {h['date']:<28} {h['author']:<20}")
        return 0

    # ── compare ──
    if args.command == "compare":
        try:
            result = compare_versions(args.a, args.b)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        if use_json:
            print(json.dumps(result, indent=2))
        else:
            print(f"  {result['a']}  vs  {result['b']}")
            print(f"  {result['relationship']}")
            d = result['diff']
            print(f"  Diff: major={d['major']:+d}  minor={d['minor']:+d}  patch={d['patch']:+d}")
            print(f"  API compatible: {'yes' if result['compatible'] else 'no'}")
        return 0

    # ── next ──
    if args.command == "next":
        result = find_version_file(project_dir, args.file)
        if not result:
            print("Error: No version file found", file=sys.stderr)
            return 1
        _, ver = result
        current = SemVer.parse(ver)
        commits = get_commits(args.from_ref, "HEAD", project_dir)
        suggested, reason = suggest_next(current, commits)
        if use_json:
            print(json.dumps({
                "current": str(current), "suggested": str(suggested),
                "reason": reason, "commits_analyzed": len(commits),
            }, indent=2))
        else:
            print(f"Current:   {current}")
            print(f"Suggested: {suggested}")
            print(f"Reason:    {reason}")
            print(f"Commits:   {len(commits)}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

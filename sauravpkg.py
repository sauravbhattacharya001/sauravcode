#!/usr/bin/env python3
"""sauravpkg -- Package manager for sauravcode (.srv) projects.

Commands:
    init                Create a new saurav.pkg.json manifest
    install <name>      Install a package from the registry
    uninstall <name>    Remove an installed package
    list                List installed packages
    search <query>      Search the package registry
    info <name>         Show package details
    pack                Bundle current project into a .srvpkg archive
    publish             Publish packed archive to local registry
    update              Update all installed packages to latest versions
    outdated            Check for outdated installed packages
    deps                Show dependency tree
    validate            Validate saurav.pkg.json manifest
    run <script>        Run a named script from the manifest

Usage:
    python sauravpkg.py init
    python sauravpkg.py install math_utils
    python sauravpkg.py pack
    python sauravpkg.py run test
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
from io import BytesIO
from pathlib import Path

__version__ = "1.0.0"

MANIFEST_NAME = "saurav.pkg.json"
LOCK_NAME = "saurav.pkg.lock"
PKG_DIR = "srv_packages"
REGISTRY_DIR = Path.home() / ".sauravcode" / "registry"
ARCHIVE_EXT = ".srvpkg"

# Semantic version comparison
def parse_semver(v):
    """Parse a semver string into (major, minor, patch) tuple."""
    v = v.lstrip("v").strip()
    parts = v.split(".")
    result = []
    for i in range(3):
        if i < len(parts):
            try:
                result.append(int(parts[i]))
            except ValueError:
                result.append(0)
        else:
            result.append(0)
    return tuple(result)


def semver_matches(version, constraint):
    """Check if version satisfies a constraint (^, ~, >=, exact)."""
    constraint = constraint.strip()
    ver = parse_semver(version)

    if constraint.startswith("^"):
        # Compatible: same major, >= minor.patch
        base = parse_semver(constraint[1:])
        if ver[0] != base[0]:
            return False
        return ver >= base
    elif constraint.startswith("~"):
        # Approximate: same major.minor, >= patch
        base = parse_semver(constraint[1:])
        if ver[0] != base[0] or ver[1] != base[1]:
            return False
        return ver[2] >= base[2]
    elif constraint.startswith(">="):
        base = parse_semver(constraint[2:])
        return ver >= base
    elif constraint.startswith("<="):
        base = parse_semver(constraint[2:])
        return ver <= base
    elif constraint.startswith(">"):
        base = parse_semver(constraint[1:])
        return ver > base
    elif constraint.startswith("<"):
        base = parse_semver(constraint[1:])
        return ver < base
    elif constraint == "*" or constraint == "latest":
        return True
    else:
        # Exact match
        return ver == parse_semver(constraint)


def find_best_version(versions, constraint):
    """Find the best matching version for a constraint."""
    matching = [v for v in versions if semver_matches(v, constraint)]
    if not matching:
        return None
    matching.sort(key=parse_semver, reverse=True)
    return matching[0]


def sha256_file(path):
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data):
    """Compute SHA-256 hash of bytes."""
    return hashlib.sha256(data).hexdigest()


# ── Registry ──────────────────────────────────────────────────────────

class LocalRegistry:
    """Filesystem-based package registry (~/.sauravcode/registry/)."""

    def __init__(self, registry_dir=None):
        self.root = Path(registry_dir) if registry_dir else REGISTRY_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "index.json"
        self._index = self._load_index()

    def _load_index(self):
        if self._index_path.exists():
            with open(self._index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"packages": {}}

    def _save_index(self):
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2)

    def publish(self, archive_path, manifest):
        """Publish a package archive to the registry."""
        name = manifest["name"]
        version = manifest["version"]

        pkg_entry = self._index["packages"].setdefault(name, {
            "description": manifest.get("description", ""),
            "author": manifest.get("author", ""),
            "versions": {}
        })

        # Update description/author from latest
        pkg_entry["description"] = manifest.get("description", pkg_entry.get("description", ""))
        pkg_entry["author"] = manifest.get("author", pkg_entry.get("author", ""))

        if version in pkg_entry["versions"]:
            return False, f"Version {version} already published for '{name}'"

        # Copy archive to registry
        dest_dir = self.root / name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{name}-{version}{ARCHIVE_EXT}"
        shutil.copy2(archive_path, dest)

        pkg_entry["versions"][version] = {
            "archive": str(dest.relative_to(self.root)),
            "checksum": sha256_file(archive_path),
            "published": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "dependencies": manifest.get("dependencies", {}),
            "files": manifest.get("files", []),
        }

        self._save_index()
        return True, f"Published {name}@{version}"

    def search(self, query=""):
        """Search packages by name or description."""
        results = []
        query_lower = query.lower()
        for name, info in self._index["packages"].items():
            if query_lower in name.lower() or query_lower in info.get("description", "").lower():
                versions = sorted(info.get("versions", {}).keys(), key=parse_semver, reverse=True)
                results.append({
                    "name": name,
                    "description": info.get("description", ""),
                    "author": info.get("author", ""),
                    "latest": versions[0] if versions else "0.0.0",
                    "versions": versions,
                })
        return results

    def info(self, name):
        """Get detailed info about a package."""
        pkg = self._index["packages"].get(name)
        if not pkg:
            return None
        versions = sorted(pkg.get("versions", {}).keys(), key=parse_semver, reverse=True)
        return {
            "name": name,
            "description": pkg.get("description", ""),
            "author": pkg.get("author", ""),
            "latest": versions[0] if versions else "0.0.0",
            "versions": {v: pkg["versions"][v] for v in versions},
        }

    def get_archive_path(self, name, version):
        """Get the archive file path for a specific version."""
        pkg = self._index["packages"].get(name)
        if not pkg:
            return None
        ver_info = pkg.get("versions", {}).get(version)
        if not ver_info:
            return None
        return self.root / ver_info["archive"]

    def get_versions(self, name):
        """Get all versions of a package."""
        pkg = self._index["packages"].get(name)
        if not pkg:
            return []
        return sorted(pkg.get("versions", {}).keys(), key=parse_semver, reverse=True)


# ── Manifest ──────────────────────────────────────────────────────────

def default_manifest(name=None):
    """Create a default saurav.pkg.json manifest."""
    if name is None:
        name = Path.cwd().name
    return {
        "name": name,
        "version": "0.1.0",
        "description": "",
        "author": "",
        "license": "MIT",
        "main": "main.srv",
        "files": ["*.srv"],
        "dependencies": {},
        "scripts": {},
    }


def load_manifest(project_dir="."):
    """Load saurav.pkg.json from a directory."""
    path = Path(project_dir) / MANIFEST_NAME
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest, project_dir="."):
    """Save saurav.pkg.json to a directory."""
    path = Path(project_dir) / MANIFEST_NAME
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def validate_manifest(manifest):
    """Validate a manifest and return list of issues."""
    issues = []
    required = ["name", "version"]
    for field in required:
        if field not in manifest:
            issues.append(f"Missing required field: '{field}'")
        elif not isinstance(manifest[field], str) or not manifest[field].strip():
            issues.append(f"Field '{field}' must be a non-empty string")

    if "version" in manifest and isinstance(manifest["version"], str):
        v = manifest["version"]
        parts = v.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            issues.append(f"Invalid semver version: '{v}' (expected X.Y.Z)")

    if "name" in manifest and isinstance(manifest["name"], str):
        name = manifest["name"]
        import re
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_-]*$', name):
            issues.append(f"Invalid package name: '{name}' (alphanumeric, underscores, hyphens)")

    if "dependencies" in manifest:
        if not isinstance(manifest["dependencies"], dict):
            issues.append("'dependencies' must be an object")
        else:
            for dep_name, constraint in manifest["dependencies"].items():
                if not isinstance(constraint, str):
                    issues.append(f"Dependency '{dep_name}' constraint must be a string")

    if "files" in manifest:
        if not isinstance(manifest["files"], list):
            issues.append("'files' must be an array of glob patterns")

    if "scripts" in manifest:
        if not isinstance(manifest["scripts"], dict):
            issues.append("'scripts' must be an object")

    return issues


# ── Lock File ─────────────────────────────────────────────────────────

def load_lockfile(project_dir="."):
    """Load saurav.pkg.lock."""
    path = Path(project_dir) / LOCK_NAME
    if not path.exists():
        return {"packages": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_lockfile(lockdata, project_dir="."):
    """Save saurav.pkg.lock."""
    path = Path(project_dir) / LOCK_NAME
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lockdata, f, indent=2)
        f.write("\n")


# ── Packing / Installing ─────────────────────────────────────────────

def collect_files(project_dir, patterns):
    """Collect files matching glob patterns."""
    project = Path(project_dir)
    files = set()
    for pattern in patterns:
        for match in project.glob(pattern):
            if match.is_file():
                files.add(match.relative_to(project))
    # Always include manifest
    manifest_path = Path(MANIFEST_NAME)
    if (project / manifest_path).exists():
        files.add(manifest_path)
    return sorted(files)


def pack_project(project_dir=".", output_dir=None):
    """Create a .srvpkg archive from the project."""
    manifest = load_manifest(project_dir)
    if manifest is None:
        return None, f"No {MANIFEST_NAME} found in {project_dir}"

    issues = validate_manifest(manifest)
    if issues:
        return None, f"Invalid manifest:\n" + "\n".join(f"  - {i}" for i in issues)

    patterns = manifest.get("files", ["*.srv"])
    files = collect_files(project_dir, patterns)
    if not files:
        return None, "No files matched the 'files' patterns"

    name = manifest["name"]
    version = manifest["version"]
    archive_name = f"{name}-{version}{ARCHIVE_EXT}"

    if output_dir is None:
        output_dir = project_dir
    output_path = Path(output_dir) / archive_name

    with tarfile.open(output_path, "w:gz") as tar:
        project = Path(project_dir)
        for rel_path in files:
            full = project / rel_path
            tar.add(str(full), arcname=str(rel_path))

    manifest["files"] = [str(f) for f in files]
    save_manifest(manifest, project_dir)

    checksum = sha256_file(output_path)
    return {
        "archive": str(output_path),
        "name": name,
        "version": version,
        "files": [str(f) for f in files],
        "checksum": checksum,
        "size": output_path.stat().st_size,
    }, None


def install_package(name, constraint="*", project_dir=".", registry=None):
    """Install a package from the registry into srv_packages/."""
    if registry is None:
        registry = LocalRegistry()

    versions = registry.get_versions(name)
    if not versions:
        return False, f"Package '{name}' not found in registry"

    version = find_best_version(versions, constraint)
    if not version:
        return False, f"No version of '{name}' matches constraint '{constraint}'"

    archive_path = registry.get_archive_path(name, version)
    if archive_path is None or not archive_path.exists():
        return False, f"Archive not found for {name}@{version}"

    # Verify checksum
    info = registry.info(name)
    expected_checksum = info["versions"][version].get("checksum")
    if expected_checksum:
        actual = sha256_file(archive_path)
        if actual != expected_checksum:
            return False, f"Checksum mismatch for {name}@{version}"

    # Extract to srv_packages/<name>/
    pkg_dest = Path(project_dir) / PKG_DIR / name
    if pkg_dest.exists():
        shutil.rmtree(pkg_dest)
    pkg_dest.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=str(pkg_dest))

    # Install transitive dependencies
    dep_manifest = load_manifest(str(pkg_dest))
    if dep_manifest and dep_manifest.get("dependencies"):
        for dep_name, dep_constraint in dep_manifest["dependencies"].items():
            sub_ok, sub_msg = install_package(dep_name, dep_constraint, project_dir, registry)
            if not sub_ok:
                return False, f"Failed to install dependency '{dep_name}' of '{name}': {sub_msg}"

    # Update lockfile
    lockdata = load_lockfile(project_dir)
    lockdata["packages"][name] = {
        "version": version,
        "checksum": expected_checksum or sha256_file(archive_path),
        "installed": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_lockfile(lockdata, project_dir)

    # Update manifest dependencies
    manifest = load_manifest(project_dir)
    if manifest:
        deps = manifest.setdefault("dependencies", {})
        if name not in deps:
            deps[name] = f"^{version}"
            save_manifest(manifest, project_dir)

    return True, f"Installed {name}@{version}"


def uninstall_package(name, project_dir="."):
    """Remove an installed package."""
    pkg_dir = Path(project_dir) / PKG_DIR / name
    if not pkg_dir.exists():
        return False, f"Package '{name}' is not installed"

    shutil.rmtree(pkg_dir)

    # Update lockfile
    lockdata = load_lockfile(project_dir)
    lockdata["packages"].pop(name, None)
    save_lockfile(lockdata, project_dir)

    # Update manifest
    manifest = load_manifest(project_dir)
    if manifest:
        manifest.get("dependencies", {}).pop(name, None)
        save_manifest(manifest, project_dir)

    return True, f"Uninstalled '{name}'"


def list_installed(project_dir="."):
    """List installed packages."""
    pkg_root = Path(project_dir) / PKG_DIR
    if not pkg_root.exists():
        return []

    lockdata = load_lockfile(project_dir)
    installed = []

    for d in sorted(pkg_root.iterdir()):
        if d.is_dir():
            pkg_manifest = load_manifest(str(d))
            lock_info = lockdata.get("packages", {}).get(d.name, {})
            installed.append({
                "name": d.name,
                "version": lock_info.get("version", pkg_manifest.get("version", "?") if pkg_manifest else "?"),
                "description": pkg_manifest.get("description", "") if pkg_manifest else "",
                "installed": lock_info.get("installed", ""),
            })

    return installed


def check_outdated(project_dir=".", registry=None):
    """Check for outdated packages."""
    if registry is None:
        registry = LocalRegistry()

    installed = list_installed(project_dir)
    outdated = []

    for pkg in installed:
        latest_versions = registry.get_versions(pkg["name"])
        if latest_versions:
            latest = latest_versions[0]
            if parse_semver(latest) > parse_semver(pkg["version"]):
                outdated.append({
                    "name": pkg["name"],
                    "current": pkg["version"],
                    "latest": latest,
                })

    return outdated


def dependency_tree(project_dir=".", registry=None, _seen=None):
    """Build a dependency tree."""
    if registry is None:
        registry = LocalRegistry()
    if _seen is None:
        _seen = set()

    manifest = load_manifest(project_dir)
    if not manifest:
        return {}

    tree = {}
    for dep_name, constraint in manifest.get("dependencies", {}).items():
        if dep_name in _seen:
            tree[dep_name] = {"version": constraint, "circular": True}
            continue

        _seen.add(dep_name)
        dep_dir = Path(project_dir) / PKG_DIR / dep_name
        dep_manifest = load_manifest(str(dep_dir)) if dep_dir.exists() else None

        entry = {
            "constraint": constraint,
            "installed": dep_manifest.get("version") if dep_manifest else None,
        }

        if dep_manifest and dep_manifest.get("dependencies"):
            # Recurse
            sub_tree = {}
            for sub_name, sub_constraint in dep_manifest["dependencies"].items():
                if sub_name in _seen:
                    sub_tree[sub_name] = {"constraint": sub_constraint, "circular": True}
                else:
                    _seen.add(sub_name)
                    sub_tree[sub_name] = {"constraint": sub_constraint, "installed": None}
            entry["dependencies"] = sub_tree

        tree[dep_name] = entry
        _seen.discard(dep_name)

    return tree


def print_tree(tree, prefix=""):
    """Pretty-print a dependency tree."""
    items = list(tree.items())
    for i, (name, info) in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        version_str = info.get("installed") or info.get("constraint", "?")
        circular = " (circular)" if info.get("circular") else ""
        print(f"{prefix}{connector}{name}@{version_str}{circular}")

        sub_deps = info.get("dependencies", {})
        if sub_deps:
            extension = "    " if is_last else "│   "
            print_tree(sub_deps, prefix + extension)


# ── CLI ───────────────────────────────────────────────────────────────

def cmd_init(args):
    """Initialize a new package manifest."""
    project_dir = args.dir
    manifest_path = Path(project_dir) / MANIFEST_NAME

    if manifest_path.exists() and not args.force:
        print(f"  {MANIFEST_NAME} already exists. Use --force to overwrite.")
        return 1

    name = args.name or Path(project_dir).resolve().name
    manifest = default_manifest(name)

    if args.description:
        manifest["description"] = args.description
    if args.author:
        manifest["author"] = args.author

    save_manifest(manifest, project_dir)
    print(f"  Created {MANIFEST_NAME}")
    print(f"  Package: {manifest['name']}@{manifest['version']}")
    return 0


def cmd_install(args):
    """Install packages."""
    project_dir = args.dir
    registry = LocalRegistry(args.registry) if args.registry else LocalRegistry()

    if args.packages:
        for spec in args.packages:
            if "@" in spec:
                name, constraint = spec.split("@", 1)
            else:
                name, constraint = spec, "*"

            ok, msg = install_package(name, constraint, project_dir, registry)
            icon = "✓" if ok else "✗"
            print(f"  {icon} {msg}")
            if not ok:
                return 1
    else:
        # Install all from manifest
        manifest = load_manifest(project_dir)
        if not manifest:
            print(f"  No {MANIFEST_NAME} found. Run 'sauravpkg init' first.")
            return 1

        deps = manifest.get("dependencies", {})
        if not deps:
            print("  No dependencies to install.")
            return 0

        for name, constraint in deps.items():
            ok, msg = install_package(name, constraint, project_dir, registry)
            icon = "✓" if ok else "✗"
            print(f"  {icon} {msg}")
            if not ok:
                return 1

    return 0


def cmd_uninstall(args):
    """Uninstall packages."""
    for name in args.packages:
        ok, msg = uninstall_package(name, args.dir)
        icon = "✓" if ok else "✗"
        print(f"  {icon} {msg}")
    return 0


def cmd_list(args):
    """List installed packages."""
    installed = list_installed(args.dir)
    if not installed:
        print("  No packages installed.")
        return 0

    if args.json:
        print(json.dumps(installed, indent=2))
        return 0

    print(f"  {'Package':<25} {'Version':<12} Description")
    print(f"  {'─' * 25} {'─' * 12} {'─' * 35}")
    for pkg in installed:
        desc = pkg["description"][:35] if pkg["description"] else ""
        print(f"  {pkg['name']:<25} {pkg['version']:<12} {desc}")

    print(f"\n  {len(installed)} package(s) installed.")
    return 0


def cmd_search(args):
    """Search the registry."""
    registry = LocalRegistry(args.registry) if args.registry else LocalRegistry()
    results = registry.search(args.query or "")

    if not results:
        print("  No packages found.")
        return 0

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    print(f"  {'Package':<25} {'Latest':<12} Description")
    print(f"  {'─' * 25} {'─' * 12} {'─' * 35}")
    for pkg in results:
        desc = pkg["description"][:35] if pkg["description"] else ""
        print(f"  {pkg['name']:<25} {pkg['latest']:<12} {desc}")

    print(f"\n  {len(results)} package(s) found.")
    return 0


def cmd_info(args):
    """Show package info."""
    registry = LocalRegistry(args.registry) if args.registry else LocalRegistry()
    info = registry.info(args.name)

    if not info:
        print(f"  Package '{args.name}' not found.")
        return 1

    if args.json:
        print(json.dumps(info, indent=2))
        return 0

    print(f"  {info['name']}@{info['latest']}")
    if info["description"]:
        print(f"  {info['description']}")
    if info["author"]:
        print(f"  Author: {info['author']}")
    print(f"\n  Versions:")
    for v, details in info["versions"].items():
        published = details.get("published", "")
        print(f"    {v}  ({published})")
    return 0


def cmd_pack(args):
    """Pack the project."""
    result, error = pack_project(args.dir, args.output)

    if error:
        print(f"  ✗ {error}")
        return 1

    print(f"  ✓ Packed {result['name']}@{result['version']}")
    print(f"    Archive: {result['archive']}")
    print(f"    Files:   {len(result['files'])}")
    print(f"    Size:    {result['size']} bytes")
    print(f"    SHA-256: {result['checksum'][:16]}...")
    return 0


def cmd_publish(args):
    """Publish to registry."""
    manifest = load_manifest(args.dir)
    if not manifest:
        print(f"  ✗ No {MANIFEST_NAME} found.")
        return 1

    name = manifest["name"]
    version = manifest["version"]
    archive_path = Path(args.dir) / f"{name}-{version}{ARCHIVE_EXT}"

    if not archive_path.exists():
        # Pack first
        result, error = pack_project(args.dir, args.dir)
        if error:
            print(f"  ✗ {error}")
            return 1
        archive_path = Path(result["archive"])

    registry = LocalRegistry(args.registry) if args.registry else LocalRegistry()
    ok, msg = registry.publish(str(archive_path), manifest)
    icon = "✓" if ok else "✗"
    print(f"  {icon} {msg}")
    return 0 if ok else 1


def cmd_update(args):
    """Update packages."""
    registry = LocalRegistry(args.registry) if args.registry else LocalRegistry()
    outdated = check_outdated(args.dir, registry)

    if not outdated:
        print("  All packages are up to date.")
        return 0

    for pkg in outdated:
        ok, msg = install_package(pkg["name"], "*", args.dir, registry)
        if ok:
            print(f"  ✓ Updated {pkg['name']}: {pkg['current']} → {pkg['latest']}")
        else:
            print(f"  ✗ Failed to update {pkg['name']}: {msg}")
    return 0


def cmd_outdated(args):
    """Check for outdated packages."""
    registry = LocalRegistry(args.registry) if args.registry else LocalRegistry()
    outdated = check_outdated(args.dir, registry)

    if not outdated:
        print("  All packages are up to date.")
        return 0

    if args.json:
        print(json.dumps(outdated, indent=2))
        return 0

    print(f"  {'Package':<25} {'Current':<12} {'Latest':<12}")
    print(f"  {'─' * 25} {'─' * 12} {'─' * 12}")
    for pkg in outdated:
        print(f"  {pkg['name']:<25} {pkg['current']:<12} {pkg['latest']:<12}")
    return 0


def cmd_deps(args):
    """Show dependency tree."""
    registry = LocalRegistry(args.registry) if args.registry else LocalRegistry()
    manifest = load_manifest(args.dir)

    if not manifest:
        print(f"  No {MANIFEST_NAME} found.")
        return 1

    tree = dependency_tree(args.dir, registry)

    if args.json:
        print(json.dumps(tree, indent=2))
        return 0

    if not tree:
        print("  No dependencies.")
        return 0

    print(f"  {manifest['name']}@{manifest['version']}")
    print_tree(tree, "  ")
    return 0


def cmd_validate(args):
    """Validate manifest."""
    manifest = load_manifest(args.dir)
    if not manifest:
        print(f"  ✗ No {MANIFEST_NAME} found.")
        return 1

    issues = validate_manifest(manifest)
    if not issues:
        print(f"  ✓ {MANIFEST_NAME} is valid.")
        return 0

    print(f"  ✗ {len(issues)} issue(s) found:")
    for issue in issues:
        print(f"    - {issue}")
    return 1


def cmd_run(args):
    """Run a named script from the manifest."""
    manifest = load_manifest(args.dir)
    if not manifest:
        print(f"  ✗ No {MANIFEST_NAME} found.")
        return 1

    scripts = manifest.get("scripts", {})
    if args.script not in scripts:
        if not scripts:
            print("  No scripts defined in manifest.")
        else:
            print(f"  Script '{args.script}' not found. Available:")
            for name in scripts:
                print(f"    - {name}")
        return 1

    command = scripts[args.script]
    print(f"  Running '{args.script}': {command}")
    return os.system(command)


def build_parser():
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="sauravpkg",
        description="Package manager for sauravcode (.srv) projects",
    )
    parser.add_argument("--version", action="version", version=f"sauravpkg {__version__}")
    parser.add_argument("--dir", default=".", help="Project directory")

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Create a new package manifest")
    p_init.add_argument("--name", help="Package name")
    p_init.add_argument("--description", help="Package description")
    p_init.add_argument("--author", help="Package author")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing manifest")

    # install
    p_install = sub.add_parser("install", help="Install packages")
    p_install.add_argument("packages", nargs="*", help="Packages to install (name or name@version)")
    p_install.add_argument("--registry", help="Registry directory")

    # uninstall
    p_uninstall = sub.add_parser("uninstall", help="Remove installed packages")
    p_uninstall.add_argument("packages", nargs="+", help="Packages to uninstall")

    # list
    p_list = sub.add_parser("list", help="List installed packages")
    p_list.add_argument("--json", action="store_true", help="JSON output")

    # search
    p_search = sub.add_parser("search", help="Search the registry")
    p_search.add_argument("query", nargs="?", default="", help="Search query")
    p_search.add_argument("--registry", help="Registry directory")
    p_search.add_argument("--json", action="store_true", help="JSON output")

    # info
    p_info = sub.add_parser("info", help="Show package details")
    p_info.add_argument("name", help="Package name")
    p_info.add_argument("--registry", help="Registry directory")
    p_info.add_argument("--json", action="store_true", help="JSON output")

    # pack
    p_pack = sub.add_parser("pack", help="Bundle project into archive")
    p_pack.add_argument("--output", help="Output directory")

    # publish
    p_publish = sub.add_parser("publish", help="Publish to registry")
    p_publish.add_argument("--registry", help="Registry directory")

    # update
    p_update = sub.add_parser("update", help="Update packages")
    p_update.add_argument("--registry", help="Registry directory")

    # outdated
    p_outdated = sub.add_parser("outdated", help="Check for outdated packages")
    p_outdated.add_argument("--registry", help="Registry directory")
    p_outdated.add_argument("--json", action="store_true", help="JSON output")

    # deps
    p_deps = sub.add_parser("deps", help="Show dependency tree")
    p_deps.add_argument("--registry", help="Registry directory")
    p_deps.add_argument("--json", action="store_true", help="JSON output")

    # validate
    sub.add_parser("validate", help="Validate manifest")

    # run
    p_run = sub.add_parser("run", help="Run a named script")
    p_run.add_argument("script", help="Script name")

    return parser


def main(argv=None):
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "init": cmd_init,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "list": cmd_list,
        "search": cmd_search,
        "info": cmd_info,
        "pack": cmd_pack,
        "publish": cmd_publish,
        "update": cmd_update,
        "outdated": cmd_outdated,
        "deps": cmd_deps,
        "validate": cmd_validate,
        "run": cmd_run,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main() or 0)

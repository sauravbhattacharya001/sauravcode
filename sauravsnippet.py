#!/usr/bin/env python3
"""
sauravsnippet — Code snippet manager for sauravcode (.srv) programs.

Save, search, tag, and reuse .srv code snippets from a local library.
Snippets are stored as JSON in a configurable directory and can be
searched by name, tag, description, or content.

Usage:
    python sauravsnippet.py save <name> <file.srv> [--tags t1,t2] [--desc "..."]
    python sauravsnippet.py save <name> --stdin [--tags t1,t2] [--desc "..."]
    python sauravsnippet.py get <name>                  Print snippet code
    python sauravsnippet.py list [--tag TAG] [--sort name|date|uses]
    python sauravsnippet.py search <query>              Full-text search
    python sauravsnippet.py info <name>                 Show snippet metadata
    python sauravsnippet.py edit <name> <file.srv>      Update snippet code
    python sauravsnippet.py tag <name> --add t1,t2      Add tags
    python sauravsnippet.py tag <name> --remove t1      Remove tags
    python sauravsnippet.py delete <name>               Delete a snippet
    python sauravsnippet.py export [--format json|srv]  Export all snippets
    python sauravsnippet.py import <file.json>          Import snippets
    python sauravsnippet.py stats                       Library statistics
    python sauravsnippet.py use <name> [-o FILE]        Copy snippet to file and bump use count
    python sauravsnippet.py rename <old> <new>          Rename a snippet
    python sauravsnippet.py duplicate <name> <newname>  Duplicate a snippet

Options:
    --lib DIR    Snippet library directory (default: ~/.sauravsnippets)
    --json       Output as JSON where applicable
"""

import json
import sys
import os
import argparse
import re
from pathlib import Path
from datetime import datetime


DEFAULT_LIB = os.path.join(os.path.expanduser("~"), ".sauravsnippets")


class SnippetLibrary:
    """Manages a collection of saved .srv code snippets."""

    def __init__(self, lib_dir=None):
        self.lib_dir = Path(lib_dir or DEFAULT_LIB)
        self.lib_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.lib_dir / "index.json"
        self.index = self._load_index()

    def _load_index(self):
        if self.index_path.exists():
            try:
                return json.loads(self.index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_index(self):
        self.index_path.write_text(
            json.dumps(self.index, indent=2, default=str),
            encoding="utf-8",
        )

    def _snippet_path(self, name):
        safe = re.sub(r'[^\w\-]', '_', name)
        return self.lib_dir / f"{safe}.srv"

    def save(self, name, code, tags=None, description=""):
        """Save a new snippet."""
        if name in self.index:
            raise ValueError(f"Snippet '{name}' already exists. Use 'edit' to update.")
        path = self._snippet_path(name)
        path.write_text(code, encoding="utf-8")
        self.index[name] = {
            "file": path.name,
            "tags": sorted(set(tags or [])),
            "description": description,
            "created": datetime.now().isoformat(),
            "modified": datetime.now().isoformat(),
            "uses": 0,
            "lines": code.count('\n') + (1 if code and not code.endswith('\n') else 0),
        }
        self._save_index()
        return self.index[name]

    def get(self, name):
        """Get snippet code by name."""
        if name not in self.index:
            raise KeyError(f"Snippet '{name}' not found.")
        path = self.lib_dir / self.index[name]["file"]
        return path.read_text(encoding="utf-8")

    def info(self, name):
        """Get snippet metadata."""
        if name not in self.index:
            raise KeyError(f"Snippet '{name}' not found.")
        return {"name": name, **self.index[name]}

    def edit(self, name, code):
        """Update snippet code."""
        if name not in self.index:
            raise KeyError(f"Snippet '{name}' not found.")
        path = self.lib_dir / self.index[name]["file"]
        path.write_text(code, encoding="utf-8")
        self.index[name]["modified"] = datetime.now().isoformat()
        self.index[name]["lines"] = code.count('\n') + (1 if code and not code.endswith('\n') else 0)
        self._save_index()

    def delete(self, name):
        """Delete a snippet."""
        if name not in self.index:
            raise KeyError(f"Snippet '{name}' not found.")
        path = self.lib_dir / self.index[name]["file"]
        if path.exists():
            path.unlink()
        del self.index[name]
        self._save_index()

    def rename(self, old_name, new_name):
        """Rename a snippet."""
        if old_name not in self.index:
            raise KeyError(f"Snippet '{old_name}' not found.")
        if new_name in self.index:
            raise ValueError(f"Snippet '{new_name}' already exists.")
        code = self.get(old_name)
        meta = self.index.pop(old_name)
        old_path = self.lib_dir / meta["file"]
        new_path = self._snippet_path(new_name)
        if old_path.exists():
            old_path.unlink()
        new_path.write_text(code, encoding="utf-8")
        meta["file"] = new_path.name
        meta["modified"] = datetime.now().isoformat()
        self.index[new_name] = meta
        self._save_index()

    def duplicate(self, name, new_name):
        """Duplicate a snippet under a new name."""
        if name not in self.index:
            raise KeyError(f"Snippet '{name}' not found.")
        if new_name in self.index:
            raise ValueError(f"Snippet '{new_name}' already exists.")
        code = self.get(name)
        old_meta = self.index[name]
        self.save(new_name, code, tags=list(old_meta.get("tags", [])),
                  description=old_meta.get("description", ""))

    def add_tags(self, name, tags):
        """Add tags to a snippet."""
        if name not in self.index:
            raise KeyError(f"Snippet '{name}' not found.")
        existing = set(self.index[name].get("tags", []))
        existing.update(tags)
        self.index[name]["tags"] = sorted(existing)
        self.index[name]["modified"] = datetime.now().isoformat()
        self._save_index()

    def remove_tags(self, name, tags):
        """Remove tags from a snippet."""
        if name not in self.index:
            raise KeyError(f"Snippet '{name}' not found.")
        existing = set(self.index[name].get("tags", []))
        existing -= set(tags)
        self.index[name]["tags"] = sorted(existing)
        self.index[name]["modified"] = datetime.now().isoformat()
        self._save_index()

    def use(self, name):
        """Bump use count and return code."""
        if name not in self.index:
            raise KeyError(f"Snippet '{name}' not found.")
        self.index[name]["uses"] = self.index[name].get("uses", 0) + 1
        self._save_index()
        return self.get(name)

    def list_snippets(self, tag=None, sort_by="name"):
        """List snippets, optionally filtered by tag."""
        items = []
        for name, meta in self.index.items():
            if tag and tag not in meta.get("tags", []):
                continue
            items.append({"name": name, **meta})

        if sort_by == "date":
            items.sort(key=lambda x: x.get("modified", ""), reverse=True)
        elif sort_by == "uses":
            items.sort(key=lambda x: x.get("uses", 0), reverse=True)
        else:
            items.sort(key=lambda x: x["name"].lower())
        return items

    def search(self, query):
        """Full-text search across names, tags, descriptions, and code content."""
        query_lower = query.lower()
        results = []
        for name, meta in self.index.items():
            score = 0
            # Name match (highest weight)
            if query_lower in name.lower():
                score += 10
            # Tag match
            for tag in meta.get("tags", []):
                if query_lower in tag.lower():
                    score += 5
            # Description match
            if query_lower in meta.get("description", "").lower():
                score += 3
            # Code content match
            try:
                code = self.get(name)
                occurrences = code.lower().count(query_lower)
                if occurrences > 0:
                    score += min(occurrences, 5)
            except (OSError, KeyError):
                pass
            if score > 0:
                results.append({"name": name, "score": score, **meta})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def stats(self):
        """Library statistics."""
        total = len(self.index)
        if total == 0:
            return {"total": 0, "tags": {}, "total_lines": 0, "total_uses": 0}
        tag_counts = {}
        total_lines = 0
        total_uses = 0
        for meta in self.index.values():
            for tag in meta.get("tags", []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            total_lines += meta.get("lines", 0)
            total_uses += meta.get("uses", 0)
        return {
            "total": total,
            "tags": dict(sorted(tag_counts.items(), key=lambda x: -x[1])),
            "total_lines": total_lines,
            "total_uses": total_uses,
            "most_used": max(self.index.items(), key=lambda x: x[1].get("uses", 0))[0] if total else None,
        }

    def export_all(self, fmt="json"):
        """Export all snippets."""
        if fmt == "json":
            export = {}
            for name, meta in self.index.items():
                try:
                    code = self.get(name)
                except (OSError, KeyError):
                    code = ""
                export[name] = {**meta, "code": code}
            return json.dumps(export, indent=2, default=str)
        else:  # srv — concatenated with headers
            parts = []
            for name in sorted(self.index.keys()):
                try:
                    code = self.get(name)
                except (OSError, KeyError):
                    code = ""
                tags = ", ".join(self.index[name].get("tags", []))
                desc = self.index[name].get("description", "")
                header = f"# === Snippet: {name} ==="
                if tags:
                    header += f"\n# Tags: {tags}"
                if desc:
                    header += f"\n# {desc}"
                parts.append(f"{header}\n{code}")
            return "\n\n".join(parts)

    def import_snippets(self, data, overwrite=False):
        """Import snippets from exported JSON data."""
        if isinstance(data, str):
            data = json.loads(data)
        imported = 0
        skipped = 0
        for name, entry in data.items():
            if name in self.index and not overwrite:
                skipped += 1
                continue
            code = entry.pop("code", "")
            if name in self.index:
                self.edit(name, code)
                self.index[name]["tags"] = entry.get("tags", [])
                self.index[name]["description"] = entry.get("description", "")
            else:
                self.save(name, code,
                          tags=entry.get("tags", []),
                          description=entry.get("description", ""))
            imported += 1
        self._save_index()
        return {"imported": imported, "skipped": skipped}


# ── CLI ─────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="sauravsnippet",
        description="Code snippet manager for sauravcode (.srv) programs",
    )
    parser.add_argument("--lib", default=None, help="Snippet library directory")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as JSON")
    sub = parser.add_subparsers(dest="command")

    # save
    p_save = sub.add_parser("save", help="Save a new snippet")
    p_save.add_argument("name", help="Snippet name")
    p_save.add_argument("file", nargs="?", help="Source .srv file")
    p_save.add_argument("--stdin", action="store_true", help="Read from stdin")
    p_save.add_argument("--tags", default="", help="Comma-separated tags")
    p_save.add_argument("--desc", default="", help="Description")

    # get
    p_get = sub.add_parser("get", help="Print snippet code")
    p_get.add_argument("name")

    # list
    p_list = sub.add_parser("list", help="List snippets")
    p_list.add_argument("--tag", default=None, help="Filter by tag")
    p_list.add_argument("--sort", default="name", choices=["name", "date", "uses"])

    # search
    p_search = sub.add_parser("search", help="Search snippets")
    p_search.add_argument("query")

    # info
    p_info = sub.add_parser("info", help="Show snippet metadata")
    p_info.add_argument("name")

    # edit
    p_edit = sub.add_parser("edit", help="Update snippet code")
    p_edit.add_argument("name")
    p_edit.add_argument("file", help="New source .srv file")

    # tag
    p_tag = sub.add_parser("tag", help="Manage tags")
    p_tag.add_argument("name")
    p_tag.add_argument("--add", default="", help="Tags to add (comma-separated)")
    p_tag.add_argument("--remove", default="", help="Tags to remove (comma-separated)")

    # delete
    p_del = sub.add_parser("delete", help="Delete a snippet")
    p_del.add_argument("name")

    # rename
    p_ren = sub.add_parser("rename", help="Rename a snippet")
    p_ren.add_argument("old")
    p_ren.add_argument("new")

    # duplicate
    p_dup = sub.add_parser("duplicate", help="Duplicate a snippet")
    p_dup.add_argument("name")
    p_dup.add_argument("newname")

    # export
    p_exp = sub.add_parser("export", help="Export all snippets")
    p_exp.add_argument("--format", default="json", choices=["json", "srv"])

    # import
    p_imp = sub.add_parser("import", help="Import snippets from JSON")
    p_imp.add_argument("file", help="JSON file to import")
    p_imp.add_argument("--overwrite", action="store_true")

    # use
    p_use = sub.add_parser("use", help="Copy snippet to file (bumps use count)")
    p_use.add_argument("name")
    p_use.add_argument("-o", "--output", default=None, help="Output file")

    # stats
    sub.add_parser("stats", help="Library statistics")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(1)

    lib = SnippetLibrary(args.lib)
    json_out = args.json_output

    try:
        if args.command == "save":
            if args.stdin:
                code = sys.stdin.read()
            elif args.file:
                code = Path(args.file).read_text(encoding="utf-8")
            else:
                print("Error: provide a file or --stdin", file=sys.stderr)
                sys.exit(1)
            tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
            meta = lib.save(args.name, code, tags=tags, description=args.desc)
            if json_out:
                print(json.dumps(meta, indent=2))
            else:
                print(f"✓ Saved snippet '{args.name}' ({meta['lines']} lines, tags: {meta['tags']})")

        elif args.command == "get":
            print(lib.get(args.name), end="")

        elif args.command == "list":
            items = lib.list_snippets(tag=args.tag, sort_by=args.sort)
            if json_out:
                print(json.dumps(items, indent=2))
            elif not items:
                print("No snippets found.")
            else:
                max_name = max(len(i["name"]) for i in items)
                for i in items:
                    tags_str = ", ".join(i.get("tags", []))
                    desc = i.get("description", "")
                    uses = i.get("uses", 0)
                    lines = i.get("lines", 0)
                    print(f"  {i['name']:<{max_name}}  {lines:>4} lines  {uses:>3} uses  [{tags_str}]"
                          + (f"  — {desc}" if desc else ""))

        elif args.command == "search":
            results = lib.search(args.query)
            if json_out:
                print(json.dumps(results, indent=2))
            elif not results:
                print("No matches found.")
            else:
                for r in results:
                    tags_str = ", ".join(r.get("tags", []))
                    print(f"  {r['name']} (score: {r['score']})  [{tags_str}]"
                          + (f"  — {r.get('description', '')}" if r.get("description") else ""))

        elif args.command == "info":
            meta = lib.info(args.name)
            if json_out:
                print(json.dumps(meta, indent=2))
            else:
                print(f"Name:        {meta['name']}")
                print(f"Description: {meta.get('description', '(none)')}")
                print(f"Tags:        {', '.join(meta.get('tags', [])) or '(none)'}")
                print(f"Lines:       {meta.get('lines', 0)}")
                print(f"Uses:        {meta.get('uses', 0)}")
                print(f"Created:     {meta.get('created', '?')}")
                print(f"Modified:    {meta.get('modified', '?')}")

        elif args.command == "edit":
            code = Path(args.file).read_text(encoding="utf-8")
            lib.edit(args.name, code)
            print(f"✓ Updated snippet '{args.name}'")

        elif args.command == "tag":
            if args.add:
                tags = [t.strip() for t in args.add.split(",") if t.strip()]
                lib.add_tags(args.name, tags)
                print(f"✓ Added tags to '{args.name}': {tags}")
            if args.remove:
                tags = [t.strip() for t in args.remove.split(",") if t.strip()]
                lib.remove_tags(args.name, tags)
                print(f"✓ Removed tags from '{args.name}': {tags}")

        elif args.command == "delete":
            lib.delete(args.name)
            print(f"✓ Deleted snippet '{args.name}'")

        elif args.command == "rename":
            lib.rename(args.old, args.new)
            print(f"✓ Renamed '{args.old}' → '{args.new}'")

        elif args.command == "duplicate":
            lib.duplicate(args.name, args.newname)
            print(f"✓ Duplicated '{args.name}' → '{args.newname}'")

        elif args.command == "export":
            print(lib.export_all(fmt=args.format))

        elif args.command == "import":
            data = Path(args.file).read_text(encoding="utf-8")
            result = lib.import_snippets(data, overwrite=args.overwrite)
            if json_out:
                print(json.dumps(result))
            else:
                print(f"✓ Imported {result['imported']} snippets, skipped {result['skipped']}")

        elif args.command == "use":
            code = lib.use(args.name)
            if args.output:
                Path(args.output).write_text(code, encoding="utf-8")
                print(f"✓ Copied '{args.name}' to {args.output}")
            else:
                print(code, end="")

        elif args.command == "stats":
            s = lib.stats()
            if json_out:
                print(json.dumps(s, indent=2))
            else:
                print(f"Total snippets: {s['total']}")
                print(f"Total lines:    {s['total_lines']}")
                print(f"Total uses:     {s['total_uses']}")
                if s.get("most_used"):
                    print(f"Most used:      {s['most_used']}")
                if s.get("tags"):
                    print("Tags:")
                    for tag, count in s["tags"].items():
                        print(f"  {tag}: {count}")

    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

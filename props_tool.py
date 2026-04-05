#!/usr/bin/env python3
"""
props_tool.py — Split or merge Java .properties files by key prefix.

Usage:
  Split (remove matching entries into a separate file):
    python props_tool.py split <file.properties> [--prefix el] [--out split_out.properties]
    python props_tool.py split <file.properties> --prefix-file prefixes.txt [--out split_out.properties]

  Merge (re-insert entries from a split file back in):
    python props_tool.py merge <file.properties> <split_file.properties>

Prefix file format (one prefix per line; blank lines and lines starting
with '#' are ignored):
    # UI component keys
    el
    kotori
    gauntlethelper

Both --prefix and --prefix-file may NOT be supplied together; use one or the
other. If neither is given, 'el' is used as the default.

Both operations sort remaining / merged entries alphabetically.
Comments and blank lines in the original file are preserved during split,
but are intentionally dropped during merge (entries only).
"""

import argparse
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

# A line is an entry if it matches:  key = value  or  key : value  or  key value
# Leading whitespace is allowed; keys may contain escaped spaces / colons.
_ENTRY_RE = re.compile(
    r"^[ \t]*"
    r"(?P<key>(?:[^\s:=\\]|\\.)+)"   # key: non-whitespace/colon/equals, or escape seq
    r"[ \t]*[:=]?[ \t]*"             # optional separator with surrounding spaces
    r"(?P<value>.*)$"
)


def _is_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    return stripped == "" or stripped.startswith("#") or stripped.startswith("!")


def parse_properties(path: Path) -> list[dict]:
    """
    Return a list of dicts, one per logical line, with keys:
      - type: 'entry' | 'comment' | 'blank'
      - raw:  the original line text (without trailing newline)
      - key:  (entries only) the property key
      - value:(entries only) the property value
    Handles line continuations (trailing backslash).
    """
    records = []
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if _is_comment_or_blank(line):
            records.append({
                "type": "blank" if line.strip() == "" else "comment",
                "raw": line,
            })
            i += 1
            continue

        # Handle line continuation
        continued = line
        while continued.rstrip("\r\n").endswith("\\") and i + 1 < len(lines):
            i += 1
            continued = continued.rstrip("\r\n")[:-1] + lines[i].lstrip()

        m = _ENTRY_RE.match(continued)
        if m:
            records.append({
                "type": "entry",
                "raw": continued,
                "key": m.group("key"),
                "value": m.group("value"),
            })
        else:
            # Unrecognised — treat as comment to avoid data loss
            records.append({"type": "comment", "raw": continued})
        i += 1
    return records


def format_entry(key: str, value: str) -> str:
    return f"{key}={value}"


def load_prefixes(args) -> list[str]:
    """Resolve the final, deduplicated prefix list from CLI arguments."""
    prefixes = []

    if args.prefix_file:
        pf = Path(args.prefix_file)
        if not pf.exists():
            sys.exit(f"Error: prefix file not found: {pf}")
        for raw in pf.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if stripped and not stripped.startswith("#"):
                prefixes.append(stripped)
        if not prefixes:
            sys.exit(f"Error: prefix file '{pf}' contains no valid prefixes.")

    elif args.prefix:
        prefixes.extend(args.prefix)  # --prefix is nargs='+'

    else:
        # Neither flag supplied — fall back to the original default
        prefixes = ["el", "El", "rlpl", "kotori"]

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for p in prefixes:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------

def cmd_split(args):
    src = Path(args.file)
    if not src.exists():
        sys.exit(f"Error: file not found: {src}")

    prefixes = load_prefixes(args)

    # Default output name: embed prefixes (truncated if many)
    if args.out:
        out_path = Path(args.out)
    else:
        label = "_".join(prefixes[:3])
        if len(prefixes) > 3:
            label += "_etc"
        out_path = src.with_stem(src.stem + f"_{label}_split")

    records = parse_properties(src)

    kept_entries: list[dict] = []
    split_entries: list[dict] = []
    non_entries: list[dict] = []   # comments / blanks — kept in main file

    for r in records:
        if r["type"] == "entry":
            if any(r["key"].startswith(p) for p in prefixes):
                split_entries.append(r)
            else:
                kept_entries.append(r)
        else:
            non_entries.append(r)

    if not split_entries:
        print(f"No entries matching prefixes {prefixes} found. Nothing to split.")
        return

    # Sort each group alphabetically by key
    kept_entries.sort(key=lambda r: r["key"].lower())
    split_entries.sort(key=lambda r: r["key"].lower())

    # Write main file: comments/blanks first, then sorted remaining entries
    with src.open("w", encoding="utf-8") as f:
        for r in non_entries:
            f.write(r["raw"] + "\n")
        if non_entries:
            f.write("\n")
        for r in kept_entries:
            f.write(format_entry(r["key"], r["value"]) + "\n")

    # Write split file: header comment + sorted extracted entries
    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"# Split from: {src.name}  (prefixes: {', '.join(prefixes)})\n")
        for r in split_entries:
            f.write(format_entry(r["key"], r["value"]) + "\n")

    print("Split complete.")
    print(f"  Prefixes    : {', '.join(prefixes)}")
    print(f"  Main file   : {src}  ({len(kept_entries)} entries)")
    print(f"  Split file  : {out_path}  ({len(split_entries)} entries)")


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def cmd_merge(args):
    src = Path(args.file)
    split_file = Path(args.split_file)

    for p in (src, split_file):
        if not p.exists():
            sys.exit(f"Error: file not found: {p}")

    main_records = parse_properties(src)
    split_records = parse_properties(split_file)

    # Collect all entries, keyed by key (split entries override duplicates)
    entries: dict[str, str] = {}
    for r in main_records:
        if r["type"] == "entry":
            entries[r["key"]] = r["value"]
    for r in split_records:
        if r["type"] == "entry":
            entries[r["key"]] = r["value"]

    # Preserve non-entry lines from the main file
    non_entries = [r for r in main_records if r["type"] != "entry"]

    # Sort merged entries alphabetically
    sorted_entries = sorted(entries.items(), key=lambda kv: kv[0].lower())

    with src.open("w", encoding="utf-8") as f:
        prev_blank = False
        for r in non_entries:
            is_blank = r["type"] == "blank"
            if is_blank and prev_blank:
                continue   # collapse consecutive blanks
            f.write(r["raw"] + "\n")
            prev_blank = is_blank
        if non_entries:
            f.write("\n")
        for key, value in sorted_entries:
            f.write(format_entry(key, value) + "\n")

    print("Merge complete.")
    print(f"  Main file   : {src}  ({len(sorted_entries)} entries total)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Split or merge Java .properties files by key prefix.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- split ---
    p_split = sub.add_parser("split", help="Extract matching entries into a separate file.")
    p_split.add_argument("file", help="Path to the source .properties file.")

    prefix_group = p_split.add_mutually_exclusive_group()
    prefix_group.add_argument(
        "--prefix", nargs="+", metavar="PREFIX",
        help="One or more key prefixes to split out (e.g. --prefix el com.example).",
    )
    prefix_group.add_argument(
        "--prefix-file", metavar="FILE",
        help=(
            "Path to a text file listing prefixes, one per line. "
            "Blank lines and lines starting with '#' are ignored."
        ),
    )

    p_split.add_argument(
        "--out", default=None,
        help="Path for the output split file (default: auto-generated from source name and prefixes).",
    )

    # --- merge ---
    p_merge = sub.add_parser("merge", help="Merge a split file back into the main file.")
    p_merge.add_argument("file", help="Path to the main .properties file.")
    p_merge.add_argument("split_file", help="Path to the split .properties file to merge in.")

    args = parser.parse_args()

    if args.command == "split":
        cmd_split(args)
    elif args.command == "merge":
        cmd_merge(args)


if __name__ == "__main__":
    main()
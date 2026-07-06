#!/usr/bin/env python3
"""Validate a JSONL evaluation dataset against eval/schema.json.

Usage: python scripts/validate-dataset.py <path.jsonl>
Exits 0 if valid, non-zero with per-line error messages on stderr otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "eval" / "schema.json").read_text())


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: validate-dataset.py <path.jsonl>", file=sys.stderr)
        return 2

    path = Path(argv[1])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    validator = jsonschema.Draft7Validator(SCHEMA)
    errors = 0
    with path.open() as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"line {line_no}: invalid JSON ({exc})", file=sys.stderr)
                errors += 1
                continue
            for err in validator.iter_errors(row):
                path_str = ".".join(str(p) for p in err.absolute_path) or "<root>"
                print(f"line {line_no}: {path_str}: {err.message}", file=sys.stderr)
                errors += 1
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

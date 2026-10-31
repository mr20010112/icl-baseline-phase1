#!/usr/bin/env python3
"""Create a portable ZIP, expanding project skill links to ordinary copies."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(output: Path) -> int:
    count = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for directory, subdirs, names in os.walk(ROOT, followlinks=True):
            current = Path(directory)
            rel = current.relative_to(ROOT)
            subdirs[:] = [n for n in subdirs if n not in {"__pycache__", ".pytest_cache", ".git"}
                          and not (rel == Path(".aris") and (n == "tmp" or n.endswith("lock.d")))]
            for name in sorted(names):
                file = current / name
                if name.endswith((".pyc", ".pyo")) or name in {".DS_Store"}:
                    continue
                if not file.is_file():
                    raise ValueError(f"Unresolved package entry: {file}")
                if not file.resolve().is_relative_to(ROOT):
                    raise ValueError(f"Package link leaves workspace: {file}")
                archive.write(file, (Path("auto-research") / file.relative_to(ROOT)).as_posix())
                count += 1
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT.parent / "auto-research.zip"))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.is_relative_to(ROOT):
        parser.error("Archive must be outside auto-research to avoid recursion")
    count = build(output)
    print(f"{output}: {count} files, {output.stat().st_size} bytes")

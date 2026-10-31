#!/usr/bin/env python3
"""Verify an exact LIBERO payload without dependencies or network access."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from gates import digest


def verify_manifest(directory: Path, manifest: dict, expected_digest: str) -> dict:
    """Check the complete file set, sizes, SHA256s, and gates.digest tree hash."""
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError(f"Not a data directory: {directory}")
    entries = manifest["files"]
    expected = {}
    for row in entries:
        name = row["path"]
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != name or name in expected:
            raise ValueError(f"Unsafe/duplicate manifest path: {name}")
        if not re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", "")):
            raise ValueError(f"Missing SHA256: {name}")
        expected[name] = row
    if len(expected) != manifest["n_files"]:
        raise ValueError("Manifest n_files mismatch")
    # Reject symlinks: gates.digest deliberately does not descend symlink directories.
    paths = list(directory.rglob("*"))
    if any(p.is_symlink() for p in paths):
        raise ValueError("Data payload must not contain symlinks")
    actual = {p.relative_to(directory).as_posix() for p in paths if p.is_file()}
    if actual != set(expected):
        raise ValueError(f"File set mismatch: missing={sorted(set(expected)-actual)}, extra={sorted(actual-set(expected))}")
    total = 0
    for name, row in expected.items():
        path = directory / name
        if path.stat().st_size != row["size"]:
            raise ValueError(f"Size mismatch: {name}")
        if digest(path) != row["sha256"]:
            raise ValueError(f"SHA256 mismatch: {name}")
        total += row["size"]
    if total != manifest["total_bytes"]:
        raise ValueError("Manifest total_bytes mismatch")
    value = digest(directory)
    if value != expected_digest:
        raise ValueError(f"Directory digest mismatch: {value} != {expected_digest}")
    return {"status": "pass", "path": str(directory), "n_files": len(expected),
            "total_bytes": total, "fingerprint": value, "version": manifest.get("revision")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[1] / "data/libero-hf-manifest.json")
    parser.add_argument("--contract", type=Path, default=Path("contracts/baseline/v1.yaml"))
    parser.add_argument("--output", type=Path, required=True, help="Evidence JSON outside the data directory")
    args = parser.parse_args()
    try:
        if args.output.resolve().is_relative_to(args.data_dir.resolve()):
            raise ValueError("Evidence must be outside the verified payload")
        manifest = json.loads(args.manifest.read_text())
        protocol = json.loads(args.contract.read_text())
        if manifest["revision"] != protocol["data"]["version"]:
            raise ValueError("Manifest revision differs from protocol")
        result = verify_manifest(args.data_dir, manifest, protocol["data"]["fingerprint"])
        result.update(manifest_sha256=digest(args.manifest), contract_sha256=digest(args.contract))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

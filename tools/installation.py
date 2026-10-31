"""Project installation reconciliation with explicit, fingerprinted local overrides.

Upstream installers run in staging, never against customized project files.
Preflight all destinations before replacing any managed copy or updating manifests.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile

from contracts import ProjectError, atomic_json, load, sha


def preserve_file(path: Path) -> None:
    """Keep the exact previous bytes under a content-addressed history name."""
    if path.is_file():
        dest = path.parent / "history" / f"{path.stem}-{sha(path)[:16]}{path.suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copyfile(path, dest)


def _path(root: Path, value: str) -> Path:
    p = Path(value)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise ProjectError(f"Installation path must be project relative: {value}")
    # Resolve the parent for safety; an existing managed symlink itself may point
    # to the same project vendor tree and is validated separately below.
    target = root / p
    if not target.parent.resolve().is_relative_to(root.resolve()):
        raise ProjectError(f"Installation path leaves project: {value}")
    return target


def _contents(path: Path) -> dict[str, str]:
    if path.is_file():
        return {".": sha(path)}
    if not path.is_dir():
        return {}
    return {p.relative_to(path).as_posix(): sha(p) for p in path.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


def configuration(root: Path) -> dict:
    path = root / "configs/local-overrides.json"
    cfg = load(path) if path.exists() else {"schema_version": 1, "overrides": [], "project_skills": []}
    if cfg.get("schema_version") != 1:
        raise ProjectError("Unknown local override schema")
    seen = set()
    for row in cfg.get("overrides", []):
        if not isinstance(row, dict) or not row.get("reason"):
            raise ProjectError("Local override requires a reason")
        dest = row.get("path", "")
        source = _path(root, row.get("source", ""))
        _path(root, dest)
        if dest in seen or not dest.startswith((".claude/skills/", ".agents/skills/")):
            raise ProjectError(f"Invalid or duplicate override: {dest}")
        seen.add(dest)
        if not source.is_file() or sha(source) != row.get("sha256"):
            raise ProjectError(f"Canonical local override changed: {row.get('source')}")
    skill_names = set()
    for row in cfg.get("project_skills", []):
        name = row.get("name", "")
        if not name or Path(name).name != name or name in {".", ".."} or name in skill_names:
            raise ProjectError("Invalid or duplicate project skill name")
        skill_names.add(name)
        source = _path(root, row.get("source", ""))
        if not row.get("files") or _contents(source) != row["files"]:
            raise ProjectError(f"Canonical project skill changed: {row.get('source')}")
    return cfg


def _preflight(root: Path, entries: list[dict], cfg: dict, *, installed: bool = False) -> None:
    matched = set()
    for row in entries:
        target, source = _path(root, row["path"]), _path(root, row["source"])
        expected = _contents(source)
        if not expected:
            raise ProjectError(f"Managed installation source missing: {row['source']}")
        overrides = []
        for override in cfg.get("overrides", []):
            try:
                rel = Path(override["path"]).relative_to(row["path"]).as_posix()
            except ValueError:
                continue
            matched.add(override["path"])
            key = "." if rel == "." else rel
            if key not in expected:
                raise ProjectError(f"Override is not an upstream file: {override['path']}")
            overrides.append((key, override))
        if not target.exists() and not target.is_symlink():
            if installed:
                raise ProjectError(f"Managed installation missing: {row['path']}; run init")
            continue
        if target.is_symlink() and target.resolve() != source.resolve():
            raise ProjectError(f"Conflicting managed link: {row['path']}")
        actual = _contents(target)
        allowed = dict(expected)
        for key, override in overrides:
            if installed or actual.get(key) == override["sha256"]:
                allowed[key] = override["sha256"]
        if actual != allowed:
            raise ProjectError(f"Managed copy has unregistered local changes: {row['path']}")
        if installed and overrides and target.is_symlink():
            raise ProjectError(f"Local override must remain a project copy: {row['path']}")
    if installed:
        missing = {row["path"] for row in cfg.get("overrides", [])} - matched
        if missing:
            raise ProjectError(f"Local overrides not covered by installation: {sorted(missing)}")


def _project_entries(cfg: dict) -> list[dict]:
    return [{"path": f"{host}/skills/{row['name']}", "source": row["source"], "project_skill": True}
            for row in cfg.get("project_skills", []) for host in (".claude", ".agents")]


def _manifests(root: Path) -> list[Path]:
    return [p for p in sorted((root / ".aris").glob("installed-*.txt*"))
            if p.is_file() and "repo_root\t" in p.read_text()]


def validate_installation(root: Path) -> dict:
    cfg = configuration(root)
    record_path = root / ".aris/installation.json"
    if not record_path.is_file():
        raise ProjectError("Project installation record missing; run init")
    entries = load(record_path).get("links", [])
    if not entries:
        raise ProjectError("Managed installation inventory empty; run init")
    _preflight(root, entries, cfg, installed=True)
    _preflight(root, _project_entries(cfg), {**cfg, "overrides": []}, installed=True)
    # Presence, current roots, and declared native target/source are all checked.
    for name in ("installed-skills.txt", "installed-skills-codex.txt"):
        if not (root / ".aris" / name).is_file():
            raise ProjectError(f"Native installation manifest missing: {name}")
    for path in _manifests(root):
        rows = [line.split("\t") for line in path.read_text().splitlines()]
        header = {row[0]: row[1] for row in rows if len(row) == 2}
        if header.get("repo_root") != str(root / "vendor/aris") or header.get("project_root") != str(root):
            raise ProjectError(f"Stale installation manifest roots: {path.name}; run init")
        for row in rows:
            if len(row) == 5 and row[0] in {"skill", "support", "agent"}:
                ref = {"path": row[3], "source": str(Path("vendor/aris") / row[2])}
                _preflight(root, [ref], {**cfg, "overrides": [x for x in cfg.get("overrides", []) if x["path"].startswith(row[3] + "/")]}, installed=True)
    return {"status": "PASS", "managed_entries": len(entries), "local_overrides": len(cfg.get("overrides", [])),
            "project_skills": len(cfg.get("project_skills", [])), "native_roots": str(root)}


def reconcile(root: Path, native_install, upstream_check) -> dict:
    root = root.resolve()
    upstream_check(root)
    cfg = configuration(root)
    old_record = root / ".aris/installation.json"
    old_entries = load(old_record).get("links", []) if old_record.exists() else []
    # All existing copies are checked before creating links or rebasing headers.
    _preflight(root, old_entries, cfg)
    _preflight(root, _project_entries(cfg), cfg)
    with tempfile.TemporaryDirectory(prefix="auto-research-install-") as tmp:
        stage = Path(tmp)
        shutil.copytree(root / "vendor/aris", stage / "vendor/aris", ignore=shutil.ignore_patterns("__pycache__", ".git"))
        shutil.copytree(root / "configs", stage / "configs")
        shutil.copytree(root / "docs/source", stage / "docs/source")
        native_install(stage)
        record = load(stage / ".aris/installation.json")
        entries = record["links"] + _project_entries(cfg)
        _preflight(root, entries, cfg)
        for row in entries:
            target, source = _path(root, row["path"]), _path(root, row["source"])
            overrides = [x for x in cfg.get("overrides", []) if x["path"].startswith(row["path"] + "/")]
            target.parent.mkdir(parents=True, exist_ok=True)
            if overrides:
                if target.is_symlink():
                    target.unlink()
                if not target.exists():
                    shutil.copytree(source, target)
                for override in overrides:
                    dest = _path(root, override["path"])
                    dest.write_bytes(_path(root, override["source"]).read_bytes())
                row["mode"] = "local_copy"
            else:
                if target.is_symlink():
                    target.unlink()
                elif target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
                target.symlink_to(os.path.relpath(source, target.parent))
                row["mode"] = "symlink"
        for path in _manifests(stage):
            dest = root / ".aris" / path.name
            preserve_file(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(path.read_text().replace(str(stage), str(root)))
        # Headers in managed previous manifests must also resolve after moving.
        for path in _manifests(root):
            text = path.read_text()
            lines = ["repo_root\t" + str(root / "vendor/aris") if line.startswith("repo_root\t") else
                     "project_root\t" + str(root) if line.startswith("project_root\t") else line
                     for line in text.splitlines()]
            rebased = "\n".join(lines) + "\n"
            if rebased != text:
                preserve_file(path)
                path.write_text(rebased)
        for name in ("installed-agent-profiles.txt",):
            source = stage / ".aris" / name
            if source.is_file():
                preserve_file(root / ".aris" / name)
                shutil.copyfile(source, root / ".aris" / name)
        logs = root / "reports/install"
        logs.mkdir(parents=True, exist_ok=True)
        for path in (stage / "reports/install").glob("*.log"):
            preserve_file(logs / path.name)
            shutil.copyfile(path, logs / path.name)
        # Restore absent initial files even if an empty state/wiki directory
        # already exists, without overwriting any research memory or phases.
        for name in ("research-wiki", ".aris/runs"):
            for source in (stage / name).rglob("*"):
                if source.is_file():
                    dest = root / name / source.relative_to(stage / name)
                    if not dest.exists():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, dest)
        record.update({"links": entries, "relative_links": sum(x["mode"] == "symlink" for x in entries),
                       "installation": "native installers in staging + verified project reconciliation",
                       "local_overrides": cfg.get("overrides", []), "project_skills": cfg.get("project_skills", [])})
        preserve_file(old_record)
        atomic_json(old_record, record)
    models = load(root / "configs/models.json")
    if models.get("schema_version", 1) >= 2:
        from model_routes import sync_routes
        sync_routes(root)
    checked = validate_installation(root)
    return {**{key: value for key, value in record.items() if key != "links"}, "verification": checked}

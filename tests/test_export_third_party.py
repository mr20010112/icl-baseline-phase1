"""Temporary standalone exports; no downloads, model calls or training."""
from __future__ import annotations

import json
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
import export_third_party as exporter


class ExportThirdPartyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="contextflow-export-test-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name)
        cls.source = cls.base / "source"
        cls.time = "2026-10-30T00:00:00+00:00"
        exporter.build(cls.source, phase=1, root=PROJECT, initialize_git=False, exported_at=cls.time)
        cls.marker = b"PRIVATE_SENTINEL_" + b"DO_NOT_EXPORT"
        for relative in ("reports/private.txt", "runs/old/manifest.json", ".aris/runs/project.json",
                         ".agents/private.txt", ".claude/private.txt", "idea-stage/private.txt",
                         "refine-logs/private.txt", "research-wiki/private.txt", "analysis/private.txt",
                         "paper/private.txt", "handoffs/implementation/private.txt",
                         "handoffs/scout/private.txt", "handoffs/proposal/private.txt",
                         ".env", ".env.local", "configs/operator.private.json",
                         "tools/__pycache__/private.pyc", "tools/private.pyc", "tools/runtime.lock"):
            path = cls.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(cls.marker)
        local_path = str(Path.home()).encode() + b"/private-resource"
        (cls.source / "docs/private-machine.md").write_bytes(local_path)
        resources = {group: [{"id": "old", "path": local_path.decode()}]
                     for group in ("data", "environments", "compute", "weights")}
        (cls.source / "configs/resources.json").write_bytes(exporter.encoded(resources))
        research = json.loads((cls.source / "configs/research.json").read_bytes())
        research.update(superseded_direction={"path": local_path.decode()},
                        legacy_import={"path": local_path.decode()}, baselines={"private": True})
        research["baseline"]["repo_path"] = local_path.decode()
        (cls.source / "configs/research.json").write_bytes(exporter.encoded(research))
        mcp = json.loads((cls.source / ".mcp.json").read_bytes())
        mcp["mcpServers"]["codex"]["env"]["PRIVATE_TOKEN"] = cls.marker.decode()
        (cls.source / ".mcp.json").write_bytes(exporter.encoded(mcp))
        budget = json.loads((cls.source / "configs/budget.json").read_bytes())
        budget["real_enabled"] = True
        budget["scopes"]["real"]["max_attempts"] = 99
        (cls.source / "configs/budget.json").write_bytes(exporter.encoded(budget))
        cls.output = cls.base / "export"
        # Git config, rather than an inherited model/session identity, supplies author.
        cls.git_env = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "user.name",
                       "GIT_CONFIG_VALUE_0": "Export Fixture", "GIT_CONFIG_KEY_1": "user.email",
                       "GIT_CONFIG_VALUE_1": "export-fixture@example.invalid"}
        with mock.patch.dict(os.environ, cls.git_env):
            cls.result = exporter.build(cls.output, phase=1, root=cls.source, exported_at=cls.time)
        cls.manifest = json.loads((cls.output / "EXPORT_MANIFEST.json").read_bytes())

    def test_allowlist_and_exclusions(self):
        for relative in (*exporter.FILES, "README.md", ".gitignore", "runs/.gitkeep",
                         "tools/export_third_party.py", "tests/test_export_third_party.py",
                         "vendor/aris/.env.example"):
            self.assertTrue((self.output / relative).is_file(), relative)
        for relative in ("contracts/legacy-icl", "baseline/checks", "baseline/legacy-evidence.json",
                         "reports/private.txt", "runs/old", ".aris", ".agents", ".claude", "skills",
                         "idea-stage", "refine-logs", "research-wiki", "analysis", "paper",
                         "handoffs/implementation", "handoffs/scout", "handoffs/proposal",
                         ".env", ".env.local", "configs/operator.private.json",
                         "tools/__pycache__", "tools/private.pyc", "tools/runtime.lock", "docs/private-machine.md"):
            self.assertFalse((self.output / relative).exists(), relative)
        papers = [p.relative_to(self.output).as_posix() for p in (self.output / "reports").rglob("*") if p.is_file()]
        self.assertEqual(papers, [exporter.PAPER])
        self.assertEqual((self.output / "vendor/aris/.env.example").read_bytes(),
                         (self.source / "vendor/aris/.env.example").read_bytes())

    def test_sanitization(self):
        read = lambda name: json.loads((self.output / name).read_bytes())
        self.assertEqual(read("configs/resources.json"), {group: [] for group in
                         ("data", "environments", "compute", "weights")})
        research = read("configs/research.json")
        source = json.loads((self.source / "configs/research.json").read_bytes())
        for key in ("question", "setting", "benchmarks"):
            self.assertEqual(research[key], source[key])
        for key in ("superseded_direction", "legacy_import", "baselines"):
            self.assertNotIn(key, research)
        self.assertEqual(research["baseline"]["repo_path"], exporter.CHECKOUT)
        self.assertFalse(read("configs/budget.json")["real_enabled"])
        self.assertEqual(read("configs/local-overrides.json"),
                         {"schema_version": 1, "overrides": [], "project_skills": []})
        self.assertTrue(all(value == 0 for key, value in read("configs/budget.json")["scopes"]["real"].items() if key.startswith("max_")))
        for server in read(".mcp.json")["mcpServers"].values():
            self.assertEqual(server["command"], "python3")
            self.assertFalse(Path(server["args"][0]).is_absolute())
            self.assertNotIn("PRIVATE_TOKEN", server["env"])
        for entry in self.manifest["files"]:
            data = (self.output / entry["path"]).read_bytes()
            self.assertIsNone(exporter.LOCAL_PATH.search(data), entry["path"])
            self.assertNotIn(str(self.source).encode(), data)
            self.assertNotIn(self.marker, data)
        self.assertEqual({row["path"] for row in self.manifest["sanitizations"]},
                         {"configs/resources.json", "configs/research.json", "configs/budget.json",
                          ".mcp.json", "docs/configuration.md", "configs/local-overrides.json", "contracts/.registry.json"})

    def test_both_frozen_protocols_export_with_registry_and_manifest_hashes(self):
        protocol = json.loads((self.output / exporter.PROTOCOL).read_bytes())
        registry = json.loads((self.output / "contracts/.registry.json").read_bytes())
        paper_hash = exporter.digest((self.output / exporter.PAPER).read_bytes())
        self.assertEqual(paper_hash, exporter.PAPER_SHA256)
        self.assertEqual(set(registry["contracts"]), {exporter.FROZEN_PROTOCOL, exporter.PROTOCOL})
        for relative in (exporter.FROZEN_PROTOCOL, exporter.PROTOCOL):
            self.assertEqual(exporter.digest((self.output / relative).read_bytes()),
                             registry["contracts"][relative]["sha256"])
            self.assertTrue(registry["contracts"][relative]["frozen_at"])
        for row in protocol["baseline"]["reported_metrics"]:
            self.assertEqual(row["source_sha256"], paper_hash)
        self.assertEqual(self.manifest["protocol"],
                         {"path": exporter.PROTOCOL, "sha256": exporter.digest((self.output / exporter.PROTOCOL).read_bytes()),
                          "status": "frozen", "frozen_at": registry["contracts"][exporter.PROTOCOL]["frozen_at"]})
        for seed in (42, 43, 44):
            job = json.loads((self.output / f"experiments/baseline-seed{seed}.json").read_bytes())
            self.assertEqual(job["contract"], exporter.PROTOCOL)
        for name in (exporter.PROTOCOL, exporter.FROZEN_PROTOCOL, exporter.PAPER, "contracts/.registry.json"):
            self.assertEqual((self.source / name).read_bytes(), (self.output / name).read_bytes())
        indexed = {row["path"] for row in self.manifest["files"]}
        actual = {p.relative_to(self.output).as_posix() for p in self.output.rglob("*")
                  if p.is_file() and ".git" not in p.relative_to(self.output).parts}
        self.assertEqual(indexed | {"EXPORT_MANIFEST.json"}, actual)
        for row in self.manifest["files"]:
            data = (self.output / row["path"]).read_bytes()
            self.assertEqual(exporter.digest(data), row["sha256"])
            self.assertEqual(len(data), row["bytes"])

    def test_deterministic_commit_and_no_remote(self):
        second = self.base / "repeat"
        with mock.patch.dict(os.environ, self.git_env):
            result = exporter.build(second, phase=1, root=self.source, exported_at=self.time)
        self.assertEqual(result["commit"], self.result["commit"])
        self.assertEqual(exporter.git(self.output, "log", "-1", "--format=%s"), exporter.COMMIT_MESSAGE + "; phase 1")
        self.assertEqual(exporter.git(self.output, "log", "-1", "--format=%an <%ae>"),
                         "Export Fixture <export-fixture@example.invalid>")
        self.assertEqual(exporter.git(self.output, "rev-list", "--count", "HEAD"), "1")
        self.assertEqual(exporter.git(self.output, "remote"), "")
        self.assertEqual(exporter.git(self.output, "status", "--porcelain"), "")

    def test_refuses_inside_project_and_nonempty_output(self):
        with self.assertRaisesRegex(ValueError, "outside this project"):
            exporter.build(self.source / "nested", phase=1, root=self.source)
        before = (self.output / "README.md").read_bytes()
        with self.assertRaisesRegex(ValueError, "non-empty"):
            exporter.build(self.output, phase=1, root=self.source)
        self.assertEqual(before, (self.output / "README.md").read_bytes())

    def test_publish_to_separate_filesystem_preserves_payload(self):
        for error in (errno.EXDEV, errno.EROFS, errno.EBUSY):
            with self.subTest(error=error):
                output = self.base / f"separate-volume-{error}"
                output.mkdir()  # Existing empty output is explicitly allowed.
                with mock.patch.object(exporter.os, "replace", side_effect=OSError(error, "mount boundary")):
                    exporter.build(output, phase=1, root=self.source, initialize_git=False, exported_at=self.time)
                self.assertEqual((output / "EXPORT_MANIFEST.json").read_bytes(),
                                 (self.output / "EXPORT_MANIFEST.json").read_bytes())
                self.assertEqual((output / exporter.PROTOCOL).read_bytes(), (self.output / exporter.PROTOCOL).read_bytes())

    def test_byte_verified_vendor_lock_is_preserved(self):
        # Synthetic pinned vendor file in this disposable fixture, never upstream.
        lockfile = self.source / "vendor/aris/fixture.lock"
        registry = self.source / "configs/upstream-lock.json"
        original = registry.read_bytes()
        try:
            lockfile.write_bytes(b"synthetic pinned dependency lock\n")
            value = json.loads(original)
            value["files"]["fixture.lock"] = exporter.digest(lockfile.read_bytes())
            registry.write_bytes(exporter.encoded(value))
            payload = exporter.plan(self.source, self.time, phase=1)
            self.assertEqual(payload["vendor/aris/fixture.lock"], lockfile.read_bytes())
            self.assertNotIn("tools/runtime.lock", payload)
        finally:
            registry.write_bytes(original)
            lockfile.unlink()

    def test_changed_paper_or_protocol_is_rejected_before_writing(self):
        for relative, message in ((exporter.PAPER, "paper SHA256"),
                                  (exporter.FROZEN_PROTOCOL, "Frozen protocol"),
                                  (exporter.PROTOCOL, "Frozen protocol")):
            path = self.source / relative
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"\n")
                with self.assertRaisesRegex(ValueError, message):
                    exporter.build(self.base / "rejected", phase=1, root=self.source, initialize_git=False)
                self.assertFalse((self.base / "rejected").exists())
            finally:
                path.write_bytes(original)

    def test_registry_hash_mismatch_is_rejected_before_writing(self):
        path = self.source / "contracts/.registry.json"
        original = path.read_bytes()
        try:
            for relative in (exporter.FROZEN_PROTOCOL, exporter.PROTOCOL):
                with self.subTest(protocol=relative):
                    registry = json.loads(original)
                    registry["contracts"][relative]["sha256"] = "0" * 64
                    path.write_bytes(exporter.encoded(registry))
                    before = path.read_bytes()
                    output = self.base / "hash-mismatch-rejected"
                    with self.assertRaisesRegex(ValueError, "Frozen protocol differs from registry"):
                        exporter.build(output, phase=1, root=self.source, initialize_git=False)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertFalse(output.exists())
        finally:
            path.write_bytes(original)

    def test_registry_requires_exactly_two_frozen_protocols(self):
        path = self.source / "contracts/.registry.json"
        original = path.read_bytes()
        try:
            for relative in (exporter.FROZEN_PROTOCOL, exporter.PROTOCOL):
                for change in ("missing_entry", "missing_frozen_at"):
                    with self.subTest(protocol=relative, change=change):
                        registry = json.loads(original)
                        if change == "missing_entry":
                            del registry["contracts"][relative]
                        else:
                            del registry["contracts"][relative]["frozen_at"]
                        path.write_bytes(exporter.encoded(registry))
                        with self.assertRaisesRegex(ValueError, "every selected frozen|lacks frozen_at"):
                            exporter.plan(self.source, self.time, phase=1)
            registry = json.loads(original)
            registry["contracts"]["contracts/baseline/v3.yaml"] = registry["contracts"][exporter.PROTOCOL]
            path.write_bytes(exporter.encoded(registry))
            payload = exporter.plan(self.source, self.time, phase=1)
            self.assertEqual(set(json.loads(payload["contracts/.registry.json"])["contracts"]),
                             {exporter.FROZEN_PROTOCOL, exporter.PROTOCOL})
        finally:
            path.write_bytes(original)

    def test_job_bound_to_v1_is_rejected_before_writing(self):
        for seed in (42, 43, 44):
            with self.subTest(seed=seed):
                path = self.source / f"experiments/baseline-seed{seed}.json"
                original = path.read_bytes()
                try:
                    job = json.loads(original)
                    job["contract"] = exporter.FROZEN_PROTOCOL
                    path.write_bytes(exporter.encoded(job))
                    output = self.base / f"v1-job-rejected-{seed}"
                    with self.assertRaisesRegex(ValueError, f"Seed {seed} job does not bind baseline v2"):
                        exporter.build(output, phase=1, root=self.source, initialize_git=False)
                    self.assertFalse(output.exists())
                finally:
                    path.write_bytes(original)

    def test_operator_text_describes_both_protocols_as_frozen(self):
        for relative in ("README.md", "docs/configuration.md", "handoffs/third-party/README.md", "baseline/runner/README.md"):
            text = " ".join((self.output / relative).read_text().split())
            with self.subTest(path=relative):
                self.assertIn("already frozen", text)
                self.assertIn("version chain", text)
                self.assertIn("must not create, edit or re-freeze any protocol", text)
                self.assertIn("new version", text)
                self.assertNotRegex(text, r"unfrozen|not frozen|未冻结|尚未冻结")

    def test_initial_dry_run_explains_operator_configuration(self):
        result = subprocess.run(["timeout", "600", sys.executable,
                                 "baseline/runner/contextflow_repro.py", "--seed", "42", "--dry-run",
                                 "--run-dir", str(self.base / "dry-run")], cwd=self.output,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                capture_output=True, text=True, timeout=600)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Missing evidence: " + exporter.CHECKOUT, result.stderr)
        self.assertIn("configs/research.json:baseline.repo_path", result.stderr)

    def test_limit_tools_and_phase1_amended_chain_export(self):
        for ref in ("tools/amend_limits.py", "tools/review_batch.py", "docs/operator-limit-authorization.md"):
            self.assertTrue((self.output / ref).is_file(), ref)
        amended = self.base / "amended-source"
        shutil.copytree(self.output, amended, ignore=shutil.ignore_patterns(".git"))
        p = json.loads((amended / exporter.PROTOCOL).read_text())
        result = exporter.amend_limits.apply_limits(amended, 1, p["stopping"]["timeout_seconds"]*2,
                                                   reason="Synthetic amended export fixture")
        output = self.base / "amended-export"
        built = exporter.build(output, phase=1, root=amended, initialize_git=False, exported_at=self.time)
        self.assertEqual(built["verification"]["contract_verify"]["count"], 3)
        self.assertEqual(built["verification"]["static"]["jobs"], 6)
        for row in result["protocols"]:
            self.assertEqual((output / row["successor"]).read_bytes(), (amended / row["successor"]).read_bytes())
            for ref in row["jobs"].values():
                self.assertTrue((output / ref).is_file())


if __name__ == "__main__":
    unittest.main()

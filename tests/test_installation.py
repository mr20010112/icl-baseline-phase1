"""Installation safety and relocation regressions; no external calls or training."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
import installation
import research
from contracts import ProjectError, atomic_json, load, sha


class InstallationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="installation-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for path, content in {
            "vendor/aris/skills/gemini-search/SKILL.md": "upstream search\n",
            "vendor/aris/skills/skills-codex/gemini-search/SKILL.md": "upstream codex search\n",
            "vendor/aris/tools/research_wiki.py": "# upstream helper\n",
            "docs/source/guide.md": "guide\n",
            "skills/antigravity-search/SKILL.md": "custom search\n",
            "skills/project-research/SKILL.md": "project workflow\n",
        }.items():
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        atomic_json(self.root / "configs/resources.json", {"data": []})
        atomic_json(self.root / "configs/models.json", {})
        self.entries = [
            {"path": ".claude/skills/gemini-search", "source": "vendor/aris/skills/gemini-search"},
            {"path": ".agents/skills/gemini-search", "source": "vendor/aris/skills/skills-codex/gemini-search"},
            {"path": ".aris/tools", "source": "vendor/aris/tools"},
        ]
        self.cfg = {"schema_version": 1, "overrides": [
            {"path": entry["path"] + "/SKILL.md", "source": "skills/antigravity-search/SKILL.md",
             "sha256": sha(self.root / "skills/antigravity-search/SKILL.md"), "reason": "local scout"}
            for entry in self.entries[:2]],
            "project_skills": [{"name": "project-research", "source": "skills/project-research",
                                "files": {"SKILL.md": sha(self.root / "skills/project-research/SKILL.md")}}]}
        atomic_json(self.root / "configs/local-overrides.json", self.cfg)
        for entry in self.entries:
            shutil.copytree(self.root / entry["source"], self.root / entry["path"])
        atomic_json(self.root / ".aris/installation.json", {"links": self.entries})
        # Existing customized Claude copy must be preserved, while Codex upgrades.
        (self.root / self.cfg["overrides"][0]["path"]).write_text("custom search\n")
        for name in ("installed-skills.txt", "installed-skills-codex.txt"):
            (self.root / ".aris" / name).write_text("version\t1\nrepo_root\t/old/vendor/aris\nproject_root\t/old\n")

    def native(self, stage):
        # The real upstream processes are replaced by deterministic staged output.
        for entry in self.entries:
            target = stage / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(stage / entry["source"])
        atomic_json(stage / ".aris/installation.json", {"links": self.entries, "installer_results": [], "status": "PASS"})
        for name, entry in zip(("installed-skills.txt", "installed-skills-codex.txt"), self.entries):
            source = Path(entry["source"]).relative_to("vendor/aris")
            (stage / ".aris" / name).write_text(
                f"version\t1\nrepo_root\t{stage}/vendor/aris\nproject_root\t{stage}\n"
                f"skill\tgemini-search\t{source}\t{entry['path']}\tsymlink\n")
        (stage / "reports/install").mkdir(parents=True)
        (stage / "reports/install/claude.log").write_text("staged native install\n")
        (stage / "research-wiki").mkdir()
        (stage / "research-wiki/index.md").write_text("wiki\n")
        atomic_json(stage / ".aris/runs/project.json", {"run_id": "project"})

    def reconcile(self):
        return installation.reconcile(self.root, self.native, lambda root: {"status": "PASS"})

    def test_registered_override_preserved_and_init_is_repeatable(self):
        self.reconcile()
        self.reconcile()
        for row in self.cfg["overrides"]:
            self.assertEqual((self.root / row["path"]).read_text(), "custom search\n")
            self.assertFalse((self.root / row["path"]).parent.is_symlink())
        for host in (".claude", ".agents"):
            target = self.root / host / "skills/project-research"
            self.assertTrue(target.is_symlink())
            self.assertFalse(Path(target.readlink()).is_absolute())
        self.assertTrue((self.root / ".aris/tools").is_symlink())
        result = installation.validate_installation(self.root)
        self.assertEqual(result["status"], "PASS")
        self.assertIn(str(self.root / "vendor/aris"), (self.root / ".aris/installed-skills-codex.txt").read_text())
        self.assertTrue((self.root / ".aris/history").is_dir())

    def test_unregistered_late_change_does_not_partially_convert_copies(self):
        (self.root / ".aris/tools/research_wiki.py").write_text("unregistered customization\n")
        with self.assertRaisesRegex(ProjectError, "unregistered local changes"):
            self.reconcile()
        self.assertFalse((self.root / ".claude/skills/gemini-search").is_symlink())
        self.assertIn("/old", (self.root / ".aris/installed-skills.txt").read_text())

    def test_new_collision_found_before_any_managed_copy_changes(self):
        collision = self.root / ".claude/skills/project-research"
        collision.mkdir()
        (collision / "SKILL.md").write_text("user version\n")
        with self.assertRaisesRegex(ProjectError, "unregistered local changes"):
            self.reconcile()
        self.assertFalse((self.root / ".aris/tools").is_symlink())
        self.assertEqual((collision / "SKILL.md").read_text(), "user version\n")

    def test_validate_rejects_stale_manifest_and_override_drift(self):
        with self.assertRaises(ProjectError):
            installation.validate_installation(self.root)
        self.reconcile()
        manifest = self.root / ".aris/installed-skills-codex.txt"
        manifest.write_text(manifest.read_text().replace(str(self.root), "/old"))
        with self.assertRaisesRegex(ProjectError, "Stale installation"):
            installation.validate_installation(self.root)
        self.reconcile()
        (self.root / self.cfg["overrides"][1]["path"]).write_text("unexpected\n")
        with self.assertRaisesRegex(ProjectError, "unregistered local changes"):
            installation.validate_installation(self.root)

    def test_changed_canonical_override_requires_new_declared_fingerprint(self):
        (self.root / "skills/antigravity-search/SKILL.md").write_text("changed canonical\n")
        with self.assertRaisesRegex(ProjectError, "Canonical local override changed"):
            self.reconcile()
        self.assertFalse((self.root / ".aris/tools").is_symlink())

    def test_empty_state_directory_does_not_prevent_initial_state_recovery(self):
        (self.root / ".aris/runs").mkdir()
        (self.root / "research-wiki").mkdir()
        self.reconcile()
        self.assertEqual(load(self.root / ".aris/runs/project.json")["run_id"], "project")
        self.assertTrue((self.root / "research-wiki/index.md").is_file())
        state = {"run_id": "project", "status": "existing research"}
        atomic_json(self.root / ".aris/runs/project.json", state)
        self.reconcile()
        self.assertEqual(load(self.root / ".aris/runs/project.json"), state)

    def test_validate_requires_project_skill_and_unique_names(self):
        self.reconcile()
        (self.root / ".agents/skills/project-research").unlink()
        with self.assertRaisesRegex(ProjectError, "installation missing"):
            installation.validate_installation(self.root)
        self.cfg["project_skills"].append(self.cfg["project_skills"][0])
        atomic_json(self.root / "configs/local-overrides.json", self.cfg)
        with self.assertRaisesRegex(ProjectError, "duplicate project skill"):
            self.reconcile()

    def test_doctor_preserves_previous_report_and_observes_host(self):
        prior = {"python": "historical"}
        atomic_json(self.root / "reports/doctor.json", prior)
        with mock.patch.object(research, "upstream_check", return_value={"status": "PASS"}):
            result = research.doctor(self.root)
        self.assertEqual(result["executable"], sys.executable)
        self.assertIn("agy", result["dependencies"])
        self.assertIn("proc", result["host_features"])
        archived = list((self.root / "reports/history").glob("doctor-*.json"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(load(archived[0]), prior)


if __name__ == "__main__":
    unittest.main()

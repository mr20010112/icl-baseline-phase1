"""Clean proposer handoffs; positive baseline status is an explicit mock fixture."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
from contracts import ProjectError, sha
import project_workflow


class ProjectWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="auto-research-proposal-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write("baseline/paper.md", "Original baseline paper: fixture only")
        self.write("idea-stage/literature/paper.md", "Verified source text: fixture only")
        self.write("idea-stage/ideas/previous.json", "CANDIDATE_POOL_SECRET")
        self.write("refine-logs/FINAL_PROPOSAL.md", "ARCHITECT_PREFERENCE_SECRET")
        self.dump("configs/research.json", {
            "question": "Fixture question", "setting": "Fixture setting", "candidate_count": 10,
            "baseline": {"paper_source": "baseline/paper.md", "commit": "a" * 40},
            "data_id": "fixture-data", "environment_id": "fixture-python", "resource_id": "fixture-cpu",
            "old_generation_history": "GENERATION_SECRET",
        })
        self.dump("configs/budget.json", {"real_enabled": False, "scopes": {"real": {"max_cpu_seconds": 0}}})
        self.dump("configs/models.json", {"policy": {"max_model_cost_usd": 0, "max_model_wall_seconds": 10}})
        self.record = {
            "id": "paper-fixture", "classification": "verified", "source": "fixture paper", "locator": "abstract",
            "statement": "Fixture source states a limited observation", "url": "https://example.invalid/paper",
            "checked_at": "fixture timestamp", "venue": "arXiv preprint", "code_url": "none", "artifact": "idea-stage/literature/paper.md",
            "artifact_sha256": sha(self.root / "idea-stage/literature/paper.md"),
            "candidate_pool": "LITERATURE_EXTRA_FIELD_SECRET",
        }
        self.literature([self.record, {"classification": "hypothesis", "statement": "UNVERIFIED_SECRET"}])
        self.baseline = mock.patch.object(project_workflow, "check_baseline").start()
        self.addCleanup(mock.patch.stopall)
        self.route = mock.patch("model_routes.role_route", return_value={
            "role": "idea_proposer", "backend": "antigravity", "model_id": None, "availability": "unverified",
        }).start()

    def write(self, ref: str, value: str) -> None:
        path = self.root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def dump(self, ref: str, value: object) -> None:
        self.write(ref, json.dumps(value))

    def literature(self, rows: list[dict]) -> None:
        self.write("idea-stage/literature/evidence.jsonl", "\n".join(json.dumps(row) for row in rows))

    def test_baseline_reproduction_failure_prevents_package(self) -> None:
        self.baseline.side_effect = ProjectError("Baseline reproduction incomplete")
        with self.assertRaisesRegex(ProjectError, "Baseline reproduction"):
            project_workflow.prepare_proposal(self.root)
        self.baseline.assert_called_once()
        self.assertTrue(self.baseline.call_args.kwargs["reproduced"])
        self.assertFalse((self.root / "handoffs").exists())
        self.route.assert_not_called()

    def test_only_verified_sources_and_allowed_constraints_enter_fresh_package(self) -> None:
        folder = project_workflow.prepare_proposal(self.root)
        self.baseline.assert_called_once()
        self.assertTrue(self.baseline.call_args.kwargs["reproduced"])
        self.route.assert_called_once_with(self.root, "idea_proposer")
        text = "\n".join(path.read_text() for path in folder.rglob("*") if path.is_file())
        for secret in ("CANDIDATE_POOL_SECRET", "ARCHITECT_PREFERENCE_SECRET", "GENERATION_SECRET",
                       "LITERATURE_EXTRA_FIELD_SECRET", "UNVERIFIED_SECRET"):
            self.assertNotIn(secret, text)
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertIsNone(manifest["actual_identity"])
        self.assertEqual(manifest["dispatch"], "not_dispatched")
        for item in manifest["files"]:
            self.assertEqual(sha(folder / item["packaged_path"]), item["sha256"])
        literature = json.loads((folder / "files/literature.json").read_text())
        self.assertEqual(len(literature), 1)
        self.assertEqual(sha(folder / literature[0]["artifact"]), literature[0]["artifact_sha256"])
        other = project_workflow.prepare_proposal(self.root)
        self.assertNotEqual(folder, other)

    def test_stale_verified_literature_blocks_before_package_creation(self) -> None:
        self.write("idea-stage/literature/paper.md", "Changed since verification")
        with self.assertRaisesRegex(ProjectError, "missing or stale"):
            project_workflow.prepare_proposal(self.root)
        self.assertFalse((self.root / "handoffs").exists())

    def test_external_baseline_paper_preserves_absolute_source_and_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-research-paper-library-") as library:
            paper = Path(library).resolve() / "baseline.md"
            paper.write_text("External original baseline paper: fixture only", encoding="utf-8")
            research_path = self.root / "configs/research.json"
            research = json.loads(research_path.read_text())
            research["baseline"]["paper_source"] = str(paper)
            self.dump("configs/research.json", research)
            folder = project_workflow.prepare_proposal(self.root)
            manifest = json.loads((folder / "manifest.json").read_text())
            entry = next(item for item in manifest["files"] if item.get("path") == str(paper))
            self.assertEqual(entry["sha256"], sha(paper))
            self.assertEqual((folder / entry["packaged_path"]).read_bytes(), paper.read_bytes())

    def test_unverified_literature_cannot_be_used_for_proposal(self) -> None:
        self.record["classification"] = "author_opinion"
        self.literature([self.record])
        with self.assertRaisesRegex(ProjectError, "at least one verified"):
            project_workflow.prepare_proposal(self.root)
        self.assertFalse((self.root / "handoffs").exists())

    def test_candidate_file_cannot_be_smuggled_as_literature_source(self) -> None:
        self.record["artifact"] = "idea-stage/ideas/previous.json"
        self.record["artifact_sha256"] = sha(self.root / self.record["artifact"])
        self.literature([self.record])
        with self.assertRaisesRegex(ProjectError, "inside idea-stage/literature"):
            project_workflow.prepare_proposal(self.root)
        self.assertFalse((self.root / "handoffs").exists())


if __name__ == "__main__":
    unittest.main()

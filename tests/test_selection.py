"""Synthetic candidate reviews only; no external reviewer or experiment runs."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from contracts import ProjectError, atomic_json, sha
from selection import SCORE_DIMENSIONS, check_selection, validate_scorecard
import evidence


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="selection-fixture-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.actor = {"provider": "fixture", "model": "proposer", "model_family": "A", "identity_source": "synthetic test"}
        self.reviewer = {"provider": "fixture", "model": "reviewer", "model_family": "B", "identity_source": "synthetic test"}
        self.write("configs/research.json", {"candidate_count": 2, "selected_idea": "idea-A", "baseline": {"paper_source": "paper.json"}})
        self.write("paper.json", {"fixture": "Synthetic baseline document"})
        self.write("configs/resources.json", {})
        self.write("configs/budget.json", {})
        self.write("configs/models.json", {"policy": {"accept_human_reviews": True}})
        candidates = []
        for idea, score in (("idea-A", 4), ("idea-B", 2)):
            source = f"idea-stage/ideas/{idea}.json"
            self.write(source, {"hypothesis": "synthetic only", "proposer_identity": self.actor})
            folder = evidence.context_pack(self.root, idea, "idea-review")
            manifest = json.loads((folder / "manifest.json").read_text())
            self.write(str((folder / "response.json").relative_to(self.root)), {"fixture": "no real model"})
            self.write(str((folder / "identity.json").relative_to(self.root)), self.reviewer)
            result = json.loads((folder / "result-template.json").read_text())
            result.update({"completion": "complete", "verdict": "PASS", "fresh_context": True,
                           "actual_identity": self.reviewer,
                           "direct_reads": [item["path"] for item in manifest["files"]],
                           "raw_response_file": "response.json", "identity_evidence_file": "identity.json",
                           "scorecard": {"scores": dict.fromkeys(SCORE_DIMENSIONS, score), "recommendation": "go", "reasons": ["synthetic comparison"], "revision_requests": []}})
            self.write(str((folder / "result.json").relative_to(self.root)), result)
            receipt_path = evidence.import_review(self.root, folder, folder / "result.json")
            ref = receipt_path.relative_to(self.root).as_posix()
            binding = {"path": source, "sha256": sha(self.root / source)}
            candidates.append({"idea_id": idea, "idea_sha256": binding["sha256"], "review_receipt": ref, "review_history": []})
        self.record = {"pool_id": "synthetic-pool", "candidate_count": 2, "candidates": candidates,
                       "ranking": ["idea-A", "idea-B"], "selected_idea": "idea-A", "architect_identity": self.actor,
                       "decision": "go", "reason": "synthetic highest score", "revision_resolutions": []}
        self.job = {"idea_id": "idea-A", "selection_record": "selection.json", "idea_review_receipt": candidates[0]["review_receipt"]}

    def write(self, ref, value):
        atomic_json(self.root / ref, value)

    def binding(self, ref):
        return {"path": ref, "sha256": sha(self.root / ref)}

    def check(self):
        self.write("selection.json", self.record)
        return check_selection(self.root, self.job)

    def alter_receipt(self, index, update):
        path = self.root / self.record["candidates"][index]["review_receipt"]
        value = json.loads(path.read_text())
        update(value)
        atomic_json(path, value)

    def test_complete_two_candidate_selection(self):
        self.assertEqual(self.check()["selected_idea"], "idea-A")

    def test_missing_candidate_or_receipt_blocks(self):
        self.record["candidates"].pop()
        with self.assertRaisesRegex(ProjectError, "every configured"):
            self.check()

    def test_missing_receipt_blocks(self):
        self.record["candidates"][1]["review_receipt"] = "missing.json"
        with self.assertRaises(ProjectError):
            self.check()

    def test_scorecard_missing_axis_or_nonfinite_blocks(self):
        card = {"scores": dict.fromkeys(SCORE_DIMENSIONS, 1), "recommendation": "go", "reasons": ["fixture"], "revision_requests": []}
        for value in (True, float("nan"), -1, 6):
            bad = copy.deepcopy(card)
            bad["scores"]["novelty"] = value
            with self.assertRaises(ProjectError):
                validate_scorecard(bad)
        del card["scores"]["novelty"]
        with self.assertRaises(ProjectError):
            validate_scorecard(card)

    def test_candidate_hash_drift_blocks(self):
        self.write("idea-stage/ideas/idea-B.json", {"changed": True})
        with self.assertRaisesRegex(ProjectError, "hash changed"):
            self.check()

    def test_incorrect_ranking_blocks(self):
        self.record["ranking"].reverse()
        with self.assertRaisesRegex(ProjectError, "descending"):
            self.check()

    def test_kill_cannot_be_selected(self):
        self.alter_receipt(0, lambda r: r["scorecard"].update(recommendation="kill"))
        with self.assertRaises(ProjectError):
            self.check()

    def test_unresolved_revise_cannot_be_selected(self):
        self.alter_receipt(0, lambda r: r["scorecard"].update(recommendation="revise", revision_requests=[{"id": "r1", "text": "fix"}]))
        with self.assertRaisesRegex(ProjectError, "new independent go"):
            self.check()

    def test_high_score_revise_does_not_block_highest_go(self):
        self.alter_receipt(0, lambda r: r["scorecard"].update(recommendation="revise", revision_requests=[{"id": "r1", "text": "fix"}]))
        self.record["selected_idea"] = self.job["idea_id"] = "idea-B"
        self.job["idea_review_receipt"] = self.record["candidates"][1]["review_receipt"]
        research = json.loads((self.root / "configs/research.json").read_text())
        research["selected_idea"] = "idea-B"
        self.write("configs/research.json", research)
        self.assertEqual(self.check()["ranking"], ["idea-A", "idea-B"])
        self.record["ranking"].reverse()
        with self.assertRaisesRegex(ProjectError, "highest-ranked|descending"):
            self.check()

    def test_lower_score_go_cannot_skip_highest_go(self):
        self.record["selected_idea"] = self.job["idea_id"] = "idea-B"
        self.job["idea_review_receipt"] = self.record["candidates"][1]["review_receipt"]
        research = json.loads((self.root / "configs/research.json").read_text())
        research["selected_idea"] = "idea-B"
        self.write("configs/research.json", research)
        with self.assertRaisesRegex(ProjectError, "highest-ranked"):
            self.check()

    def test_shared_review_package_blocks(self):
        first = json.loads((self.root / self.job["idea_review_receipt"]).read_text())
        package = first["package_manifest"]
        self.alter_receipt(1, lambda r: r.update(package_manifest=package))
        with self.assertRaisesRegex(ProjectError, "distinct isolated|scope differs"):
            self.check()

    def test_tie_requires_reason(self):
        self.alter_receipt(1, lambda r: r["scorecard"].update(scores=dict.fromkeys(SCORE_DIMENSIONS, 4)))
        with self.assertRaisesRegex(ProjectError, "tie_break_reason"):
            self.check()
        self.record["tie_break_reason"] = "Synthetic predefined order"
        self.check()

    def prepare_revision_history(self):
        current = json.loads((self.root / self.job["idea_review_receipt"]).read_text())
        old = copy.deepcopy(current)
        old["scorecard"].update(recommendation="revise", revision_requests=[{"id": "r1", "text": "Document control"}])
        folder = "handoffs/prior"
        source = "idea-stage/ideas/idea-A.json"
        # Historical materials are checked against immutable package copies,
        # rather than requiring the current candidate to retain old bytes.
        self.write(f"{folder}/files/idea.json", json.loads((self.root / source).read_text()))
        entry = {"path": source, "sha256": sha(self.root / source), "packaged_path": "files/idea.json"}
        old["scope"]["files"] = [entry]
        old["direct_reads"] = [source]
        package = {"idea_id": "idea-A", "purpose": "idea-review", "executor_identity": self.actor,
                   "files": [entry], "input_bindings": old["scope"]["input_bindings"]}
        self.write(f"{folder}/manifest.json", package)
        old["package_manifest"] = self.binding(f"{folder}/manifest.json")
        old_ref = "reviews/receipts/prior/receipt.json"
        self.write(old_ref, old)
        self.write("resolutions/control.json", {"reason": "Synthetic evidence documents retained control"})
        self.record["candidates"][0]["review_history"] = [old_ref]
        self.record["revision_resolutions"] = [{"idea_id": "idea-A", "review_receipt": old_ref,
              "receipt_sha256": sha(self.root / old_ref), "final_review_receipt": self.job["idea_review_receipt"],
              "resolutions": [{"request_id": "r1", "reason": "Independent current go review accepts documented control",
                               "evidence": self.binding("resolutions/control.json")}]}]
        return old_ref

    def test_resolved_revision_requires_current_go_and_archived_evidence(self):
        self.prepare_revision_history()
        self.check()
        self.write("handoffs/prior/files/idea.json", {"tampered": True})
        with self.assertRaisesRegex(ProjectError, "packaged material"):
            self.check()

    def test_revision_cannot_omit_one_requested_resolution(self):
        self.prepare_revision_history()
        self.record["revision_resolutions"][0]["resolutions"] = []
        with self.assertRaisesRegex(ProjectError, "Every revision request"):
            self.check()

    def test_historical_revision_requires_independent_acceptance(self):
        old_ref = self.prepare_revision_history()
        old = json.loads((self.root / old_ref).read_text())
        old["actual_identity"] = self.actor
        old["independence"] = "same-family"
        self.write(old_ref, old)
        self.record["revision_resolutions"][0]["receipt_sha256"] = sha(self.root / old_ref)
        with self.assertRaisesRegex(ProjectError, "independent fresh-context"):
            self.check()

    def test_history_cannot_be_omitted(self):
        old = json.loads((self.root / self.job["idea_review_receipt"]).read_text())
        old["scorecard"].update(recommendation="revise", revision_requests=[{"id": "r1", "text": "fix"}])
        self.write("reviews/receipts/old/receipt.json", old)
        with self.assertRaisesRegex(ProjectError, "missing from revision_resolutions"):
            self.check()


if __name__ == "__main__":
    unittest.main()

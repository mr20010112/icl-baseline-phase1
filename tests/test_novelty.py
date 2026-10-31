import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import contracts
import gates
from contracts import sha


class NoveltyRecordTest(unittest.TestCase):
    """Structural fixture only; no search or model was actually run."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for name in ("raw.txt", "identity.txt", "source.md"):
            (self.root / name).write_text("fixture\n")
        self.record = {
            "idea_id": "i1", "decision": "go", "queries": ["q"], "checked_at": "fixture",
            "executor_identity": {"provider": "p", "model": "m", "model_family": "f", "identity_source": "fixture"},
            "raw_response": {"path": "raw.txt", "sha256": sha(self.root / "raw.txt")},
            "identity_evidence": {"path": "identity.txt", "sha256": sha(self.root / "identity.txt")},
            "sources": [{"url": "https://example.invalid", "locator": "abstract", "artifact": "source.md"}],
        }
        self.job = {"idea_id": "i1", "novelty_record": "novelty.json"}

    def check(self) -> None:
        (self.root / "novelty.json").write_text(json.dumps(self.record))
        gates.check_novelty(self.root, self.job)

    def test_complete_record_passes(self) -> None:
        self.check()

    def test_missing_or_unknown_identity_blocks(self) -> None:
        self.record["executor_identity"]["model"] = "unknown"
        with self.assertRaisesRegex(contracts.ProjectError, "identity"):
            self.check()

    def test_missing_raw_response_or_tamper_blocks(self) -> None:
        del self.record["raw_response"]
        with self.assertRaisesRegex(contracts.ProjectError, "raw response"):
            self.check()
        self.setUp()
        (self.root / "identity.txt").write_text("changed\n")
        with self.assertRaisesRegex(contracts.ProjectError, "identity evidence"):
            self.check()


if __name__ == "__main__":
    unittest.main()

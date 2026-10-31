"""Protocol provenance regressions with synthetic manifests; no training."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import contracts


class ContractProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="contract-provenance-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        project = Path(__file__).resolve().parents[1]
        self.protocol = contracts.load(project / "examples/toy/contract.yaml")
        self.protocol.update(idea_id="new-idea", kind="real", hypothesis="A hypothesis derived from the prior method's failure")
        self.protocol["statistics"] = {"metric": "mse", "aggregation": "mean", "atol": 0,
                                       "rtol": 0, "statistical_rule": "Synthetic schema fixture",
                                       "hardware_scope": "Synthetic CPU fixture"}
        self.protocol["provenance"] = {"mode": "preregistered", "observed_runs": ["prior-failure"],
                                       "hypothesis_basis_runs": ["prior-failure"]}
        self.ref = "contracts/new-idea/v1.yaml"
        contracts.atomic_json(self.root / "runs/prior-failure/manifest.json",
                              {"idea_id": "prior-idea", "status": "failed"})

    def freeze(self):
        contracts.atomic_json(self.root / self.ref, self.protocol)
        return contracts.freeze(self.root, self.ref)

    def test_cross_idea_result_derived_hypothesis_cannot_be_preregistered(self):
        with self.assertRaisesRegex(contracts.ProjectError, "exploratory"):
            self.freeze()

    def test_cross_idea_result_derived_hypothesis_can_be_exploratory(self):
        self.protocol["provenance"]["mode"] = "exploratory"
        self.assertEqual(self.freeze()["kind"], "real")

    def test_hypothesis_basis_must_be_disclosed_as_observed(self):
        self.protocol["provenance"].update(mode="exploratory", observed_runs=[])
        with self.assertRaisesRegex(contracts.ProjectError, "observed_runs"):
            self.freeze()

    def test_new_protocol_requires_explicit_hypothesis_basis_declaration(self):
        del self.protocol["provenance"]["hypothesis_basis_runs"]
        with self.assertRaisesRegex(contracts.ProjectError, "hypothesis_basis_runs"):
            self.freeze()

    def test_independent_confirmation_can_reference_other_idea_as_background(self):
        self.protocol["hypothesis"] = "A separately specified hypothesis with prior method as background only"
        self.protocol["provenance"]["hypothesis_basis_runs"] = []
        self.assertEqual(self.freeze()["kind"], "real")

    def test_hypothesis_basis_requires_unique_existing_run_ids(self):
        for index, basis in enumerate((["missing"], ["prior-failure", "prior-failure"], None, "prior-failure")):
            with self.subTest(basis=basis):
                self.protocol["idea_id"] = f"new-idea-{index}"
                self.ref = f"contracts/new-idea-{index}/v1.yaml"
                self.protocol["provenance"].update(mode="exploratory", hypothesis_basis_runs=basis)
                with self.assertRaises(contracts.ProjectError):
                    self.freeze()

    def test_historical_frozen_protocol_without_basis_keeps_bytes_and_idempotence(self):
        del self.protocol["provenance"]["hypothesis_basis_runs"]
        contracts.atomic_json(self.root / self.ref, self.protocol)
        source = self.root / self.ref
        before = source.read_bytes()
        record = {"sha256": contracts.sha(source), "frozen_at": "2026-10-01T00:00:00+00:00",
                  "idea_id": "new-idea", "version": 1, "kind": "real"}
        contracts.atomic_json(self.root / "contracts/.registry.json",
                              {"schema_version": 1, "contracts": {self.ref: record}})
        self.assertEqual(contracts.verify(self.root, self.ref)["sha256"], record["sha256"])
        self.assertEqual(contracts.freeze(self.root, self.ref)["sha256"], record["sha256"])
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

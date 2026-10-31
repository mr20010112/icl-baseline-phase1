"""Local role routing checks without authentication or provider calls."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
from contracts import ProjectError, atomic_json, load
import model_routes


class ModelRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="project-model-routes-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = load(PROJECT / "configs/models.json")
        atomic_json(self.root / "configs/models.json", self.config)
        for directory, *_ in model_routes.SERVERS.values():
            script = self.root / "vendor/aris/mcp-servers" / directory / "server.py"
            script.parent.mkdir(parents=True)
            script.write_text("# local transport fixture; never executed\n")

    def test_sync_rebases_managed_routes_and_preserves_other_settings(self):
        other = {"command": "untouched-service", "args": ["--custom"]}
        atomic_json(self.root / ".mcp.json", {"mcpServers": {
            "other": other, "codex": {"command": "/old/python", "args": ["/old/server.py"], "env": {"CUSTOM_FLAG": "retained"}}}})
        model_routes.sync_routes(self.root)
        config = load(self.root / ".mcp.json")
        self.assertEqual(config["mcpServers"]["other"], other)
        self.assertEqual(config["mcpServers"]["codex"]["env"]["CUSTOM_FLAG"], "retained")
        self.assertEqual(model_routes.validate_routes(self.root)["status"], "PASS")
        self.assertEqual(load(self.root / ".aris/reviewer.json"), {"backend": "claude-code"})

    def test_stale_native_reviewer_route_is_rejected(self):
        model_routes.sync_routes(self.root)
        atomic_json(self.root / ".aris/reviewer.json", {"backend": "codex"})
        with self.assertRaisesRegex(ProjectError, "Native reviewer"):
            model_routes.validate_routes(self.root)

    def test_stale_mcp_path_and_role_mismatch_are_rejected(self):
        model_routes.sync_routes(self.root)
        config = load(self.root / ".mcp.json")
        config["mcpServers"]["antigravity"]["args"] = ["/old/server.py"]
        atomic_json(self.root / ".mcp.json", config)
        with self.assertRaisesRegex(ProjectError, "stale managed MCP"):
            model_routes.validate_routes(self.root)
        model_routes.sync_routes(self.root)
        self.config["roles"]["independent_reviewer"]["backend"] = "codex"
        atomic_json(self.root / "configs/models.json", self.config)
        with self.assertRaisesRegex(ProjectError, "common rules"):
            model_routes.validate_routes(self.root)

    def test_route_does_not_invent_model_identity(self):
        route = model_routes.role_route(self.root, "independent_reviewer")
        self.assertEqual(route["server"], "claude-review")
        self.assertEqual(route["fresh_tool"], "mcp__claude-review__review")
        self.assertIsNone(route["model_id"])
        self.assertEqual(model_routes.role_route(self.root, "analyst")["mode"], "manual")

    def test_non_python_executable_is_not_a_valid_mcp_launcher(self):
        model_routes.sync_routes(self.root)
        config = load(self.root / ".mcp.json")
        config["mcpServers"]["antigravity"]["command"] = "/usr/bin/false"
        atomic_json(self.root / ".mcp.json", config)
        with self.assertRaisesRegex(ProjectError, "stale managed MCP"):
            model_routes.validate_routes(self.root)

    def test_invalid_roles_leave_existing_routes_untouched(self):
        model_routes.sync_routes(self.root)
        paths = [self.root / ".mcp.json", self.root / ".aris/reviewer.json"]
        before = [p.read_bytes() for p in paths]
        atomic_json(self.root / "configs/models.json", {"roles": {}})
        with self.assertRaisesRegex(ProjectError, "model roles"):
            model_routes.sync_routes(self.root)
        self.assertEqual([p.read_bytes() for p in paths], before)


if __name__ == "__main__":
    unittest.main()

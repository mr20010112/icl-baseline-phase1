"""Project role routing and local MCP configuration; never invokes a model."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

from contracts import ProjectError, atomic_json, load, project_path, sha


PRODUCTS = {
    "architect": "Claude Code", "scout": "Antigravity",
    "idea_proposer": "Antigravity", "independent_reviewer": "Claude Code",
    "implementer": "Codex", "analyst": "GPT Pro / Ultra", "writer": "Codex",
}
BACKENDS = {
    "architect": "claude-code", "scout": "antigravity",
    "idea_proposer": "antigravity", "independent_reviewer": "claude-code",
    "implementer": "codex", "analyst": "manual", "writer": "codex",
}
SERVERS = {
    "codex": ("codex-exec", "CODEX_BIN", "codex", "mcp__codex__codex", "mcp__codex__codex-reply"),
    "antigravity": ("antigravity-exec", "AGY_BIN", "agy", "mcp__antigravity__antigravity", "mcp__antigravity__antigravity-reply"),
    "claude-review": ("claude-review", "CLAUDE_BIN", "claude", "mcp__claude-review__review", "mcp__claude-review__review_reply"),
}


# Claude Code (architect) leads and proactively delegates work in these scopes.
# `delegate TASK` prints the full entry; fields are the operating procedure.
DELEGATION = {
    "literature-search": {
        "role": "scout",
        "trigger": "Research question/setting is set and verified literature is missing or thin; a new sub-question needs sources; cross-domain context is needed.",
        "send": ["one bounded research question", "filters: venues, code-only, year range", "known baseline title (not the project discussion)"],
        "withhold": ["candidate ideas", "rankings", "earlier failed ideas", "architect preferences"],
        "call": "fresh mcp__antigravity__antigravity; cwd = an empty or package directory; one question per call; do not use -reply across unrelated questions",
        "prompt": "Find papers for: <question>. Prefer top venues and papers with open-source code. For each give title, authors, year, exact venue, arXiv id, code URL (or 'none'), source URL, and which sections you read. Mark anything not opened as unverified. Do not edit files or run experiments.",
        "returns": "table of papers with venue, code_url, source_url; raw text response saved verbatim",
        "architect_checks": ["open each source URL/arXiv entry for the claimed title/venue/year", "fetch LaTeX/Markdown source where available, save under idea-stage/literature/", "write evidence.jsonl rows with venue and code_url; unresolved when unknown"],
        "next_step": "python3 tools/research.py audit",
        "on_failure": "timeout or nonzero exit = failed search even with partial text; retry once with a narrower question, then report blocked",
    },
    "candidate-generation": {
        "role": "idea_proposer",
        "trigger": "Baseline reproduction has been accepted and verified literature exists.",
        "send": ["only the folder from python3 tools/project_workflow.py prepare-proposal (REQUEST.md and files/)"],
        "withhold": ["anything outside the package", "previous candidates", "generation discussions", "this conversation"],
        "call": "fresh mcp__antigravity__antigravity with cwd = the package folder, or a manual session in an empty workspace",
        "prompt": "Follow REQUEST.md: generate candidate_count candidates from constraints.json using templates/idea.example.json fields (hypothesis, description, compatibility, implementation_cost, expected_signal, risks). One JSON object per candidate.",
        "returns": "candidate_count idea objects; raw response saved verbatim",
        "architect_checks": ["count equals configs/research.json candidate_count", "write each as idea-stage/ideas/<id>.json with proposer_identity from the actual response; unknown stays unknown", "no candidate cites unsupplied literature as verified"],
        "next_step": "per candidate: python3 tools/research.py context-pack --idea ID --purpose idea-review, then a new Claude review session each",
        "on_failure": "wrong count or unparseable output: one regeneration from the same package; do not patch candidates by hand",
    },
    "novelty-search": {
        "role": "scout",
        "trigger": "An idea is selected (go) and before any implementation or training.",
        "send": ["the single selected idea card", "baseline paper reference", "request to find prior work that already does it"],
        "withhold": ["other candidates", "scores", "review reasons"],
        "call": "fresh mcp__antigravity__antigravity; cwd = a directory containing only the idea card",
        "prompt": "Search for existing work that already proposes or closely overlaps this idea: <idea card>. List queries used, each overlapping paper with URL and the exact overlapping claim, and polishing room. State go/revise/kill with reasons.",
        "returns": "queries, sources with URL/locator, decision; raw response saved verbatim",
        "architect_checks": ["each source URL opened and locator matches", "save source artifacts and the raw response; write executor_identity, raw_response and identity_evidence into the novelty_record", "decision is the architect's, recorded with reason; revise/kill goes back to idea revision"],
        "next_step": "set job.novelty_record; gates.check_novelty validates it",
        "on_failure": "missing sources or identity means blocked, not go",
    },
    "implementation": {
        "role": "implementer",
        "trigger": "Idea selected, protocol frozen (contract freeze), novelty go; or a baseline protocol is frozen and code must be prepared.",
        "send": ["frozen protocol path and version", "baseline checkout path and commit", "selected idea card", "method-to-code map (templates/method-implementation-map.md)", "registered resource ids"],
        "withhold": ["other candidates", "unrelated idea documents", "result-based rationalizations"],
        "call": "fresh mcp__codex__codex with sandbox=workspace-write and cwd = the project; one module or change per call; mcp__codex__codex-reply only for the same change",
        "prompt": "Implement <module> exactly per protocol <path> vN: hyperparameters, metrics and data split as written. Do not run training; training goes through tools/research.py run. If anything in the protocol is ambiguous or needs a deviation, stop and report instead of choosing. List every file changed.",
        "returns": "changed files list, method-to-code map entries, any reported deviation; raw response saved",
        "architect_checks": ["diff touches only declared code_paths", "no hyperparameter/metric/split differs from the protocol; deviations are decided by the architect, and a protocol change means a new version", "implementation is covered by the job's code_paths for code review", "build the code-review context pack and send it to a new Claude review session"],
        "next_step": "python3 tools/research.py context-pack --idea ID --purpose code-review --job JOB; then import-review; then research.py run",
        "on_failure": "failed or partial change is kept and reported; retry once with the error; repeated failure goes to the user",
    },
    "formula-derivation": {
        "role": "implementer",
        "trigger": "The method needs a derivation (loss, update rule, bound) before coding.",
        "send": ["selected idea card", "the exact quantity to derive and notation from the baseline paper"],
        "withhold": ["results", "other candidates"],
        "call": "fresh mcp__codex__codex with sandbox=read-only",
        "prompt": "Derive <quantity> step by step with stated assumptions. Mark each step as standard result, assumption or your own inference. Give a numeric sanity check that can be run on CPU.",
        "returns": "derivation with assumptions and a checkable numeric case",
        "architect_checks": ["run the numeric check yourself", "unproven steps stay hypothesis", "derivation is referenced from the method-to-code map before coding"],
        "next_step": "hand to implementation",
        "on_failure": "an unchecked derivation is not used in code",
    },
    "result-analysis": {
        "role": "analyst",
        "trigger": "Runs have finished and been reviewed; results are ambiguous, a signal failed, or the next analysis experiment must be chosen.",
        "send": ["frozen protocol", "raw run artifacts and metrics", "a structured experiment summary", "one bounded analysis question (templates/analysis-question.md)"],
        "withhold": ["other candidates", "architect's preferred explanation", "secrets, credentials, data or weights"],
        "call": "preferred: steipete/oracle CLI (https://github.com/steipete/oracle) from a handoff folder containing only the send items, with --engine browser (signed-in ChatGPT, `-m` defaults to gpt-5.5-pro in oracle 0.21.2 as installed here; the actual model must still be read from the session output). Never --engine api: it spends money and policy.max_model_cost_usd is 0. Run `oracle --render ...` first and check the exact bundle, then ask the user before the real send because it uploads to an external service. Fallback: manual handoff. The analyst role stays mode=manual; no API model ID is inferred from the product name.",
        "prompt": "Per templates/analysis-question.md: distinguish competing explanations of the results, and propose bounded analysis experiments with expected information and cost. Say which further experiments you need to decide.",
        "returns": "competing explanations and proposed analysis experiments; copy the oracle session output from ~/.oracle/sessions into the project verbatim; identity is what the session reports, otherwise unknown",
        "architect_checks": ["the bundle held only the allowed files (compare with the --render output)", "proposed experiments are new exploratory hypotheses with hypothesis_basis_runs, under a new protocol version", "analysis cannot replace the independent result review"],
        "next_step": "new protocol version, then research.py run; for a further round send the new results as a new bounded question",
        "on_failure": "browser login/automation failure or no response means blocked (browser mode is fragile); do not self-analyze and label it as analyst output",
    },
    "paper-writing": {
        "role": "writer",
        "trigger": "claims.json has claims with signal_ids and imported result_review_receipt and audit --paper passes.",
        "send": ["paper/claims.json", "the cited analysis files and run metrics", "the frozen protocol"],
        "withhold": ["rejected or unreviewed results presented as findings", "toy runs"],
        "call": "fresh mcp__codex__codex with sandbox=workspace-write and cwd = paper/",
        "prompt": "Write section <name> using only the claims and numbers in the supplied files. Every claim sentence cites its claim id. Report failures and insufficient signals as such. Do not add results or citations not supplied.",
        "returns": "LaTeX/Markdown section with claim-id citations",
        "architect_checks": ["every number matches a run metric", "every claim sentence maps to a claim id", "negative signals are not softened"],
        "next_step": "python3 tools/research.py audit --paper",
        "on_failure": "unsupported sentences are removed, not justified afterward",
    },
}
FIELDS = ("role", "trigger", "send", "withhold", "call", "prompt", "returns", "architect_checks", "next_step", "on_failure")


def delegation_route(root: Path, task: str) -> dict:
    if task not in DELEGATION:
        raise ProjectError(f"Not a delegable task: {task}; choices: {', '.join(sorted(DELEGATION))}")
    spec = DELEGATION[task]
    return {"task": task, **role_route(root, spec["role"]), **{k: spec[k] for k in FIELDS if k != "role"},
            "log": "python3 tools/model_routes.py log-delegation TASK --prompt P --response R --identity JSON"}


def log_delegation(root: Path, task: str, prompt: Path, response: Path, identity: dict) -> dict:
    """Append one delegation record; counts against policy.max_review_calls."""
    root = root.resolve()
    route = delegation_route(root, task)
    limit = load(root / "configs/models.json").get("policy", {}).get("max_review_calls")
    log = root / ".aris/delegations.jsonl"
    count = len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0
    if isinstance(limit, int) and count >= limit:
        raise ProjectError("Delegation call budget exhausted; architect must stop or raise policy.max_review_calls")
    entry = {"at": datetime.now(timezone.utc).isoformat(), "task": task, "role": route["role"],
             "requested_route": {k: route[k] for k in ("preferred_product", "server", "model_id")},
             "actual_identity": identity or "unknown"}
    for key, path in (("prompt", prompt), ("response", response)):
        p = project_path(root, path)
        if not p.is_file() or not p.stat().st_size:
            raise ProjectError(f"Delegation {key} file missing or empty")
        entry[key] = {"path": p.relative_to(root).as_posix(), "sha256": sha(p)}
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _check_roles(root: Path) -> dict:
    roles = load(root / "configs/models.json").get("roles", {})
    if not isinstance(roles, dict) or set(roles) != set(PRODUCTS):
        raise ProjectError("Project model roles differ from docs/agent-rules.md")
    for role, product in PRODUCTS.items():
        item = roles[role]
        if not isinstance(item, dict):
            raise ProjectError(f"Invalid model role: {role}")
        expected_mode = "host" if role == "architect" else "manual" if role == "analyst" else "mcp"
        if (item.get("preferred_product") != product or item.get("backend") != BACKENDS[role]
                or item.get("mode") != expected_mode):
            raise ProjectError(f"Role route differs from common rules: {role}")
        expected_server = "claude-review" if role == "independent_reviewer" else BACKENDS[role]
        if expected_mode == "mcp" and item.get("server") != expected_server:
            raise ProjectError(f"Role has wrong MCP server: {role}")
    return roles


def role_route(root: Path, role: str) -> dict:
    roles = load(root / "configs/models.json").get("roles", {})
    if role not in roles or role not in PRODUCTS:
        raise ProjectError(f"Unknown project role: {role}")
    config = roles[role]
    server = config.get("server")
    details = SERVERS.get(server)
    return {"role": role, "preferred_product": config.get("preferred_product"),
            "backend": config.get("backend"), "mode": config.get("mode"),
            "server": server, "model_id": config.get("requested_model"),
            "fresh_tool": details[3] if details else None,
            "continuation_tool": details[4] if details else None,
            "availability": config.get("availability", "unverified"),
            "identity": "requested route only; actual returned identity must be recorded per call"}


def sync_routes(root: Path) -> dict:
    """Rebase only this project's managed MCP servers; preserve other settings."""
    root = root.resolve()
    roles = _check_roles(root)
    role = roles["independent_reviewer"]
    reviewer = {"backend": role["backend"]}
    if role.get("requested_model"):
        reviewer["model"] = role["requested_model"]
    path = root / ".mcp.json"
    config = load(path) if path.exists() else {"mcpServers": {}}
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ProjectError(".mcp.json:mcpServers must be an object")
    # Build and verify all entries before writing anything.
    for name, (directory, bin_var, cli, _, _) in SERVERS.items():
        script = root / "vendor/aris/mcp-servers" / directory / "server.py"
        if not script.is_file():
            raise ProjectError(f"Missing MCP bridge: {script}")
        entry = dict(servers.get(name, {}))
        env = dict(entry.get("env", {}))
        env[bin_var] = shutil.which(cli) or cli
        if name == "claude-review":
            env["CLAUDE_REVIEW_TOOLS"] = "Read,Grep,Glob"
            env["CLAUDE_REVIEW_STATE_DIR"] = str(root / ".aris/project-runtime/claude-review")
            env["CLAUDE_REVIEW_DEBUG_LOG"] = str(root / ".aris/project-runtime/claude-review-debug.log")
        entry.update(type="stdio", command=sys.executable, args=[str(script)], env=env)
        servers[name] = entry
    atomic_json(path, config)
    atomic_json(root / ".aris/reviewer.json", reviewer)
    return {"servers": list(SERVERS), "reviewer_backend": reviewer["backend"],
            "external_integrations": "UNVERIFIED; local configuration only"}


def validate_routes(root: Path) -> dict:
    root = root.resolve()
    roles = _check_roles(root)
    reviewer = load(root / ".aris/reviewer.json")
    requested = roles["independent_reviewer"].get("requested_model")
    if reviewer.get("backend") != "claude-code" or reviewer.get("model") != requested or reviewer.get("effort") is not None:
        raise ProjectError("Native reviewer route differs from project independent_reviewer")
    mcp = load(root / ".mcp.json").get("mcpServers", {})
    availability = {}
    for name, (directory, bin_var, _, _, _) in SERVERS.items():
        entry = mcp.get(name, {})
        script = root / "vendor/aris/mcp-servers" / directory / "server.py"
        command = entry.get("command", "")
        executable = shutil.which(command) if isinstance(command, str) and command else None
        if (entry.get("type") != "stdio" or entry.get("args") != [str(script)]
                or not script.is_file() or not executable
                or Path(executable).resolve() != Path(sys.executable).resolve()):
            raise ProjectError(f"Missing or stale managed MCP route: {name}; run init")
        cli = entry.get("env", {}).get(bin_var, "")
        available = isinstance(cli, str) and bool(cli) and shutil.which(cli) is not None
        availability[name] = "binary-present; invocation unverified" if available else "CLI unavailable"
    return {"status": "PASS", "roles": {role: role_route(root, role) for role in PRODUCTS},
            "local_transports": availability, "scientific_acceptance": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("sync")
    sub.add_parser("check")
    route = sub.add_parser("route")
    route.add_argument("role", choices=sorted(PRODUCTS))
    deleg = sub.add_parser("delegate", help="show where the architect should delegate a task")
    deleg.add_argument("task", choices=sorted(DELEGATION))
    log = sub.add_parser("log-delegation", help="record a completed delegation")
    log.add_argument("task", choices=sorted(DELEGATION))
    log.add_argument("--prompt", type=Path, required=True)
    log.add_argument("--response", type=Path, required=True)
    log.add_argument("--identity", default="{}", help="JSON of the actual returned identity; omit if unknown")
    args = parser.parse_args()
    try:
        if args.action == "delegate":
            print(json.dumps(delegation_route(args.root, args.task), ensure_ascii=False, indent=2))
            return 0
        if args.action == "log-delegation":
            print(json.dumps(log_delegation(args.root, args.task, args.prompt, args.response, json.loads(args.identity)), ensure_ascii=False, indent=2))
            return 0
        result = sync_routes(args.root) if args.action == "sync" else validate_routes(args.root) if args.action == "check" else role_route(args.root, args.role)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ProjectError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

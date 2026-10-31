"""Validate complete candidate reviews and an explicit architect selection.

Scores measure desirability: complexity is *controllability*, so all five axes
are higher-is-better. Scientific merit remains the independent reviewer's judgment.
"""
from __future__ import annotations

import math
from pathlib import Path
import re

from contracts import ProjectError, load, project_path, sha

SCORE_DIMENSIONS = ("novelty", "feasibility", "compatibility", "complexity", "expected_gain")


def validate_scorecard(card: dict) -> dict:
    if not isinstance(card, dict):
        raise ProjectError("Idea review requires a scorecard")
    scores = card.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(SCORE_DIMENSIONS):
        raise ProjectError("Scorecard requires all five score dimensions")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 5 for x in scores.values()):
        raise ProjectError("Scorecard scores must be finite numbers in [0,5]")
    if card.get("recommendation") not in ("go", "revise", "kill"):
        raise ProjectError("Scorecard recommendation must be go/revise/kill")
    reasons = card.get("reasons")
    if not isinstance(reasons, list) or not reasons or any(not isinstance(x, str) or not x.strip() for x in reasons):
        raise ProjectError("Scorecard requires nonempty reasons")
    requests = card.get("revision_requests")
    if not isinstance(requests, list):
        raise ProjectError("Scorecard revision_requests must be a list")
    ids = []
    for item in requests:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", item["id"]) or not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ProjectError("Revision request requires a stable id and text")
        ids.append(item["id"])
    if len(ids) != len(set(ids)) or (card["recommendation"] == "revise" and not ids):
        raise ProjectError("Revise requires unique, nonempty revision requests")
    if card["recommendation"] == "go" and requests:
        raise ProjectError("Go review cannot retain unresolved revision requests")
    return card


def _binding(root: Path, value: dict, label: str) -> Path:
    if not isinstance(value, dict) or not value.get("path"):
        raise ProjectError(f"Missing {label} evidence binding")
    path = project_path(root, value["path"])
    if not path.is_file() or not path.stat().st_size or sha(path) != value.get("sha256"):
        raise ProjectError(f"Changed or missing {label} evidence")
    return path


def check_selection(root: Path, job: dict) -> dict:
    from gates import check_receipt, known_identity, independence

    root = Path(root).resolve()
    if not job.get("selection_record"):
        raise ProjectError("Complete candidate selection_record is required")
    record = load(project_path(root, job["selection_record"]))
    if not isinstance(record, dict):
        raise ProjectError("Selection record must be an object")
    research = load(root / "configs/research.json")
    count = research.get("candidate_count", 10)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ProjectError("research.candidate_count must be a positive integer")
    if not isinstance(record.get("pool_id"), str) or not record["pool_id"].strip() or (isinstance(record.get("candidate_count"), bool) or record.get("candidate_count") != count):
        raise ProjectError("Selection pool_id/candidate_count is missing or inconsistent")
    candidates = record.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != count:
        raise ProjectError("Selection must cover every configured candidate")
    selected = record.get("selected_idea")
    if selected != job.get("idea_id") or selected != research.get("selected_idea") or record.get("decision") != "go":
        raise ProjectError("Selection differs from selected idea or architect go")
    if not known_identity(record.get("architect_identity", {})) or not isinstance(record.get("reason"), str) or not record["reason"].strip():
        raise ProjectError("Selection requires architect identity and reason")
    seen, packages, totals, cards = set(), set(), {}, {}
    declared_history = set()
    receipts = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ProjectError("Candidate record must be an object")
        idea = candidate.get("idea_id")
        if not isinstance(idea, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", idea) or idea in seen:
            raise ProjectError("Duplicate or invalid candidate idea_id")
        seen.add(idea)
        history_refs = candidate.get("review_history")
        if not isinstance(history_refs, list) or any(not isinstance(ref, str) for ref in history_refs):
            raise ProjectError("Candidate requires review_history (empty if none)")
        declared_history.update(str(project_path(root, ref)) for ref in history_refs)
        path = root / "idea-stage/ideas" / f"{idea}.json"
        if sha(path) != candidate.get("idea_sha256"):
            raise ProjectError("Candidate source hash changed")
        source = load(path)
        if not known_identity(source.get("proposer_identity", {})):
            raise ProjectError("Candidate proposer identity is required")
        receipt = check_receipt(root, candidate.get("review_receipt"), "idea-review", {"idea_id": idea, "executor_identity": source["proposer_identity"], "proposer_identity": source["proposer_identity"]})
        bindings = receipt.get("scope", {}).get("input_bindings", [])
        rel = path.relative_to(root).as_posix()
        if not any(x.get("path") == rel and x.get("sha256") == candidate["idea_sha256"] for x in bindings):
            raise ProjectError("Candidate review is not bound to this idea source")
        package = _binding(root, receipt.get("package_manifest"), "review package")
        if str(package) in packages:
            raise ProjectError("Each candidate requires a distinct isolated review package")
        packages.add(str(package))
        card = validate_scorecard(receipt.get("scorecard"))
        cards[idea] = card
        receipts[idea] = candidate["review_receipt"]
        totals[idea] = sum(card["scores"].values())
    ranking = record.get("ranking")
    if not isinstance(ranking, list) or any(not isinstance(x, str) for x in ranking) or len(ranking) != len(set(ranking)) or set(ranking) != set(totals):
        raise ProjectError("Ranking must contain every candidate exactly once")
    if not ranking or any((cards[a]["recommendation"] == "kill", -totals[a]) > (cards[b]["recommendation"] == "kill", -totals[b]) for a, b in zip(ranking, ranking[1:])):
        raise ProjectError("Ranking must follow descending scores, with kill candidates last")
    if len(set(totals.values())) != len(totals) and not str(record.get("tie_break_reason", "")).strip():
        raise ProjectError("Tied scores require an explicit tie_break_reason")
    if cards[selected]["recommendation"] != "go":
        raise ProjectError("Selected revise candidate requires a new independent go review")
    eligible = [idea for idea in ranking if cards[idea]["recommendation"] == "go"]
    if selected != eligible[0]:
        raise ProjectError("Selection must choose the highest-ranked go candidate")
    if job.get("idea_review_receipt") != receipts[selected]:
        raise ProjectError("Selected review receipt differs from the run's idea review")
    histories = record.get("revision_resolutions")
    if not isinstance(histories, list):
        raise ProjectError("Selection requires revision_resolutions (empty if none)")
    covered = set()
    for history in histories:
        if not isinstance(history, dict):
            raise ProjectError("Revision resolution must be an object")
        idea = history.get("idea_id")
        if idea not in seen:
            raise ProjectError("Revision history refers to an unknown candidate")
        prior_path = project_path(root, history.get("review_receipt", ""))
        prior = load(prior_path)
        if sha(prior_path) != history.get("receipt_sha256"):
            raise ProjectError("Revision receipt changed")
        _binding(root, prior.get("raw_response"), "revision response")
        _binding(root, prior.get("identity_evidence"), "revision identity")
        package = load(_binding(root, prior.get("package_manifest"), "revision package"))
        if prior.get("scope", {}).get("idea_id") != idea or prior.get("scope", {}).get("purpose") != "idea-review" or package.get("idea_id") != idea:
            raise ProjectError("Revision review belongs to another candidate")
        scope = prior.get("scope", {})
        policy = load(root / "configs/models.json").get("policy", {})
        relation = independence(prior.get("executor_identity", {}), prior.get("actual_identity", {}))
        allowed = relation == "cross-family" or (relation == "human-review" and policy.get("accept_human_reviews", True))
        if (prior.get("completion") != "complete" or prior.get("verdict") != "PASS"
                or prior.get("fresh_context") is not True or not allowed or prior.get("independence") != relation
                or prior.get("executor_identity") != package.get("executor_identity")):
            raise ProjectError("Historical revision review lacks independent fresh-context acceptance")
        if (not package.get("files") or scope.get("files") != package["files"]
                or scope.get("input_bindings", []) != package.get("input_bindings", [])):
            raise ProjectError("Historical revision scope differs from preserved review package")
        package_dir = project_path(root, prior["package_manifest"]["path"]).parent
        reads = prior.get("direct_reads", [])
        for item in package["files"]:
            archived = project_path(package_dir, item.get("packaged_path", ""))
            if item.get("path") not in reads or not archived.is_file() or sha(archived) != item.get("sha256"):
                raise ProjectError("Historical revision packaged material missing, changed, or unread")
        previous = validate_scorecard(prior.get("scorecard"))
        if previous["recommendation"] != "revise" or history.get("final_review_receipt") != receipts[idea] or cards[idea]["recommendation"] != "go":
            raise ProjectError("Revision resolutions need a revise review followed by a current go review")
        responses = history.get("resolutions", [])
        if not isinstance(responses, list) or any(not isinstance(x, dict) for x in responses) or {x.get("request_id") for x in responses} != {x["id"] for x in previous["revision_requests"]} or len(responses) != len(previous["revision_requests"]):
            raise ProjectError("Every revision request needs exactly one resolution")
        for response in responses:
            if not isinstance(response.get("reason"), str) or not response["reason"].strip():
                raise ProjectError("Revision resolution requires a reason")
            _binding(root, response.get("evidence"), "revision resolution")
        if str(prior_path) not in declared_history:
            raise ProjectError("Revision receipt missing from candidate review_history")
        covered.add(str(prior_path))
    if declared_history - covered:
        raise ProjectError("Declared revision history lacks resolution records")
    # Retained review history must not disappear from the architect decision.
    for path in (root / "reviews/receipts").glob("*/receipt.json"):
        old = load(path)
        scope = old.get("scope", {})
        if scope.get("idea_id") in seen and scope.get("purpose") == "idea-review" and old.get("scorecard", {}).get("recommendation") == "revise" and cards[scope["idea_id"]]["recommendation"] == "go" and str(path.resolve()) not in covered:
            raise ProjectError("Prior revise review is missing from revision_resolutions")
    return record

"""Explicit, reviewed Agent World snapshots in the existing SF Social store.

Preparation is read-only. Publishing is a separate human action and never a
completion hook. Raw model answers, prompts, private Memory, judge rationale,
credentials, report files and hidden reasoning are not public snapshot fields.
The server supplies fresh rights and the existing numeric social identity.
"""
from __future__ import annotations

import hashlib
import json
import re

from .. import community, preview_sandbox, runtime_env
from . import contracts as c
from .domain_contracts import CourtCase, CourtVote
from .model_evaluation import evaluate
from .states import ContractError, EntityKind


_HEX = re.compile(r"^[0-9a-f]{64}$")
_SECRET = re.compile(r"(?i)(?:\bsk-[A-Za-z0-9_-]{16,}|\b(?:api[_ -]?key|password|authorization|access[_ -]?token)\s*[:=]\s*\S+|\bbearer\s+[A-Za-z0-9._-]{12,})")
_LIMITATION = "Evidence conformance only; not profitability or general model quality."
_NO_PRIVATE = "No prompts, raw answers, private Memory, judge reasoning or source files are published."


def _bytes(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise ContractError("social_snapshot_invalid") from None


def _sha(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _uuid(value):
    from uuid import UUID
    try:
        identity = value if isinstance(value, UUID) else UUID(str(value))
        c.require_uuid(identity)
        return identity
    except (ValueError, TypeError):
        raise ContractError("social_source_invalid") from None


class SocialPublicationService:
    def __init__(self, repository, *, community_api=None, backtest_loader=None):
        self.repository = repository
        self.community = community_api if community_api is not None else community
        self.backtest_loader = backtest_loader

    @staticmethod
    def _guard(context, admit):
        if (not isinstance(context, c.RequestContext) or context.scope.environment != c.Environment.DEVELOPMENT
                or not runtime_env.is_development() or preview_sandbox.enabled()
                or context.actor.kind != c.ActorKind.HUMAN or not callable(admit)):
            raise ContractError("social_local_human_admission_required")
        if admit() is False:
            raise ContractError("social_admission_denied")

    def _owned(self, context, kind, identity):
        record = self.repository.get(context=context, kind=kind, entity_id=_uuid(identity))
        if record is None or record.header.owner_user_uuid != context.user_uuid or record.header.scope != context.scope:
            raise ContractError("social_source_not_found")
        return record

    def _json(self, context, ref):
        if not isinstance(ref, c.SnapshotRef) or ref.scope != context.scope:
            raise ContractError("social_evidence_required")
        value = self.repository.get_artifact(context=context, reference=ref)
        if value is None or value[1] != "application/json" or hashlib.sha256(value[0]).hexdigest() != ref.sha256:
            raise ContractError("social_evidence_unavailable")
        try:
            data = json.loads(value[0])
        except (ValueError, UnicodeError):
            raise ContractError("social_evidence_invalid") from None
        if not isinstance(data, dict):
            raise ContractError("social_evidence_invalid")
        return data

    def _wire_ref(self, context, value):
        if not isinstance(value, dict):
            raise ContractError("social_evidence_required")
        scope = value.get("scope")
        if scope is not None and scope != c.primitive(context.scope):
            raise ContractError("social_evidence_scope_mismatch")
        return c.SnapshotRef(scope=context.scope, artifact_id=_uuid(value.get("artifact_id")), sha256=value.get("sha256"))

    def _evidence(self, context, refs):
        if not refs:
            raise ContractError("social_evidence_required")
        hashes = []
        for ref in refs:
            if not isinstance(ref, c.SnapshotRef) or ref.scope != context.scope:
                raise ContractError("social_evidence_required")
            found = self.repository.get_artifact(context=context, reference=ref)
            if found is None or hashlib.sha256(found[0]).hexdigest() != ref.sha256:
                raise ContractError("social_evidence_unavailable")
            hashes.append(ref.sha256)
        return sorted(set(hashes))

    def _model_receipt(self, context, task):
        if task.status != "succeeded" or task.checkpoint is None:
            raise ContractError("social_verified_source_required")
        checkpoint = self._json(context, task.checkpoint)
        spec = checkpoint.get("spec")
        if (checkpoint.get("source") != "real_model_task" or checkpoint.get("synthetic") is not False
                or checkpoint.get("task_id") != str(task.header.entity_id) or not isinstance(spec, dict)
                or not _HEX.fullmatch(str(checkpoint.get("request_sha256") or ""))):
            raise ContractError("social_real_source_required")
        model = self._owned(context, EntityKind.MODEL, checkpoint.get("model_id"))
        ref = self._wire_ref(context, checkpoint.get("receipt"))
        receipt = self._json(context, ref)
        if (receipt.get("source") != "provider_response" or receipt.get("synthetic") is not False
                or receipt.get("task_id") != str(task.header.entity_id)
                or receipt.get("request_sha256") != checkpoint["request_sha256"]):
            raise ContractError("social_receipt_mismatch")
        try:
            evaluated = evaluate(spec, receipt.get("response"))
        except (KeyError, TypeError, ValueError):
            raise ContractError("social_evaluation_invalid") from None
        if evaluated.get("passed") is not True:
            raise ContractError("social_verified_source_required")
        return checkpoint, model, ref, receipt, evaluated

    def _outcome(self, context, identity):
        outcome = self._owned(context, EntityKind.OUTCOME, identity)
        if outcome.status != "verified" or outcome.verification is None:
            raise ContractError("social_verified_source_required")
        task = self._owned(context, EntityKind.TASK, outcome.task.entity_id)
        checkpoint, model, receipt_ref, receipt, evaluated = self._model_receipt(context, task)
        proof = self._json(context, outcome.verification)
        hashes = self._evidence(context, outcome.evidence + (outcome.verification, receipt_ref))
        if outcome.execution is None:
            raise ContractError("social_execution_link_required")
        execution = self._owned(context, EntityKind.EXECUTION, outcome.execution.entity_id)
        if execution.status != "succeeded":
            raise ContractError("social_verified_source_required")
        common = (proof.get("task_id") == str(task.header.entity_id)
                  and proof.get("model_id") == str(model.header.entity_id)
                  and proof.get("self_scored") is False and proof.get("synthetic") is False and proof.get("passed") is True)
        if not common:
            raise ContractError("social_evaluation_mismatch")
        metrics = {}
        if proof.get("source") == "existing_application_receipt":
            request = checkpoint.get("application_request") or {}
            verification = proof.get("verification") or {}
            dispatch = checkpoint.get("application_dispatch") or {}
            expected_kind = {"backtest": "ninjatrader_report", "chart": "desktop_chart"}.get(request.get("kind"))
            expected_ids = [str(ref.artifact_id) for ref in outcome.evidence if ref != outcome.verification]
            if (not expected_kind or proof.get("source_kind") != expected_kind
                    or proof.get("evaluator") != "existing_application_evidence_verifier"
                    or verification.get("verified") is not True or verification.get("synthetic") is not False
                    or verification.get("source_kind") != expected_kind
                    or verification.get("request_sha256") != request.get("request_sha256")
                    or verification.get("source_id") != proof.get("source_id")
                    or dispatch.get("source_id") != proof.get("source_id")
                    or proof.get("artifact_ids") != expected_ids or verification.get("sha256") not in hashes
                    or execution.receipt != outcome.verification):
                raise ContractError("social_application_link_mismatch")
            source_ref = next(ref for ref in outcome.evidence if ref.sha256 == verification["sha256"])
            content, media_type = self.repository.get_artifact(context=context, reference=source_ref)
            if expected_kind == "desktop_chart":
                import base64
                from .http_api import decode_chart_png
                if media_type != "image/png" or verification.get("source_sha256") != source_ref.sha256:
                    raise ContractError("social_application_evidence_invalid")
                decode_chart_png("data:image/png;base64," + base64.b64encode(content).decode("ascii"))
            else:
                source = self._json(context, source_ref)
                checksums = source.get("source_checksums") or {}
                if (source.get("representation") != "verified_existing_report_summary" or source.get("synthetic") is not False
                        or source.get("source_kind") != expected_kind or source.get("source_id") != proof["source_id"]
                        or source.get("model_task_id") != str(task.header.entity_id)
                        or source.get("request_sha256") != request.get("request_sha256")
                        or checksums != verification.get("source_checksums")
                        or not {"result.json", "trades.json", "bars.json", "job.json"} <= set(checksums)
                        or any(not _HEX.fullmatch(str(value)) for value in checksums.values())
                        or verification.get("source_sha256") != checksums.get("result.json")):
                    raise ContractError("social_application_evidence_invalid")
                raw_metrics = (source.get("result") or {}).get("metrics") or {}
                metrics.update(community.attested_result_snapshot(proof["source_id"], {
                    "status": "done", "metrics": raw_metrics}, origin={"type": "backtest"})["metrics"])
                # Reuse the same sanitizer/rounding, and name each basis. Old
                # immutable publications are never rewritten by this projection.
                after_commission = community.attested_result_snapshot(proof["source_id"], {
                    "status": "done", "metrics": {key: raw_metrics.get(key) for key in
                        ("net_profit_after_commission", "profit_factor_after_commission")}}, origin={"type": "backtest"})["metrics"]
                for label in ("Net P&L", "Profit factor"):
                    if label in metrics:
                        basis = "after commission" if label in after_commission else "before commission"
                        metrics[f"{label} ({basis})"] = metrics.pop(label)
            source_kind, title = expected_kind, "Agent World · " + ("NinjaTrader result" if request["kind"] == "backtest" else "Desktop chart receipt")
            summary = "Existing application evidence verified; private source bytes are not published."
            metrics["Evidence files"] = len(expected_ids)
        else:
            if (checkpoint.get("application_request") or evaluated["rubric_key"] in {"court_vote", "connection_exact"}
                    or proof.get("evaluator") != "independent_local_evidence_verifier"
                    or any(proof.get(key) != value for key, value in evaluated.items())
                    or self._wire_ref(context, proof.get("receipt")) != receipt_ref or execution.receipt != receipt_ref):
                raise ContractError("social_evaluation_mismatch")
            source_kind, title = "real_model_response", "Agent World · verified capability result"
            summary = "Independent bounded capability test; no general model-quality claim."
            metrics = {"Passed checks": len(evaluated["checks"]), "Observed score %": evaluated["observed_score_pct"]}
        return outcome, {"kind": "Agent World Result", "title": title, "summary": summary,
                         "metrics": metrics, "source_kind": source_kind, "evidence_sha256": hashes,
                         "market_performance_claim": False, "routing_effect": "none"}

    def _decision(self, context, identity):
        decision = self._owned(context, EntityKind.DECISION, identity)
        if decision.status not in {"approved", "rejected"} or decision.approval is None:
            raise ContractError("social_verified_decision_required")
        approval = self._json(context, decision.approval)
        packet = self._json(context, decision.evidence_packet)
        if (approval.get("type") != "court_advisory_verdict" or approval.get("execution_allowed") is not False
                or approval.get("human_execution_approval_required") is not True
                or approval.get("packet_sha256") != decision.evidence_packet.sha256
                or approval.get("quorum") != "2-of-3-unweighted" or packet.get("policy_version") != "court-review-v1"):
            raise ContractError("social_verified_decision_required")
        case = self._owned(context, EntityKind.COURT_CASE, approval.get("case_id"))
        if (not isinstance(case, CourtCase) or case.status != "decided" or case.packet != decision.evidence_packet
                or case.decision.entity_id != decision.header.entity_id or len(case.votes) != 3
                or approval.get("votes") != [c.primitive(ref) for ref in case.votes]):
            raise ContractError("social_court_link_mismatch")
        votes, hashes = [], self._evidence(context, (decision.evidence_packet, decision.approval))
        for index, reference in enumerate(case.votes):
            vote = self._owned(context, EntityKind.COURT_VOTE, reference.entity_id)
            if (not isinstance(vote, CourtVote) or vote.ref() != reference or vote.status != "recorded"
                    or vote.case.entity_id != case.header.entity_id or vote.packet != case.packet
                    or vote.model != case.models[index] or vote.session_id != case.session_ids[index]
                    or vote.contribution is None):
                raise ContractError("social_court_link_mismatch")
            contribution = self._owned(context, EntityKind.CONTRIBUTION, vote.contribution.entity_id)
            task = self._owned(context, EntityKind.TASK, contribution.task.entity_id)
            checkpoint, model, receipt_ref, receipt, _ = self._model_receipt(context, task)
            spec = checkpoint["spec"]
            expected = {"rubric_key": "court_vote", "case_id": str(case.header.entity_id), "session_id": str(vote.session_id),
                        "packet_sha256": case.packet.sha256, "policy_version": "court-review-v1", "prompt_version": "isolated-judge-v1"}
            rationale = self._json(context, vote.rationale)
            if (contribution.status != "accepted" or contribution.ref() != vote.contribution
                    or contribution.result != receipt_ref or model.header.entity_id != vote.model.entity_id
                    or vote.provider_key != model.provider_key or vote.model_key != model.model_key
                    or any(spec.get(key) != value for key, value in expected.items())
                    or json.loads(receipt["response"]) != {"verdict": vote.verdict, "confidence": vote.confidence, "rationale": rationale.get("rationale")}):
                raise ContractError("social_court_link_mismatch")
            hashes += self._evidence(context, contribution.evidence + (vote.rationale,))
            votes.append(vote)
        counts = {value: sum(vote.verdict == value for vote in votes) for value in ("approve", "reject", "abstain")}
        verdict = "approve" if counts["approve"] >= 2 else "reject" if counts["reject"] >= 2 else "no_quorum"
        if (verdict != case.verdict or verdict != approval.get("verdict")
                or decision.status != ("approved" if verdict == "approve" else "rejected")
                or case.risk == c.Risk.CRITICAL and len({vote.failure_domain for vote in votes}) < 2):
            raise ContractError("social_court_quorum_mismatch")
        return decision, {"kind": "Agent World Decision", "title": "Agent World · independently reviewed decision",
                          "summary": "Court advisory verdict: " + verdict + ". No authority to execute.",
                          "metrics": {"Approve": counts["approve"], "Reject": counts["reject"], "Abstain": counts["abstain"]},
                          "verdict": verdict, "risk": case.risk.value, "source_kind": "court_advisory_verdict",
                          "evidence_sha256": sorted(set(hashes)), "execution_allowed": False}

    def _backtest(self, context, admit, identity):
        if not callable(self.backtest_loader):
            raise ContractError("social_backtest_adapter_required")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", identity):
            raise ContractError("social_source_invalid")
        detail = self.backtest_loader(context=context, source_id=identity, admit=admit)
        if not isinstance(detail, dict):
            raise ContractError("social_source_not_found")
        task, verification, result = detail.get("task") or {}, detail.get("verification") or {}, detail.get("result") or {}
        hashes = verification.get("source_checksums") or {}
        if (task.get("source_job_id") != identity or task.get("source_kind") != "ninjatrader_report"
                or task.get("synthetic") is not False or task.get("source_status") != "done" or task.get("status") != "succeeded"
                or verification.get("passed") is not True or verification.get("reasons") != []
                or result.get("synthetic") is not False or result.get("source_job_id") != identity
                or not {"result.json", "trades.json", "bars.json", "job.json"} <= set(hashes)
                or any(not isinstance(value, str) or not _HEX.fullmatch(value) for value in hashes.values())):
            raise ContractError("social_verified_source_required")
        snapshot = community.attested_result_snapshot(identity, {"status": "done", "metrics": result.get("metrics"),
            "finished_at_utc": task.get("updated_at")}, origin={"type": "backtest"})
        snapshot.update(title="Agent World · verified NinjaTrader result", source_kind="ninjatrader_report",
                        evidence_sha256=sorted(set(hashes.values())), source_type="agent_world_backtest",
                        source_revision=1, synthetic=False, market_performance_claim=False,
                        limitations=[_LIMITATION, _NO_PRIVATE])
        snapshot.pop("attestation", None)
        return snapshot

    def prepare(self, *, context, admit, source_kind, source_id):
        """Return exactly the public card proposed for an explicit human POST."""
        self._guard(context, admit)
        if source_kind == "backtest":
            snapshot = self._backtest(context, admit, source_id)
        elif source_kind in {"outcome", "decision"}:
            record, snapshot = (self._outcome(context, source_id) if source_kind == "outcome" else self._decision(context, source_id))
            snapshot.update(snapshot_version=1, source_type="agent_world_" + source_kind,
                            source_id=str(record.header.entity_id), source_revision=record.header.revision,
                            timestamp_utc=c.primitive(record.header.updated_at), synthetic=False,
                            limitations=[_LIMITATION, _NO_PRIVATE])
        else:
            # Arbitrary artifacts and Memory can never be laundered as a result.
            raise ContractError("social_source_kind_denied")
        snapshot["attestation"] = {"algorithm": "sha256", "digest": _sha(snapshot)}
        self._guard(context, admit)
        return {"snapshot": snapshot, "snapshot_sha256": _sha(snapshot), "source_revision": snapshot["source_revision"],
                "permanent": True, "requires_explicit_confirmation": True}

    def publish(self, *, context, admit, user_id, source_kind, source_id,
                approved_snapshot_sha256, expected_revision, idempotency_key,
                text="", visibility="network", confirm_permanent=False):
        self._guard(context, admit)
        if confirm_permanent is not True:
            raise ContractError("social_permanent_confirmation_required")
        if type(user_id) is not int or user_id <= 0:
            raise ContractError("social_server_identity_required")
        if (type(expected_revision) is not int or expected_revision < 1
                or not isinstance(approved_snapshot_sha256, str) or not _HEX.fullmatch(approved_snapshot_sha256)):
            raise ContractError("social_approved_snapshot_required")
        if (not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 160
                or any(ord(char) < 33 or ord(char) > 126 for char in idempotency_key)):
            raise ContractError("social_idempotency_required")
        if (not isinstance(text, str) or len(text) > 4000 or _SECRET.search(text)
                or any(ord(char) < 32 and char not in "\n\t" for char in text)):
            raise ContractError("social_public_text_invalid")
        if visibility not in {"network", "followers", "private"}:
            raise ContractError("social_visibility_invalid")
        prepared = self.prepare(context=context, admit=admit, source_kind=source_kind, source_id=source_id)
        if prepared["snapshot_sha256"] != approved_snapshot_sha256 or prepared["source_revision"] != expected_revision:
            raise ContractError("social_approved_snapshot_changed")
        text = text.strip()
        request_hash = _sha({"environment": context.scope.environment.value, "workspace_id": context.scope.workspace_id,
            "user_uuid": str(context.user_uuid), "user_id": user_id, "snapshot_sha256": approved_snapshot_sha256,
            "text": text, "visibility": visibility, "permanent": True})
        # The immutable approval stays private. Actor and business requester are
        # separate fields; no model claims to be the person who approved sharing.
        approval = {"schema_version": 1, "type": "explicit_human_social_publication",
            "request_sha256": request_hash, "snapshot_sha256": approved_snapshot_sha256,
            "scope": c.primitive(context.scope), "actor": c.primitive(context.actor),
            "requester_user_uuid": str(context.user_uuid), "snapshot": prepared["snapshot"],
            "visibility": visibility, "text": text, "permanent": True}
        self._guard(context, admit)
        approval_ref = self.repository.put_artifact(context=context, content=_bytes(approval), media_type="application/json")
        # Recheck mutable source authority/hash after saving the approval, before
        # the external store effect. A stale/withdrawn source is not republished.
        fresh = self.prepare(context=context, admit=admit, source_kind=source_kind, source_id=source_id)
        if fresh["snapshot_sha256"] != approved_snapshot_sha256:
            raise ContractError("social_approved_snapshot_changed")
        snapshot = dict(prepared["snapshot"])
        snapshot["publication_approval"] = {"request_sha256": request_hash, "snapshot_sha256": approved_snapshot_sha256,
                                           "approval_sha256": approval_ref.sha256, "explicit_human": True}
        key = "agent-world-social." + _sha([context.scope.environment.value, context.scope.workspace_id,
                                             str(context.user_uuid), idempotency_key])
        self._guard(context, admit)
        result = self.community.create_social_post(user_id, text=text, visibility=visibility,
            workspace_id=context.scope.workspace_id, user_uuid=str(context.user_uuid), idempotency_key=key,
            object_snapshot=snapshot, trusted_snapshot=True)
        post = result.get("post") if isinstance(result, dict) else None
        # Existing Community deduplicates by author/key. Check the original
        # semantic request too, rather than accepting a different-body retry.
        saved = ((post or {}).get("object") or {}).get("publication_approval") or {}
        if not result.get("ok") or saved.get("request_sha256") != request_hash:
            raise ContractError("social_idempotency_conflict")
        return {"ok": True, "post": post, "deduplicated": result.get("deduplicated") is True,
                "snapshot_sha256": approved_snapshot_sha256, "approval": c.primitive(approval_ref),
                "permanent": True, "published_to": "sf_social"}

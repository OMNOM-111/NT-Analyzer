"""Read-only structured work patterns -> explicit existing-domain proposals.

No transcript reader, model call, schedule/grant, new job or side database.
The caller supplies existing scoped services/admission; retained Routine and
CalendarItem records are the durable suggestion and cooldown history.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
import re
from statistics import median

from . import contracts as c
from .domain_service import _hash, _utc
from .model_evaluation import APPLICATION_RUBRIC
from .repositories import PageRequest
from .social_publication import SocialPublicationService
from .states import ContractError, EntityKind


VERSION = "process-intelligence-v1"
_EVENTS = frozenset({"stratforge.ai.outcome.verified", "stratforge.ai.outcome.changed"})
_DOMAINS = {"routines": EntityKind.ROUTINE, "calendar": EntityKind.CALENDAR_ITEM}
_KINDS = {"ninjatrader_report": ("backtest", "Разбор результатов бэктеста"),
          "desktop_chart": ("chart", "Разбор проверенных графиков")}
_HEX = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Policy:
    minimum_observations: int = 3
    cooldown_minutes: int = 1440
    lookback_days: int = 30
    max_events: int = 10000

    def __post_init__(self):
        for name, low, high in (("minimum_observations", 2, 24), ("cooldown_minutes", 60, 525600),
                                ("lookback_days", 1, 365), ("max_events", 1, 10000)):
            if type(getattr(self, name)) is not int or not low <= getattr(self, name) <= high:
                raise ContractError("process_policy_invalid")


class ProcessIntelligence:
    def __init__(self, domains, models, *, policy=None):
        if domains.repository is not models.repository:
            raise ContractError("process_repository_mismatch")
        self.domains, self.models, self.repository = domains, models, domains.repository
        self.policy = Policy() if policy is None else policy
        if not isinstance(self.policy, Policy):
            raise ContractError("process_policy_invalid")
        self.verifier = SocialPublicationService(self.repository)

    @staticmethod
    def _guard(context, admit, *, write=False):
        if (not isinstance(context, c.RequestContext) or not callable(admit)
                or write and context.actor.kind != c.ActorKind.HUMAN):
            raise ContractError("process_admission_required")
        if admit() is False:
            raise ContractError("process_admission_denied")

    def _all(self, context, admit, *, kind=None):
        """Use only tenant/user-bound repository cursors; incomplete is explicit."""
        result, cursor, visited = [], None, set()
        while True:
            self._guard(context, admit)
            page = PageRequest(limit=min(100, self.policy.max_events-len(result)), cursor=cursor)
            batch = (self.repository.events.list(context=context, page=page) if kind is None
                     else self.repository.list(context=context, kind=kind, page=page))
            result.extend(batch.items)
            if not batch.next_cursor:
                return result, True
            if len(result) >= self.policy.max_events or batch.next_cursor in visited:
                return result, False
            cursor = batch.next_cursor
            visited.add(cursor)

    def _metadata(self, context, identity):
        """Strict existing verifier + task projection; expose only allowlisted facts."""
        outcome = self.domains._owned(context, EntityKind.OUTCOME, identity)
        if outcome.status != "verified" or outcome.verification is None:
            raise ContractError("process_source_unverified")
        proof = self.domains._json(context, outcome.verification)
        if proof.get("synthetic") is not False:
            raise ContractError("process_source_synthetic")
        if proof.get("rubric_key") != APPLICATION_RUBRIC:
            if proof.get("rubric_key") in {"backtest_spec", "chart_spec"}:
                raise ContractError("process_provider_plan_only")
            raise ContractError("process_bounded_capability")
        checked, public = self.verifier._outcome(context, identity)
        if checked.ref() != outcome.ref() or public.get("source_kind") not in _KINDS:
            raise ContractError("process_source_unverified")
        detail = self.models.task_detail(context=context, task_id=outcome.task.entity_id)
        execution = detail.get("execution_v2") or {}
        review = (detail.get("human_review") or {}).get("status", "not_required")
        application = detail.get("application_evaluation") or {}
        if (detail.get("status") != "succeeded" or review in {"rejected", "blocked"}
                or execution and (execution.get("status") != "succeeded" or execution.get("deviation_count", 0))
                or application.get("outcome_id") != str(outcome.header.entity_id)):
            raise ContractError("process_source_review_required")
        if type(proof.get("source_id")) is not str or not _HEX.fullmatch(str(proof.get("input_sha256", ""))):
            raise ContractError("process_source_unverified")
        c.require_token(proof["source_id"], limit=160)
        return {"outcome_id": str(outcome.header.entity_id), "revision": outcome.header.revision,
                "task_id": str(outcome.task.entity_id), "verification_id": str(outcome.verification.artifact_id),
                "verification_sha256": outcome.verification.sha256, "source_kind": public["source_kind"],
                "source_id": proof["source_id"], "at": c.primitive(outcome.header.updated_at),
                "pending_review": review == "pending"}

    @staticmethod
    def _source(metadata):
        return {key: value for key, value in metadata.items() if key != "pending_review"}

    @staticmethod
    def _pattern(context, source_kind):
        return _hash([VERSION, c.primitive(context.scope), str(context.user_uuid), source_kind])

    @staticmethod
    def _identity(pattern, domain, sequence):
        return _hash([VERSION, pattern, domain, sequence])

    def _marker(self, context, record):
        definition = self.domains._json(context, record.definition)
        markers = []
        for ref in record.provenance:
            artifact = self.repository.get_artifact(context=context, reference=ref)
            if artifact is None:
                raise ContractError("process_marker_unavailable")
            if artifact[1] != "application/json":
                continue
            data = self.domains._json(context, ref)
            if data.get("source") == "process_intelligence_suggestion" and data.get("version") == VERSION:
                markers.append(data)
        if not markers:
            return None
        if len(markers) != 1:
            raise ContractError("process_marker_invalid")
        marker = markers[0]
        domain, sequence = marker.get("domain"), marker.get("sequence")
        sources = marker.get("sources")
        if (domain not in _DOMAINS or record.KIND != _DOMAINS[domain]
                or type(sequence) is not int or sequence < 1
                or type(sources) is not list or not 2 <= len(sources) <= 24
                or not all(type(row) is dict for row in sources)
                or not _HEX.fullmatch(str(marker.get("source_sha256", "")))
                or marker.get("pattern_id") != self._pattern(context, sources[0].get("source_kind"))
                or marker.get("candidate_id") != self._identity(marker["pattern_id"], domain, sequence)
                or marker.get("observations_sha256") != _hash(sources)
                or any(row.get("verification_id") not in definition.get("source_ids", []) for row in sources)):
            raise ContractError("process_marker_invalid")
        key = self._key(marker["pattern_id"], domain, sequence)
        expected = self.domains._id(context, "domain." + domain + ".create:" + self.domains._key(context, key))
        if record.header.entity_id != expected:
            raise ContractError("process_marker_invalid")
        return marker

    def _history(self, context, admit):
        result = []
        for domain, kind in _DOMAINS.items():
            rows, complete = self._all(context, admit, kind=kind)
            if not complete:
                return [], False
            for record in rows:
                if record.header.owner_user_uuid != context.user_uuid:
                    continue
                marker = self._marker(context, record)
                if marker:
                    result.append({"domain": domain, "record": record, "marker": marker})
        return result, True

    @staticmethod
    def _key(pattern, domain, sequence):
        return f"process-v1.{domain}.{pattern}.{sequence}"

    def analyze(self, *, context, admit):
        self._guard(context, admit)
        now = self.domains.now()
        c.require_utc(now)
        events, complete = self._all(context, admit)
        base = {"version": VERSION, "automation_enabled": False, "quality_claim": False,
                "private_messages_read": False, "candidates": [], "suppressed": [], "excluded": {},
                "incomplete": not complete, "source_denominator": "verified_application_workflow_occurrences",
                "minimum_observations": self.policy.minimum_observations,
                "limitations": ["Предложение не включает автоматизацию и не закрывает проверки результата.",
                    "Повторяемость работ не является профессиональной оценкой модели.",
                    "Пока анализируются только проверенные результаты бэктеста и графика за ограниченное окно."]}
        if not complete:
            return {**base, "reason": "event_scan_limit"}
        history, complete = self._history(context, admit)
        if not complete:
            return {**base, "incomplete": True, "reason": "proposal_scan_limit"}
        cutoff = now-timedelta(days=self.policy.lookback_days)
        selected = {}
        for event in events:
            if event is None or event.scope != context.scope:
                raise ContractError("process_event_scope_invalid")
            if (event.event_type in _EVENTS and event.subject.kind == EntityKind.OUTCOME
                    and cutoff <= event.time <= now):
                previous = selected.get(event.subject.entity_id)
                if previous is None or event.subject.revision > previous.subject.revision:
                    selected[event.subject.entity_id] = event
        excluded, grouped, seen = Counter(), defaultdict(list), set()
        for identity, event in sorted(selected.items(), key=lambda pair: pair[1].time):
            self._guard(context, admit)
            try:
                row = self._metadata(context, identity)
                if row["revision"] != event.subject.revision:
                    raise ContractError("process_stale_outcome_event")
                receipt = (row["source_kind"], row["source_id"])
                if receipt in seen:
                    excluded["duplicate_source"] += 1
                    continue
                seen.add(receipt)
                grouped[row["source_kind"]].append(row)
            except ContractError as exc:
                reason = {"process_bounded_capability": "bounded_capability",
                          "process_provider_plan_only": "provider_plan_only",
                          "process_source_synthetic": "synthetic_source",
                          "process_source_review_required": "review_or_deviation"}.get(exc.code, "unverified_or_unavailable")
                excluded[reason] += 1
        suppressed, candidates = [], []
        for source_kind, observations in grouped.items():
            rows = sorted(observations, key=lambda row: (row["at"], row["outcome_id"]))[-24:]
            times = [_utc(row["at"]) for row in rows]
            if (len(rows) < self.policy.minimum_observations
                    or len({row["task_id"] for row in rows}) < self.policy.minimum_observations
                    or len({stamp.date() for stamp in times}) < 2
                    or (times[-1]-times[0]).total_seconds() < 600):
                suppressed.append({"source_kind": source_kind, "reason": "insufficient_repeated_work",
                                   "sample_size": len(rows)})
                continue
            minutes = max(5, min(525600, round(median([(b-a).total_seconds()/60 for a, b in zip(times, times[1:])]))))
            pattern = self._pattern(context, source_kind)
            sources = [self._source(row) for row in rows]
            source_hash = _hash(sources)
            for domain in _DOMAINS:
                previous = [entry for entry in history if entry["domain"] == domain and entry["marker"]["pattern_id"] == pattern]
                previous.sort(key=lambda entry: entry["marker"]["sequence"])
                last = previous[-1] if previous else None
                reason = None
                if last:
                    record, marker = last["record"], last["marker"]
                    if (record.status == "proposed" or record.status == "accepted"
                            and (domain == "routines" or record.ends_at > now)):
                        reason = "existing_proposal"
                    elif record.header.created_at+timedelta(minutes=self.policy.cooldown_minutes) > now:
                        reason = "cooldown"
                    elif not ({(row["source_kind"], row["source_id"]) for row in rows}
                              - {(source["source_kind"], source["source_id"]) for entry in previous
                                 for source in entry["marker"]["sources"]}):
                        reason = "duplicate_observations"
                if reason:
                    suppressed.append({"domain": domain, "pattern_id": pattern, "reason": reason,
                                       "suggestion_id": str(last["record"].header.entity_id)})
                    continue
                sequence = last["marker"]["sequence"]+1 if last else 1
                candidate = {"id": self._identity(pattern, domain, sequence), "domain": domain,
                    "pattern_id": pattern, "sequence": sequence, "title": _KINDS[source_kind][1],
                    "source_kind": source_kind, "task_class": _KINDS[source_kind][0],
                    "sample_size": len(rows), "interval_minutes": minutes, "first_at": rows[0]["at"],
                    "last_at": rows[-1]["at"], "sources": sources, "observations_sha256": source_hash,
                    "pending_source_reviews": sum(row["pending_review"] for row in rows),
                    "cadence_basis": "median_spacing_between_verified_outcomes", "confidence": "low",
                    "automation_enabled": False, "quality_claim": False,
                    "description": f"Повторяющаяся работа: {len(rows)} проверенных результатов. Только предложение для ручного рассмотрения.",
                    "actions": ["propose"]}
                if domain == "calendar":
                    period = timedelta(minutes=minutes)
                    steps = max(1, int((now-times[-1]).total_seconds()//period.total_seconds())+1)
                    starts = times[-1]+steps*period
                    candidate.update(starts_at=c.primitive(starts), ends_at=c.primitive(starts+timedelta(minutes=30)))
                candidate["source_sha256"] = _hash(candidate)
                candidates.append(candidate)
        self._guard(context, admit)
        return {**base, "candidates": candidates, "suppressed": suppressed, "excluded": dict(excluded)}

    def validate_suggestion(self, *, context, admit, domain, entity_id, expected_revision):
        self._guard(context, admit)
        if domain not in _DOMAINS:
            raise ContractError("process_domain_invalid")
        record = self.domains._owned(context, _DOMAINS[domain], entity_id)
        if type(expected_revision) is not int or record.header.revision != expected_revision:
            raise ContractError("process_suggestion_stale")
        marker = self._marker(context, record)
        if marker is None:
            return {"managed": False, "source_valid": None, "automation_enabled": False}
        try:
            for source in marker["sources"]:
                self._guard(context, admit)
                current = self._metadata(context, source["outcome_id"])
                if self._source(current) != source:
                    raise ContractError("process_sources_changed")
        except ContractError:
            self._guard(context, admit)
            raise ContractError("process_sources_changed") from None
        self._guard(context, admit)
        return {"managed": True, "source_valid": True, "quality_claim": False,
                "source_sha256": marker["source_sha256"], "automation_enabled": False}

    def _replay(self, context, admit, domain, candidate_id, source_sha256):
        history, complete = self._history(context, admit)
        if not complete:
            raise ContractError("process_scan_incomplete")
        for entry in history:
            marker, record = entry["marker"], entry["record"]
            if entry["domain"] == domain and marker["candidate_id"] == candidate_id:
                if marker["source_sha256"] != source_sha256:
                    raise ContractError("process_sources_changed")
                self.validate_suggestion(context=context, admit=admit, domain=domain,
                    entity_id=record.header.entity_id, expected_revision=record.header.revision)
                return {"domain": domain, "replayed": True, "item": self.domains.get(
                    context=context, admit=admit, domain=domain, entity_id=record.header.entity_id)}
        return None

    def propose(self, *, context, admit, domain, candidate_id, source_sha256):
        self._guard(context, admit, write=True)
        if (domain not in _DOMAINS or type(candidate_id) is not str or not _HEX.fullmatch(candidate_id)
                or type(source_sha256) is not str or not _HEX.fullmatch(source_sha256)):
            raise ContractError("process_candidate_invalid")
        replay = self._replay(context, admit, domain, candidate_id, source_sha256)
        if replay is not None:
            return replay
        current = self.analyze(context=context, admit=admit)
        row = next((row for row in current["candidates"] if row["domain"] == domain and row["id"] == candidate_id), None)
        if row is None or row["source_sha256"] != source_sha256:
            # Another process may have committed this exact suggestion between
            # the first history read and analysis. Never adopt different input.
            replay = self._replay(context, admit, domain, candidate_id, source_sha256)
            if replay is not None:
                return replay
            raise ContractError("process_sources_changed")
        marker = {"version": VERSION, "source": "process_intelligence_suggestion", "domain": domain,
            "pattern_id": row["pattern_id"], "sequence": row["sequence"], "candidate_id": row["id"],
            "source_sha256": row["source_sha256"], "observations_sha256": row["observations_sha256"],
            "sources": row["sources"], "automation_enabled": False, "quality_claim": False}
        reference = self.domains._put(context, admit, marker)
        fields = ("title", "description", "interval_minutes") if domain == "routines" else ("title", "description", "starts_at", "ends_at")
        payload = {key: row[key] for key in fields}
        payload["source_ids"] = list(dict.fromkeys([source["verification_id"] for source in row["sources"]]+[str(reference.artifact_id)]))
        self._guard(context, admit, write=True)
        for source in row["sources"]:
            if self._source(self._metadata(context, source["outcome_id"])) != source:
                raise ContractError("process_sources_changed")
        result = self.domains.create(context=context, admit=admit, domain=domain, payload=payload,
            idempotency_key=self._key(row["pattern_id"], domain, row["sequence"]))
        return {"domain": domain, **result}

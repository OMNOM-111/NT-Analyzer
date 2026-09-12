"""Schedule source/preview contracts; browser acceptance is separate."""
import json
import subprocess

import pytest

from tests.test_agent_world_ui import SCRIPT, evaluate


def preview_check(result, source, payload):
    # Expose the production pure validator without changing browser exports.
    program = "const fs=require('fs'),vm=require('vm');const module={exports:{}};"
    program += "vm.runInNewContext(fs.readFileSync(" + json.dumps(str(SCRIPT)) + ", 'utf8').replace('module.exports = { esc,', 'module.exports = { validSchedulePreview, esc,'),{module,console});"
    program += "process.stdout.write(JSON.stringify(module.exports.validSchedulePreview(" + ",".join(json.dumps(v) for v in (result, source, payload)) + ")));"
    completed = subprocess.run(["node", "-e", program], capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)


def fixture():
    source = {"domain": "routines", "id": "11111111-1111-4111-8111-111111111111", "revision": 2, "status": "accepted"}
    payload = {"model_id": "22222222-2222-4222-8222-222222222222", "rubric_key": "json_arithmetic", "occurrences": 2}
    result = {"approved": False, "actions": ["enable"], "plan": {"source": {"entity_id": source["id"], "revision": 2},
        "domain": "routines", "model_id": payload["model_id"], "synthetic": True,
        "due_at": ["2026-09-13T01:00:00Z", "2026-09-13T01:01:00Z"], "spec": {"rubric_key": "json_arithmetic"}}}
    return result, source, payload


@pytest.mark.parametrize("domain", ["routines", "calendar"])
def test_accepted_sources_validate_preview(domain):
    result, source, payload = fixture()
    result["plan"]["domain"] = source["domain"] = domain
    assert preview_check(result, source, payload)


@pytest.mark.parametrize("field,value", [("id", "new"), ("revision", 3), ("status", "proposed"), ("domain", "memory")])
def test_changed_or_unaccepted_source_refused(field, value):
    result, source, payload = fixture()
    source[field] = value
    assert not preview_check(result, source, payload)


def test_schedule_bounds_match_backend():
    fields = evaluate("ui.domainFormFields('automation','propose')")
    fields = {row["key"]: row for row in fields}
    assert fields["grace_minutes"]["max"] == 60
    assert fields["interval_minutes"]["max"] == 43200


def test_source_entrypoint_preserves_identity_revision_and_two_step_consent():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "API.aiControlCenterDomainItem(domain, id, { signal })" in source
    assert "scheduleSource: source" in source
    assert "payload.source_domain = state.scheduleSource.domain" in source
    assert "revision: state.scheduleSource.revision" in source
    assert "scheduleApproval: { payload }" in source
    assert "state.scheduleApproval ? { ...state.scheduleApproval.payload }" in source
    assert "data-aw-schedule-source" in source
    assert "Разрешаю именно эти запуски" in source

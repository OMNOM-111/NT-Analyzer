#!/usr/bin/env python3
"""Fail closed when the current Timeline and AI_CONTEXT drift apart.

The optional base commit also enforces the documentation contract for a PR or
main commit. CI passes the first parent of its checked-out commit.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import validate_external_gpt_context


REPO = Path(__file__).resolve().parents[2]
PACK = REPO / "AI_CONTEXT"
TIMELINE = REPO / "timeline.html"
OLD_PACK = REPO / "NT-Analyzer" / "docs" / "external-gpt-context"
VERSION = re.compile(r"0\.10\.0-beta\.\d+")
ARTIFACT = re.compile(r"art_[0-9a-f]{32}")
SHA = re.compile(r"[0-9a-f]{40}")


def _run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO, input=input_text, text=True,
                          encoding="utf-8", errors="replace", capture_output=True)


def _javascript_data(html: str) -> tuple[list[dict], list[dict], list[str]]:
    errors: list[str] = []
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)
    if not scripts:
        return [], [], ["timeline.html contains no inline JavaScript"]
    for number, script in enumerate(scripts, 1):
        checked = _run(["node", "--check"], input_text=script)
        if checked.returncode:
            errors.append(f"timeline.html script {number} syntax: {checked.stderr.strip()[:400]}")
    start = html.find("  const environments = [")
    end = html.find("  const element =", start)
    if start < 0 or end < 0:
        return [], [], errors + ["timeline.html environment/milestone data missing"]
    program = html[start:end] + "\nconsole.log(JSON.stringify({environments,milestones}));\n"
    evaluated = _run(["node"], input_text=program)
    if evaluated.returncode:
        return [], [], errors + [f"timeline.html data evaluation: {evaluated.stderr.strip()[:400]}"]
    try:
        data = json.loads(evaluated.stdout)
    except json.JSONDecodeError:
        return [], [], errors + ["timeline.html data is not serializable"]
    return data["environments"], data["milestones"], errors


def _index_value(text: str, label: str) -> str:
    match = re.search(r"^\|\s*" + re.escape(label) + r"\s*\|\s*(.*?)\s*\|\s*$", text, re.MULTILINE)
    return match.group(1) if match else ""


def _changed(base: str) -> list[str]:
    diff = _run(["git", "diff", "--name-only", "--diff-filter=ACMR", base, "HEAD", "--"])
    if diff.returncode:
        raise ValueError(f"cannot inspect documentation diff from {base}: {diff.stderr.strip()}")
    return [line.strip().replace("\\", "/") for line in diff.stdout.splitlines() if line.strip()]


def validate(base: str | None = None) -> list[str]:
    errors: list[str] = []
    context = validate_external_gpt_context.validate()
    errors.extend(context.errors)
    if OLD_PACK.exists():
        errors.append("old docs/external-gpt-context still exists; AI_CONTEXT must be canonical")
    if not TIMELINE.is_file() or not PACK.is_dir():
        return errors + ["timeline.html or root AI_CONTEXT missing"]

    html = TIMELINE.read_text(encoding="utf-8")
    index = (PACK / "00_STRATFORGE_CONTEXT_INDEX.md").read_text(encoding="utf-8")
    current_state = (PACK / "02_CURRENT_SYSTEM_STATE.md").read_text(encoding="utf-8")
    handoff = (PACK / "11_ACTIVE_WORK_AND_HANDOFF.md").read_text(encoding="utf-8")
    environments, milestones, js_errors = _javascript_data(html)
    errors.extend(js_errors)
    if not index.strip() or not current_state.strip() or not handoff.strip():
        errors.append("AI_CONTEXT index/current-state/handoff must be nonempty")
    current_cards = [item for item in milestones if item.get("current") is True]
    if len(current_cards) != 1:
        errors.append(f"Timeline must have exactly one current card, found {len(current_cards)}")
    elif current_cards[0].get("workStatus") == "done":
        if "unresolvedBlockers" not in current_cards[0]:
            errors.append("Done current card must explicitly declare unresolvedBlockers:[]")
        elif current_cards[0]["unresolvedBlockers"]:
            errors.append("Done current card has unresolved blockers")
        if "- Status: DONE" not in handoff.split("\n##", 1)[0]:
            errors.append("Done current card conflicts with active handoff status")

    production = next((item for item in environments if item.get("kind") == "production"), {})
    version = VERSION.search(_index_value(index, "Current public version"))
    artifact = ARTIFACT.search(_index_value(index, "Operational artifact"))
    source = SHA.search(_index_value(index, "Deployed application source"))
    if not version or production.get("version") != version.group():
        errors.append("Timeline Production version differs from AI_CONTEXT index")
    if not artifact or artifact.group() not in html or artifact.group() not in current_state or artifact.group() not in handoff:
        errors.append("Production artifact identity differs across Timeline and AI_CONTEXT")
    if not source or not production.get("commit") or not source.group().startswith(production["commit"]):
        errors.append("Timeline Production SHA differs from AI_CONTEXT index")
    elif source.group() not in current_state or source.group() not in handoff:
        errors.append("Deployed source SHA missing from current-state/handoff")
    if "docs/external-gpt-context/" in index.split("\n## Snapshot", 1)[0] and "выведен" not in index:
        errors.append("old context path still described as canonical")

    if base:
        changed = _changed(base)
        relevant = any(path.startswith(("NT-Analyzer/app/", "NT-Analyzer/tools/", "NT-Analyzer/tests/", ".github/workflows/"))
                       or path in {"AGENTS.md", "CLAUDE.md", "NT-Analyzer/VERSION.json"}
                       for path in changed)
        if relevant:
            needed = {"timeline.html", "AI_CONTEXT/02_CURRENT_SYSTEM_STATE.md", "AI_CONTEXT/11_ACTIVE_WORK_AND_HANDOFF.md"}
            missing = needed - set(changed)
            if missing:
                errors.append("code/config change lacks Timeline + AI_CONTEXT sync: " + ", ".join(sorted(missing)))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="base commit to enforce changed-file synchronization")
    args = parser.parse_args()
    try:
        errors = validate(args.base)
    except ValueError as exc:
        errors = [str(exc)]
    if errors:
        print("DOCUMENTATION SYNC FAIL")
        for error in errors:
            print("  " + error)
        return 1
    print("DOCUMENTATION SYNC OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

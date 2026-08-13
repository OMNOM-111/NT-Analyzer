#!/usr/bin/env python3
"""Validate the compact External GPT Context Pack.

The validator is intentionally static and conservative. It checks that the pack
exists, keeps the expected compact shape, contains the required metadata,
resolves its internal links and does not accidentally leak obvious secrets,
runtime values or absolute local paths.
"""
from __future__ import annotations

import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "docs" / "external-gpt-context"
REQUIRED_DOCS = [
    "00_STRATFORGE_CONTEXT_INDEX.md",
    "01_PRODUCT_VISION_AND_SCOPE.md",
    "02_CURRENT_SYSTEM_STATE.md",
    "03_ARCHITECTURE_AND_DATA_MODEL.md",
    "04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md",
    "05_AUTH_USERS_SECURITY.md",
    "06_MARKET_DATA_TRADING_CONNECTOR.md",
    "07_AI_AGENTS_AND_AUTOMATION.md",
    "08_UI_UX_AND_PRODUCT_CONTRACTS.md",
    "09_DOCUMENTATION_GOVERNANCE_LEGAL.md",
    "10_DECISIONS_HISTORY_AND_CHANGELOG.md",
    "11_ACTIVE_WORK_AND_HANDOFF.md",
    "12_API_AND_SCHEMA_REFERENCE.md",
    "13_TEST_AND_ACCEPTANCE_MATRIX.md",
    "14_EXTERNAL_GPT_OPERATING_INSTRUCTIONS.md",
]
MAX_DOCS = 15
ALLOWED_STATUSES = {
    "DONE",
    "PARTIAL",
    "EXTERNAL BLOCKED",
    "IN DEVELOPMENT",
    "PLANNED",
    "DEPRECATED",
}
SECRET_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b")),
    ("github_token", re.compile(r"\bgh[psoru]_[A-Za-z0-9]{30,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("telegram_token", re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")),
)
SUSPECT_ENV_VALUE = re.compile(
    r"\b(?:[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)|DATABASE_URL|REDIS_URL|CSRF_KEY)\s*=\s*(?!.*(?:placeholder|example|masked|redacted|owner decision))\S+",
)
ABSOLUTE_PATH = re.compile(r"(?i)(?:\b[A-Z]:\\|\\\\[A-Za-z0-9_. -]+\\|/Users/|/home/|/var/)")
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip().lower()


def _parse_header(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()[:18]
    fields: dict[str, str] = {}
    for line in lines:
        if not line.startswith("- ") or ":" not in line:
            continue
        key, value = line[2:].split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def _validate_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return value.endswith("Z")


def _resolve_markdown_links(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    for match in MARKDOWN_LINK.finditer(text):
        target = match.group(1).strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:", "data:")):
            continue
        clean = urllib.parse.unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not clean:
            continue
        candidate = Path(clean)
        if not candidate.is_absolute():
            candidate = (path.parent / candidate).resolve()
        if not candidate.exists():
            line_no = text.count("\n", 0, match.start()) + 1
            errors.append(f"{path.name}:{line_no}: missing link target {target}")
    return errors


def validate() -> ValidationResult:
    result = ValidationResult()
    if not PACK_DIR.is_dir():
        result.errors.append(f"missing pack directory: {PACK_DIR}")
        return result

    docs = sorted(PACK_DIR.glob("*.md"))
    doc_names = [path.name for path in docs]
    if len(docs) > MAX_DOCS:
        result.errors.append(f"too many context-pack files: {len(docs)} > {MAX_DOCS}")

    missing = [name for name in REQUIRED_DOCS if name not in doc_names]
    if missing:
        result.errors.append("missing required docs: " + ", ".join(missing))

    index_path = PACK_DIR / "00_STRATFORGE_CONTEXT_INDEX.md"
    handoff_path = PACK_DIR / "11_ACTIVE_WORK_AND_HANDOFF.md"
    header_shas: dict[str, str] = {}

    for path in docs:
        text = path.read_text(encoding="utf-8")
        if path == handoff_path and not text.strip():
            result.errors.append("11_ACTIVE_WORK_AND_HANDOFF.md is empty")
        fields = _parse_header(path)
        required = {
            "Context Pack document",
            "Last verified UTC",
            "Verified against Git SHA",
            "Scope",
            "Status",
        }
        if path.name in {
            "02_CURRENT_SYSTEM_STATE.md",
            "11_ACTIVE_WORK_AND_HANDOFF.md",
        }:
            required.add("Current Production version/build/artifact when known")
        missing_fields = sorted(field for field in required if field not in fields)
        if missing_fields:
            result.errors.append(f"{path.name}: missing metadata fields: {', '.join(missing_fields)}")
            continue

        if fields["Context Pack document"] != path.name:
            result.errors.append(
                f"{path.name}: Context Pack document must equal filename"
            )
        if not _validate_timestamp(fields["Last verified UTC"]):
            result.errors.append(f"{path.name}: invalid Last verified UTC")
        sha = fields["Verified against Git SHA"].lower()
        header_shas[path.name] = sha
        if not SHA_RE.fullmatch(sha):
            result.errors.append(f"{path.name}: invalid Git SHA format")
        if fields["Status"] not in ALLOWED_STATUSES:
            result.errors.append(f"{path.name}: invalid Status '{fields['Status']}'")

        result.errors.extend(_resolve_markdown_links(path, text))

        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                result.errors.append(f"{path.name}: potential {label}")
        if SUSPECT_ENV_VALUE.search(text):
            result.errors.append(f"{path.name}: looks like a real .env-style secret assignment")
        if ABSOLUTE_PATH.search(text):
            result.errors.append(f"{path.name}: contains an absolute local path")

    if index_path.is_file():
        index_text = index_path.read_text(encoding="utf-8")
        for name in REQUIRED_DOCS[1:]:
            if name not in index_text:
                result.errors.append(f"00_STRATFORGE_CONTEXT_INDEX.md: missing file reference {name}")
        for status in sorted(ALLOWED_STATUSES):
            if status not in index_text:
                result.errors.append(f"00_STRATFORGE_CONTEXT_INDEX.md: missing status legend entry {status}")

    unique_shas = {value for value in header_shas.values() if value}
    if len(unique_shas) > 1:
        result.errors.append("pack docs use conflicting verification SHAs")

    if handoff_path.is_file():
        handoff_text = handoff_path.read_text(encoding="utf-8")
        match = re.search(r"Current Git SHA \| `?([0-9a-f]{7,40})`?", handoff_text, re.IGNORECASE)
        if not match:
            result.errors.append("11_ACTIVE_WORK_AND_HANDOFF.md: missing Current Git SHA table entry")
        elif unique_shas and match.group(1).lower() not in unique_shas:
            result.errors.append("11_ACTIVE_WORK_AND_HANDOFF.md: Current Git SHA does not match header SHA")

    head = _git_head()
    if head and unique_shas and head not in unique_shas:
        result.warnings.append(
            "pack verification SHA differs from current HEAD; update only when pack facts changed"
        )

    return result


def main() -> int:
    result = validate()
    if result.errors:
        print(f"EXTERNAL GPT CONTEXT FAIL ({len(result.errors)})")
        for entry in result.errors:
            print("  " + entry)
        if result.warnings:
            print(f"WARNINGS ({len(result.warnings)})")
            for entry in result.warnings:
                print("  " + entry)
        return 1
    print("EXTERNAL GPT CONTEXT OK")
    for entry in result.warnings:
        print("WARNING: " + entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
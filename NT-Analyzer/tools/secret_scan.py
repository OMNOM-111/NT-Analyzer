"""Refuse to ship a repository that carries a real credential.

This is a release blocker, not a linter. It looks for the shapes that only
occur in genuine provider credentials -- a Google client secret prefix, a
Resend key prefix, a private key header -- rather than for the word
"password", which appears legitimately all over a codebase and would train
everyone to ignore the output.

Two rules keep it honest:

* it scans what Git actually tracks, because that is what gets published;
  an ignored file holding a live value is fine and is the whole design.
* the example file is scanned too, and any value there is a failure. A
  committed template is exactly where a real secret gets pasted by accident.

Exit code 1 blocks the release.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Shapes that are credentials and essentially nothing else.
PATTERNS = [
    ("google_client_secret", re.compile(r"GOCSPX-[A-Za-z0-9_\-]{20,}")),
    ("resend_api_key", re.compile(r"\bre_[A-Za-z0-9]{20,}")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{32,}")),
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{32,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("telegram_bot_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
]

# Text that legitimately contains a pattern while being nobody's credential.
ALLOW = re.compile(
    r"(?:example|sample|placeholder|dummy|fake|redacted|your[-_]?key|"
    r"xxxx|<[a-z_]+>|\*\*\*)",
    re.IGNORECASE,
)

SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webm", ".mp4", ".woff",
    ".woff2", ".ttf", ".zip", ".dll", ".exe", ".pdb", ".pyc",
}


def tracked_files() -> list[Path]:
    try:
        # Bytes, not text: the checkout can contain non-ASCII path names and
        # the console encoding would turn listing them into a decode error.
        raw = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
            check=True,
        ).stdout or b""
    except (OSError, subprocess.CalledProcessError):
        return []
    names = raw.decode("utf-8", "replace").split("\0")
    return [ROOT / name for name in names if name]


def scan() -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for path in tracked_files():
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        # The scanner's own pattern table is not a leak.
        if path.name == "secret_scan.py":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if ALLOW.search(line):
                continue
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append((
                        str(path.relative_to(ROOT)).replace("\\", "/"),
                        number, label,
                    ))
                    break
    return findings


def example_file_has_values() -> list[str]:
    """A committed template with a value in it is the classic accident."""
    example = ROOT / "secrets.example.env"
    if not example.is_file():
        return ["secrets.example.env is missing"]
    bad = []
    for number, line in enumerate(
            example.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        if value.strip():
            bad.append(f"secrets.example.env:{number}: {name.strip()} has a value")
    return bad


def main() -> int:
    findings = scan()
    template = example_file_has_values()
    if not findings and not template:
        print("secret scan: clean")
        return 0
    for path, number, label in findings:
        print(f"SECRET {path}:{number}: looks like a {label}")
    for line in template:
        print(f"SECRET {line}")
    print(
        f"\nsecret scan: {len(findings) + len(template)} finding(s). "
        "Release blocked. Real credentials must never be tracked by Git; "
        "put them in the external secrets directory instead."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

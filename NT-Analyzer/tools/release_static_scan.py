#!/usr/bin/env python3
"""Release-gate scans for Aurora CSP, committed secrets and Markdown links."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AURORA = ROOT / "app" / "static" / "aurora"


def _tracked_files() -> list[Path]:
    raw = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT,
    ).decode("utf-8", errors="surrogateescape")
    return [ROOT / value for value in raw.split("\0") if value]


def _working_source_files() -> list[Path]:
    """Scan tracked files plus untracked release sources that may be committed."""
    found = {path.resolve() for path in _tracked_files() if path.is_file()}
    for name in ("app", "tests", "tools", "docs", "bridge"):
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            lowered = {part.lower() for part in path.parts}
            if lowered & {"__pycache__", ".pytest_cache", "bin", "obj"}:
                continue
            found.add(path.resolve())
    for path in ROOT.iterdir():
        if path.is_file() and (path.suffix.lower() in TEXT_SUFFIXES or path.name == ".gitignore"):
            found.add(path.resolve())
    return sorted(found)


def scan_csp() -> list[str]:
    errors: list[str] = []
    pages = sorted(AURORA.glob("*.html"))
    required = ("default-src 'self'", "script-src 'self'", "object-src 'none'", "base-uri 'none'")
    for path in pages:
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(ROOT)
        # Aurora pages deliberately use a double-quoted attribute because the
        # CSP itself contains single-quoted keywords such as ``'self'``.  Do
        # not terminate the capture on those inner quotes.
        match = re.search(
            r'<meta\s+http-equiv=["\']Content-Security-Policy["\']\s+content="([^"]+)"',
            text, re.IGNORECASE,
        )
        if not match:
            errors.append(f"{relative}: missing CSP meta")
        elif any(item not in match.group(1) for item in required):
            errors.append(f"{relative}: incomplete CSP")
        if re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", text, re.IGNORECASE):
            errors.append(f"{relative}: inline script")
        if re.search(r"\son[a-z]+\s*=", text, re.IGNORECASE):
            errors.append(f"{relative}: inline event handler")
        if re.search(r"(?:href|src)\s*=\s*[\"']\s*javascript:", text, re.IGNORECASE):
            errors.append(f"{relative}: javascript URL")
    server = (ROOT / "app" / "server.py").read_text(encoding="utf-8", errors="replace")
    if "Content-Security-Policy\", STATIC_CSP" not in server:
        errors.append("app/server.py: uniform CSP response header missing")
    return errors


SECRET_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b")),
    ("github_token", re.compile(r"\bgh[psoru]_[A-Za-z0-9]{30,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("telegram_token", re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")),
)
TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".html", ".css", ".json", ".jsonl", ".md",
    ".yml", ".yaml", ".toml", ".ini", ".cfg", ".ps1", ".cmd", ".cs",
    ".csproj", ".xml", ".txt", ".env", ".gitignore",
}


def scan_secrets() -> list[str]:
    errors: list[str] = []
    for path in _working_source_files():
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".gitignore":
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, 1):
            lowered = line.lower()
            fixture = any(word in lowered for word in (
                "fake", "test-token", "test-bot", "probe_token", "example", "abcdef",
                "abcdefghijklmnopqrstuvwxyz", "placeholder", "test-key",
                "real-looking-secret", "[скрыто]",
            ))
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line) and not fixture:
                    errors.append(f"{path.relative_to(ROOT)}:{line_no}: potential {label}")
    return errors


MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")


def scan_markdown_links() -> list[str]:
    errors: list[str] = []
    for path in _working_source_files():
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in MARKDOWN_LINK.finditer(text):
            target = match.group(1).strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:", "data:")):
                continue
            clean = urllib.parse.unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not clean:
                continue
            candidate = Path(clean)
            if not candidate.is_absolute():
                candidate = path.parent / candidate
            if not candidate.exists():
                line_no = text.count("\n", 0, match.start()) + 1
                errors.append(f"{path.relative_to(ROOT)}:{line_no}: missing {target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", choices=("all", "csp", "secrets", "markdown"), default="all")
    args = parser.parse_args()
    scans = {
        "csp": scan_csp,
        "secrets": scan_secrets,
        "markdown": scan_markdown_links,
    }
    selected = scans if args.scan == "all" else {args.scan: scans[args.scan]}
    failed = False
    for name, scanner in selected.items():
        errors = scanner()
        if errors:
            failed = True
            print(f"{name.upper()} FAIL ({len(errors)})")
            for error in errors:
                print("  " + error)
        else:
            print(f"{name.upper()} OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

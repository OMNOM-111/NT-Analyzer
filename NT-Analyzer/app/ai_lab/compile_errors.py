"""Compile-error stream consumed by the AI sandbox autofix loop.

The bridge writes append-only JSONL records to
``<project_root>/data/runtime/compile_errors.jsonl``. This module:
  - tails that file and filters by timestamp / class name;
  - mirrors records into the registry for long-term audit;
  - accepts manually pasted error text from the UI as a fallback when the
    bridge cannot find any source on this machine;
  - exposes the bridge-written discovery status to the UI.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import paths
from .io_utils import append_jsonl, iter_jsonl, read_json


def _runtime_dir() -> Path:
    return paths.PROJECT_ROOT / "data" / "runtime"


def jsonl_path() -> Path:
    return _runtime_dir() / "compile_errors.jsonl"


def status_path() -> Path:
    return _runtime_dir() / "compile_error_source_status.json"


CS_ERROR_RE = re.compile(
    r"(?P<file>[^\r\n]+?\.cs)\((?P<line>\d+),(?P<col>\d+)\)\s*:\s*error\s+(?P<code>CS\d+)\s*:\s*(?P<msg>.+)"
)

NT_TABLE_ERROR_RE = re.compile(
    r"^(?P<file>[A-Za-z0-9_.\\/-]+(?:\.cs)?)\s+"
    r"(?P<msg>.+?)\s+"
    r"(?P<code>CS\d{4})\s+"
    r"(?P<line>\d+)\s+"
    r"(?P<col>\d+)\s*$"
)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    txt = value.rstrip("Z")
    try:
        return datetime.fromisoformat(txt).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def read_since(
    baseline_ts: datetime,
    class_name: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Return JSONL records with ``timestamp_utc >= baseline_ts``."""
    if baseline_ts.tzinfo is None:
        baseline_ts = baseline_ts.replace(tzinfo=timezone.utc)
    path = jsonl_path()
    out: List[Dict[str, Any]] = []
    for rec in iter_jsonl(path):
        ts = _parse_ts(rec.get("timestamp_utc"))
        if ts is None or ts < baseline_ts:
            continue
        if class_name:
            rec_cls = (rec.get("class_name") or "").strip()
            file_field = (rec.get("file") or "")
            if rec_cls != class_name and class_name not in file_field:
                continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def mirror_to_registry(
    experiment_id: str,
    class_name: str,
    records: List[Dict[str, Any]],
) -> None:
    paths.ensure_dirs()
    for rec in records:
        slim = {
            "timestamp_utc": rec.get("timestamp_utc") or _now(),
            "experiment_id": experiment_id,
            "class_name": class_name,
            "file": rec.get("file"),
            "line": rec.get("line"),
            "column": rec.get("column"),
            "code": rec.get("code"),
            "message": rec.get("message"),
            "source": rec.get("source"),
        }
        append_jsonl(paths.COMPILE_FAIL_PATH, slim)


def append_manual(experiment_id: str, class_name: str, pasted_text: str) -> int:
    """Parse user-pasted error text and append matching lines.

    Accepts both compiler lines such as
    ``Foo.cs(47,31) : error CS0103: ...`` and NinjaScript Editor table
    copies such as ``Foo.cs<TAB>message<TAB>CS0103<TAB>47<TAB>31``.
    """
    path = jsonl_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    seen = set()

    def emit(file: str, line: Any, col: Any, code: str, msg: str, source: str) -> None:
        nonlocal count
        file = (file or "").strip().strip('"')
        code = (code or "").strip()
        msg = (msg or "").strip()
        if not file or not code or not msg:
            return
        try:
            line_i = int(line)
            col_i = int(col)
        except (TypeError, ValueError):
            return
        key = (file, line_i, col_i, code, msg)
        if key in seen:
            return
        seen.add(key)
        rec = {
            "class_name": class_name or None,
            "file": file,
            "line": line_i,
            "column": col_i,
            "code": code,
            "message": msg[:1000],
            "timestamp_utc": _now(),
            "source": source,
            "experiment_id": experiment_id,
        }
        append_jsonl(path, rec)
        count += 1

    for m in CS_ERROR_RE.finditer(pasted_text or ""):
        emit(
            m.group("file"),
            m.group("line"),
            m.group("col"),
            m.group("code"),
            m.group("msg"),
            "manual_paste",
        )

    for raw in (pasted_text or "").splitlines():
        line = raw.strip()
        if not line or "CS" not in line:
            continue
        cols = [c.strip() for c in line.split("\t") if c.strip()]
        if len(cols) >= 5 and re.fullmatch(r"CS\d{4}", cols[-3] or ""):
            emit(cols[0], cols[-2], cols[-1], cols[-3], cols[1], "manual_paste_table")
            continue
        m = NT_TABLE_ERROR_RE.match(line)
        if m:
            emit(
                m.group("file"),
                m.group("line"),
                m.group("col"),
                m.group("code"),
                m.group("msg"),
                "manual_paste_table",
            )
    return count


def source_status() -> Dict[str, Any]:
    payload = read_json(status_path(), default=None)
    if payload is None:
        return {
            "ok": False,
            "reason": "bridge not running or status file absent",
            "path": str(status_path()),
        }
    payload["ok"] = True
    return payload

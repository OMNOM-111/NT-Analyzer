"""Persistent, append-only portfolio cell registry.

The historical CELL-001..CELL-180 mapping is seeded from portfolio_cells and
never recalculated from a mutable root order. New ids are allocated after the
largest id (or from an explicit unused range) and archived ids are never reused.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import portfolio_cells, runtime_env


_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "portfolio" / "cells.json"
REGISTRY_PATH = _DEFAULT_REGISTRY_PATH
_LOCK = threading.RLock()
_ROOT_RE = re.compile(r"^[A-Z][A-Z0-9]{0,11}$")


def _registry_path() -> Path:
    # Tests and explicit embedding callers may override the legacy constant.
    if REGISTRY_PATH != _DEFAULT_REGISTRY_PATH:
        return Path(REGISTRY_PATH)
    return runtime_env.data_path("portfolio", "cells.json", project_root=Path(__file__).resolve().parents[1])


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _cell_number(cell_id: str) -> int:
    match = re.fullmatch(r"CELL-(\d{3})", str(cell_id or "").strip().upper())
    if not match:
        raise ValueError("cell_id must use CELL-NNN format")
    value = int(match.group(1))
    if value < 1 or value > 999:
        raise ValueError("cell_id must be between CELL-001 and CELL-999")
    return value


def _normalize_root(value: Any) -> str:
    root = str(value or "").strip().upper().split()[0] if str(value or "").strip() else ""
    if not _ROOT_RE.fullmatch(root):
        raise ValueError("root must contain 1-12 uppercase letters/digits")
    return root


def _default_cells() -> List[Dict[str, Any]]:
    cells: List[Dict[str, Any]] = []
    for root in portfolio_cells.PORTFOLIO_ROOT_ORDER:
        for slot in range(1, portfolio_cells.TARGET_PORTFOLIO_SLOTS + 1):
            cells.append({
                "cell_id": portfolio_cells.cell_id_for(root, slot),
                "root": root,
                "slot": slot,
                "status": "active",
                "legacy": True,
                "created_at_utc": "2026-06-28T00:00:00Z",
                "archived_at_utc": None,
            })
    return cells


def _default_doc() -> Dict[str, Any]:
    return {"schema_version": 1, "updated_at_utc": _now(), "cells": _default_cells(), "history": []}


def _read() -> Dict[str, Any]:
    path = _registry_path()
    if not path.exists():
        return _default_doc()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"portfolio registry is unreadable: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("cells"), list):
        raise RuntimeError("portfolio registry has invalid shape")
    # Repair an older partial registry without changing any existing assignment.
    existing = {str(row.get("cell_id") or "").upper() for row in raw["cells"] if isinstance(row, dict)}
    for row in _default_cells():
        if row["cell_id"] not in existing:
            raw["cells"].append(row)
    raw.setdefault("history", [])
    raw.setdefault("schema_version", 1)
    return raw


def _write(doc: Dict[str, Any]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["updated_at_utc"] = _now()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _public(doc: Dict[str, Any]) -> Dict[str, Any]:
    cells = sorted(doc["cells"], key=lambda row: _cell_number(row["cell_id"]))
    roots: List[Dict[str, Any]] = []
    for root in dict.fromkeys(row["root"] for row in cells):
        rows = [row for row in cells if row["root"] == root]
        roots.append({
            "root": root,
            "cell_count": len(rows),
            "active_count": sum(1 for row in rows if row.get("status") == "active"),
            "legacy": all(bool(row.get("legacy")) for row in rows),
        })
    return {
        "schema_version": doc.get("schema_version", 1),
        "updated_at_utc": doc.get("updated_at_utc"),
        "roots": roots,
        "cells": cells,
        "summary": {
            "roots": len(roots),
            "cells": len(cells),
            "active": sum(1 for row in cells if row.get("status") == "active"),
            "archived": sum(1 for row in cells if row.get("status") == "archived"),
            "next_auto_id": f"CELL-{min(999, max(_cell_number(row['cell_id']) for row in cells) + 1):03d}",
        },
    }


def read_registry() -> Dict[str, Any]:
    with _LOCK:
        return _public(_read())


def _next_free(used: set[int], start: Optional[int] = None) -> int:
    candidate = start if start is not None else (max(used) + 1 if used else 1)
    while candidate in used and candidate <= 999:
        candidate += 1
    if candidate > 999:
        raise ValueError("no free CELL-NNN ids remain")
    return candidate


def add_root(root: Any, slots: Any = 15, start_id: Any = None, actor: str = "ui") -> Dict[str, Any]:
    root = _normalize_root(root)
    slots = int(slots)
    if slots < 1 or slots > 50:
        raise ValueError("slots must be between 1 and 50")
    with _LOCK:
        doc = _read()
        if any(row.get("root") == root for row in doc["cells"]):
            raise ValueError(f"root {root} already exists")
        used = {_cell_number(row["cell_id"]) for row in doc["cells"]}
        explicit = _cell_number(str(start_id).upper().replace("CELL-", "CELL-")) if str(start_id or "").upper().startswith("CELL-") else (int(start_id) if start_id not in (None, "") else None)
        if explicit is not None and any((explicit + offset) in used for offset in range(slots)):
            raise ValueError("explicit CELL range collides with existing or archived ids")
        created = []
        cursor = explicit
        for slot in range(1, slots + 1):
            number = _next_free(used, cursor)
            used.add(number)
            cursor = number + 1
            row = {"cell_id": f"CELL-{number:03d}", "root": root, "slot": slot, "status": "active", "legacy": False, "created_at_utc": _now(), "archived_at_utc": None}
            doc["cells"].append(row)
            created.append(row)
        doc["history"].append({"at_utc": _now(), "actor": actor, "action": "add_root", "root": root, "cell_ids": [row["cell_id"] for row in created]})
        _write(doc)
        return {"ok": True, "created": created, "registry": _public(doc)}


def add_cell(root: Any, cell_id: Any = None, actor: str = "ui") -> Dict[str, Any]:
    root = _normalize_root(root)
    with _LOCK:
        doc = _read()
        root_rows = [row for row in doc["cells"] if row.get("root") == root]
        if not root_rows:
            raise ValueError(f"unknown root {root}; add the root first")
        used = {_cell_number(row["cell_id"]) for row in doc["cells"]}
        number = _cell_number(cell_id) if cell_id else _next_free(used)
        if number in used:
            raise ValueError(f"CELL-{number:03d} already exists or is archived")
        slot = max(int(row.get("slot") or 0) for row in root_rows) + 1
        row = {"cell_id": f"CELL-{number:03d}", "root": root, "slot": slot, "status": "active", "legacy": False, "created_at_utc": _now(), "archived_at_utc": None}
        doc["cells"].append(row)
        doc["history"].append({"at_utc": _now(), "actor": actor, "action": "add_cell", "root": root, "cell_ids": [row["cell_id"]]})
        _write(doc)
        return {"ok": True, "created": row, "registry": _public(doc)}


def archive_cell(cell_id: Any, actor: str = "ui") -> Dict[str, Any]:
    normalized = f"CELL-{_cell_number(cell_id):03d}"
    with _LOCK:
        doc = _read()
        row = next((item for item in doc["cells"] if item.get("cell_id") == normalized), None)
        if row is None:
            raise ValueError(f"unknown cell {normalized}")
        row["status"] = "archived"
        row["archived_at_utc"] = _now()
        doc["history"].append({"at_utc": _now(), "actor": actor, "action": "archive_cell", "cell_ids": [normalized]})
        _write(doc)
        return {"ok": True, "cell": row, "registry": _public(doc)}

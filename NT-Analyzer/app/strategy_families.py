from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import portfolio_cells


FAMILY_FIELDS = (
    "root_family",
    "strategy_family",
    "family_status",
    "family_role",
    "hub_class",
    "new_research_allowed",
)

_CACHE_SIG: Optional[Tuple[int, int]] = None
_CACHE_VALUE: Dict[str, Any] = {"schema_version": "1.0", "class_map": {}, "profile_map": {}}


def reset_caches() -> None:
    global _CACHE_SIG, _CACHE_VALUE
    _CACHE_SIG = None
    _CACHE_VALUE = {"schema_version": "1.0", "class_map": {}, "profile_map": {}}


def family_map_path(project_root: Path) -> Path:
    return project_root / "data" / "profiles" / "strategy_families.json"


def read_family_map(project_root: Path) -> Dict[str, Any]:
    global _CACHE_SIG, _CACHE_VALUE
    path = family_map_path(project_root)
    try:
        stat = path.stat()
        sig = (int(stat.st_size), int(stat.st_mtime_ns))
    except OSError:
        _CACHE_SIG = None
        _CACHE_VALUE = {"schema_version": "1.0", "class_map": {}, "profile_map": {}}
        return _CACHE_VALUE

    if sig == _CACHE_SIG:
        return _CACHE_VALUE

    try:
        with path.open("r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        data = {}

    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("class_map"), dict):
        data["class_map"] = {}
    if not isinstance(data.get("profile_map"), dict):
        data["profile_map"] = {}
    if not isinstance(data.get("roots"), dict):
        data["roots"] = {}

    _CACHE_SIG = sig
    _CACHE_VALUE = data
    return _CACHE_VALUE


def _class_candidates(profile: Dict[str, Any]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []

    def add(value: Any) -> None:
        cls = str(value or "").strip()
        if not cls:
            return
        key = cls.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(cls)

    add(profile.get("deploy_strategy_class"))
    add(profile.get("strategy_class"))
    add(profile.get("strategy"))
    for value in profile.get("runtime_strategy_classes") or []:
        add(value)
    add(profile.get("class_name"))
    return out


def _casefold_lookup(mapping: Any, key: Any) -> Dict[str, Any]:
    if not isinstance(mapping, dict):
        return {}
    wanted = str(key or "").strip().lower()
    if not wanted:
        return {}
    for raw_key, value in mapping.items():
        if str(raw_key or "").strip().lower() == wanted and isinstance(value, dict):
            return dict(value)
    return {}


def infer_root_family(profile: Dict[str, Any]) -> str:
    for key in ("root_family", "instrument_root", "root", "instrument", "current_contract", "contract_month"):
        root = portfolio_cells.normalize_root(profile.get(key))
        if root:
            return root
    return ""


def family_metadata_for_profile(profile: Dict[str, Any], project_root: Path) -> Dict[str, Any]:
    data = read_family_map(project_root)
    meta: Dict[str, Any] = {}

    profile_id = str(profile.get("profile_id") or profile.get("id") or "").strip()
    if profile_id:
        meta.update(_casefold_lookup(data.get("profile_map"), profile_id))

    class_map = data.get("class_map") or {}
    for cls in _class_candidates(profile):
        class_meta = _casefold_lookup(class_map, cls)
        if not class_meta:
            continue
        for key, value in class_meta.items():
            meta.setdefault(key, value)

    root = str(meta.get("root_family") or "").strip()
    if not root or root.lower() == "cross-root":
        inferred = infer_root_family(profile)
        if inferred:
            meta["root_family"] = inferred
    elif root:
        meta["root_family"] = root.upper()

    if not meta.get("strategy_family"):
        for cls in _class_candidates(profile):
            if cls:
                meta["strategy_family"] = cls
                break
    if not meta.get("family_status"):
        meta["family_status"] = "unclassified"
    if not meta.get("family_role"):
        meta["family_role"] = "profile"
    if "new_research_allowed" not in meta:
        meta["new_research_allowed"] = False

    return {key: meta[key] for key in FAMILY_FIELDS if key in meta}


def apply_family_metadata(profile: Dict[str, Any], project_root: Path) -> Dict[str, Any]:
    out = dict(profile)
    meta = family_metadata_for_profile(out, project_root)
    for key, value in meta.items():
        if key == "root_family" and str(out.get(key) or "").strip():
            continue
        if key not in out or out.get(key) in (None, ""):
            out[key] = value
    if not out.get("root_family"):
        root = infer_root_family(out)
        if root:
            out["root_family"] = root
    return out

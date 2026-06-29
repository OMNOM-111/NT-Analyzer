"""Remove failed/archived strategies from NinjaTrader safely.

"Removing from NinjaTrader" means taking the strategy's NinjaScript ``.cs`` source
out of every compile path NinjaTrader scans, so a recompile no longer exposes the
class. We do this by *quarantining* (moving, not hard-deleting) the files into
``ninjatrader/strategies/_quarantine/`` so the action stays reversible.

Two hard safety rules:

  1. Only the CELL-specific ``deploy_strategy_class`` wrapper is removed. The shared
     research engine / hub ``strategy_class`` is never touched (other live
     strategies inherit from it).
  2. A class is only removed when **no active** (non-archived) profile references
     it. If any active profile still uses the class, removal is skipped.

The selection logic (which class, sharing guard) is pure and unit-tested. The
file move is the only IO and degrades gracefully when a file is already absent
(e.g. NinjaTrader is installed on another machine).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import xml.etree.ElementTree as ET

from . import strategy_lifecycle


def _project_root() -> Path:
    # app/ninjatrader_ops.py -> app -> NT-Analyzer
    return Path(__file__).resolve().parent.parent


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ninjatrader_user_dir(nt_user_home: Optional[Path] = None) -> Path:
    """Resolve the real ``Documents/NinjaTrader 8`` user directory.

    ``nt_user_home`` may be either:
      * the actual NinjaTrader user dir (``.../Documents/NinjaTrader 8``), or
      * a plain user home path, in which case ``Documents/NinjaTrader 8`` is
        appended (legacy test helper behaviour).
    """
    if nt_user_home is None:
        return Path.home() / "Documents" / "NinjaTrader 8"
    raw = Path(nt_user_home)
    if raw.name.lower() == "ninjatrader 8" or (raw / "bin" / "Custom").exists():
        return raw
    return raw / "Documents" / "NinjaTrader 8"


def ninjatrader_is_running() -> bool:
    """Best-effort check for a live NinjaTrader desktop process."""
    if os.name != "nt":
        return False
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq NinjaTrader.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    text = (proc.stdout or "").strip().lower()
    return bool(text) and "no tasks are running" not in text and "ninjatrader.exe" in text


def _all_classes(profile: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for key in ("deploy_strategy_class", "strategy_class", "strategy", "class_name"):
        value = str((profile or {}).get(key) or "").strip()
        if value:
            out.append(value)
    for value in (profile or {}).get("runtime_strategy_classes") or []:
        text = str(value or "").strip()
        if text:
            out.append(text)
    return out


def removal_candidate_class(profile: Dict[str, Any]) -> Optional[str]:
    """The single class whose ``.cs`` should leave NinjaTrader for this profile.

    Prefer the CELL-specific deploy wrapper; fall back to the strategy class only
    when there is no deploy wrapper.
    """
    deploy = str((profile or {}).get("deploy_strategy_class") or "").strip()
    if deploy:
        return deploy
    base = str((profile or {}).get("strategy_class") or (profile or {}).get("strategy") or "").strip()
    return base or None


def active_class_usage(profiles: List[Dict[str, Any]]) -> Set[str]:
    """Lower-cased set of every class referenced by a non-archived profile."""
    used: Set[str] = set()
    for profile in profiles or []:
        if not isinstance(profile, dict):
            continue
        if strategy_lifecycle.classify_lifecycle(profile) == strategy_lifecycle.FAILED_ARCHIVED:
            continue
        for cls in _all_classes(profile):
            used.add(cls.lower())
    return used


def plan_removal(profile: Dict[str, Any], active_used: Set[str]) -> Dict[str, Any]:
    """Decide whether (and which) class is safe to remove for one profile."""
    cls = removal_candidate_class(profile)
    if not cls:
        return {"ok": False, "reason": "no_class", "class_name": None}
    if cls.lower() in active_used:
        return {"ok": False, "reason": "shared_with_active", "class_name": cls}
    return {"ok": True, "reason": "removable", "class_name": cls}


def strategy_source_dirs(nt_user_home: Optional[Path] = None) -> List[Path]:
    """Directories NinjaTrader compiles strategies from, in removal priority."""
    root = _project_root()
    dirs = [root / "ninjatrader" / "strategies"]
    custom = ninjatrader_user_dir(nt_user_home) / "bin" / "Custom" / "Strategies"
    dirs.append(custom)
    for sub in ("NT-Analyzer_strategies", "NT-Analyzer_AI Labstrategies"):
        dirs.append(custom / sub)
    return dirs


def _quarantine_root() -> Path:
    return _project_root() / "ninjatrader" / "strategies" / "_quarantine"


def _ui_xml_path(nt_user_home: Optional[Path] = None) -> Path:
    return ninjatrader_user_dir(nt_user_home) / "UI.xml"


def _workspace_files(nt_user_home: Optional[Path] = None) -> List[Path]:
    root = ninjatrader_user_dir(nt_user_home) / "workspaces"
    out: List[Path] = []
    if root.is_dir():
        out.extend(sorted(root.glob("*.xml")))
        recovery = root / "recovery"
        if recovery.is_dir():
            out.extend(sorted(recovery.rglob("*.xml")))
    return out


def _backup_file(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    backup = path.with_name(f"{path.name}.bak_nta_cleanup_{_stamp()}")
    shutil.copy2(path, backup)
    return str(backup)


def _write_xml_atomic(path: Path, tree: ET.ElementTree) -> None:
    tmp = path.with_name(f"{path.name}.tmp")
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    os.replace(tmp, path)


def _parse_xml(path: Path) -> ET.ElementTree:
    return ET.ElementTree(ET.fromstring(path.read_text(encoding="utf-8-sig")))


def _file_name_matches_class(file_name: str, class_name: str) -> bool:
    norm = str(file_name or "").strip().replace("\\", "/")
    if not norm:
        return False
    base = Path(norm).name.lower()
    cls = str(class_name or "").strip().lower()
    return base == f"{cls}.cs" or (base.startswith(f"{cls}.") and base.endswith(".cs"))


def _strategy_type_matches(value: str, class_name: str) -> bool:
    text = str(value or "").strip()
    cls = str(class_name or "").strip()
    return text == f"NinjaTrader.NinjaScript.Strategies.{cls}"


def _purge_ui_xml_state(class_name: str,
                        *,
                        nt_user_home: Optional[Path] = None) -> Dict[str, Any]:
    path = _ui_xml_path(nt_user_home)
    result: Dict[str, Any] = {
        "path": str(path),
        "removed_nodes": 0,
        "changed": False,
        "clean": True,
        "reason": "already_clean",
    }
    if not path.is_file():
        result["reason"] = "absent"
        return result
    try:
        tree = _parse_xml(path)
    except (OSError, ET.ParseError) as exc:
        result["clean"] = False
        result["reason"] = f"parse_error: {exc}"
        return result
    root = tree.getroot()
    tag = f"NinjaTrader.NinjaScript.Strategies.{class_name}"
    removed = 0
    for parent in root.iter():
        for child in list(parent):
            if child.tag != tag:
                continue
            parent.remove(child)
            removed += 1
    if not removed:
        return result
    result["removed_nodes"] = removed
    result["changed"] = True
    result["reason"] = "purged"
    backup = _backup_file(path)
    if backup:
        result["backup_path"] = backup
    _write_xml_atomic(path, tree)
    return result


def _purge_workspace_state(class_name: str,
                           *,
                           nt_user_home: Optional[Path] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "files_scanned": 0,
        "files_changed": [],
        "removed_entries": 0,
        "removed_script_tabs": 0,
        "removed_full_templates": 0,
        "clean": True,
        "reason": "already_clean",
    }
    for path in _workspace_files(nt_user_home):
        result["files_scanned"] += 1
        try:
            tree = _parse_xml(path)
        except (OSError, ET.ParseError) as exc:
            result["clean"] = False
            result["reason"] = f"parse_error: {exc}"
            continue
        changed = False
        removed_tabs_here = 0
        removed_templates_here = 0
        for parent in tree.iter():
            for child in list(parent):
                if child.tag == "ScriptTabStateSerialize":
                    file_name = child.findtext("FileName", default="")
                    if not _file_name_matches_class(file_name, class_name):
                        continue
                    parent.remove(child)
                    changed = True
                    removed_tabs_here += 1
                    continue
                if child.tag == "FullTemplate":
                    strategy_type = child.findtext("StrategyType", default="")
                    if not _strategy_type_matches(strategy_type, class_name):
                        continue
                    parent.remove(child)
                    changed = True
                    removed_templates_here += 1
        if not changed:
            continue
        backup = _backup_file(path)
        if backup:
            result.setdefault("backup_paths", []).append(backup)
        _write_xml_atomic(path, tree)
        result["removed_script_tabs"] += removed_tabs_here
        result["removed_full_templates"] += removed_templates_here
        result["removed_entries"] += removed_tabs_here + removed_templates_here
        result["files_changed"].append(str(path))
    if result["removed_entries"]:
        result["reason"] = "purged"
    return result


def purge_strategy_ui_state(class_name: str,
                            *,
                            nt_user_home: Optional[Path] = None,
                            nt_running: Optional[bool] = None) -> Dict[str, Any]:
    """Remove stale NinjaTrader UI/workspace state for a decommissioned class."""
    cls = str(class_name or "").strip()
    result: Dict[str, Any] = {
        "class_name": cls,
        "removed": False,
        "clean": False,
        "reason": "no_class" if not cls else "unknown",
        "ui_xml": {},
        "workspaces": {},
    }
    if not cls:
        return result
    if nt_running is None:
        nt_running = ninjatrader_is_running()
    result["ninjatrader_running"] = bool(nt_running)
    if nt_running:
        result["reason"] = "ninjatrader_running"
        return result

    ui = _purge_ui_xml_state(cls, nt_user_home=nt_user_home)
    workspaces = _purge_workspace_state(cls, nt_user_home=nt_user_home)
    result["ui_xml"] = ui
    result["workspaces"] = workspaces
    result["ui_nodes_removed"] = int(ui.get("removed_nodes") or 0)
    result["workspace_entries_removed"] = int(workspaces.get("removed_entries") or 0)
    result["clean"] = bool(ui.get("clean")) and bool(workspaces.get("clean"))
    result["removed"] = result["clean"]
    if not result["clean"]:
        result["reason"] = str(workspaces.get("reason") or ui.get("reason") or "error")
    elif result["ui_nodes_removed"] or result["workspace_entries_removed"]:
        result["reason"] = "purged"
    else:
        result["reason"] = "already_clean"
    return result


def find_class_files(class_name: str, dirs: List[Path]) -> List[Path]:
    """All ``{class}.cs`` and ``{class}.*.cs`` files for a class.

    Handles both layouts: flat (NinjaTrader Custom: ``dir/Class.cs``) and the
    repo's per-class folder (``dir/Class/Class.cs``).
    """
    cls = str(class_name or "").strip()
    if not cls:
        return []
    found: List[Path] = []
    for d in dirs:
        if not d.is_dir():
            continue
        # Loose files directly in the dir (NinjaTrader Custom flat layout).
        for path in sorted(d.glob(f"{cls}.cs")) + sorted(d.glob(f"{cls}.*.cs")):
            if path.is_file() and not _excluded_under(path, d):
                found.append(path)
    return found


# Directory names that are build output / our own quarantine — never sources.
_EXCLUDED_DIR_NAMES = {"obj", "bin", "_quarantine"}


def _excluded_under(path: Path, base: Path) -> bool:
    """True if ``path`` lives in an excluded subdir *relative to* ``base``.

    Checks parts relative to the search root so an absolute prefix like
    ``NinjaTrader 8/bin/Custom`` does not wrongly exclude the deploy tree.
    """
    try:
        rel = path.relative_to(base)
    except ValueError:
        return False
    return any(part.lower() in _EXCLUDED_DIR_NAMES for part in rel.parts)


def find_class_folders(class_name: str, dirs: List[Path]) -> List[Path]:
    """Per-class source folders (``dir/**/Class/`` holding ``Class.cs``).

    Searches recursively so nested deploy wrappers (e.g. a CELL wrapper placed
    inside its base-class folder ``Base/Wrapper/Wrapper.cs``) are also found and
    can be removed without touching the shared base class.
    """
    cls = str(class_name or "").strip()
    if not cls:
        return []
    out: List[Path] = []
    seen: Set[str] = set()
    for d in dirs:
        if not d.is_dir():
            continue
        for sub in d.rglob(cls):
            if not sub.is_dir() or _excluded_under(sub, d):
                continue
            if (sub / f"{cls}.cs").exists() or list(sub.glob(f"{cls}.*.cs")):
                key = str(sub).lower()
                if key not in seen:
                    seen.add(key)
                    out.append(sub)
    return out


def remove_strategy_from_ninjatrader(profile: Dict[str, Any],
                                     active_used: Set[str],
                                     *,
                                     nt_user_home: Optional[Path] = None,
                                     nt_running: Optional[bool] = None) -> Dict[str, Any]:
    """Quarantine the CELL wrapper ``.cs`` for one archived profile.

    Returns a record describing what happened. ``removed`` is True whenever the
    class is gone from every compile path *and* stale NinjaTrader UI state has
    been purged (or was already absent).
    """
    decision = plan_removal(profile, active_used)
    cell_id = str(profile.get("cell_id") or profile.get("archived_cell_id") or "").strip()
    result: Dict[str, Any] = {
        "profile_id": str(profile.get("profile_id") or profile.get("id") or "").strip(),
        "class_name": decision.get("class_name"),
        "cell_id": cell_id,
        "removed": False,
        "source_removed": False,
        "moved_files": [],
        "reason": decision.get("reason"),
        "source_reason": decision.get("reason"),
        "ui_state_reason": "",
        "at_utc": _now(),
    }
    if not decision["ok"]:
        return result

    cls = decision["class_name"]
    dirs = strategy_source_dirs(nt_user_home)
    folders = find_class_folders(cls, dirs)
    flat_files = [f for f in find_class_files(cls, dirs)
                  if not any(str(f).startswith(str(fl)) for fl in folders)]
    if not folders and not flat_files:
        # Nothing on disk to move (e.g. source already removed earlier).
        result["source_removed"] = True
        result["source_reason"] = "already_absent"
    else:
        stamp = _stamp()
        target_dir = _quarantine_root() / f"{(cell_id or cls)}_{stamp}"
        target_dir.mkdir(parents=True, exist_ok=True)
        moved: List[str] = []
        for folder in folders:
            dest = target_dir / folder.name
            try:
                shutil.move(str(folder), str(dest))
                moved.append(str(dest))
            except OSError as exc:  # noqa: PERF203
                result["error"] = f"{folder.name}: {exc}"
        for src in flat_files:
            dest = target_dir / src.name
            try:
                shutil.move(str(src), str(dest))
                moved.append(str(dest))
            except OSError as exc:  # noqa: PERF203
                result["error"] = f"{src.name}: {exc}"
        meta = {
            "class_name": cls,
            "cell_id": cell_id,
            "profile_id": result["profile_id"],
            "reason": str(profile.get("archive_reason") or ""),
            "quarantined_at_utc": _now(),
            "moved": moved,
        }
        (target_dir / "_quarantine.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        result["source_removed"] = bool(moved)
        result["source_reason"] = "quarantined" if moved else "move_failed"
        result["moved_files"] = moved
        result["quarantine_dir"] = str(target_dir)

    ui_state = purge_strategy_ui_state(
        cls,
        nt_user_home=nt_user_home,
        nt_running=nt_running,
    )
    result["ui_state"] = ui_state
    result["ui_state_removed"] = bool(ui_state.get("removed"))
    result["ui_state_reason"] = str(ui_state.get("reason") or "")
    result["ui_nodes_removed"] = int(ui_state.get("ui_nodes_removed") or 0)
    result["workspace_entries_removed"] = int(ui_state.get("workspace_entries_removed") or 0)
    result["removed"] = bool(result["source_removed"] and ui_state.get("removed"))
    if result["removed"]:
        result["reason"] = result["source_reason"]
    elif not result["source_removed"]:
        result["reason"] = result["source_reason"]
    else:
        result["reason"] = result["ui_state_reason"] or "ui_state_pending"
    return result


# ---------------------------------------------------------------------------
# Full cleanup: keep NinjaTrader's strategy list to APPROVED strategies only.
#
# Goal: after this runs (and the operator presses F5 / restarts NinjaTrader) the
# "Available strategies" picker shows ONLY approved/ready strategies plus the
# base engine classes they inherit from. Everything else (archived production
# wrappers, AI sandbox experiments, reference-library examples, orphan research
# engines) is moved to the reversible quarantine.
#
# Safety: we never remove a class that an approved strategy needs to compile.
# The keep-set is the *closure* of approved classes over both inheritance
# (``class X : Base``) and direct code references, computed from the NinjaScript
# source. The repo source tree is NOT touched (dev history is preserved); only
# the NinjaTrader Custom compile folders are cleaned.
# ---------------------------------------------------------------------------

_CLASS_DECL_RE = re.compile(r"\bclass\s+([A-Za-z_]\w*)\s*(?::\s*([A-Za-z_][\w\.]*))?")
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")


def approved_strategy_classes(profiles: List[Dict[str, Any]]) -> Set[str]:
    """Classes referenced by approved (demo/live) profiles — the must-keep seed."""
    keep: Set[str] = set()
    for p in profiles or []:
        if not isinstance(p, dict):
            continue
        if strategy_lifecycle.classify_lifecycle(p) in (
            strategy_lifecycle.APPROVED_DEMO, strategy_lifecycle.APPROVED_LIVE
        ):
            for c in _all_classes(p):
                keep.add(c)
    return keep


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def _parse_class_decls(text: str) -> List[tuple]:
    out: List[tuple] = []
    for m in _CLASS_DECL_RE.finditer(_strip_comments(text)):
        base = (m.group(2) or "").split("<")[0].split(".")[-1].strip()
        out.append((m.group(1), base))
    return out


def cleanup_custom_dirs(nt_user_home: Optional[Path] = None,
                        *,
                        include_ai_sandbox: bool = True,
                        include_ref_lib: bool = True) -> List[Path]:
    """NinjaTrader Custom strategy folders to clean (never the repo source)."""
    custom = ninjatrader_user_dir(nt_user_home) / "bin" / "Custom" / "Strategies"
    dirs = [custom / "NT-Analyzer_strategies"]
    if include_ai_sandbox:
        dirs.append(custom / "NT-Analyzer_AI Labstrategies")
    if include_ref_lib:
        dirs.append(custom / "NT-Analyzer_Ref Lib")
    return [d for d in dirs if d.is_dir()]


def build_class_index(dirs: List[Path]) -> Dict[str, Dict[str, Any]]:
    """Map every file-level strategy class -> {bases, files, tokens}.

    Only classes whose source file is named after them (``Class.cs`` or
    ``Class.partial.cs``) become closure nodes. Nested helper classes (e.g. a
    private ``RiskManager`` declared inside an engine file) are intentionally
    excluded so same-named helpers across files do not create false
    cross-references in the keep closure.

    ``tokens`` is the set of identifiers used in the class' source (comments
    stripped) so we can follow direct code references, not only inheritance.
    """
    index: Dict[str, Dict[str, Any]] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for f in d.rglob("*.cs"):
            if _excluded_under(f, d):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            code = _strip_comments(text)
            tokens = set(_IDENT_RE.findall(code))
            for cls, base in _parse_class_decls(text):
                # Only register top-level, file-named classes as closure nodes.
                if not _file_name_matches_class(f.name, cls):
                    continue
                entry = index.setdefault(cls, {"bases": set(), "files": [], "tokens": set()})
                if base:
                    entry["bases"].add(base)
                entry["files"].append(f)
                entry["tokens"] |= tokens
    return index


def compute_keep_closure(approved: Set[str],
                         index: Dict[str, Dict[str, Any]],
                         *,
                         follow_usage: bool = True) -> Set[str]:
    """Approved classes + everything they need to compile (bases + references)."""
    all_classes = set(index.keys())
    keep: Set[str] = set(approved)
    stack: List[str] = [c for c in approved if c in index]
    while stack:
        cls = stack.pop()
        entry = index.get(cls)
        if not entry:
            continue
        refs: Set[str] = set(entry["bases"])
        if follow_usage:
            refs |= (entry["tokens"] & all_classes)
        for ref in refs:
            if ref in all_classes and ref not in keep:
                keep.add(ref)
                stack.append(ref)
    return keep


def _declared_classes_in(item: Path) -> Set[str]:
    classes: Set[str] = set()
    files = [item] if item.is_file() else [
        f for f in item.rglob("*.cs") if not _excluded_under(f, item)
    ]
    for f in files:
        if f.suffix.lower() != ".cs":
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for cls, _base in _parse_class_decls(text):
            classes.add(cls)
    return classes


def cleanup_to_approved(profiles: List[Dict[str, Any]],
                        *,
                        include_ai_sandbox: bool = True,
                        include_ref_lib: bool = True,
                        dry_run: bool = True,
                        nt_user_home: Optional[Path] = None) -> Dict[str, Any]:
    """Quarantine every NinjaTrader Custom strategy that is not approved.

    Only the NinjaTrader Custom compile folders are touched. The repo source
    tree is preserved. ``dry_run`` reports what *would* move without moving.
    After a real run the operator must recompile NinjaTrader (F5) for the picker
    to drop the removed classes.
    """
    approved = approved_strategy_classes(profiles)
    custom = ninjatrader_user_dir(nt_user_home) / "bin" / "Custom" / "Strategies"
    repo = _project_root() / "ninjatrader" / "strategies"
    # Index repo + all custom subfolders so the closure sees every base class.
    index_dirs = [repo, custom / "NT-Analyzer_strategies",
                  custom / "NT-Analyzer_AI Labstrategies", custom / "NT-Analyzer_Ref Lib"]
    index = build_class_index([d for d in index_dirs if d.is_dir()])
    keep = compute_keep_closure(approved, index)

    clean_dirs = cleanup_custom_dirs(
        nt_user_home, include_ai_sandbox=include_ai_sandbox, include_ref_lib=include_ref_lib)

    stamp = _stamp()
    qroot = _quarantine_root() / f"cleanup_{stamp}"
    kept: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    errors: List[str] = []

    for d in clean_dirs:
        for item in sorted(d.iterdir()):
            if item.name.lower() in _EXCLUDED_DIR_NAMES:
                continue
            if item.is_dir():
                decl = _declared_classes_in(item)
            elif item.suffix.lower() == ".cs":
                decl = _declared_classes_in(item)
            else:
                continue
            # Keep if it declares an approved/needed class, or declares nothing
            # parseable (utility/partial) — never risk breaking compilation.
            if (decl & keep) or not decl:
                kept.append({"item": str(item), "folder": d.name, "classes": sorted(decl)})
                continue
            removed.append({"item": str(item), "folder": d.name, "classes": sorted(decl)})
            if not dry_run:
                dest = qroot / d.name / item.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(item), str(dest))
                except OSError as exc:  # noqa: PERF203
                    errors.append(f"{item.name}: {exc}")

    if not dry_run and removed and qroot.exists():
        (qroot / "_cleanup.json").write_text(json.dumps({
            "cleaned_at_utc": _now(),
            "approved": sorted(approved),
            "keep_closure": sorted(keep),
            "removed": removed,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "dry_run": dry_run,
        "approved": sorted(approved),
        "keep_closure_count": len(keep),
        "kept_count": len(kept),
        "removed_count": len(removed),
        "kept": kept,
        "removed": removed,
        "errors": errors,
        "quarantine_dir": str(qroot) if (not dry_run and removed) else None,
        "ninjatrader_running": ninjatrader_is_running(),
        "recompile_required": True,
    }

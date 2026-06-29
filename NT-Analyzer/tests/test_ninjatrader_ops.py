"""ninjatrader_ops removal-safety tests.

Run from NT-Analyzer/ root:
    python -m tests.test_ninjatrader_ops
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ninjatrader_ops as nto  # noqa: E402

PASSED: List[str] = []
FAILED: List[Tuple[str, str]] = []


def case(name: str):
    def deco(fn):
        def wrap():
            try:
                fn()
                PASSED.append(name)
                print(f"  PASS  {name}")
            except Exception as e:  # noqa: BLE001
                FAILED.append((name, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
                print(f"  FAIL  {name}: {e}")
        return wrap
    return deco


@case("removal_candidate prefers deploy wrapper")
def t01() -> None:
    p = {"deploy_strategy_class": "WrapperC007", "strategy_class": "SharedHub"}
    assert nto.removal_candidate_class(p) == "WrapperC007"


@case("removal_candidate falls back to strategy_class")
def t02() -> None:
    assert nto.removal_candidate_class({"strategy_class": "Solo"}) == "Solo"
    assert nto.removal_candidate_class({}) is None


@case("active_class_usage excludes archived, includes active")
def t03() -> None:
    profiles = [
        {"status": "ready", "strategy_class": "SharedHub"},
        {"status": "archived", "deploy_strategy_class": "WrapperC007", "strategy_class": "SharedHub"},
    ]
    used = nto.active_class_usage(profiles)
    assert "sharedhub" in used
    assert "wrapperc007" not in used


@case("plan_removal blocks shared class")
def t04() -> None:
    used = {"sharedhub"}
    d = nto.plan_removal({"strategy_class": "SharedHub"}, used)
    assert d["ok"] is False and d["reason"] == "shared_with_active", d


@case("plan_removal allows isolated deploy wrapper")
def t05() -> None:
    used = {"sharedhub"}
    d = nto.plan_removal({"deploy_strategy_class": "WrapperC007", "strategy_class": "SharedHub"}, used)
    assert d["ok"] is True and d["class_name"] == "WrapperC007", d


@case("find_class_files matches main + partials")
def t06() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        for name in ["WrapperC007.cs", "WrapperC007.Entry.cs", "WrapperC007.Time.cs", "Other.cs"]:
            (d / name).write_text("// x", encoding="utf-8")
        files = nto.find_class_files("WrapperC007", [d])
        names = sorted(p.name for p in files)
        assert names == ["WrapperC007.Entry.cs", "WrapperC007.Time.cs", "WrapperC007.cs"], names


@case("remove returns already_absent when no files and not shared")
def t07() -> None:
    with tempfile.TemporaryDirectory() as td:
        # No matching files in an empty home -> already absent.
        prof = {"profile_id": "x", "deploy_strategy_class": "DoesNotExistC999", "status": "archived"}
        res = nto.remove_strategy_from_ninjatrader(prof, set(), nt_user_home=Path(td), nt_running=False)
        # The repo dir may exist but won't contain DoesNotExistC999.
        assert res["removed"] is True, res
        assert res["reason"] == "already_absent", res


@case("remove blocked for shared class -> removed False")
def t08() -> None:
    prof = {"profile_id": "x", "strategy_class": "SharedHub", "status": "archived"}
    res = nto.remove_strategy_from_ninjatrader(prof, {"sharedhub"})
    assert res["removed"] is False, res
    assert res["reason"] == "shared_with_active", res


@case("remove cleans stale UI and workspace state when source already absent")
def t09() -> None:
    with tempfile.TemporaryDirectory() as td:
        nt_root = Path(td) / "NinjaTrader 8"
        (nt_root / "bin" / "Custom").mkdir(parents=True, exist_ok=True)
        ui = nt_root / "UI.xml"
        ui.write_text(
            "<NinjaTrader>"
            "<NinjaTrader.NinjaScript.Strategies.GhostC001><x>true</x></NinjaTrader.NinjaScript.Strategies.GhostC001>"
            "</NinjaTrader>",
            encoding="utf-8",
        )
        ws = nt_root / "workspaces" / "main.xml"
        ws.parent.mkdir(parents=True, exist_ok=True)
        ws.write_text(
            "<NinjaTrader><OpenFiles><ArrayOfScriptTabStateSerialize>"
            "<ScriptTabStateSerialize><FileName>C:\\Users\\dimon\\Documents\\NinjaTrader 8\\bin\\Custom\\Strategies\\GhostC001.cs</FileName></ScriptTabStateSerialize>"
            "</ArrayOfScriptTabStateSerialize></OpenFiles></NinjaTrader>",
            encoding="utf-8",
        )

        prof = {"profile_id": "x", "deploy_strategy_class": "GhostC001", "status": "archived"}
        res = nto.remove_strategy_from_ninjatrader(prof, set(), nt_user_home=nt_root, nt_running=False)
        assert res["source_removed"] is True, res
        assert res["removed"] is True, res
        assert res["reason"] == "already_absent", res
        assert res["ui_state_removed"] is True, res
        assert res["ui_nodes_removed"] == 1, res
        assert res["workspace_entries_removed"] == 1, res

        ui_doc = ui.read_text(encoding="utf-8")
        ws_doc = ws.read_text(encoding="utf-8")
        assert "GhostC001" not in ui_doc, ui_doc
        assert "GhostC001.cs" not in ws_doc, ws_doc


@case("remove leaves stale UI state pending while NinjaTrader is running")
def t10() -> None:
    with tempfile.TemporaryDirectory() as td:
        nt_root = Path(td) / "NinjaTrader 8"
        (nt_root / "bin" / "Custom").mkdir(parents=True, exist_ok=True)
        ui = nt_root / "UI.xml"
        ui.write_text(
            "<NinjaTrader>"
            "<NinjaTrader.NinjaScript.Strategies.GhostC002><x>true</x></NinjaTrader.NinjaScript.Strategies.GhostC002>"
            "</NinjaTrader>",
            encoding="utf-8",
        )
        prof = {"profile_id": "x", "deploy_strategy_class": "GhostC002", "status": "archived"}
        res = nto.remove_strategy_from_ninjatrader(prof, set(), nt_user_home=nt_root, nt_running=True)
        assert res["source_removed"] is True, res
        assert res["removed"] is False, res
        assert res["reason"] == "ninjatrader_running", res
        assert res["ui_state_reason"] == "ninjatrader_running", res
        assert "GhostC002" in ui.read_text(encoding="utf-8")


@case("remove also purges matching workspace FullTemplate blocks")
def t11() -> None:
    with tempfile.TemporaryDirectory() as td:
        nt_root = Path(td) / "NinjaTrader 8"
        (nt_root / "bin" / "Custom").mkdir(parents=True, exist_ok=True)
        ws = nt_root / "workspaces" / "recovery" / "main.xml"
        ws.parent.mkdir(parents=True, exist_ok=True)
        ws.write_text(
            "<NinjaTrader><Tabs>"
            "<Tab><FullTemplate><StrategyType>NinjaTrader.NinjaScript.Strategies.GhostC003</StrategyType>"
            "<Strategy><GhostC003 /></Strategy></FullTemplate></Tab>"
            "<Tab><FullTemplate><StrategyType>NinjaTrader.NinjaScript.Strategies.OtherC999</StrategyType>"
            "<Strategy><OtherC999 /></Strategy></FullTemplate></Tab>"
            "</Tabs></NinjaTrader>",
            encoding="utf-8",
        )
        prof = {"profile_id": "x", "deploy_strategy_class": "GhostC003", "status": "archived"}
        res = nto.remove_strategy_from_ninjatrader(prof, set(), nt_user_home=nt_root, nt_running=False)
        assert res["removed"] is True, res
        assert res["workspace_entries_removed"] == 1, res
        assert res["ui_state"]["workspaces"]["removed_full_templates"] == 1, res
        doc = ws.read_text(encoding="utf-8")
        assert "GhostC003" not in doc, doc
        assert "OtherC999" in doc, doc


@case("parse class decls ignores comments")
def t12() -> None:
    text = "// this class Foo is a comment\nclass Real : Base { }\n/* class Ghost */"
    decls = dict(nto._parse_class_decls(text))
    assert decls.get("Real") == "Base", decls
    assert "Foo" not in decls and "Ghost" not in decls, decls


@case("keep closure follows inheritance chain only")
def t13() -> None:
    index = {
        "Wrapper": {"bases": {"Engine"}, "files": [], "tokens": set()},
        "Engine": {"bases": {"Hub"}, "files": [], "tokens": set()},
        "Hub": {"bases": {"Strategy"}, "files": [], "tokens": set()},
        "Other": {"bases": {"Strategy"}, "files": [], "tokens": set()},
    }
    keep = nto.compute_keep_closure({"Wrapper"}, index, follow_usage=False)
    assert keep == {"Wrapper", "Engine", "Hub"}, keep


@case("keep closure follows code usage references")
def t14() -> None:
    index = {
        "Wrapper": {"bases": {"Strategy"}, "files": [], "tokens": {"Helper"}},
        "Helper": {"bases": {"Strategy"}, "files": [], "tokens": set()},
        "Unused": {"bases": {"Strategy"}, "files": [], "tokens": set()},
    }
    keep = nto.compute_keep_closure({"Wrapper"}, index, follow_usage=True)
    assert "Helper" in keep and "Unused" not in keep, keep


@case("approved_strategy_classes picks approved profiles only")
def t15() -> None:
    profiles = [
        {"status": "ready", "deploy_strategy_class": "Appr"},
        {"status": "archived", "deploy_strategy_class": "Arch"},
        {"status": "in_progress", "deploy_strategy_class": "Trial"},
    ]
    appr = nto.approved_strategy_classes(profiles)
    assert "Appr" in appr and "Arch" not in appr and "Trial" not in appr, appr


def main() -> int:
    print("ninjatrader_ops tests")
    for name, fn in sorted(globals().items()):
        if name.startswith("t") and callable(fn) and name[1:].isdigit():
            fn()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for n, err in FAILED:
            print(f"\nFAIL {n}\n{err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

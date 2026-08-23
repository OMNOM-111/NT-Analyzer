"""Regression contracts for the authenticated responsive application shell."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AURORA = ROOT / "app" / "static" / "aurora"
THEME = (AURORA / "assets" / "theme.css").read_text(encoding="utf-8")
DESKTOP = (AURORA / "desktop.html").read_text(encoding="utf-8")


def test_authenticated_topbar_collapses_before_controls_leave_the_viewport():
    assert ".tb-title { display: flex; flex: 0 1 180px" in THEME
    assert ".tb-right { margin-left: auto; display: flex; flex: 0 1 auto" in THEME
    for breakpoint in (2300, 2150, 2000, 1700, 900):
        assert f"@media (max-width: {breakpoint}px)" in THEME
    assert "#chip-nt, #chip-user, .tb-datetime { display: none; }" in THEME
    assert "#admin-env-switcher .env-seg-btn:not(.on) { display: none; }" in THEME


def test_chart_windows_have_tablet_and_phone_compact_modes():
    tablet = DESKTOP[DESKTOP.index("@media(max-width:1100px){"):]
    tablet = tablet[:tablet.index("@media(max-width:600px){")]
    assert ".dsk-canvas{position:relative" in tablet
    assert "transform:none!important" in tablet
    assert ".dwin:not(.maximized){position:relative!important" in tablet
    assert "width:100%!important" in tablet
    assert ".dwin-grip{display:none!important}" in tablet

    phone = DESKTOP[DESKTOP.index("@media(max-width:600px){"):]
    phone = phone[:phone.index("</style>")]
    assert "padding:0 0 82px!important" in phone
    assert "padding-bottom:108px!important" in phone


def test_mobile_admin_content_wraps_inside_its_drawer():
    assert ".drawer .cab-sub { white-space: normal" in THEME
    assert ".conn-steps { grid-template-columns: minmax(0, 1fr); min-width: 0; }" in THEME
    assert ".conn-steps > li { min-width: 0; max-width: 100%; }" in THEME
    assert "grid-template-rows: max-content max-content" in THEME
    assert "min-height: 0; flex: 0 0 auto" in THEME


def test_mobile_kanban_reflows_instead_of_hiding_cards_to_the_right():
    assert ".kanban { grid-auto-flow: row; grid-auto-columns: auto;" in THEME
    assert "grid-template-columns: minmax(0, 1fr); overflow-x: hidden;" in THEME
    assert ".kan-col { max-height: none; }" in THEME

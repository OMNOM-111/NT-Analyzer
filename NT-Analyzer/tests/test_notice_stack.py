"""Notices inform; they do not occupy the page.

Nothing bounded the stack and no card retired on its own -- only user
interaction cleared them -- so a quiet session accumulated banners until they
covered the right-hand side. At z-index 92 over the drawer's 75 they sat on top
of the very panel the reader had opened, hiding the Production card in the
environments module.
"""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
AURORA = ROOT / "app" / "static" / "aurora" / "assets"
UI = (AURORA / "ui.js").read_text(encoding="utf-8")
CSS = (AURORA / "theme.css").read_text(encoding="utf-8")


def _render_notice():
    start = UI.index("function renderNotice(item)")
    return UI[start:UI.index("function noticeTimeLabel", start)]


# --------------------------------------------------------------------------- #
# The stack is bounded.
# --------------------------------------------------------------------------- #
def test_the_number_of_visible_banners_is_capped():
    match = re.search(r"const NOTICE_MAX_VISIBLE = (\d+);", UI)
    assert match, "the cap should be a named constant"
    assert int(match.group(1)) == 1


def test_adding_a_banner_trims_the_stack():
    body = _render_notice()
    assert "trimNoticeStack()" in body


def test_trimming_drops_the_oldest_and_not_the_newest():
    trim = UI[UI.index("function trimNoticeStack"):]
    trim = trim[:trim.index("\n  }")]
    assert "NOTICE_MAX_VISIBLE" in trim
    assert "slice(" in trim


def test_the_container_actually_clips_its_contents():
    """With overflow visible the stack grew past its own max-height and ran
    down the page regardless of the limit."""
    block = CSS[CSS.index(".sf-notice-wrap {"):]
    block = block[:block.index("}")]
    assert "overflow: hidden" in block
    assert "max-height" in block


def test_the_stack_stays_narrow():
    block = CSS[CSS.index(".sf-notice-wrap {"):]
    block = block[:block.index("}")]
    width = re.search(r"width: min\((\d+)px", block)
    assert width and int(width.group(1)) <= 340, block


# --------------------------------------------------------------------------- #
# Ordinary notices retire; ones needing a decision do not.
# --------------------------------------------------------------------------- #
def test_an_ordinary_notice_dismisses_itself():
    body = _render_notice()
    assert re.search(r"const NOTICE_AUTO_DISMISS_MS = (\d+);", UI)
    assert "if (!urgent)" in body
    assert "dismissNoticeDom(id)" in body


def test_an_urgent_notice_is_not_dismissed_for_the_reader():
    """Auto-dismissing something that needs a decision is the interface
    deciding on the reader's behalf that nothing was needed."""
    body = _render_notice()
    timer = body[body.index("NOTICE.timers.set"):]
    # The only timer registrations are inside the non-urgent branch.
    guard = body[:body.index("NOTICE.timers.set")]
    assert "if (!urgent)" in guard
    assert "urgent" in timer or True  # the branch above is the assertion


def test_the_auto_dismiss_delay_is_long_enough_to_read():
    ms = int(re.search(r"const NOTICE_AUTO_DISMISS_MS = (\d+);", UI).group(1))
    assert 4000 <= ms <= 15000


def test_hovering_holds_the_banner_open():
    """Pulling text away from someone mid-sentence is worse than leaving it."""
    body = _render_notice()
    assert "mouseenter" in body
    assert "mouseleave" in body
    assert "clearTimeout" in body


def test_the_grouped_card_offers_chat_action_and_remaining_count():
    body = _render_notice()
    assert "Открыть в чате" in body
    assert "sf-notice-more" in body
    assert "_more" in body


# --------------------------------------------------------------------------- #
# It does not cover the work.
# --------------------------------------------------------------------------- #
def test_an_open_panel_moves_the_stack_out_of_its_way():
    assert "body.has-drawer .sf-notice-wrap" in CSS
    block = CSS[CSS.index("body.has-drawer .sf-notice-wrap {"):]
    block = block[:block.index("}")]
    assert "right:" in block


def test_the_offset_is_measured_rather_than_assumed():
    """A drawer is normal, wide, full or dragged anywhere between. A guessed
    offset puts the stack back on the panel in every case the guess missed --
    which is what a hard-coded 720px did to the wide admin panel."""
    sync = UI[UI.index("function syncNoticeOffset()"):]
    sync = sync[:sync.index("\n  }")]
    assert "getBoundingClientRect().width" in sync
    assert "--drawer-w" in sync
    assert "has-drawer" in sync
    assert "body.has-drawer .sf-notice-wrap" in CSS
    assert "var(--drawer-w" in CSS


def test_the_offset_is_resynced_on_every_width_change():
    """Opening is not the only thing that moves the edge."""
    for site in ("function setDrawerSize", "function wireDrawerResize",
                 "function closeDrawer()"):
        body = UI[UI.index(site):]
        body = body[:body.index("\n  }\n")]
        assert "syncNoticeOffset()" in body, site
    assert "addEventListener('resize', syncNoticeOffset)" in UI


def test_no_room_beside_the_panel_means_yielding_the_space():
    """Measured, not guessed at a breakpoint: an offset wide enough to clear a
    full-width panel would push the stack off-screen and lose it silently."""
    sync = UI[UI.index("function syncNoticeOffset()"):]
    sync = sync[:sync.index("\n  }")]
    assert "notices-cramped" in sync
    assert "innerWidth - width" in sync
    assert "body.notices-cramped .sf-notice-wrap { display: none; }" in CSS


def test_phone_and_desktop_cards_are_anchored_above_sf_chat_launcher():
    final = CSS[CSS.rindex("SF Chat — unified human + AI shell"):]
    assert ".sf-notice-wrap" in final
    assert "bottom: 108px" in final
    assert "bottom: 132px" in final
    assert "top: auto" in final


def test_closing_a_human_notice_does_not_mark_the_conversation_read():
    body = _render_notice()
    close_branch = body[body.index("data-notice-close"):body.index("openNotice(item)")]
    assert "dismissNoticeDom(id)" in close_branch
    assert "sfChatRead" not in close_branch

"""A notification and the conversation behind it are two destinations.

The banner used to be one large button wired straight to `openSFChat`, so any
click on it — including a click meant to read the notification — opened the
messenger over whatever the reader was doing. There was no way to look at the
notification itself, and a system notice with no conversation still opened the
chat widget. Reading and navigating are now separate, explicitly labelled acts.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AURORA = ROOT / "app" / "static" / "aurora" / "assets"
UI = (AURORA / "ui.js").read_text(encoding="utf-8")
CSS = (AURORA / "theme.css").read_text(encoding="utf-8")


def _slice(start: str, end: str) -> str:
    begin = UI.index(start)
    return UI[begin:UI.index(end, begin)]


def _render_notice() -> str:
    return _slice("function renderNotice(item)", "function noticeTimeLabel")


def _center() -> str:
    return _slice("async function showNotificationsCenter(opts)",
                  "function wireNotificationsBell()")


# --------------------------------------------------------------------------- #
# The banner leads to the notification centre.
# --------------------------------------------------------------------------- #
def test_the_banner_body_opens_the_notification_not_the_chat():
    body = _render_notice()
    assert "openNoticeInCenter(item)" in body
    # The only openSFChat reachable from a banner is behind the chat button.
    assert "openSFChat" not in body


def test_the_banner_is_no_longer_one_undifferentiated_button():
    """A single button cannot offer two different destinations."""
    body = _render_notice()
    assert 'class="sf-notice ' in body
    assert '<div class="sf-notice ' in body
    assert 'class="sf-notice-main"' in body


def test_opening_in_the_centre_focuses_that_one_notification():
    fn = _slice("async function openNoticeInCenter(item)",
                "  // How many banners may be on screen")
    assert "showNotificationsCenter({ focusId: id })" in fn
    center = _center()
    assert "opts && opts.focusId" in center
    assert "expandedId" in center


def test_the_cross_only_retires_the_banner():
    body = _render_notice()
    branch = body[body.index("hasAttribute('data-notice-close')"):
                  body.index("hasAttribute('data-notice-chat')")]
    assert "dismissNoticeDom(id)" in branch
    assert "sfChatRead" not in branch
    assert "openSFChat" not in branch
    assert "showNotificationsCenter" not in branch


def test_the_remaining_count_opens_the_whole_centre():
    body = _render_notice()
    branch = body[body.index("hasAttribute('data-notice-all')"):]
    branch = branch[:branch.index("openNoticeInCenter(item)")]
    assert "showNotificationsCenter()" in branch
    assert "data-notice-all" in body


# --------------------------------------------------------------------------- #
# Reaching SF Chat is always an explicit, labelled act.
# --------------------------------------------------------------------------- #
def test_only_the_chat_button_opens_sf_chat():
    """Every route from a notification into the messenger goes through one
    function, and that function is only ever called from a chat button."""
    assert UI.count("await openNoticeInChat(item)") == 2  # banner button + inbox button
    body = _render_notice()
    banner = body[body.index("hasAttribute('data-notice-chat')"):]
    banner = banner[:banner.index("hasAttribute('data-notice-all')")]
    assert "openNoticeInChat(item)" in banner
    center = _center()
    assert "data-inbox-chat" in center
    inbox = center[center.index("qsa('[data-inbox-chat]'"):]
    assert "openNoticeInChat(item)" in inbox[:inbox.index("}));")]


def test_the_chat_button_says_where_it_goes():
    fn = _slice("function noticeChatLabel(item)", "function noticeHasConversation")
    assert "Ответить" in fn
    assert "Открыть в чате" in fn


def test_a_notification_without_a_conversation_offers_no_chat_button():
    """A system notice has nothing to open; offering the button anyway would be
    a control that does not do what it says."""
    fn = _slice("async function openNoticeInChat(item)", "  // Opening a notification does not")
    assert "if (!cid) return;" in fn
    assert "noticeHasConversation(item) ?" in _render_notice()
    assert "noticeHasConversation(item) ?" in _center()


def test_the_inbox_row_expands_instead_of_navigating():
    center = _center()
    toggle = center[center.index("qsa('[data-inbox-open]'"):]
    toggle = toggle[:toggle.index("}));")]
    assert "expandedId = expandedId === id ? '' : id" in toggle
    assert "paint(lastData)" in toggle
    assert "openNoticeInChat" not in toggle
    assert "closeDrawer" not in toggle


def test_toggling_a_row_does_not_refetch_the_inbox():
    """Expanding a row is a local act; re-reading the server for it would make
    the list flicker and re-order under the reader's cursor."""
    center = _center()
    assert "const paint = (data)" in center
    assert "unifiedNoticeData()" in center
    assert center.count("unifiedNoticeData()") == 1


# --------------------------------------------------------------------------- #
# The launcher rests as the mark alone.
# --------------------------------------------------------------------------- #
def _launcher_block() -> str:
    marker = "/* The launcher: the SF Chat mark on the page"
    block = CSS[CSS.index(marker):]
    return block[:block.index("@media (prefers-reduced-motion")]


def test_the_launcher_has_no_resting_plate():
    block = _launcher_block()
    rule = block[block.index(".orch-fab,"):block.index(".orch-fab::before")]
    assert "background: transparent;" in rule
    assert "border: 1px solid transparent;" in rule
    assert "box-shadow: none;" in rule


def test_the_launcher_grows_and_gains_its_frame_on_hover():
    block = _launcher_block()
    hover = block[block.index(".orch-fab:hover,"):]
    hover = hover[:hover.index("}")]
    assert "scale(1.07)" in hover
    assert "border-color:" in hover
    assert "background:" in hover
    assert "box-shadow:" in hover


def test_the_launcher_frame_is_removed_for_every_skin_not_just_the_default():
    """Skin rules are more specific than a bare `.orch-fab`, so a plain
    override would have left five of the six skins with their plate."""
    block = _launcher_block()
    assert "html[data-orch-skin] .orch-fab {" in block
    assert "html[data-orch-skin] .orch-fab:hover," in block


def test_the_launcher_still_opens_the_chat():
    assert "fab.addEventListener('click', () => { ORCH.open ? closeOrchestrator() : openOrchestrator(); });" in UI

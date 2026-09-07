"""A hidden tab never boots the Aurora shell. Documented, not yet fixed here.

`ui.js` ends with `document.addEventListener('DOMContentLoaded', buildShell)`,
and `buildShell` defers the whole authenticated start through
`requestAnimationFrame(() => authenticateAndStart(newsStrip))`. A browser does
not run rAF callbacks for a hidden document, so a page opened in a background
tab — middle-click, a restored session, a collapsed preview pane — stays on its
loading skeleton with `CURRENT_AUTH` null, no error and no console message,
until the tab becomes visible. It then boots normally, so the defect
self-heals on focus and is low severity.

Reproduced during this review on both the owner Local (8765) and an isolated
instance (8799): with the pane hidden, `document.hidden` was true,
`UI.CURRENT_AUTH` null, the AI Center content stuck at 169 bytes of skeleton
and the rail label still the static "AI Lab"; fronting the pane completed the
boot within one frame.

**Deliberately not fixed in this branch.** `ui.js` is a shared file that
currently has uncommitted changes in the `codex/agent-world-mechanisms`
worktree, so it has an active editor who is not this reviewer. Editing it here
would create a second editor on one file and a conflict at integration, which
is exactly what the working agreement forbids. The fix belongs to whoever owns
`ui.js` during integration.

The expected fix is one line beside the existing call, not a rewrite: schedule
the same start through a timeout as well as a frame, and let whichever fires
first win, so a hidden document still boots.

    let started = false;
    const start = () => { if (!started) { started = true; authenticateAndStart(newsStrip); } };
    requestAnimationFrame(start);
    setTimeout(start, 0);

The `started` latch is the point of the test below: the two schedulers must not
be able to start the application twice, because `authenticateAndStart` performs
the auth exchange and builds the shell.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "app" / "static" / "aurora" / "assets" / "ui.js"


def test_the_shell_start_is_still_scheduled_only_through_a_frame():
    """Records the present state. Delete this test when the fix lands."""
    source = UI.read_text(encoding="utf-8", errors="ignore")
    assert "document.addEventListener('DOMContentLoaded', buildShell)" in source
    assert re.search(r"requestAnimationFrame\(\s*\(\)\s*=>\s*\{\s*authenticateAndStart", source), (
        "The rAF-only boot appears to have changed. If the visibility fix has landed, "
        "replace this module with a check of the new contract: the shell starts exactly "
        "once whether or not the document was hidden.")
    # Not a bare "setTimeout(start" sentinel: the speech fallback already uses
    # that name for an unrelated timer. Look only at the boot region.
    boot = source[source.index("requestAnimationFrame(() => { authenticateAndStart"):][:400]
    assert "setTimeout" not in boot, "fix appears present in the boot path; update this module"


@pytest.mark.xfail(reason="ui.js has an active uncommitted editor in "
                          "codex/agent-world-mechanisms; the fix belongs to the integrator",
                   strict=False)
def test_a_hidden_document_still_boots_the_shell():
    assert "setTimeout(start, 0)" in UI.read_text(encoding="utf-8", errors="ignore")


def test_the_proposed_latch_starts_the_application_exactly_once():
    """The guard the fix must carry, verified independently of ui.js.

    Two schedulers may fire; the application must start once. This pins the
    behaviour the integrator has to preserve, so the fix cannot land as a
    double boot that performs the auth exchange twice.
    """
    script = """
    const results = [];
    for (const hidden of [true, false]) {
      let starts = 0, started = false;
      const start = () => { if (!started) { started = true; starts += 1; } };
      const frames = [], timers = [];
      const requestAnimationFrame = fn => { if (!hidden) frames.push(fn); };
      const setTimeout_ = fn => timers.push(fn);
      requestAnimationFrame(start);
      setTimeout_(start, 0);
      frames.forEach(fn => fn());
      timers.forEach(fn => fn());
      // A late frame after the tab becomes visible must not start a second time.
      start();
      results.push({ hidden, starts });
    }
    process.stdout.write(JSON.stringify(results));
    """
    out = subprocess.run(["node", "-e", script], check=True, capture_output=True,
                         text=True, encoding="utf-8", timeout=20)
    assert json.loads(out.stdout) == [{"hidden": True, "starts": 1},
                                      {"hidden": False, "starts": 1}]

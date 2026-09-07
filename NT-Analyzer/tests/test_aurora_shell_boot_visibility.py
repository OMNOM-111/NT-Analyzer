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

**Fixed in the integration branch**, where this reviewer is the single owner of
the `ui.js` edit. It was deliberately left alone earlier, while the file still
had uncommitted changes in the `codex/agent-world-mechanisms` worktree; that
worktree was never modified.

The fix schedules the same start through a timeout as well as a frame and lets
whichever fires first win, so a hidden document still boots.

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


def test_the_shell_start_is_scheduled_through_both_a_frame_and_a_timeout():
    """A hidden document runs no animation frame, so a timeout must also fire."""
    source = UI.read_text(encoding="utf-8", errors="ignore")
    assert "document.addEventListener('DOMContentLoaded', buildShell)" in source
    boot = source[source.index("const startShell ="):][:400]
    assert "requestAnimationFrame(startShell)" in boot
    assert "setTimeout(startShell, 0)" in boot


def test_the_boot_latch_is_present_so_the_two_schedulers_start_it_once():
    """Without the latch the fix would run the auth exchange twice."""
    source = UI.read_text(encoding="utf-8", errors="ignore")
    boot = source[source.index("let shellStarted = false;"):][:400]
    assert "if (!shellStarted) { shellStarted = true; authenticateAndStart(newsStrip); }" in boot


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

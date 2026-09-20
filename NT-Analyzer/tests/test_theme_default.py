from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "app" / "static" / "aurora" / "assets" / "ui.js"


def run_theme(stored):
    source = UI.read_text(encoding="utf-8")
    start = source.index("  const THEME_KEY = lsKey('app.theme');")
    end = source.index("  applyTheme(loadTheme());", start)
    script = """
      const vm = require('node:vm');
      const store = new Map(STORED === null ? [] : [['sf.app.theme', STORED]]);
      const root = {attrs: {}, setAttribute(key, value) { this.attrs[key] = value; }};
      const env = {lsKey: key => 'sf.' + key, document: {documentElement: root},
        localStorage: {getItem: key => store.has(key) ? store.get(key) : null, setItem: (key, value) => store.set(key, value)}};
      vm.createContext(env);
      vm.runInContext(SOURCE + '\\napplyTheme(loadTheme());', env);
      process.stdout.write(JSON.stringify({applied: root.attrs['data-theme'], stored: store.get('sf.app.theme') ?? null}));
    """.replace("STORED", json.dumps(stored)).replace("SOURCE", json.dumps(source[start:end]))
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_without_a_saved_choice_the_product_opens_dark_and_saves_nothing():
    assert run_theme(None) == {"applied": "dark", "stored": None}


def test_an_explicit_light_or_system_choice_is_never_overwritten():
    assert run_theme("light") == {"applied": "light", "stored": "light"}
    assert run_theme("auto") == {"applied": "auto", "stored": "auto"}
    assert run_theme("dark") == {"applied": "dark", "stored": "dark"}


def test_only_the_settings_choice_writes_the_theme():
    source = UI.read_text(encoding="utf-8")
    assert len(re.findall(r"localStorage\.setItem\(THEME_KEY", source)) == 1
    assert "function setTheme(mode)" in source

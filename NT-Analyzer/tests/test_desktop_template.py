"""Unit tests for the desktop chart template (макет графика).

Covers save/load of indicators, apply-to-all merge onto open chart configs,
and round-trip persistence through a fake localStorage.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_JS = ROOT / "app" / "static" / "aurora" / "assets" / "desktop-template.js"


def test_first_desktop_opens_chart_but_saved_empty_layout_is_preserved():
    source = (ROOT / "app/static/aurora/assets/pages/desktop.js").read_text(encoding="utf-8")
    load = source[source.index("  function loadStore() {"):source.index("  function migrate(raw) {")]
    boot = source[source.index("  // ---- boot "):source.rindex("});")]
    script = """
    const STORE_KEY='test'; let saved=null, firstDesktopOpen=false, opened=0;
    const localStorage={getItem:()=>saved,removeItem:()=>{}};
    const migrate=x=>x, newLayout=(id,name)=>({id,name,windows:[]});
    const mountLayout=()=>{},refreshContractsIfDue=()=>{},toast=()=>{};
    const ensureAnyWindow=()=>{opened++;return Promise.resolve();};
    """ + load + "\nlet first=loadStore();\n" + boot + """
    if(opened!==1) throw Error('first visit did not open chart');
    saved=JSON.stringify(first);firstDesktopOpen=false;
    loadStore();
    """ + boot + "\nif(opened!==1) throw Error('saved empty layout was replaced');"
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True)


def _eval(expression: str):
    source = TEMPLATE_JS.read_text(encoding="utf-8")
    script = source + "\nconsole.log(JSON.stringify(" + expression + "));"
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(proc.stdout.strip())


def test_default_template_has_empty_indicators_and_cloned_style():
    out = _eval("""(() => {
      const a = DesktopTemplate.defaultTemplate();
      const b = DesktopTemplate.defaultTemplate();
      a.indicators.push('macd');
      a.style.macd.fill = false;
      return {
        aInd: a.indicators,
        bInd: b.indicators,
        aFill: a.style.macd.fill,
        bFill: b.style.macd.fill,
        tf: b.timeframe,
      };
    })()""")
    assert out["aInd"] == ["macd"]
    assert out["bInd"] == []
    assert out["aFill"] is False
    assert out["bFill"] is True
    assert out["tf"] == "5m"


def test_make_template_from_config_keeps_indicators():
    out = _eval("""(() => {
      const tpl = DesktopTemplate.makeTemplateFromConfig({
        instrument: 'MNQ 09-26', root: 'MNQ',
        timeframe: '15m', type: 'candles',
        indicators: ['vol', 'macd', 'ema:21'],
        range: { id: '1w', days: 7, from: '', to: '' },
        aspect: 'wide',
        style: { upColor: '#00ff00', macd: { fill: false, vol: true } },
      });
      return {
        hasInstrument: 'instrument' in tpl,
        indicators: tpl.indicators,
        timeframe: tpl.timeframe,
        aspect: tpl.aspect,
        rangeId: tpl.range.id,
        up: tpl.style.upColor,
        macdFill: tpl.style.macd.fill,
        macdVol: tpl.style.macd.vol,
        macdLine: tpl.style.macd.line,
      };
    })()""")
    assert out["hasInstrument"] is False
    assert out["indicators"] == ["vol", "macd", "ema:21"]
    assert out["timeframe"] == "15m"
    assert out["aspect"] == "wide"
    assert out["rangeId"] == "1w"
    assert out["up"] == "#00ff00"
    assert out["macdFill"] is False
    assert out["macdVol"] is True
    assert out["macdLine"] == "#4fd1e0"  # default preserved for unset fields


def test_save_and_load_roundtrip_preserves_indicators():
    out = _eval("""(() => {
      const mem = (() => {
        const bag = {};
        return {
          getItem: (k) => (k in bag ? bag[k] : null),
          setItem: (k, v) => { bag[k] = String(v); },
        };
      })();
      const saved = DesktopTemplate.saveTemplate({
        timeframe: '1h',
        indicators: ['rsi', 'hma:55'],
        style: { downColor: '#abcdef', macd: { area: false } },
      }, mem);
      const loaded = DesktopTemplate.loadTemplate(mem);
      return {
        key: DesktopTemplate.TEMPLATE_KEY,
        raw: JSON.parse(mem.getItem(DesktopTemplate.TEMPLATE_KEY)),
        savedInd: saved.indicators,
        loadedInd: loaded.indicators,
        loadedTf: loaded.timeframe,
        loadedDown: loaded.style.downColor,
        loadedArea: loaded.style.macd.area,
        loadedFill: loaded.style.macd.fill,
      };
    })()""")
    assert out["key"] == "desktop.chart-template.v1"
    assert out["raw"]["indicators"] == ["rsi", "hma:55"]
    assert out["savedInd"] == ["rsi", "hma:55"]
    assert out["loadedInd"] == ["rsi", "hma:55"]
    assert out["loadedTf"] == "1h"
    assert out["loadedDown"] == "#abcdef"
    assert out["loadedArea"] is False
    assert out["loadedFill"] is True


def test_apply_template_to_config_updates_indicators_keeps_instrument():
    out = _eval("""(() => {
      const open = {
        instrument: 'MES 09-26', root: 'MES',
        timeframe: '5m', type: 'candles',
        indicators: [],
        range: { id: '1m', days: 31, from: '', to: '' },
        aspect: 'auto',
        style: DesktopTemplate.cloneStyle(),
      };
      const tpl = DesktopTemplate.makeTemplateFromConfig({
        timeframe: '15m',
        indicators: ['vol', 'macd'],
        range: { id: '1d', days: 1, from: '', to: '' },
        aspect: 'square',
        style: { upColor: '#111111', macd: { vol: true } },
      });
      const next = DesktopTemplate.applyTemplateToConfig(open, tpl);
      // Mutating the template after apply must not leak into the chart config.
      tpl.indicators.push('rsi');
      tpl.style.macd.vol = false;
      return {
        instrument: next.instrument,
        root: next.root,
        timeframe: next.timeframe,
        indicators: next.indicators,
        rangeId: next.range.id,
        aspect: next.aspect,
        up: next.style.upColor,
        macdVol: next.style.macd.vol,
      };
    })()""")
    assert out["instrument"] == "MES 09-26"
    assert out["root"] == "MES"
    assert out["timeframe"] == "15m"
    assert out["indicators"] == ["vol", "macd"]
    assert out["rangeId"] == "1d"
    assert out["aspect"] == "square"
    assert out["up"] == "#111111"
    assert out["macdVol"] is True


def test_apply_template_to_all_windows_simulation():
    """Simulate the desktop apply-to-all loop over N open window configs."""
    out = _eval("""(() => {
      const windows = [
        { id: 'a', config: { instrument: 'MNQ 09-26', root: 'MNQ', timeframe: '5m', indicators: [], type: 'candles',
          range: { id: '1m', days: 31 }, aspect: 'auto', style: DesktopTemplate.cloneStyle() } },
        { id: 'b', config: { instrument: 'MES 09-26', root: 'MES', timeframe: '5m', indicators: ['vol'], type: 'candles',
          range: { id: '1m', days: 31 }, aspect: 'auto', style: DesktopTemplate.cloneStyle() } },
        { id: 'c', config: { instrument: 'MGC 08-26', root: 'MGC', timeframe: '1h', indicators: ['rsi'], type: 'candles',
          range: { id: '1w', days: 7 }, aspect: 'wide', style: DesktopTemplate.cloneStyle() } },
      ];
      const tpl = DesktopTemplate.makeTemplateFromConfig({
        timeframe: '15m',
        indicators: ['macd', 'ema:21'],
        range: { id: '1d', days: 1 },
        aspect: 'auto',
        style: { legendMode: 'full', macd: { fill: false } },
      });
      const applied = windows.map(w => {
        w.config = DesktopTemplate.applyTemplateToConfig(w.config, tpl);
        return {
          id: w.id,
          instrument: w.config.instrument,
          indicators: w.config.indicators.slice(),
          timeframe: w.config.timeframe,
          legend: w.config.style.legendMode,
          macdFill: w.config.style.macd.fill,
        };
      });
      // Each window must own its own indicators array.
      applied[0].indicators.push('vol');
      return {
        applied,
        bStill: windows[1].config.indicators,
        cInstrument: windows[2].config.instrument,
      };
    })()""")
    assert len(out["applied"]) == 3
    for row in out["applied"]:
        assert row["indicators"][:2] == ["macd", "ema:21"]
        assert row["timeframe"] == "15m"
        assert row["legend"] == "full"
        assert row["macdFill"] is False
    assert out["applied"][0]["instrument"] == "MNQ 09-26"
    assert out["applied"][1]["instrument"] == "MES 09-26"
    assert out["bStill"] == ["macd", "ema:21"]  # not polluted by push on window A
    assert out["cInstrument"] == "MGC 08-26"


def test_apply_to_all_continues_after_one_bad_window():
    """One broken config must not prevent the rest from receiving indicators."""
    out = _eval("""(() => {
      const windows = [
        { id: 'rty', config: { instrument: 'RTY 09-26', root: 'RTY', timeframe: '5m', indicators: [],
          range: { id: '1m', days: 31 }, style: DesktopTemplate.cloneStyle() } },
        { id: 'mes', config: { instrument: 'MES 09-26', root: 'MES', timeframe: '5m', indicators: [],
          range: { id: '1m', days: 31 }, style: DesktopTemplate.cloneStyle() } },
        { id: 'mnq', config: null },  // broken mid-list — must be skipped
        { id: 'm2k', config: { instrument: 'M2K 09-26', root: 'M2K', timeframe: '5m', indicators: [],
          range: { id: '1m', days: 31 }, style: DesktopTemplate.cloneStyle() } },
        { id: 'mym', config: { instrument: 'MYM 09-26', root: 'MYM', timeframe: '5m', indicators: [],
          range: { id: '1m', days: 31 }, style: DesktopTemplate.cloneStyle() } },
      ];
      const tpl = DesktopTemplate.makeTemplateFromConfig({ indicators: ['macd'], timeframe: '5m' });
      let applied = 0, failed = 0;
      windows.forEach(w => {
        try {
          if (!w.config) throw new Error('missing config');
          w.config = DesktopTemplate.applyTemplateToConfig(w.config, tpl);
          applied += 1;
        } catch (e) { failed += 1; }
      });
      return {
        applied, failed,
        indicators: windows.filter(w => w.config).map(w => ({ id: w.id, ind: w.config.indicators.slice() })),
      };
    })()""")
    assert out["applied"] == 4
    assert out["failed"] == 1
    assert all(row["ind"] == ["macd"] for row in out["indicators"])
    assert [row["id"] for row in out["indicators"]] == ["rty", "mes", "m2k", "mym"]


def test_normalize_rejects_non_array_indicators():
    out = _eval("""(() => {
      const tpl = DesktopTemplate.normalizeTemplate({ indicators: 'macd', timeframe: '4h' });
      return { indicators: tpl.indicators, timeframe: tpl.timeframe };
    })()""")
    assert out["indicators"] == []
    assert out["timeframe"] == "4h"


def test_empty_storage_loads_default():
    out = _eval("""(() => {
      const mem = { getItem: () => null, setItem: () => {} };
      const tpl = DesktopTemplate.loadTemplate(mem);
      return { indicators: tpl.indicators, timeframe: tpl.timeframe, type: tpl.type };
    })()""")
    assert out == {"indicators": [], "timeframe": "5m", "type": "candles"}

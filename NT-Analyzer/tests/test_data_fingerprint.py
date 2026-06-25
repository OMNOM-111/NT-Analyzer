"""historical_data_fingerprint tests.

Run from NT-Analyzer/ root:
    python -m tests.test_data_fingerprint
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import data_fingerprint as df  # noqa: E402

PASSED: List[str] = []
FAILED: List[Tuple[str, str]] = []


def case(name: str):
    def deco(fn):
        def wrap():
            tmp = Path(tempfile.mkdtemp(prefix="fp_test_"))
            try:
                fn(tmp)
                PASSED.append(name)
                print(f"  PASS  {name}")
            except Exception as e:
                FAILED.append((name, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
                print(f"  FAIL  {name}: {e}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        return wrap
    return deco


@case("fingerprint is real sha256 of bars and is reproducible")
def t01(tmp: Path) -> None:
    bars = [{"t": "2026-05-13T00:00:00Z", "o": 1, "h": 2, "l": 0, "c": 1, "v": 10},
            {"t": "2026-05-13T00:01:00Z", "o": 1, "h": 3, "l": 1, "c": 2, "v": 12}]
    raw = json.dumps(bars).encode("utf-8")
    (tmp / "bars.json").write_bytes(raw)
    fp = df.fingerprint_for_job(tmp)
    assert fp["method"] == "sha256_of_bars_json_artifact", fp
    assert fp["bar_count"] == 2, fp
    assert fp["value"] == "sha256:" + hashlib.sha256(raw).hexdigest(), fp
    # Reproducible.
    assert df.fingerprint_for_job(tmp)["value"] == fp["value"]


@case("different bars yield a different fingerprint")
def t02(tmp: Path) -> None:
    (tmp / "bars.json").write_text(json.dumps([{"c": 1}]), encoding="utf-8")
    a = df.fingerprint_for_job(tmp)["value"]
    (tmp / "bars.json").write_text(json.dumps([{"c": 2}]), encoding="utf-8")
    b = df.fingerprint_for_job(tmp)["value"]
    assert a != b, (a, b)


@case("missing bars -> explicit placeholder, never invented")
def t03(tmp: Path) -> None:
    fp = df.fingerprint_for_job(tmp)
    assert fp["method"] == "placeholder", fp
    assert fp["value"] == "sha256:placeholder", fp
    assert fp["source"] == "no_bars_artifact", fp


@case("backfill writes sidecar and flags placeholder run_hash")
def t04(tmp: Path) -> None:
    (tmp / "bars.json").write_text(json.dumps([{"c": 1}, {"c": 2}]), encoding="utf-8")
    (tmp / "result.json").write_text(json.dumps({
        "job_id": "JOB1", "run_hash": "sha256:abc",
        "context": {"historical_data_fingerprint": {"method": "placeholder", "value": "sha256:placeholder"}},
    }), encoding="utf-8")
    side = df.backfill_job(tmp)
    assert side["job_id"] == "JOB1", side
    assert side["run_hash_includes_fingerprint"] is False, side
    assert side["historical_data_fingerprint"]["method"] == "sha256_of_bars_json_artifact", side
    written = json.loads((tmp / "data_fingerprint.json").read_text(encoding="utf-8"))
    assert written["historical_data_fingerprint"]["value"].startswith("sha256:"), written


@case("backfill recognizes a run_hash that already embeds a real fingerprint")
def t05(tmp: Path) -> None:
    (tmp / "bars.json").write_text(json.dumps([{"c": 1}]), encoding="utf-8")
    (tmp / "result.json").write_text(json.dumps({
        "job_id": "JOB2", "run_hash": "sha256:def",
        "context": {"historical_data_fingerprint": {"method": "sha256_of_primary_bar_series", "value": "sha256:real"}},
    }), encoding="utf-8")
    side = df.backfill_job(tmp)
    assert side["run_hash_includes_fingerprint"] is True, side


def main() -> int:
    for fn in (t01, t02, t03, t04, t05):
        fn()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for name, err in FAILED:
            print(f"\n--- {name} ---\n{err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

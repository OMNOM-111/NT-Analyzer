from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import validate_external_gpt_context  # noqa: E402


def test_external_gpt_context_pack_is_valid():
    result = validate_external_gpt_context.validate()
    assert result.errors == [], "external context pack errors: " + "; ".join(result.errors)
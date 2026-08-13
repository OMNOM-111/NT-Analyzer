from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import export_external_gpt_context  # noqa: E402


def test_export_external_gpt_context_preserves_user_files_and_recreates_managed_docs(tmp_path: Path):
    keep = tmp_path / "keep.txt"
    keep.write_text("do not remove", encoding="utf-8")

    result = export_external_gpt_context.export(tmp_path)
    assert result.output_dir == tmp_path
    assert result.exported_docs == export_external_gpt_context.EXPORT_DOCS
    assert (tmp_path / export_external_gpt_context.INFO_NAME).is_file()
    assert (tmp_path / export_external_gpt_context.MANIFEST_NAME).is_file()
    assert keep.read_text(encoding="utf-8") == "do not remove"

    damaged = tmp_path / export_external_gpt_context.EXPORT_DOCS[0]
    damaged.write_text("damaged", encoding="utf-8")

    export_external_gpt_context.export(tmp_path)

    assert keep.read_text(encoding="utf-8") == "do not remove"
    assert damaged.read_text(encoding="utf-8") == (
        export_external_gpt_context.SOURCE_DIR / export_external_gpt_context.EXPORT_DOCS[0]
    ).read_text(encoding="utf-8")
"""Freeze the old «AI агенты» registry, migrate its facts, reconcile both sides.

    python tools/legacy_registry_migrate.py            # freeze if needed, migrate, reconcile
    python tools/legacy_registry_migrate.py --report    # print the current state only
    python tools/legacy_registry_migrate.py --refreeze  # take a new archive as well

Nothing in the old registry is moved, edited or deleted: the archive is a
copy, and the migration reads the copy. The new registry becomes the single
working registry only if the reconciliation passes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai_control_center import legacy_migration  # noqa: E402
from app.ai_lab import legacy_archive  # noqa: E402


def _print(title, value):
    print(f"\n== {title} ==")
    print(json.dumps(value, ensure_ascii=False, indent=1))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="только показать текущее состояние")
    parser.add_argument("--refreeze", action="store_true", help="снять новый архив, даже если он уже есть")
    parser.add_argument("--note", default="перевод старого реестра «AI агенты» в архив")
    parser.add_argument("--data-root", default=None,
                        help="каталог данных, если запускаете не в профиле этой среды")
    args = parser.parse_args(argv)

    if args.data_root:
        # An operator naming the data root explicitly; the archive and the new
        # registry are written under it and nowhere else.
        root = Path(args.data_root).resolve()
        if not root.is_dir():
            print(f"каталог данных не найден: {root}")
            return 2
        named = SimpleNamespace(data_path=lambda *parts, project_root=None: root.joinpath(*[str(part) for part in parts]))
        legacy_archive.runtime_env = named
        legacy_migration.runtime_env = named
        print(f"каталог данных: {root}")

    if args.report:
        _print("состояние", legacy_migration.state())
        return 0

    existing = legacy_archive.latest()
    if existing and not args.refreeze:
        print(f"архив уже снят: {existing['archive_id']} ({existing['totals']['records']} записей)")
        manifest = existing
    else:
        manifest = legacy_archive.freeze(note=args.note)
        print(f"архив снят: {manifest['archive_id']} — файлов {manifest['totals']['files']}, "
              f"записей {manifest['totals']['records']}")

    checked = legacy_archive.verify(manifest["archive_id"])
    if not checked["ok"]:
        _print("целостность архива", checked)
        return 2

    _print("перенесено как история", legacy_migration.migrate(manifest["archive_id"]))
    report = legacy_migration.reconcile()
    _print("сверка", report)
    print("\nновый реестр рабочий:" if report["ok"] else "\nсверка не сошлась, новый реестр не включён:",
          legacy_migration.state()["authoritative"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""SQLite reader ownership must not leave disposable Windows files locked."""
import gc
import queue
import sqlite3
import threading
import weakref
import pytest
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository


def test_readers_close_when_collected_on_preview_cleanup_thread(tmp_path):
    path = tmp_path / 'agent-world.sqlite3'
    SQLiteAgentWorldRepository(path)
    handoff = queue.Queue()
    def request():
        repo = SQLiteAgentWorldRepository(path, read_only=True)
        with repo._transaction() as connection:
            assert connection.execute('PRAGMA application_id').fetchone()[0]
        handoff.put((repo, connection))
    worker = threading.Thread(target=request)
    worker.start(); worker.join(timeout=10)
    assert not worker.is_alive()
    repo, connection = handoff.get_nowait()
    ref = weakref.ref(repo)
    del repo
    gc.collect()
    assert ref() is None
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')
    path.unlink()  # Windows also confirms the OS handle was released.

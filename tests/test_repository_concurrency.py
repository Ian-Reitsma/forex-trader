from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from forex_trader.infrastructure.repository import SqliteDecisionRepository


def test_sqlite_repository_uses_long_busy_timeout_for_shared_runtime_database(tmp_path) -> None:
    repository = SqliteDecisionRepository(tmp_path / "runtime.db")
    try:
        row = repository._connection.execute("PRAGMA busy_timeout").fetchone()  # noqa: SLF001
        assert row is not None
        assert int(row[0]) == 30_000
    finally:
        repository.close()


def test_sqlite_repository_serializes_shared_connection_reads_and_writes(tmp_path) -> None:
    repository = SqliteDecisionRepository(tmp_path / "runtime.db")

    def round_trip(index: int) -> int:
        name = f"runtime-{index}"
        repository.set_runtime_state(name, {"index": index})
        payload = repository.runtime_state(name)
        assert payload is not None
        return int(payload["index"])

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(round_trip, range(64)))
        assert values == list(range(64))
    finally:
        repository.close()

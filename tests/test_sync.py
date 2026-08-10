from datetime import UTC, datetime, timedelta

from forex_trader.application.sync import BrokerStateSynchronizer
from forex_trader.infrastructure.repository import SqliteDecisionRepository


class FakeTransactionSource:
    def __init__(self) -> None:
        self.last = "10"
        self.backfilled = False

    def last_transaction_id(self) -> str:
        return self.last

    def transactions_between(self, start, end):  # type: ignore[no-untyped-def]
        assert start.tzinfo is not None and end.tzinfo is not None
        self.backfilled = True
        return [{"id": "8", "type": "ORDER_FILL"}, {"id": "9", "type": "DAILY_FINANCING"}]

    def transactions_since(self, transaction_id: str):  # type: ignore[no-untyped-def]
        assert transaction_id in {"10", "12", "13"}
        if transaction_id == "10":
            return ([{"id": "11", "type": "MARKET_ORDER"}, {"id": "12", "type": "ORDER_FILL"}], "12")
        if transaction_id == "12":
            return ([], "12")
        return ([], "13")

    def transaction_stream(self, *, max_events=None, include_heartbeats=False):  # type: ignore[no-untyped-def]
        assert include_heartbeats is True
        yield {"type": "HEARTBEAT", "lastTransactionID": "12"}
        yield {"id": "13", "type": "ORDER_FILL"}


def test_state_sync_bootstraps_with_history_then_catches_up_idempotently() -> None:
    repository = SqliteDecisionRepository(":memory:")
    source = FakeTransactionSource()
    sync = BrokerStateSynchronizer(source, repository)
    assert sync.bootstrap() == "10"
    assert source.backfilled is True
    assert [item["id"] for item in repository.broker_transactions()] == ["8", "9"]
    assert sync.catch_up() == 2
    assert repository.get_broker_cursor("oanda.transactions") == "12"
    assert sync.catch_up() == 0
    assert len(repository.broker_transactions()) == 4


def test_state_sync_stream_persists_events_and_cursor_without_heartbeat_gap() -> None:
    repository = SqliteDecisionRepository(":memory:")
    source = FakeTransactionSource()
    sync = BrokerStateSynchronizer(source, repository)
    assert sync.stream(max_events=2) == 1
    assert repository.get_broker_cursor("oanda.transactions") == "13"
    ids = [item["id"] for item in repository.broker_transactions()]
    assert ids == ["8", "9", "11", "12", "13"]


class HeartbeatGapSource(FakeTransactionSource):
    def transactions_since(self, transaction_id: str):  # type: ignore[no-untyped-def]
        if transaction_id == "10":
            return ([{"id": "11", "type": "MARKET_ORDER"}], "11")
        if transaction_id == "11":
            return ([{"id": "12", "type": "ORDER_FILL"}], "12")
        if transaction_id == "13":
            return ([], "13")
        return ([], transaction_id)

    def transaction_stream(self, *, max_events=None, include_heartbeats=False):  # type: ignore[no-untyped-def]
        yield {"type": "HEARTBEAT", "lastTransactionID": "12"}
        yield {"id": "13", "type": "ORDER_FILL"}


def test_heartbeat_rest_catchup_persists_transaction_created_before_stream_connect() -> None:
    repository = SqliteDecisionRepository(":memory:")
    source = HeartbeatGapSource()
    sync = BrokerStateSynchronizer(source, repository)
    sync.stream(max_events=2)
    ids = [item["id"] for item in repository.broker_transactions()]
    assert "12" in ids
    assert ids[-1] == "13"


class InvalidTimeRange(RuntimeError):
    status_code = 416


class NewPracticeAccountSource(FakeTransactionSource):
    def __init__(self) -> None:
        super().__init__()
        self.history_windows: list[tuple[datetime, datetime]] = []

    def transactions_between(self, start, end):  # type: ignore[no-untyped-def]
        self.history_windows.append((start, end))
        if len(self.history_windows) <= 2:
            raise InvalidTimeRange("INVALID_TIME_RANGE")
        return [{"id": "1", "type": "CREATE"}, {"id": "2", "type": "CLIENT_CONFIGURE"}]


def test_state_sync_skips_only_leading_pre_account_416_windows() -> None:
    repository = SqliteDecisionRepository(":memory:")
    source = NewPracticeAccountSource()
    sync = BrokerStateSynchronizer(source, repository, initial_history_days=800)

    assert sync.bootstrap() == "10"
    assert len(source.history_windows) == 3
    assert all(end - start <= timedelta(days=364) for start, end in source.history_windows)
    assert source.history_windows[-1][1] <= datetime.now(UTC)
    assert [item["id"] for item in repository.broker_transactions()] == ["1", "2"]


class LaterInvalidTimeRangeSource(NewPracticeAccountSource):
    def transactions_between(self, start, end):  # type: ignore[no-untyped-def]
        self.history_windows.append((start, end))
        if len(self.history_windows) == 1:
            return [{"id": "1", "type": "CREATE"}]
        raise InvalidTimeRange("unexpected later INVALID_TIME_RANGE")


def test_state_sync_fails_closed_on_416_after_valid_history_begins() -> None:
    repository = SqliteDecisionRepository(":memory:")
    source = LaterInvalidTimeRangeSource()
    sync = BrokerStateSynchronizer(source, repository, initial_history_days=500)

    try:
        sync.bootstrap()
    except InvalidTimeRange as exc:
        assert "unexpected later" in str(exc)
    else:
        raise AssertionError("later invalid time range must not be suppressed")

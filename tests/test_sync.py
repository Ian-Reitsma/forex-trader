from forex_trader.application.sync import BrokerStateSynchronizer
from forex_trader.infrastructure.repository import SqliteDecisionRepository


class FakeTransactionSource:
    def __init__(self) -> None:
        self.last = "10"

    def last_transaction_id(self) -> str:
        return self.last

    def transactions_since(self, transaction_id: str):  # type: ignore[no-untyped-def]
        assert transaction_id in {"10", "12"}
        if transaction_id == "10":
            return ([{"id": "11", "type": "MARKET_ORDER"}, {"id": "12", "type": "ORDER_FILL"}], "12")
        return ([], "12")

    def transaction_stream(self, *, max_events=None, include_heartbeats=False):  # type: ignore[no-untyped-def]
        assert include_heartbeats is True
        yield {"type": "HEARTBEAT", "lastTransactionID": "12"}
        yield {"id": "13", "type": "ORDER_FILL"}


def test_state_sync_bootstraps_catches_up_and_is_idempotent() -> None:
    repository = SqliteDecisionRepository(":memory:")
    source = FakeTransactionSource()
    sync = BrokerStateSynchronizer(source, repository)
    assert sync.bootstrap() == "10"
    assert sync.catch_up() == 2
    assert repository.get_broker_cursor("oanda.transactions") == "12"
    assert sync.catch_up() == 0
    assert len(repository.broker_transactions()) == 2


def test_state_sync_stream_persists_events_and_cursor() -> None:
    repository = SqliteDecisionRepository(":memory:")
    source = FakeTransactionSource()
    sync = BrokerStateSynchronizer(source, repository)
    assert sync.stream(max_events=2) == 1
    assert repository.get_broker_cursor("oanda.transactions") == "13"
    assert repository.broker_transactions()[-1]["id"] == "13"

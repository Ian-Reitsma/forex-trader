from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from forex_trader.application.trading_economics_sync import _date_windows, sync_trading_economics_fundamentals
from forex_trader.domain.context import HealthState
from forex_trader.infrastructure.source_evidence_repository import SourceEvidenceRepository
from forex_trader.infrastructure.trading_repository import TradingRepository
from forex_trader.ingestion.official_sources import RawSourcePayload, SourceAuthority
from forex_trader.ingestion.trading_economics import (
    TRADING_ECONOMICS_SOURCE,
    TradingEconomicsApiError,
    TradingEconomicsCalendarClient,
    TradingEconomicsCalendarEvent,
    TradingEconomicsCalendarSnapshot,
    TradingEconomicsRateLimitedError,
    TradingEconomicsSettings,
    _parse_decimal,
    _parse_vendor_datetime,
    parse_calendar_event,
)


NOW = datetime(2026, 8, 10, 2, 0, tzinfo=UTC)


def _row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "CalendarId": "us-cpi-2026-08",
        "Country": "United States",
        "Category": "Inflation Rate",
        "Event": "CPI YoY",
        "Date": "2026-08-09T12:30:00",
        "ActualValue": 2.8,
        "ForecastValue": 2.7,
        "PreviousValue": 2.6,
        "Importance": 3,
        "Source": "U.S. Bureau of Labor Statistics",
        "SourceURL": "https://www.bls.gov/",
    }
    row.update(changes)
    return row


def _event(**changes: object) -> TradingEconomicsCalendarEvent:
    values: dict[str, object] = {
        "event_id": "us-cpi-2026-08",
        "country": "United States",
        "currency": "USD",
        "indicator": "CPI YoY",
        "category": "inflation",
        "scheduled_at": NOW - timedelta(hours=2),
        "actual": Decimal("2.8"),
        "forecast": Decimal("2.7"),
        "previous": Decimal("2.6"),
        "importance": Decimal("1"),
        "raw_importance": 3,
        "higher_is_positive": False,
        "vendor_source": "BLS",
        "vendor_source_url": "https://www.bls.gov/",
    }
    values.update(changes)
    return TradingEconomicsCalendarEvent(**values)  # type: ignore[arg-type]


def _payload(at: datetime = NOW, body: bytes = b"[]") -> RawSourcePayload:
    return RawSourcePayload.create(
        descriptor=TRADING_ECONOMICS_SOURCE,
        url="https://api.tradingeconomics.com/calendar/country/United%20States/2026-08-10/2026-08-10?values=true&f=json",
        body=body,
        content_type="application/json",
        retrieved_at=at,
        published_at=at,
        available_at=at,
    )


def test_settings_validate_security_bounds_countries_and_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    TradingEconomicsSettings(api_key="client:secret").validate()
    invalid = [
        (TradingEconomicsSettings(), "API_KEY"),
        (TradingEconomicsSettings(api_key="x", base_url="https://evil.example"), "locked"),
        (TradingEconomicsSettings(api_key="x", timeout_seconds=0), "TIMEOUT"),
        (TradingEconomicsSettings(api_key="x", history_days=91), "HISTORY"),
        (TradingEconomicsSettings(api_key="x", window_days=0), "WINDOW"),
        (TradingEconomicsSettings(api_key="x", minimum_importance=4), "MIN_IMPORTANCE"),
        (TradingEconomicsSettings(api_key="x", auth_mode="basic"), "AUTH_MODE"),
        (TradingEconomicsSettings(api_key="x", maximum_payload_bytes=0), "MAX_PAYLOAD"),
        (TradingEconomicsSettings(api_key="x", countries=()), "COUNTRIES"),
        (TradingEconomicsSettings(api_key="x", countries=("United States?c=secret",)), "COUNTRIES"),
    ]
    for settings, match in invalid:
        with pytest.raises(ValueError, match=match):
            settings.validate()

    monkeypatch.setenv("TRADING_ECONOMICS_API_KEY", "abc:def")
    monkeypatch.setenv("TRADING_ECONOMICS_HISTORY_DAYS", "14")
    monkeypatch.setenv("TRADING_ECONOMICS_WINDOW_DAYS", "5")
    monkeypatch.setenv("TRADING_ECONOMICS_MIN_IMPORTANCE", "3")
    monkeypatch.setenv("TRADING_ECONOMICS_AUTO_REFRESH", "false")
    monkeypatch.setenv("TRADING_ECONOMICS_AUTH_MODE", "query")
    monkeypatch.setenv("TRADING_ECONOMICS_COUNTRIES", "United States, Canada")
    loaded = TradingEconomicsSettings.from_env()
    assert loaded.api_key == "abc:def"
    assert loaded.history_days == 14
    assert loaded.window_days == 5
    assert loaded.minimum_importance == 3
    assert loaded.auto_refresh is False
    assert loaded.auth_mode == "query"
    assert loaded.countries == ("United States", "Canada")


def test_parse_calendar_event_classifies_currency_direction_and_numeric_values() -> None:
    event, reason = parse_calendar_event(_row(), observed_at=NOW, minimum_importance=2)
    assert reason is None
    assert event is not None
    assert event.currency == "USD"
    assert event.category == "inflation"
    assert event.actual == Decimal("2.8")
    assert event.forecast == Decimal("2.7")
    assert event.previous == Decimal("2.6")
    assert event.importance == Decimal("1.00")
    assert event.higher_is_positive is False
    assert event.source_key == "trading_economics:us-cpi-2026-08"
    assert event.scheduled_at == datetime(2026, 8, 9, 12, 30, tzinfo=UTC)

    policy, _ = parse_calendar_event(
        _row(
            CalendarId="boe",
            Country="United Kingdom",
            Category="Interest Rate",
            Event="BoE Interest Rate Decision",
            ActualValue=None,
            ForecastValue=None,
            PreviousValue=None,
            Actual="4.00%",
            Forecast="3.75%",
            Previous="3.75%",
            Importance=2,
        ),
        observed_at=NOW,
    )
    assert policy is not None
    assert policy.currency == "GBP"
    assert policy.category == "policy"
    assert policy.higher_is_positive is True
    assert policy.importance == Decimal("0.75")

    labor, _ = parse_calendar_event(
        _row(
            CalendarId="ca-jobs",
            Country="Canada",
            Category="Labour",
            Event="Unemployment Rate",
            ActualValue="6.5",
            ForecastValue="6.4",
            PreviousValue="6.3",
        ),
        observed_at=NOW,
    )
    assert labor is not None
    assert labor.currency == "CAD"
    assert labor.category == "labor"
    assert labor.higher_is_positive is False

    growth, _ = parse_calendar_event(
        _row(
            CalendarId="au-gdp",
            Country="Australia",
            Category="GDP Growth Rate",
            Event="GDP Growth Rate QoQ",
            ActualValue="0.5",
            ForecastValue="0.4",
            PreviousValue="0.3",
        ),
        observed_at=NOW,
    )
    assert growth is not None
    assert growth.currency == "AUD"
    assert growth.category == "growth"
    assert growth.higher_is_positive is True


def test_parse_calendar_event_rejects_ineligible_or_incomplete_rows() -> None:
    cases = [
        (_row(Country="Atlantis", Currency=""), "unsupported_currency"),
        (_row(Event="", Category=""), "missing_indicator"),
        (_row(Event="Ceremonial Holiday", Category="Holiday"), "unclassified_indicator"),
        (_row(Date="bad"), "invalid_schedule"),
        (_row(Date="2026-08-11T12:00:00"), "not_released"),
        (_row(Importance=1), "low_importance"),
        (_row(ActualValue=None, Actual=""), "missing_actual"),
        (_row(ForecastValue=None, Forecast=""), "missing_forecast"),
        (_row(PreviousValue=None, Previous=""), "missing_previous"),
    ]
    for row, expected in cases:
        event, reason = parse_calendar_event(row, observed_at=NOW, minimum_importance=2)
        assert event is None
        assert reason == expected
    with pytest.raises(ValueError, match="timezone"):
        parse_calendar_event(_row(), observed_at=datetime(2026, 8, 10), minimum_importance=2)


def test_parser_supports_explicit_currency_fallback_identity_and_scaled_numbers() -> None:
    row = _row(
        CalendarId="",
        Country="China",
        Currency="CNY",
        Event="Industrial Production YoY",
        Category="Industrial Production",
        ActualValue=None,
        ForecastValue=None,
        PreviousValue=None,
        Actual="1.2M",
        Forecast="1.1M",
        Previous="900K",
    )
    event, reason = parse_calendar_event(row, observed_at=NOW)
    assert reason is None
    assert event is not None
    assert event.currency == "CNH"
    assert len(event.event_id) == 32
    assert event.actual == Decimal("1200000")
    assert event.forecast == Decimal("1100000")
    assert event.previous == Decimal("900000")
    assert _parse_decimal("$1.25B") == Decimal("1250000000.00")
    assert _parse_decimal("n/a") is None
    assert _parse_decimal(True) is None
    assert _parse_decimal("not-a-number") is None
    assert _parse_vendor_datetime("2026-08-10T01:00:00Z") == datetime(2026, 8, 10, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        _parse_vendor_datetime(None)


def test_calendar_client_uses_documented_header_auth_date_range_and_numeric_mode() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("Authorization", "")
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[_row()], headers={"content-type": "application/json; charset=utf-8"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    settings = TradingEconomicsSettings(
        api_key="client:secret",
        history_days=1,
        countries=("United States", "United Kingdom"),
    )
    snapshot = TradingEconomicsCalendarClient(settings, client=http).fetch_calendar(
        date(2026, 8, 9), date(2026, 8, 10), retrieved_at=NOW
    )
    assert seen["authorization"] == "client:secret"
    assert "client:secret" not in seen["url"]
    assert "/calendar/country/United%20States,United%20Kingdom/2026-08-09/2026-08-10" in seen["url"]
    assert "values=true" in seen["url"]
    assert "f=json" in seen["url"]
    assert snapshot.payload.authority is SourceAuthority.LICENSED
    assert snapshot.payload.source_id == "trading_economics"
    assert snapshot.rows_received == 1
    assert len(snapshot.events) == 1
    assert snapshot.skipped == {}
    http.close()


def test_calendar_client_query_auth_sanitizes_persisted_url_and_tracks_skips() -> None:
    seen_url = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx.Response(200, json=[_row(), "bad", _row(Importance=1)])

    http = httpx.Client(transport=httpx.MockTransport(handler))
    settings = TradingEconomicsSettings(
        api_key="query-secret",
        auth_mode="query",
        history_days=1,
        countries=("United States",),
    )
    snapshot = TradingEconomicsCalendarClient(settings, client=http).fetch_calendar(
        date(2026, 8, 9), date(2026, 8, 10), retrieved_at=NOW
    )
    assert "query-secret" in seen_url
    assert "query-secret" not in snapshot.payload.url
    assert "c=" not in snapshot.payload.url
    assert "values=true" in snapshot.payload.url
    assert snapshot.skipped == {"non_object": 1, "low_importance": 1}
    http.close()


def test_calendar_client_fails_closed_for_transport_status_shape_and_size() -> None:
    base_settings = TradingEconomicsSettings(api_key="top-secret", history_days=1, countries=("United States",))

    def transport_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("boom", request=request)

    http = httpx.Client(transport=httpx.MockTransport(transport_failure))
    with pytest.raises(TradingEconomicsApiError, match="ReadTimeout"):
        TradingEconomicsCalendarClient(base_settings, client=http).fetch_calendar(
            date(2026, 8, 10), date(2026, 8, 10)
        )
    http.close()

    for status in (409, 429):
        http = httpx.Client(transport=httpx.MockTransport(lambda request, status=status: httpx.Response(status, text="limited")))
        with pytest.raises(TradingEconomicsRateLimitedError, match="rate limited"):
            TradingEconomicsCalendarClient(base_settings, client=http).fetch_calendar(
                date(2026, 8, 10), date(2026, 8, 10), retrieved_at=NOW
            )
        http.close()

    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401, text="bad top-secret credential")))
    with pytest.raises(TradingEconomicsApiError, match=r"\[REDACTED\]"):
        TradingEconomicsCalendarClient(base_settings, client=http).fetch_calendar(
            date(2026, 8, 10), date(2026, 8, 10), retrieved_at=NOW
        )
    http.close()

    malformed = [
        (httpx.Response(200, content=b"not-json", headers={"content-type": "application/json"}), "valid JSON"),
        (httpx.Response(200, json={"wrong": []}), "JSON list"),
    ]
    for response, match in malformed:
        http = httpx.Client(transport=httpx.MockTransport(lambda request, response=response: response))
        with pytest.raises(TradingEconomicsApiError, match=match):
            TradingEconomicsCalendarClient(base_settings, client=http).fetch_calendar(
                date(2026, 8, 10), date(2026, 8, 10), retrieved_at=NOW
            )
        http.close()

    tiny_settings = TradingEconomicsSettings(
        api_key="x", history_days=1, maximum_payload_bytes=5, countries=("United States",)
    )
    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"[123456789]")))
    with pytest.raises(TradingEconomicsApiError, match="maximum size"):
        TradingEconomicsCalendarClient(tiny_settings, client=http).fetch_calendar(
            date(2026, 8, 10), date(2026, 8, 10), retrieved_at=NOW
        )
    http.close()

    with pytest.raises(ValueError, match="precede"):
        http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])))
        try:
            TradingEconomicsCalendarClient(base_settings, client=http).fetch_calendar(
                date(2026, 8, 11), date(2026, 8, 10)
            )
        finally:
            http.close()


def test_calendar_client_rejects_response_host_escape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        request.url = httpx.URL("https://evil.example/calendar")
        return httpx.Response(200, json=[])

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(TradingEconomicsApiError, match="escaped"):
        TradingEconomicsCalendarClient(
            TradingEconomicsSettings(api_key="x", countries=("United States",)), client=http
        ).fetch_calendar(date(2026, 8, 10), date(2026, 8, 10), retrieved_at=NOW)
    http.close()


def test_sync_is_prospective_idempotent_preserves_event_age_and_records_health(tmp_path) -> None:
    database = tmp_path / "trading.db"
    event = _event()

    class FakeCalendar:
        def __init__(self, settings: TradingEconomicsSettings) -> None:
            self.settings = settings

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, traceback):  # type: ignore[no-untyped-def]
            return None

        def fetch_calendar(self, start, end, *, retrieved_at=None):  # type: ignore[no-untyped-def]
            assert start == end == retrieved_at.date()
            return TradingEconomicsCalendarSnapshot(_payload(retrieved_at), (event,), 3, {"low_importance": 2})

    settings = TradingEconomicsSettings(api_key="x", history_days=1, window_days=1, countries=("United States",))
    first = sync_trading_economics_fundamentals(database, settings, as_of=NOW, client_factory=FakeCalendar)
    second = sync_trading_economics_fundamentals(
        database,
        settings,
        as_of=NOW + timedelta(hours=1),
        client_factory=FakeCalendar,
    )
    assert first.observations_inserted == 1
    assert first.observations_existing == 0
    assert first.raw_payloads_inserted == 1
    assert first.currencies == ("USD",)
    assert first.categories == {"inflation": 1}
    assert first.skipped == {"low_importance": 2}
    assert second.observations_inserted == 0
    assert second.observations_existing == 1

    observations = TradingRepository(database).macro_observations()
    assert len(observations) == 1
    assert observations[0].available_at == NOW
    assert observations[0].event_at == event.scheduled_at
    assert observations[0].source == event.source_key
    assert observations[0].actual == Decimal("2.8")
    health = SourceEvidenceRepository(database).latest_health(
        "trading_economics",
        as_of=NOW + timedelta(hours=1),
        maximum_age_seconds=Decimal("5"),
    )
    assert health.state is HealthState.HEALTHY
    assert "sync succeeded" in health.detail
    assert first.to_jsonable()["authority"] == "licensed"
    assert "event_at" in str(first.to_jsonable()["point_in_time_policy"])


def test_sync_records_rate_limit_and_unavailable_health(tmp_path) -> None:
    database = tmp_path / "health.db"
    settings = TradingEconomicsSettings(api_key="x", history_days=1, window_days=1, countries=("United States",))

    class LimitedCalendar:
        def __init__(self, settings: TradingEconomicsSettings) -> None:
            pass

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, traceback):  # type: ignore[no-untyped-def]
            return None

        def fetch_calendar(self, start, end, *, retrieved_at=None):  # type: ignore[no-untyped-def]
            raise TradingEconomicsRateLimitedError("409", status_code=409)

    with pytest.raises(TradingEconomicsRateLimitedError):
        sync_trading_economics_fundamentals(database, settings, as_of=NOW, client_factory=LimitedCalendar)
    limited = SourceEvidenceRepository(database).latest_health(
        "trading_economics", as_of=NOW, maximum_age_seconds=Decimal("60")
    )
    assert limited.state is HealthState.DEGRADED
    assert limited.rate_limited is True

    class BrokenCalendar(LimitedCalendar):
        def fetch_calendar(self, start, end, *, retrieved_at=None):  # type: ignore[no-untyped-def]
            raise TradingEconomicsApiError("broken", status_code=500)

    with pytest.raises(TradingEconomicsApiError):
        sync_trading_economics_fundamentals(database, settings, as_of=NOW, client_factory=BrokenCalendar)
    broken = SourceEvidenceRepository(database).latest_health(
        "trading_economics", as_of=NOW, maximum_age_seconds=Decimal("60")
    )
    assert broken.state is HealthState.UNAVAILABLE
    assert "TradingEconomicsApiError" in broken.detail


def test_date_windows_cover_range_without_overlap() -> None:
    assert _date_windows(date(2026, 8, 1), date(2026, 8, 10), 4) == (
        (date(2026, 8, 1), date(2026, 8, 4)),
        (date(2026, 8, 5), date(2026, 8, 8)),
        (date(2026, 8, 9), date(2026, 8, 10)),
    )
    with pytest.raises(ValueError, match="precede"):
        _date_windows(date(2026, 8, 2), date(2026, 8, 1), 1)
    with pytest.raises(ValueError, match="positive"):
        _date_windows(date(2026, 8, 1), date(2026, 8, 1), 0)

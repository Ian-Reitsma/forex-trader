from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx

from forex_trader.application.free_official_sync import sync_free_official_fundamentals
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.macro_history import MacroObservationKind, PointInTimeFundamentalBook
from forex_trader.infrastructure.source_evidence_repository import SourceEvidenceRepository
from forex_trader.infrastructure.trading_repository import TradingRepository
from forex_trader.ingestion.free_official import (
    BLS,
    OfficialCurrencySnapshot,
    OfficialIndicatorEvidence,
    OfficialWebClient,
    fetch_currency,
    supported_currencies,
)
from forex_trader.ingestion.official_sources import RawSourcePayload, SourceAuthority


NOW = datetime(2026, 8, 10, 11, 0, tzinfo=UTC)


def _response(request: httpx.Request, body: str, content_type: str = "text/html") -> httpx.Response:
    return httpx.Response(
        200,
        content=body.encode(),
        headers={"content-type": content_type},
        request=request,
    )


def _official_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url == "https://www.federalreserve.gov/monetarypolicy.htm":
        return _response(
            request,
            '<a href="/newsevents/pressreleases/monetary20260729a.htm">latest</a>'
            '<a href="/newsevents/pressreleases/monetary20260617a.htm">prior</a>',
        )
    if url.endswith("monetary20260729a.htm"):
        return _response(request, "target range for the federal funds rate at 3-1/2 to 3-3/4 percent")
    if url.endswith("monetary20260617a.htm"):
        return _response(request, "target range for the federal funds rate at 3-1/2 to 3-3/4 percent")
    if url == "https://www.bls.gov/news.release/cpi.t05.htm":
        return _response(
            request,
            "<table><tr><td>May 2026</td><td>0.6</td><td>0.6</td><td>4.0</td><td>4.2</td></tr>"
            "<tr><td>June 2026</td><td>-0.3</td><td>-0.3</td><td>3.4</td><td>3.5</td></tr></table>",
        )
    if "key-ecb-interest-rates" in url:
        return _response(request, "Deposit facility 17 June 2026 2.25 %")
    if "data-api.ecb.europa.eu/service/data/HICP" in url:
        return _response(
            request,
            "TIME_PERIOD,OBS_VALUE\n2026-05,3.2\n2026-06,2.8\n",
            "text/csv",
        )
    if "Bank-Rate.asp" in url:
        return _response(
            request,
            "<table><tr><td>18 Dec 25</td><td>3.75</td></tr>"
            "<tr><td>07 Aug 25</td><td>4.00</td></tr></table>",
        )
    if "/consumerpriceinflation/latest" in url:
        return _response(
            request,
            "The Consumer Prices Index (CPI) rose by 2.6% in the 12 months to June 2026, "
            "down from 2.8% the previous month.",
        )
    if url.endswith("/state_2026/index.htm"):
        return _response(request, "<table><tr><td>June 16, 2026</td><td>Change in the Guideline</td></tr></table>")
    if url.endswith("/state_2026/k260616a.htm"):
        return _response(
            request,
            "The Bank will encourage the uncollateralized overnight call rate to remain at around 0.75 percent.",
        )
    if url == "https://www.stat.go.jp/english/":
        return _response(request, "Consumer Price Index 1.5% May 2026 change over the year")
    if url.endswith("/monetary-policy/decisions"):
        return _response(
            request,
            '<a href="/en/publications/communication/press-releases-restricted/pre_20260618">June decision</a>',
        )
    if url.endswith("/pre_20260618"):
        return _response(
            request,
            "Swiss National Bank leaves SNB policy rate unchanged at 0%. "
            "Inflation has risen in recent months, from 0.1% in February to 0.6% in May.",
        )
    if url.endswith("/rates/indicators/key-variables/"):
        return _response(
            request,
            "<table>"
            "<tr><td>2026-05</td><td>1-3</td><td>3.2</td><td>2.0</td><td>2.1</td><td>2.7</td><td>3.0</td><td>--</td><td>2.06</td><td>113.46</td><td>7.1</td><td>7.0</td><td>6.0</td><td>2.25</td><td>2.2422</td></tr>"
            "<tr><td>2026-06</td><td>1-3</td><td>2.8</td><td>1.8</td><td>1.9</td><td>2.6</td><td>3.3</td><td>--</td><td>2.04</td><td>111.48</td><td>--</td><td>--</td><td>--</td><td>2.25</td><td>2.2875</td></tr>"
            "</table>",
        )
    if url == "https://www.rba.gov.au/statistics/cash-rate/":
        return _response(
            request,
            "<table><tr><td>6 May 2026</td><td>+0.25</td><td>4.35</td></tr>"
            "<tr><td>17 Jun 2026</td><td>0.00</td><td>4.35</td></tr></table>",
        )
    if url == "https://www.rba.gov.au/inflation/measures-cpi.html":
        return _response(
            request,
            "<table><tr><td>2026</td></tr><tr><td>May</td><td>4.0</td></tr>"
            "<tr><td>June</td><td>3.8</td></tr></table>",
        )
    if url.endswith("/the-official-cash-rate"):
        return _response(request, "Official Cash Rate 2.5 % Updated: 2:00pm, 08 Jul 2026")
    if url.endswith("/statistics/series/economic-indicators/prices"):
        return _response(
            request,
            "<table><tr><td>Mar 2026</td><td>1339</td><td>0.9</td><td>3.1</td></tr>"
            "<tr><td>Jun 2026</td><td>1359</td><td>1.5</td><td>4.1</td></tr></table>",
        )
    raise AssertionError(f"unexpected URL: {url}")


def test_all_supported_free_official_sources_emit_policy_and_inflation() -> None:
    assert supported_currencies() == ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD")
    http = httpx.Client(transport=httpx.MockTransport(_official_handler))
    try:
        with OfficialWebClient(client=http) as client:
            for currency in supported_currencies():
                snapshot = fetch_currency(currency, client, retrieved_at=NOW)
                assert snapshot.currency == currency
                assert {item.category for item in snapshot.indicators} == {"policy", "inflation"}
                assert len(snapshot.indicators) == 2
                assert snapshot.payloads
                assert all(item.authority is SourceAuthority.OFFICIAL for item in snapshot.payloads)
    finally:
        http.close()


def test_policy_plus_inflation_can_clear_existing_gate_for_monthly_cycle() -> None:
    book = FundamentalBook()
    for currency in ("EUR", "USD"):
        book.apply_indicator(
            currency=currency,
            category="policy",
            actual=Decimal("2.5"),
            previous=None,
            higher_is_positive=True,
            observed_at=NOW,
            source_confidence=Decimal("1"),
        )
        book.apply_indicator(
            currency=currency,
            category="inflation",
            actual=Decimal("2.8"),
            previous=Decimal("3.2"),
            higher_is_positive=False,
            observed_at=NOW,
            source_confidence=Decimal("1"),
        )
    assessment = book.assess_pair("EUR_USD", as_of=NOW + timedelta(days=29))
    assert assessment.confidence >= Decimal("0.50")


def test_policy_alone_cannot_clear_existing_gate() -> None:
    book = FundamentalBook()
    for currency in ("EUR", "USD"):
        book.apply_indicator(
            currency=currency,
            category="policy",
            actual=Decimal("2.5"),
            previous=None,
            higher_is_positive=True,
            observed_at=NOW,
            source_confidence=Decimal("1"),
        )
    assert book.assess_pair("EUR_USD", as_of=NOW).confidence < Decimal("0.50")


def _payload() -> RawSourcePayload:
    return RawSourcePayload.create(
        descriptor=BLS,
        url="https://www.bls.gov/cpi/",
        body=b"official",
        content_type="text/plain",
        retrieved_at=NOW,
        published_at=NOW,
        available_at=NOW,
    )


def _sync_fetcher(currency: str, client: OfficialWebClient, observed: datetime) -> OfficialCurrencySnapshot:
    del client, observed
    return OfficialCurrencySnapshot(
        currency,
        (_payload(),),
        (
            OfficialIndicatorEvidence(
                "bls",
                f"{currency.lower()}_policy",
                currency,
                "policy",
                Decimal("2"),
                None,
                True,
                "2026-08",
            ),
            OfficialIndicatorEvidence(
                "bls",
                f"{currency.lower()}_inflation",
                currency,
                "inflation",
                Decimal("3"),
                Decimal("2.5"),
                False,
                "2026-07",
            ),
        ),
    )


def test_free_official_sync_is_durable_point_in_time_and_idempotent(tmp_path) -> None:
    database = tmp_path / "official.db"
    first = sync_free_official_fundamentals(
        database,
        as_of=NOW,
        currencies=("USD", "EUR"),
        fetcher=_sync_fetcher,
    )
    second = sync_free_official_fundamentals(
        database,
        as_of=NOW,
        currencies=("USD", "EUR"),
        fetcher=_sync_fetcher,
    )
    assert first.observations_inserted == 4
    assert second.observations_inserted == 0
    assert second.observations_existing == 4
    observations = TradingRepository(database).macro_observations()
    assert len(observations) == 4
    assert all(item.kind is MacroObservationKind.INDICATOR for item in observations)
    assert all(item.forecast is None for item in observations)
    assert all(item.available_at == NOW for item in observations)
    book = PointInTimeFundamentalBook(observations)
    assert book.assess_pair("EUR_USD", as_of=NOW - timedelta(seconds=1)).confidence == 0
    assert book.assess_pair("EUR_USD", as_of=NOW).confidence >= Decimal("0.50")
    health = SourceEvidenceRepository(database).latest_health(
        "free_official_usd",
        as_of=NOW,
        maximum_age_seconds=Decimal("60"),
    )
    assert health is not None
    assert health.state.value == "healthy"

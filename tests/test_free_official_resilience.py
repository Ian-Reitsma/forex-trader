from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from forex_trader.application.free_official_sync import sync_free_official_fundamentals
from forex_trader.ingestion.free_official import (
    FreeOfficialSourceError,
    OfficialCurrencySnapshot,
    OfficialIndicatorEvidence,
)
from forex_trader.ingestion.free_official_resilient import (
    ResilientOfficialWebClient,
    fetch_currency_resilient,
)
from forex_trader.ingestion.official_sources import OFFICIAL_MACRO_SOURCES, RawSourcePayload


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _html(request: httpx.Request, body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/html"}, request=request)


def _csv(request: httpx.Request, rows: list[tuple[str, str]]) -> httpx.Response:
    body = "TIME_PERIOD,OBS_VALUE\n" + "".join(f"{period},{value}\n" for period, value in rows)
    return httpx.Response(200, text=body, headers={"content-type": "text/csv"}, request=request)


def _stats_nz_release_source(current: str, period: str) -> str:
    return (
        "<!doctype html><html><body><div id=\"app\"></div>"
        "<script type=\"application/json\">"
        '{"content":"The consumers price index (CPI) increased '
        f'{current} percent in the 12 months to the {period} quarter."}'
        "</script></body></html>"
    )


def test_usd_uses_unregistered_bls_v1_api_not_blocked_html_page() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        url = str(request.url)
        if url == "https://www.federalreserve.gov/monetarypolicy.htm":
            return _html(
                request,
                '<a href="/newsevents/pressreleases/monetary20260729a.htm">latest</a>'
                '<a href="/newsevents/pressreleases/monetary20260617a.htm">prior</a>',
            )
        if url.endswith("monetary20260729a.htm"):
            return _html(request, "target range for the federal funds rate at 3-1/2 to 3-3/4 percent")
        if url.endswith("monetary20260617a.htm"):
            return _html(request, "target range for the federal funds rate at 3-1/2 to 3-3/4 percent")
        if url == "https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0":
            assert request.method == "GET"
            return httpx.Response(
                200,
                json={
                    "status": "REQUEST_SUCCEEDED",
                    "Results": {
                        "series": [
                            {
                                "seriesID": "CUUR0000SA0",
                                "data": [
                                    {"year": "2026", "period": "M06", "value": "320.0"},
                                    {"year": "2026", "period": "M05", "value": "318.0"},
                                    {"year": "2025", "period": "M06", "value": "310.0"},
                                    {"year": "2025", "period": "M05", "value": "309.0"},
                                ],
                            }
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"unexpected request: {request.method} {url}")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with ResilientOfficialWebClient(client=http) as client:
            snapshot = fetch_currency_resilient("USD", client, retrieved_at=NOW)
    finally:
        http.close()
    assert {item.category for item in snapshot.indicators} == {"policy", "inflation"}
    inflation = next(item for item in snapshot.indicators if item.category == "inflation")
    assert inflation.series_id == "cpi_u_12m_from_index"
    assert inflation.reference == "2026-06"
    assert all("news.release/cpi" not in url for _, url in calls)
    assert any("/publicAPI/v1/" in url for _, url in calls)


def test_jpy_uses_bis_machine_readable_policy_and_cpi_series() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url.startswith("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.JP"):
            return _csv(request, [("2026-05", "0.50"), ("2026-06", "0.75")])
        if url.startswith("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_LONG_CPI/1.0/M.JP.771"):
            return _csv(request, [("2026-05", "2.5"), ("2026-06", "2.8")])
        raise AssertionError(f"unexpected request: {url}")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with ResilientOfficialWebClient(client=http) as client:
            snapshot = fetch_currency_resilient("JPY", client, retrieved_at=NOW)
    finally:
        http.close()
    policy = next(item for item in snapshot.indicators if item.category == "policy")
    inflation = next(item for item in snapshot.indicators if item.category == "inflation")
    assert policy.source_id == "bis"
    assert policy.actual == Decimal("0.75")
    assert policy.previous == Decimal("0.50")
    assert inflation.source_id == "bis"
    assert inflation.actual == Decimal("2.8")
    assert inflation.previous == Decimal("2.5")
    assert all("stat.go.jp" not in url for url in calls)
    assert all("boj.or.jp" not in url for url in calls)


def test_nzd_uses_two_published_stats_nz_release_sources_without_rendered_tables() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url.startswith("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.NZ"):
            return _csv(request, [("2026-06", "2.25"), ("2026-07", "2.50")])
        if url.endswith("consumers-price-index-june-2026-quarter/"):
            return _html(request, _stats_nz_release_source("4.1", "June 2026"))
        if url.endswith("consumers-price-index-march-2026-quarter/"):
            return _html(request, _stats_nz_release_source("3.1", "March 2026"))
        raise AssertionError(f"unexpected request: {url}")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with ResilientOfficialWebClient(client=http) as client:
            snapshot = fetch_currency_resilient("NZD", client, retrieved_at=NOW)
    finally:
        http.close()
    policy = next(item for item in snapshot.indicators if item.category == "policy")
    inflation = next(item for item in snapshot.indicators if item.category == "inflation")
    assert policy.source_id == "bis"
    assert policy.actual == Decimal("2.50")
    assert policy.previous == Decimal("2.25")
    assert inflation.source_id == "stats_nz"
    assert inflation.actual == Decimal("4.1")
    assert inflation.previous == Decimal("3.1")
    assert inflation.reference == "2026-06-01"
    assert len(snapshot.payloads) == 3
    assert all("rbnz.govt.nz" not in url for url in calls)
    assert any("june-2026" in url for url in calls)
    assert any("march-2026" in url for url in calls)


def test_stats_nz_release_probe_falls_back_only_on_404() -> None:
    before_march_release = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url.startswith("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.NZ"):
            return _csv(request, [("2026-02", "3.00"), ("2026-03", "2.75")])
        if url.endswith("consumers-price-index-march-2026-quarter/"):
            return httpx.Response(404, text="not yet published", request=request)
        if url.endswith("consumers-price-index-december-2025-quarter/"):
            return _html(request, _stats_nz_release_source("3.1", "December 2025"))
        if url.endswith("consumers-price-index-september-2025-quarter/"):
            return _html(request, _stats_nz_release_source("3.0", "September 2025"))
        raise AssertionError(f"unexpected request: {url}")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with ResilientOfficialWebClient(client=http) as client:
            snapshot = fetch_currency_resilient("NZD", client, retrieved_at=before_march_release)
    finally:
        http.close()
    inflation = next(item for item in snapshot.indicators if item.category == "inflation")
    assert inflation.actual == Decimal("3.1")
    assert inflation.previous == Decimal("3.0")
    assert any("march-2026" in url for url in calls)
    assert any("december-2025" in url for url in calls)
    assert any("september-2025" in url for url in calls)


def test_stats_nz_published_release_parser_failure_does_not_silently_use_stale_data() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url.startswith("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.NZ"):
            return _csv(request, [("2026-06", "2.25"), ("2026-07", "2.50")])
        if url.endswith("consumers-price-index-june-2026-quarter/"):
            return _html(request, "<html><body>published but unsupported payload</body></html>")
        if url.endswith("consumers-price-index-march-2026-quarter/"):
            return _html(request, _stats_nz_release_source("3.1", "March 2026"))
        raise AssertionError(f"unexpected request: {url}")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with ResilientOfficialWebClient(client=http) as client:
            with pytest.raises(FreeOfficialSourceError, match="June 2026 was not found"):
                fetch_currency_resilient("NZD", client, retrieved_at=NOW)
    finally:
        http.close()
    assert not any("march-2026" in url for url in calls)


def _payload(currency: str) -> RawSourcePayload:
    descriptor = OFFICIAL_MACRO_SOURCES["bls"]
    return RawSourcePayload.create(
        descriptor=descriptor,
        url="https://www.bls.gov/cpi/",
        body=currency.encode(),
        content_type="text/plain",
        retrieved_at=NOW,
        published_at=NOW,
        available_at=NOW,
    )


def test_partial_source_success_is_reported_degraded_not_healthy(tmp_path) -> None:
    def fetcher(currency: str, client, observed: datetime) -> OfficialCurrencySnapshot:  # type: ignore[no-untyped-def]
        del client, observed
        if currency == "JPY":
            raise RuntimeError("simulated source failure")
        return OfficialCurrencySnapshot(
            currency,
            (_payload(currency),),
            (
                OfficialIndicatorEvidence("bls", f"{currency}_policy", currency, "policy", Decimal("1"), None, True, "now"),
                OfficialIndicatorEvidence("bls", f"{currency}_inflation", currency, "inflation", Decimal("2"), Decimal("2.1"), False, "now"),
            ),
        )

    report = sync_free_official_fundamentals(
        tmp_path / "health.db",
        as_of=NOW,
        currencies=("USD", "JPY"),
        fetcher=fetcher,
    )
    assert report.healthy is False
    assert report.status == "degraded"
    assert report.to_jsonable()["status"] == "degraded"

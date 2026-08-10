from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from forex_trader.application.free_official_sync import sync_free_official_fundamentals
from forex_trader.ingestion.free_official import OfficialCurrencySnapshot, OfficialIndicatorEvidence
from forex_trader.ingestion.free_official_resilient import (
    ResilientOfficialWebClient,
    fetch_currency_resilient,
)
from forex_trader.ingestion.official_sources import OFFICIAL_MACRO_SOURCES, RawSourcePayload


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _html(request: httpx.Request, body: str, *, encoding: str = "utf-8") -> httpx.Response:
    return httpx.Response(
        200,
        content=body.encode(encoding),
        headers={"content-type": "text/html"},
        request=request,
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


def test_jpy_decodes_statistics_japan_cp932_national_cpi_page() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url.endswith("/en/statistics/boj/other/discount/discount.htm"):
            return _html(
                request,
                "<table>"
                "<tr><td>Dec. 22, 2025</td><td>1.00</td></tr>"
                "<tr><td>Jun. 17, 2026</td><td>1.25</td></tr>"
                "</table>",
            )
        if url == "https://www.stat.go.jp/data/cpi/sokuhou/tsuki/index-z.html":
            return _html(
                request,
                "<html><body>"
                "2020年基準 消費者物価指数 全国 2026年（令和8年）5月分 "
                "総合指数は2020年を100として113.5 前年同月比は1.5%の上昇 "
                "生鮮食品を除く総合指数は113.0 前年同月比は1.4％の上昇"
                "</body></html>",
                encoding="cp932",
            )
        raise AssertionError(f"unexpected request: {url}")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with ResilientOfficialWebClient(client=http) as client:
            snapshot = fetch_currency_resilient("JPY", client, retrieved_at=NOW)
    finally:
        http.close()
    policy = next(item for item in snapshot.indicators if item.category == "policy")
    inflation = next(item for item in snapshot.indicators if item.category == "inflation")
    assert policy.series_id == "basic_loan_rate"
    assert policy.actual == Decimal("1.25")
    assert policy.previous == Decimal("1.00")
    assert inflation.source_id == "statistics_japan"
    assert inflation.actual == Decimal("1.5")
    assert inflation.reference == "2026-05"
    assert not any("/mopo/mpmdeci/state_2026/k" in url for url in calls)


def test_nzd_uses_bis_policy_rate_and_stats_nz_cpi_without_rbnz_requests() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url.startswith("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.NZ"):
            return httpx.Response(
                200,
                text=(
                    "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\n"
                    "M,NZ,2026-04,3.25\n"
                    "M,NZ,2026-05,3.25\n"
                    "M,NZ,2026-06,2.50\n"
                    "M,NZ,2026-07,2.50\n"
                ),
                headers={"content-type": "text/csv;charset=UTF-8"},
                request=request,
            )
        if url == "https://www.stats.govt.nz/topics/consumers-price-index/":
            return _html(
                request,
                '<a href="/information-releases/consumers-price-index-march-2026-quarter/">March</a>'
                '<a href="/information-releases/consumers-price-index-june-2026-quarter/">June</a>',
            )
        if url == "https://www.stats.govt.nz/information-releases/consumers-price-index-june-2026-quarter/":
            return _html(
                request,
                "<table>"
                "<tr><th>Quarter</th><th>CPI all groups (quarterly)</th><th>CPI all groups (annual)</th></tr>"
                "<tr><td>Mar-26</td><td>0.9</td><td>3.1</td></tr>"
                "<tr><td>Jun-26</td><td>1.5</td><td>4.1</td></tr>"
                "</table>",
            )
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
    assert policy.previous == Decimal("3.25")
    assert inflation.source_id == "stats_nz"
    assert inflation.actual == Decimal("4.1")
    assert inflation.previous == Decimal("3.1")
    assert all("rbnz.govt.nz" not in url for url in calls)


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

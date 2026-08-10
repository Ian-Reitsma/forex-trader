from __future__ import annotations

import io
import json
import zipfile
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


def _html(request: httpx.Request, body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/html"}, request=request)


def _xlsx(rows: list[list[str | float]]) -> bytes:
    def cell(column: int, row: int, value: str | float) -> str:
        reference = f"{chr(ord('A') + column)}{row}"
        if isinstance(value, str):
            escaped = (
                value.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            return f'<c r="{reference}" t="inlineStr"><is><t>{escaped}</t></is></c>'
        return f'<c r="{reference}"><v>{value}</v></c>'

    sheet_rows = []
    for row_number, values in enumerate(rows, start=1):
        cells = "".join(cell(column, row_number, value) for column, value in enumerate(values))
        sheet_rows.append(f'<row r="{row_number}">{cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


def test_usd_uses_bls_public_api_not_blocked_html_page() -> None:
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
        if url == "https://api.bls.gov/publicAPI/v2/timeseries/data/":
            assert request.method == "POST"
            submitted = json.loads(request.content.decode())
            assert submitted["seriesid"] == ["CUUR0000SA0"]
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


def test_jpy_uses_maintained_boj_rate_table_instead_of_guessed_decision_url() -> None:
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
        if url == "https://www.stat.go.jp/english/":
            return _html(request, "Consumer Price Index 1.7% June 2026 change over the year")
        raise AssertionError(f"unexpected request: {url}")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with ResilientOfficialWebClient(client=http) as client:
            snapshot = fetch_currency_resilient("JPY", client, retrieved_at=NOW)
    finally:
        http.close()
    policy = next(item for item in snapshot.indicators if item.category == "policy")
    assert policy.series_id == "basic_loan_rate"
    assert policy.actual == Decimal("1.25")
    assert policy.previous == Decimal("1.00")
    assert not any("/mopo/mpmdeci/state_2026/k" in url for url in calls)


def test_nzd_uses_rbnz_automation_data_files() -> None:
    ocr = _xlsx(
        [
            ["Date", "Official Cash Rate (OCR)"],
            ["2026-04-01", 3.25],
            ["2026-07-09", 2.50],
            ["2026-07-23", 2.50],
        ]
    )
    cpi = _xlsx(
        [
            ["Date", "Index", "q/q%", "y/y%"],
            ["Mar 2026", 1339.0, 0.9, 3.1],
            ["Jun 2026", 1359.0, 1.5, 4.1],
        ]
    )
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url.endswith("/b/b2/hb2-daily-close.xlsx"):
            return httpx.Response(200, content=ocr, headers={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}, request=request)
        if url.endswith("/m/m1/hm1.xlsx"):
            return httpx.Response(200, content=cpi, headers={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}, request=request)
        raise AssertionError(f"unexpected request: {url}")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with ResilientOfficialWebClient(client=http) as client:
            snapshot = fetch_currency_resilient("NZD", client, retrieved_at=NOW)
    finally:
        http.close()
    policy = next(item for item in snapshot.indicators if item.category == "policy")
    inflation = next(item for item in snapshot.indicators if item.category == "inflation")
    assert policy.actual == Decimal("2.5")
    assert policy.previous == Decimal("3.25")
    assert inflation.actual == Decimal("4.1")
    assert inflation.previous == Decimal("3.1")
    assert all("/monetary-policy/" not in url for url in calls)
    assert all("/statistics/series/economic-indicators/prices" not in url for url in calls)


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

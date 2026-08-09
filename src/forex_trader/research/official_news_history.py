from __future__ import annotations

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

import httpx

from forex_trader.domain.macro_history import MacroObservation
from forex_trader.research.public_history import HistoricalNewsRecord


@dataclass(frozen=True, slots=True)
class OfficialFeedSpec:
    currency: str
    institution: str
    url: str
    source: str


_OFFICIAL_FEEDS: dict[str, OfficialFeedSpec] = {
    "USD": OfficialFeedSpec(
        currency="USD",
        institution="Federal Reserve Board",
        url="https://www.federalreserve.gov/feeds/press_monetary.xml",
        source="federal-reserve-monetary-policy-rss",
    ),
    "EUR": OfficialFeedSpec(
        currency="EUR",
        institution="European Central Bank",
        url="https://www.ecb.europa.eu/rss/press.html",
        source="ecb-official-rss",
    ),
    "GBP": OfficialFeedSpec(
        currency="GBP",
        institution="Bank of England",
        url="https://www.bankofengland.co.uk/rss/news",
        source="bank-of-england-official-rss",
    ),
    "JPY": OfficialFeedSpec(
        currency="JPY",
        institution="Bank of Japan",
        url="https://www.boj.or.jp/en/rss/whatsnew.xml",
        source="bank-of-japan-official-rss",
    ),
}

_RELEVANT_TERMS = (
    "monetary policy",
    "interest rate",
    "bank rate",
    "policy rate",
    "inflation",
    "prices",
    "economic activity",
    "economic outlook",
    "economy",
    "growth",
    "employment",
    "labour",
    "labor",
    "wage",
    "financial stability",
    "market operations",
    "minutes",
    "statement",
    "press conference",
    "speech",
    "testimony",
    "fomc",
    "mpc",
    "governing council",
    "policy board",
    "outlook report",
    "summary of opinions",
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def official_feed_specs(currencies: Iterable[str]) -> tuple[OfficialFeedSpec, ...]:
    normalized = tuple(sorted({currency.upper() for currency in currencies}))
    missing = [currency for currency in normalized if currency not in _OFFICIAL_FEEDS]
    if missing:
        raise ValueError(f"no official central-bank feed configured for: {', '.join(missing)}")
    return tuple(_OFFICIAL_FEEDS[currency] for currency in normalized)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", value))).strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, names: tuple[str, ...]) -> str:
    wanted = set(names)
    for child in element:
        if _local_name(child.tag) in wanted:
            return "".join(child.itertext()).strip()
    return ""


def _entry_link(element: ET.Element) -> str:
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
        text = "".join(child.itertext()).strip()
        if text:
            return text
    return ""


def _parse_feed_datetime(value: str) -> datetime:
    raw = value.strip()
    if not raw:
        raise ValueError("official feed entry is missing publication time")
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        pass
    candidates = (
        raw,
        raw.replace("Z", "+00:00"),
    )
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"unsupported official-feed timestamp: {value}")


def parse_official_feed(
    payload: bytes,
    *,
    spec: OfficialFeedSpec,
    start: datetime,
    end: datetime,
) -> tuple[HistoricalNewsRecord, ...]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("official feed range must be timezone-aware")
    if end <= start:
        raise ValueError("official feed range end must be after start")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f"{spec.institution} returned invalid RSS/Atom XML") from exc

    entries = [element for element in root.iter() if _local_name(element.tag) in {"item", "entry"}]
    records: list[HistoricalNewsRecord] = []
    for entry in entries:
        title = _clean_text(_child_text(entry, ("title",)))
        summary = _clean_text(_child_text(entry, ("description", "summary", "content")))
        published_raw = _child_text(entry, ("pubdate", "published", "updated", "date"))
        if not title or not published_raw:
            continue
        published = _parse_feed_datetime(published_raw)
        if published < start.astimezone(UTC) or published >= end.astimezone(UTC):
            continue
        combined = f"{title} {summary}".lower()
        if not any(term in combined for term in _RELEVANT_TERMS):
            continue
        link = _entry_link(entry)
        domain = urlparse(link or spec.url).netloc
        records.append(
            HistoricalNewsRecord(
                currency=spec.currency,
                seen_at=published,
                title=_clean_text(f"{title}. {summary}" if summary else title),
                url=link,
                domain=domain,
            )
        )
    unique: dict[tuple[datetime, str, str], HistoricalNewsRecord] = {}
    for record in records:
        unique[(record.seen_at, record.url, record.title)] = record
    return tuple(sorted(unique.values(), key=lambda item: (item.seen_at, item.url, item.title)))


class OfficialCentralBankHistoryClient:
    """Fetch low-request, first-party central-bank publication history.

    Each requested currency maps to the corresponding central bank's official
    RSS/news feed. Responses are cached verbatim. No syndicated news provider is
    required for the backtest and a missing official source fails closed.
    """

    def __init__(
        self,
        *,
        cache_dir: str | Path = ".cache/forex-trader/official-news",
        timeout_seconds: float = 30.0,
        retries: int = 4,
    ) -> None:
        if retries < 1:
            raise ValueError("retries must be positive")
        self.cache_dir = Path(cache_dir)
        self.timeout_seconds = timeout_seconds
        self.retries = retries

    async def records(
        self,
        currencies: Iterable[str],
        start: datetime,
        end: datetime,
    ) -> tuple[HistoricalNewsRecord, ...]:
        specs = official_feed_specs(currencies)
        timeout = httpx.Timeout(self.timeout_seconds)
        headers = {"User-Agent": "forex-trader-research/0.7.28"}
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
            chunks = await asyncio.gather(*(self._records_for_spec(client, spec, start, end) for spec in specs))
        values = [record for chunk in chunks for record in chunk]
        values.sort(key=lambda item: (item.seen_at, item.currency, item.url, item.title))
        return tuple(values)

    async def _records_for_spec(
        self,
        client: httpx.AsyncClient,
        spec: OfficialFeedSpec,
        start: datetime,
        end: datetime,
    ) -> tuple[HistoricalNewsRecord, ...]:
        cache_file = self.cache_dir / f"{spec.currency}-{start:%Y%m%d}-{end:%Y%m%d}.xml"
        if cache_file.exists():
            return parse_official_feed(cache_file.read_bytes(), spec=spec, start=start, end=end)
        response: httpx.Response | None = None
        for attempt in range(self.retries):
            try:
                response = await client.get(spec.url)
                response.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError):
                if attempt + 1 >= self.retries:
                    raise
                await asyncio.sleep(0.75 * (2**attempt))
        if response is None or not response.content:
            raise ValueError(f"{spec.institution} official feed returned no content")
        parsed = parse_official_feed(response.content, spec=spec, start=start, end=end)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(response.content)
        return parsed


def official_news_observations(
    records: Iterable[HistoricalNewsRecord],
    *,
    source_weight: Decimal = Decimal("0.90"),
) -> tuple[MacroObservation, ...]:
    if not Decimal("0") <= source_weight <= Decimal("1"):
        raise ValueError("source_weight must be in [0,1]")
    observations: list[MacroObservation] = []
    for record in records:
        identity = f"official-central-bank:{record.currency}:{record.seen_at.isoformat()}:{record.url}:{record.title}"
        observations.append(
            MacroObservation.news(
                currency=record.currency,
                headline=record.title,
                available_at=record.seen_at,
                source=f"official-central-bank:{record.domain or record.currency}",
                source_weight=source_weight,
                observation_id=uuid5(NAMESPACE_URL, identity),
            )
        )
    return tuple(sorted(observations, key=lambda item: (item.available_at, str(item.observation_id))))

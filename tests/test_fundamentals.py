from decimal import Decimal

from forex_trader.domain.fundamentals import FundamentalBook


def test_release_updates_currency_state() -> None:
    book = FundamentalBook()
    state = book.apply_release(
        currency="USD",
        category="labor",
        actual=Decimal("250"),
        forecast=Decimal("200"),
        previous=Decimal("180"),
        higher_is_positive=True,
        importance=Decimal("1"),
    )
    assert state.labor > 0
    assert state.confidence >= Decimal("0.8")


def test_negative_news_updates_sentiment() -> None:
    book = FundamentalBook()
    state = book.apply_news(
        currency="EUR",
        headline="Growth weak as activity contracts",
        source_weight=Decimal("1"),
    )
    assert state.news < 0


def test_pair_assessment_requires_both_currencies() -> None:
    book = FundamentalBook()
    book.apply_news(currency="EUR", headline="Growth strong")
    assessment = book.assess_pair("EUR_USD")
    assert assessment.confidence == 0
    assert "missing fundamental state" in assessment.reasons[0]

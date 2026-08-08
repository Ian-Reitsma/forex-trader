from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from forex_trader.intelligence.official_documents import DocumentTextChange, OfficialDocumentDiff


STANCE_RULESET_VERSION = "central-bank-statement-rules-v1"


class PolicyDimension(StrEnum):
    POLICY_RATE = "policy_rate"
    INFLATION = "inflation"
    LABOR = "labor"
    GROWTH = "growth"
    BALANCE_SHEET = "balance_sheet"
    FX = "fx"
    FINANCIAL_STABILITY = "financial_stability"


class StanceDirection(StrEnum):
    HAWKISH = "hawkish"
    DOVISH = "dovish"
    NEUTRAL = "neutral"
    CONTRADICTORY = "contradictory"


class EvidenceDisposition(StrEnum):
    SUPPORTED = "supported"
    AMBIGUOUS = "ambiguous"
    CONTRADICTORY = "contradictory"
    ABSTAINED = "abstained"


@dataclass(frozen=True, slots=True)
class StanceRule:
    rule_id: str
    phrase: str
    dimension: PolicyDimension
    direction: StanceDirection
    weight: Decimal

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.phrase.strip():
            raise ValueError("stance rule identity is required")
        if self.direction not in {StanceDirection.HAWKISH, StanceDirection.DOVISH}:
            raise ValueError("stance rule direction must be directional")
        if not Decimal("0") < self.weight <= Decimal("1"):
            raise ValueError("stance rule weight must be in (0,1]")


_RULES: tuple[StanceRule, ...] = (
    StanceRule("rate_raise_target", "raise the target range", PolicyDimension.POLICY_RATE, StanceDirection.HAWKISH, Decimal("1.0")),
    StanceRule("rate_increase_target", "increase the target range", PolicyDimension.POLICY_RATE, StanceDirection.HAWKISH, Decimal("1.0")),
    StanceRule("rate_hike", "rate hike", PolicyDimension.POLICY_RATE, StanceDirection.HAWKISH, Decimal("0.9")),
    StanceRule("rate_higher_longer", "higher for longer", PolicyDimension.POLICY_RATE, StanceDirection.HAWKISH, Decimal("0.9")),
    StanceRule("rate_restrictive", "restrictive stance", PolicyDimension.POLICY_RATE, StanceDirection.HAWKISH, Decimal("0.75")),
    StanceRule("rate_additional_firming", "additional firming", PolicyDimension.POLICY_RATE, StanceDirection.HAWKISH, Decimal("0.85")),
    StanceRule("rate_further_tightening", "further tightening", PolicyDimension.POLICY_RATE, StanceDirection.HAWKISH, Decimal("0.9")),
    StanceRule("rate_lower_target", "lower the target range", PolicyDimension.POLICY_RATE, StanceDirection.DOVISH, Decimal("1.0")),
    StanceRule("rate_reduce_target", "reduce the target range", PolicyDimension.POLICY_RATE, StanceDirection.DOVISH, Decimal("1.0")),
    StanceRule("rate_cut", "rate cut", PolicyDimension.POLICY_RATE, StanceDirection.DOVISH, Decimal("0.9")),
    StanceRule("rate_less_restrictive", "less restrictive", PolicyDimension.POLICY_RATE, StanceDirection.DOVISH, Decimal("0.8")),
    StanceRule("rate_policy_easing", "policy easing", PolicyDimension.POLICY_RATE, StanceDirection.DOVISH, Decimal("0.85")),
    StanceRule("inflation_elevated", "inflation remains elevated", PolicyDimension.INFLATION, StanceDirection.HAWKISH, Decimal("0.8")),
    StanceRule("inflation_somewhat_elevated", "inflation remains somewhat elevated", PolicyDimension.INFLATION, StanceDirection.HAWKISH, Decimal("0.8")),
    StanceRule("inflation_upside_risks", "upside risks to inflation", PolicyDimension.INFLATION, StanceDirection.HAWKISH, Decimal("0.9")),
    StanceRule("inflation_too_high", "inflation is too high", PolicyDimension.INFLATION, StanceDirection.HAWKISH, Decimal("0.9")),
    StanceRule("inflation_persistent", "persistent inflation", PolicyDimension.INFLATION, StanceDirection.HAWKISH, Decimal("0.75")),
    StanceRule("inflation_eased", "inflation has eased", PolicyDimension.INFLATION, StanceDirection.DOVISH, Decimal("0.75")),
    StanceRule("inflation_closer", "inflation has moved closer", PolicyDimension.INFLATION, StanceDirection.DOVISH, Decimal("0.7")),
    StanceRule("inflation_cooling", "inflation is cooling", PolicyDimension.INFLATION, StanceDirection.DOVISH, Decimal("0.75")),
    StanceRule("inflation_diminished", "inflation pressures have diminished", PolicyDimension.INFLATION, StanceDirection.DOVISH, Decimal("0.8")),
    StanceRule("labor_strong", "labor market remains strong", PolicyDimension.LABOR, StanceDirection.HAWKISH, Decimal("0.6")),
    StanceRule("labor_solid_gains", "job gains have remained solid", PolicyDimension.LABOR, StanceDirection.HAWKISH, Decimal("0.55")),
    StanceRule("labor_softened", "labor market has softened", PolicyDimension.LABOR, StanceDirection.DOVISH, Decimal("0.7")),
    StanceRule("labor_gains_slowed", "job gains have slowed", PolicyDimension.LABOR, StanceDirection.DOVISH, Decimal("0.7")),
    StanceRule("labor_downside_risks", "downside risks to employment", PolicyDimension.LABOR, StanceDirection.DOVISH, Decimal("0.85")),
    StanceRule("growth_slowed", "economic activity has slowed", PolicyDimension.GROWTH, StanceDirection.DOVISH, Decimal("0.65")),
    StanceRule("growth_downside_risks", "downside risks to growth", PolicyDimension.GROWTH, StanceDirection.DOVISH, Decimal("0.75")),
    StanceRule("balance_runoff", "balance sheet runoff", PolicyDimension.BALANCE_SHEET, StanceDirection.HAWKISH, Decimal("0.75")),
    StanceRule("balance_reduce_holdings", "reduce its holdings", PolicyDimension.BALANCE_SHEET, StanceDirection.HAWKISH, Decimal("0.7")),
    StanceRule("balance_end_runoff", "end balance sheet runoff", PolicyDimension.BALANCE_SHEET, StanceDirection.DOVISH, Decimal("0.85")),
    StanceRule("balance_asset_purchases", "asset purchases", PolicyDimension.BALANCE_SHEET, StanceDirection.DOVISH, Decimal("0.75")),
    StanceRule("fx_depreciation_inflation", "currency depreciation", PolicyDimension.FX, StanceDirection.HAWKISH, Decimal("0.45")),
    StanceRule("stability_tight_conditions", "tighter financial conditions", PolicyDimension.FINANCIAL_STABILITY, StanceDirection.HAWKISH, Decimal("0.4")),
)

_NEGATION_MARKERS = (
    "not",
    "no",
    "never",
    "neither",
    "without",
    "unlikely",
    "not appropriate",
    "not warranted",
    "no longer",
)
_UNCERTAINTY_MARKERS = (
    "may",
    "might",
    "could",
    "uncertain",
    "uncertainty",
    "possibly",
    "potentially",
    "appears",
    "seems",
)
_CONDITIONAL_MARKERS = (
    "if",
    "unless",
    "provided that",
    "subject to",
    "conditional on",
    "depending on",
    "depending upon",
)


@dataclass(frozen=True, slots=True)
class StanceEvidenceSpan:
    evidence_id: str
    change_side: str
    paragraph_index: int
    paragraph_sha256: str
    paragraph_text: str
    rule_id: str
    phrase: str
    start_char: int
    end_char: int
    dimension: PolicyDimension
    lexical_direction: StanceDirection
    effective_direction: StanceDirection
    weight: Decimal
    negated: bool
    uncertain: bool
    conditional: bool

    def __post_init__(self) -> None:
        if self.change_side not in {"added", "removed"}:
            raise ValueError("stance evidence change_side must be added or removed")
        if self.paragraph_index < 0 or self.start_char < 0 or self.end_char <= self.start_char:
            raise ValueError("stance evidence offsets are invalid")
        if self.end_char > len(self.paragraph_text):
            raise ValueError("stance evidence offsets exceed paragraph text")
        if self.paragraph_text[self.start_char : self.end_char].lower() != self.phrase.lower():
            raise ValueError("stance evidence offsets do not resolve to the matched phrase")
        if hashlib.sha256(self.paragraph_text.encode()).hexdigest() != self.paragraph_sha256:
            raise ValueError("stance evidence paragraph hash does not match paragraph text")
        if not Decimal("0") < self.weight <= Decimal("1"):
            raise ValueError("stance evidence weight must be in (0,1]")
        expected_id = _evidence_id(
            self.change_side,
            self.paragraph_sha256,
            self.rule_id,
            self.start_char,
            self.end_char,
        )
        if self.evidence_id != expected_id:
            raise ValueError("stance evidence ID does not match evidence provenance")

    @property
    def qualified(self) -> bool:
        return self.negated or self.uncertain or self.conditional

    @property
    def directional_weight(self) -> Decimal:
        if self.negated:
            return Decimal("0")
        multiplier = Decimal("0.5") if self.uncertain or self.conditional else Decimal("1")
        return self.weight * multiplier


@dataclass(frozen=True, slots=True)
class DimensionStanceEvidence:
    dimension: PolicyDimension
    direction: StanceDirection
    disposition: EvidenceDisposition
    hawkish_weight: Decimal
    dovish_weight: Decimal
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CentralBankStanceEvidence:
    research_only: bool
    execution_authority: bool
    ruleset_version: str
    family_id: str
    previous_version_id: str
    current_version_id: str
    direction: StanceDirection
    disposition: EvidenceDisposition
    evidence_quality: Decimal
    evidence_quality_is_probability: bool
    dimensions: tuple[DimensionStanceEvidence, ...]
    spans: tuple[StanceEvidenceSpan, ...]
    abstention_reason: str | None

    def __post_init__(self) -> None:
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("central-bank stance evidence must remain research-only with no execution authority")
        if self.evidence_quality_is_probability:
            raise ValueError("uncalibrated evidence quality cannot be labeled probability")
        if not Decimal("0") <= self.evidence_quality <= Decimal("1"):
            raise ValueError("evidence_quality must be in [0,1]")
        if self.disposition is EvidenceDisposition.ABSTAINED and not self.abstention_reason:
            raise ValueError("abstained stance evidence requires a reason")


def extract_central_bank_stance(diff: OfficialDocumentDiff) -> CentralBankStanceEvidence:
    spans: list[StanceEvidenceSpan] = []
    for change in (*diff.added, *diff.removed):
        spans.extend(_extract_change_spans(change))
    spans.sort(key=lambda item: (item.change_side, item.paragraph_index, item.start_char, item.rule_id))

    dimensions = tuple(
        summary
        for dimension in PolicyDimension
        if (summary := _summarize_dimension(dimension, spans)) is not None
    )
    overall_direction, disposition = _overall_stance(dimensions, spans)
    abstention_reason = None
    if disposition is EvidenceDisposition.ABSTAINED:
        abstention_reason = "no supported directional rule matched the source-backed document diff"
    quality = _evidence_quality(spans, disposition)
    return CentralBankStanceEvidence(
        research_only=True,
        execution_authority=False,
        ruleset_version=STANCE_RULESET_VERSION,
        family_id=diff.family_id,
        previous_version_id=diff.previous_version_id,
        current_version_id=diff.current_version_id,
        direction=overall_direction,
        disposition=disposition,
        evidence_quality=quality,
        evidence_quality_is_probability=False,
        dimensions=dimensions,
        spans=tuple(spans),
        abstention_reason=abstention_reason,
    )


def _extract_change_spans(change: DocumentTextChange) -> list[StanceEvidenceSpan]:
    if hashlib.sha256(change.text.encode()).hexdigest() != change.text_sha256:
        raise ValueError("document change hash does not match stance input text")
    lowered = change.text.lower()
    spans: list[StanceEvidenceSpan] = []
    for rule in _RULES:
        pattern = re.compile(rf"(?<!\w){re.escape(rule.phrase)}(?!\w)")
        for match in pattern.finditer(lowered):
            sentence = _sentence_context(lowered, match.start(), match.end())
            negated = _contains_marker_before(sentence, rule.phrase, _NEGATION_MARKERS)
            uncertain = _contains_any_marker(sentence, _UNCERTAINTY_MARKERS)
            conditional = _contains_any_marker(sentence, _CONDITIONAL_MARKERS)
            effective = _invert(rule.direction) if change.side == "removed" else rule.direction
            spans.append(
                StanceEvidenceSpan(
                    evidence_id=_evidence_id(
                        change.side,
                        change.text_sha256,
                        rule.rule_id,
                        match.start(),
                        match.end(),
                    ),
                    change_side=change.side,
                    paragraph_index=change.paragraph_index,
                    paragraph_sha256=change.text_sha256,
                    paragraph_text=change.text,
                    rule_id=rule.rule_id,
                    phrase=change.text[match.start() : match.end()],
                    start_char=match.start(),
                    end_char=match.end(),
                    dimension=rule.dimension,
                    lexical_direction=rule.direction,
                    effective_direction=effective,
                    weight=rule.weight,
                    negated=negated,
                    uncertain=uncertain,
                    conditional=conditional,
                )
            )
    return spans


def _summarize_dimension(
    dimension: PolicyDimension,
    spans: list[StanceEvidenceSpan],
) -> DimensionStanceEvidence | None:
    relevant = [item for item in spans if item.dimension is dimension]
    if not relevant:
        return None
    hawkish = sum(
        (item.directional_weight for item in relevant if item.effective_direction is StanceDirection.HAWKISH),
        Decimal("0"),
    )
    dovish = sum(
        (item.directional_weight for item in relevant if item.effective_direction is StanceDirection.DOVISH),
        Decimal("0"),
    )
    if hawkish > 0 and dovish > 0:
        direction = StanceDirection.CONTRADICTORY
        disposition = EvidenceDisposition.CONTRADICTORY
    elif hawkish > 0:
        direction = StanceDirection.HAWKISH
        disposition = EvidenceDisposition.AMBIGUOUS if all(item.qualified for item in relevant) else EvidenceDisposition.SUPPORTED
    elif dovish > 0:
        direction = StanceDirection.DOVISH
        disposition = EvidenceDisposition.AMBIGUOUS if all(item.qualified for item in relevant) else EvidenceDisposition.SUPPORTED
    else:
        direction = StanceDirection.NEUTRAL
        disposition = EvidenceDisposition.AMBIGUOUS
    return DimensionStanceEvidence(
        dimension=dimension,
        direction=direction,
        disposition=disposition,
        hawkish_weight=hawkish,
        dovish_weight=dovish,
        evidence_ids=tuple(item.evidence_id for item in relevant),
    )


def _overall_stance(
    dimensions: tuple[DimensionStanceEvidence, ...],
    spans: list[StanceEvidenceSpan],
) -> tuple[StanceDirection, EvidenceDisposition]:
    hawkish = sum((item.hawkish_weight for item in dimensions), Decimal("0"))
    dovish = sum((item.dovish_weight for item in dimensions), Decimal("0"))
    if hawkish > 0 and dovish > 0:
        return StanceDirection.CONTRADICTORY, EvidenceDisposition.CONTRADICTORY
    if hawkish == 0 and dovish == 0:
        if spans:
            return StanceDirection.NEUTRAL, EvidenceDisposition.AMBIGUOUS
        return StanceDirection.NEUTRAL, EvidenceDisposition.ABSTAINED
    direction = StanceDirection.HAWKISH if hawkish > 0 else StanceDirection.DOVISH
    contributing = [item for item in spans if item.directional_weight > 0]
    if contributing and all(item.qualified for item in contributing):
        return direction, EvidenceDisposition.AMBIGUOUS
    return direction, EvidenceDisposition.SUPPORTED


def _evidence_quality(spans: list[StanceEvidenceSpan], disposition: EvidenceDisposition) -> Decimal:
    if not spans:
        return Decimal("0")
    directional = [item for item in spans if item.directional_weight > 0]
    if not directional:
        return Decimal("0.10")
    total_weight = sum((item.directional_weight for item in directional), Decimal("0"))
    coverage = min(Decimal("1"), total_weight / Decimal("2"))
    qualified = sum(item.qualified for item in directional)
    qualification_factor = max(Decimal("0.35"), Decimal("1") - Decimal(qualified) * Decimal("0.15"))
    contradiction_factor = Decimal("0.55") if disposition is EvidenceDisposition.CONTRADICTORY else Decimal("1")
    return max(Decimal("0"), min(Decimal("1"), coverage * qualification_factor * contradiction_factor))


def _sentence_context(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind(";", 0, start), text.rfind("!", 0, start), text.rfind("?", 0, start))
    right_candidates = [position for marker in ".;!?" if (position := text.find(marker, end)) >= 0]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left + 1 : right]


def _contains_marker_before(sentence: str, phrase: str, markers: tuple[str, ...]) -> bool:
    phrase_index = sentence.find(phrase.lower())
    if phrase_index < 0:
        return False
    prefix = sentence[max(0, phrase_index - 96) : phrase_index]
    return _contains_any_marker(prefix, markers)


def _contains_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", lowered) is not None for marker in markers)


def _invert(direction: StanceDirection) -> StanceDirection:
    if direction is StanceDirection.HAWKISH:
        return StanceDirection.DOVISH
    if direction is StanceDirection.DOVISH:
        return StanceDirection.HAWKISH
    raise ValueError("only directional stance can be inverted")


def _evidence_id(change_side: str, paragraph_hash: str, rule_id: str, start: int, end: int) -> str:
    payload = f"{change_side}\n{paragraph_hash}\n{rule_id}\n{start}\n{end}".encode()
    return hashlib.sha256(payload).hexdigest()

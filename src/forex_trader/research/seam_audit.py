from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


COMPONENT_PATTERNS: Mapping[str, tuple[str, ...]] = {
    "fundamentals": (
        "fundamental",
        "macro",
        "currency_strength",
        "confidence",
        "policy",
        "inflation",
        "growth",
        "labor",
    ),
    "flow": (
        "flow",
        "tick_pressure",
        "relative_activity",
        "activity_proxy",
        "volume",
    ),
    "session": (
        "session",
        "rollover",
        "london",
        "new_york",
        "tokyo",
        "holiday",
    ),
    "zone_quality": (
        "zone_quality",
        "location_score",
        "zone",
        "location",
        "quality",
        "penetration",
        "touches",
    ),
    "retest": (
        "retest",
        "structure_shift",
        "sweep",
        "reclaim",
        "entry_confirmed",
    ),
}


@dataclass(frozen=True, slots=True)
class ProductionSeamCandidate:
    component: str
    module: str
    qualname: str
    line: int
    matched_tokens: tuple[str, ...]
    score: int


class _FunctionInventory(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.stack: list[str] = []
        self.functions: list[tuple[str, int, set[str]]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record(node)

    def _record(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        tokens = _tokens(node)
        self.functions.append((".".join(self.stack), node.lineno, tokens))
        self.generic_visit(node)
        self.stack.pop()


def audit_production_seams(
    source_root: str | Path,
    *,
    components: Iterable[str] = COMPONENT_PATTERNS,
) -> tuple[ProductionSeamCandidate, ...]:
    root = Path(source_root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    requested = tuple(components)
    unknown = tuple(item for item in requested if item not in COMPONENT_PATTERNS)
    if unknown:
        raise ValueError(f"unknown ablation components: {','.join(sorted(unknown))}")

    results: list[ProductionSeamCandidate] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == "research":
            continue
        if any(part == "__pycache__" for part in relative.parts):
            continue
        module = ".".join(relative.with_suffix("").parts)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            raise ValueError(f"cannot audit syntactically invalid module {path}: {exc}") from exc
        inventory = _FunctionInventory(module)
        inventory.visit(tree)
        for qualname, line, tokens in inventory.functions:
            for component in requested:
                patterns = COMPONENT_PATTERNS[component]
                matched = tuple(sorted(pattern for pattern in patterns if _matches(tokens, pattern)))
                if not matched:
                    continue
                results.append(
                    ProductionSeamCandidate(
                        component=component,
                        module=module,
                        qualname=qualname,
                        line=line,
                        matched_tokens=matched,
                        score=len(matched),
                    )
                )
    return tuple(
        sorted(
            results,
            key=lambda item: (item.component, -item.score, item.module, item.line, item.qualname),
        )
    )


def top_seams(
    candidates: Iterable[ProductionSeamCandidate],
    *,
    per_component: int = 8,
) -> Mapping[str, tuple[ProductionSeamCandidate, ...]]:
    if per_component < 1:
        raise ValueError("per_component must be positive")
    grouped: dict[str, list[ProductionSeamCandidate]] = {component: [] for component in COMPONENT_PATTERNS}
    for candidate in candidates:
        grouped.setdefault(candidate.component, []).append(candidate)
    return {
        component: tuple(values[:per_component])
        for component, values in sorted(grouped.items())
    }


def assert_required_seams(candidates: Iterable[ProductionSeamCandidate]) -> None:
    observed = {item.component for item in candidates}
    missing = set(COMPONENT_PATTERNS) - observed
    if missing:
        raise ValueError(f"production seam audit found no candidates for: {','.join(sorted(missing))}")


def _tokens(node: ast.AST) -> set[str]:
    values: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            values.add(child.id.lower())
        elif isinstance(child, ast.Attribute):
            values.add(child.attr.lower())
        elif isinstance(child, ast.arg):
            values.add(child.arg.lower())
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            for token in _split_string(child.value):
                values.add(token)
    return values


def _split_string(value: str) -> tuple[str, ...]:
    normalized = "".join(char.lower() if char.isalnum() or char == "_" else " " for char in value)
    return tuple(token for token in normalized.split() if token)


def _matches(tokens: set[str], pattern: str) -> bool:
    needle = pattern.lower()
    return any(needle == token or needle in token for token in tokens)

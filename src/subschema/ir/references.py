"""
Typed reference facts for compiled schema IR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from subschema.contracts import (
    ProofSide,
    UnsupportedCategory,
    UnsupportedDiagnostic,
)
from subschema.ir.terms import SchemaNodeRef, SchemaTerm

RecursiveReferenceGuard = Literal["array", "object", "object/array", "unguarded"]
RecursiveReferencePolarity = Literal["positive", "negative"]

__all__ = [
    "DynamicReferenceSemantics",
    "RecursiveReferenceFact",
    "RecursiveReferenceGuard",
    "RecursiveReferenceObligation",
    "RecursiveReferencePolarity",
    "ReferenceSemantics",
    "ReferenceUnsupportedFact",
    "StaticReferenceSemantics",
]


@dataclass(frozen=True)
class RecursiveReferenceFact:
    keyword: str
    path: tuple[str, ...]
    ref: str | None = None
    guard_kind: RecursiveReferenceGuard = "unguarded"
    polarity: RecursiveReferencePolarity = "positive"
    target_ref: SchemaNodeRef | None = None


@dataclass(frozen=True)
class RecursiveReferenceObligation:
    side: ProofSide
    keyword: str
    path: tuple[str, ...]
    ref: str | None
    guard_kind: RecursiveReferenceGuard
    polarity: RecursiveReferencePolarity
    target_ref: SchemaNodeRef | None = None

    @property
    def can_defer(self) -> bool:
        return (
            self.keyword == "$ref"
            and self.polarity == "positive"
            and self.guard_kind in {"array", "object", "object/array"}
        )

    def diagnostic(self) -> UnsupportedDiagnostic:
        return UnsupportedDiagnostic(
            "recursive-reference",
            _recursive_reference_obligation_reason(self),
            keyword=self.keyword,
            path=self.path,
            side=self.side,
            disposition="deferable" if self.can_defer else "terminal",
        )


def _recursive_reference_obligation_reason(
    obligation: RecursiveReferenceObligation,
) -> str:
    if obligation.keyword == "$recursiveRef":
        if obligation.polarity == "negative":
            return (
                "negative-polarity $recursiveRef requires guarded recursive "
                "reference proof support"
            )
        return "$recursiveRef requires guarded recursive reference proof support"
    ref = repr(obligation.ref) if obligation.ref is not None else "<unknown>"
    polarity = "negative-polarity " if obligation.polarity == "negative" else ""
    if obligation.guard_kind == "unguarded":
        return (
            "SAT static-reference fragment found "
            f"{polarity}unguarded recursive {obligation.side} $ref {ref}"
        )
    return (
        "SAT static-reference fragment found "
        f"{polarity}{obligation.guard_kind}-guarded recursive "
        f"{obligation.side} $ref {ref}; guarded recursive reference proofs are "
        "unsupported"
    )


@dataclass(frozen=True)
class ReferenceUnsupportedFact:
    reason: str
    path: tuple[str, ...]
    category: UnsupportedCategory = "static-reference"
    keyword: str = "$ref"
    ref: str | None = None
    guard_kind: RecursiveReferenceGuard | None = None
    polarity: RecursiveReferencePolarity = "positive"

    def diagnostic(self, side: ProofSide) -> UnsupportedDiagnostic:
        return UnsupportedDiagnostic(
            category=self.category,
            reason=self.reason,
            keyword=self.keyword,
            path=self.path,
            side=side,
        )


@dataclass(frozen=True)
class StaticReferenceSemantics:
    ref: str | None = None
    target: SchemaTerm | None = None
    lhs_unsupported: ReferenceUnsupportedFact | None = None
    rhs_unsupported: ReferenceUnsupportedFact | None = None

    def unsupported(self, side: ProofSide) -> ReferenceUnsupportedFact | None:
        return self.lhs_unsupported if side == "lhs" else self.rhs_unsupported


@dataclass(frozen=True)
class DynamicReferenceSemantics:
    target: SchemaTerm | None = None
    lhs_unsupported: ReferenceUnsupportedFact | None = None
    rhs_unsupported: ReferenceUnsupportedFact | None = None

    def unsupported(self, side: ProofSide) -> ReferenceUnsupportedFact | None:
        return self.lhs_unsupported if side == "lhs" else self.rhs_unsupported


@dataclass(frozen=True)
class ReferenceSemantics:
    has_static_reference_boundary: bool = False
    has_non_recursive_static_reference_boundary: bool = False
    static_reference_paths: tuple[tuple[str, ...], ...] = ()
    has_dynamic_reference: bool = False
    has_recursive_reference: bool = False
    recursive_references: tuple[RecursiveReferenceFact, ...] = ()
    recursive_obligations: tuple[RecursiveReferenceObligation, ...] = ()
    static_reference: StaticReferenceSemantics = field(
        default_factory=StaticReferenceSemantics
    )
    dynamic_reference: DynamicReferenceSemantics = field(
        default_factory=DynamicReferenceSemantics
    )

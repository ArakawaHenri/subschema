"""
Stable contracts shared by the proof kernel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from subschema.dialects import Dialect
from subschema.exceptions import UnsupportedProofError

ProofStatus = Literal[
    "proved_true", "proved_false", "unsupported", "resource_exhausted"
]
ProofClass = Literal["simple_exact", "endeavor_expensive", "unsupported_unreliable"]
ExpensiveProofKind = Literal[
    "array_product",
    "branch_product",
    "evaluation_trace",
    "object_product",
    "regex_product",
]
ProofSide = Literal["lhs", "rhs"]
UnsupportedCategory = Literal[
    "dialect-keyword",
    "dynamic-reference",
    "evaluation-frontier",
    "format-assertion",
    "non-regular-regex",
    "recursive-reference",
    "semantic-keyword",
    "static-reference",
    "unknown-vocabulary",
]


@dataclass(frozen=True)
class UnsupportedDiagnostic:
    category: UnsupportedCategory
    reason: str
    keyword: str | None = None
    path: tuple[str, ...] = ()
    side: ProofSide | None = None

    @property
    def pointer(self) -> str:
        if not self.path:
            return "#"
        return "#/" + "/".join(
            _escape_pointer_segment(segment) for segment in self.path
        )

    def format(self) -> str:
        location = self.pointer if self.side is None else f"{self.side} {self.pointer}"
        return f"{location}: {self.reason}"


@dataclass(frozen=True)
class CounterexampleCertificate:
    kind: str
    reason: str
    path: tuple[str, ...] = ()
    children: tuple[CounterexampleCertificate, ...] = ()


VERIFIABLE_CERTIFICATE_KINDS = frozenset(
    {
        "applicator-base",
        "applicator-right-allof",
        "applicator-right-anyof",
        "applicator-right-oneof",
        "array-inhabitant",
        "array-item-anyof",
        "array-item-value",
        "closed-object-property",
        "concrete-witness",
        "object-inhabitant",
        "object-key-value",
        "object-property-value",
    }
)

_CERTIFICATE_CHILD_KINDS: dict[str, frozenset[str] | None] = {
    "applicator-base": None,
    "applicator-right-allof": None,
    "applicator-right-anyof": None,
    "applicator-right-oneof": None,
    "array-inhabitant": frozenset(),
    "array-item-anyof": None,
    "array-item-value": None,
    "closed-object-property": None,
    "concrete-witness": frozenset(),
    "object-inhabitant": frozenset(),
    "object-key-value": None,
    "object-property-value": None,
}


@dataclass(frozen=True)
class ProofResult:
    status: ProofStatus
    witness: Any = None
    certificate: CounterexampleCertificate | None = None
    reason: str | None = None
    error: Exception | None = None
    diagnostics: tuple[UnsupportedDiagnostic, ...] = ()

    def __repr__(self) -> str:
        parts = [f"status={self.status!r}"]
        if self.reason is not None:
            parts.append(f"reason={self.reason!r}")
        if self.diagnostics:
            parts.append(f"diagnostics={len(self.diagnostics)}")
        if self.certificate is not None:
            parts.append(f"certificate={self.certificate.kind!r}")
        if self.witness is not None:
            parts.append(f"witness_type={type(self.witness).__name__}")
        if self.error is not None:
            parts.append(f"error={type(self.error).__name__}")
        return f"{type(self).__name__}({', '.join(parts)})"

    @classmethod
    def true(cls) -> ProofResult:
        return cls("proved_true")

    @classmethod
    def false(cls, witness: Any) -> ProofResult:
        return cls("proved_false", witness=witness)

    @classmethod
    def certified_false(cls, certificate: CounterexampleCertificate) -> ProofResult:
        if not certificate_is_verifiable(certificate):
            return cls(
                "unsupported",
                reason=f"counterexample certificate {
                    certificate.kind!r
                } is not verifiable",
            )
        return cls("proved_false", certificate=certificate)

    @property
    def has_counterexample(self) -> bool:
        return self.status == "proved_false"

    @classmethod
    def unsupported(
        cls,
        reason: str,
        error: Exception | None = None,
        diagnostics: UnsupportedDiagnostic | tuple[UnsupportedDiagnostic, ...] = (),
    ) -> ProofResult:
        if isinstance(diagnostics, UnsupportedDiagnostic):
            diagnostics = (diagnostics,)
        return cls("unsupported", reason=reason, error=error, diagnostics=diagnostics)

    @classmethod
    def resource_exhausted(cls, reason: str) -> ProofResult:
        return cls("resource_exhausted", reason=reason)

    def as_bool(self, dialect: Dialect) -> bool:
        _ = dialect
        if self.status == "proved_true":
            return True
        if self.status == "proved_false":
            return False
        if self.error is not None:
            raise self.error
        raise UnsupportedProofError(
            self.reason or "schema proof could not be proven",
            status=self.status,
            diagnostics=self.diagnostics,
        )


def proof_is_inconclusive(result: ProofResult) -> bool:
    return result.status in {"unsupported", "resource_exhausted"}


@dataclass(frozen=True)
class ProofBudgets:
    max_work: int = 4096
    timeout_ms: int = 1000

    def __post_init__(self) -> None:
        if isinstance(self.max_work, bool) or not isinstance(self.max_work, int):
            raise TypeError("max_work must be an integer")
        if isinstance(self.timeout_ms, bool) or not isinstance(self.timeout_ms, int):
            raise TypeError("timeout_ms must be an integer")
        if self.max_work < -1:
            raise ValueError("max_work must be -1 or greater")
        if self.timeout_ms < -1:
            raise ValueError("timeout_ms must be -1 or greater")


@dataclass
class ProofWorkMeter:
    limit: int
    spent: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("proof work limit must be an integer")
        if self.limit < -1:
            raise ValueError("proof work limit must be -1 or greater")
        if self.spent < 0:
            raise ValueError("spent proof work must be non-negative")

    @property
    def exhausted(self) -> bool:
        return self.limit >= 0 and self.spent >= self.limit

    def spend(
        self, units: int, kind: str, reason: str | None = None
    ) -> ProofResult | None:
        if isinstance(units, bool) or not isinstance(units, int):
            raise TypeError("proof work units must be an integer")
        if units < 0:
            raise ValueError("proof work units must be non-negative")
        if units == 0:
            return None
        if self.limit >= 0 and self.spent + units > self.limit:
            return ProofResult.resource_exhausted(
                reason or f"{kind} exceeded proof work budget"
            )
        self.spent += units
        return None


@dataclass(frozen=True)
class ProofOptions:
    endeavor: bool = False
    budgets: ProofBudgets = field(default_factory=ProofBudgets)

    def __post_init__(self) -> None:
        if not isinstance(self.endeavor, bool):
            raise TypeError("endeavor must be a boolean")
        if not isinstance(self.budgets, ProofBudgets):
            raise TypeError("budgets must be a ProofBudgets instance")
        if not self.endeavor and self.budgets != ProofBudgets():
            raise ValueError("proof budgets require endeavor=True")


def _escape_pointer_segment(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def certificate_is_verifiable(certificate: CounterexampleCertificate) -> bool:
    if certificate.kind not in VERIFIABLE_CERTIFICATE_KINDS:
        return False
    if not isinstance(certificate.reason, str) or not certificate.reason:
        return False
    if not all(isinstance(segment, str) for segment in certificate.path):
        return False
    allowed_children = _CERTIFICATE_CHILD_KINDS[certificate.kind]
    if allowed_children is not None and any(
        child.kind not in allowed_children for child in certificate.children
    ):
        return False
    if (
        certificate.kind
        in {"concrete-witness", "array-inhabitant", "object-inhabitant"}
        and certificate.children
    ):
        return False
    return all(certificate_is_verifiable(child) for child in certificate.children)

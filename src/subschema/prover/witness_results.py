"""
Shared witness construction result types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from subschema.contracts import CounterexampleCertificate, ProofResult

WitnessBuildStatus = Literal[
    "certificate", "resource_exhausted", "unsupported", "witness"
]

__all__ = ["WitnessBuildResult", "WitnessBuildStatus"]


@dataclass(frozen=True)
class WitnessBuildResult:
    status: WitnessBuildStatus
    witness: Any = None
    certificate: CounterexampleCertificate | None = None
    reason: str = ""

    @classmethod
    def concrete(cls, witness: Any) -> WitnessBuildResult:
        return cls("witness", witness=witness)

    @classmethod
    def certified(cls, certificate: CounterexampleCertificate) -> WitnessBuildResult:
        return cls("certificate", certificate=certificate, reason=certificate.reason)

    @classmethod
    def unsupported(cls, reason: str) -> WitnessBuildResult:
        return cls("unsupported", reason=reason)

    @classmethod
    def resource_exhausted(cls, reason: str) -> WitnessBuildResult:
        return cls("resource_exhausted", reason=reason)

    @property
    def has_witness(self) -> bool:
        return self.status == "witness"

    def as_proof_result(self) -> ProofResult:
        if self.status == "witness":
            return ProofResult.false(self.witness)
        if self.status == "certificate" and self.certificate is not None:
            return ProofResult.certified_false(self.certificate)
        if self.status == "resource_exhausted":
            return ProofResult.resource_exhausted(self.reason)
        return ProofResult.unsupported(self.reason)

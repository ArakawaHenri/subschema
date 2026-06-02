"""
Counterexample certificate verification.
"""

from __future__ import annotations

from subschema.kernel.contracts import (
    CounterexampleCertificate,
    certificate_is_verifiable,
)


def verify_counterexample_certificate(certificate: CounterexampleCertificate) -> bool:
    return certificate_is_verifiable(certificate)

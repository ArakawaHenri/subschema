"""
Compiler-owned schema preparation for proof compilation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from subschema.compiler.normalization import (
    normalize_simple_lhs_unevaluated_for_proof,
)
from subschema.compiler.resources import inline_static_refs_for_proof
from subschema.dialects import Dialect, strip_inactive_keywords_for_dialect

__all__ = ["prepare_for_proof"]


def prepare_for_proof(
    lhs: Any,
    rhs: Any,
    *,
    dialect: Dialect,
    resources: Mapping[str, Any],
) -> tuple[Any, Any]:
    prepared_lhs = strip_inactive_keywords_for_dialect(lhs, dialect)
    prepared_rhs = strip_inactive_keywords_for_dialect(rhs, dialect)
    proof_lhs = inline_static_refs_for_proof(
        prepared_lhs,
        dialect,
        resources=resources,
    )
    proof_rhs = inline_static_refs_for_proof(
        prepared_rhs,
        dialect,
        resources=resources,
    )
    return normalize_simple_lhs_unevaluated_for_proof(proof_lhs), proof_rhs

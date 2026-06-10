"""
Scalar and finite SAT difference rules.
"""

from __future__ import annotations

from typing import Any, Literal

from subschema.contracts import ProofResult
from subschema.ir import IRAssertionKind
from subschema.ir.constraints import (
    FiniteConstraint,
    NumericAtomFact,
    NumericConstraint,
    StringLanguageConstraint,
    StringLengthConstraint,
    TypeConstraint,
    type_atom_witness,
)
from subschema.prover.confirmation import confirm_difference
from subschema.prover.finite import (
    finite_complement_excluded_values_for_ir,
    inhabited_finite_values_for_ir,
)
from subschema.prover.protocols import DifferenceProblemProtocol
from subschema.prover.rules.common import (
    _contains_static_reference,
    _lhs_confirmation_source,
    _rhs_confirmation_source,
    _validated_any_false,
    _validated_false,
)
from subschema.prover.scalars import (
    finite_rhs_difference_plan_from_constraints,
    numeric_difference_plan_from_constraints,
    string_language_difference_plan_from_constraints,
    string_length_difference_plan_from_constraints,
    type_difference_plan_from_constraints,
    typed_scalar_difference_plan_from_constraints,
)
from subschema.prover.witnesses import build_ir_witness
from subschema.values import json_semantic_key

_SCALAR_FACT_REQUIREMENTS: dict[
    str, tuple[tuple[Literal["lhs", "rhs"], IRAssertionKind], ...]
] = {
    "SAT type fragment requires exact type shapes": (
        ("lhs", "type"),
        ("rhs", "type"),
    ),
    "SAT type fragment requires language-complete right type shape": (("rhs", "type"),),
    "SAT numeric fragment requires exact numeric shapes": (
        ("lhs", "numeric"),
        ("rhs", "numeric"),
    ),
    "SAT string-length fragment requires exact string shapes": (
        ("lhs", "string-length"),
        ("rhs", "string-length"),
    ),
    "SAT string-language fragment requires exact language shapes": (
        ("lhs", "string-language"),
        ("rhs", "string-language"),
    ),
}


def _scalar_fact_unsupported(
    problem: DifferenceProblemProtocol,
    reason: str,
) -> ProofResult | None:
    for side, kind in _SCALAR_FACT_REQUIREMENTS.get(reason, ()):
        proof = (
            problem.lhs_require_exact(kind, reason)
            if side == "lhs"
            else problem.rhs_require_exact(kind, reason)
        )
        if proof is not None:
            return proof
    return None


def _prove_finite_lhs_difference(problem: DifferenceProblemProtocol) -> ProofResult:
    finite_constraint = _finite_constraint(problem.lhs_constraint("finite"))
    if finite_constraint is None:
        return ProofResult.unsupported(
            "SAT finite fragment requires finite left language"
        )

    for value in finite_constraint.values:
        confirmed = confirm_difference(
            _lhs_confirmation_source(problem),
            _rhs_confirmation_source(problem),
            value,
        )
        if confirmed.status == "unsupported":
            if confirmed.proof is None:
                return ProofResult.unsupported("finite witness confirmation failed")
            return confirmed.proof
        if confirmed.status == "confirmed":
            return ProofResult.false(value)
    return ProofResult.true()


def _prove_finite_rhs_difference(problem: DifferenceProblemProtocol) -> ProofResult:
    if _contains_static_reference(problem):
        return ProofResult.unsupported(
            "SAT finite-rhs fragment is deferred for static references"
        )

    rhs_finite = _finite_constraint(problem.rhs_constraint("finite"))
    confirmed_rhs_finite = None
    if rhs_finite is not None:
        rhs_values = inhabited_finite_values_for_ir(
            problem.formula.rhs, problem.context
        )
        if rhs_values is None:
            return ProofResult.unsupported(
                "SAT finite-rhs fragment requires confirmed finite right language"
            )
        confirmed_rhs_finite = FiniteConstraint(
            tuple(rhs_values), requires_confirmation=False
        )

    plan = finite_rhs_difference_plan_from_constraints(
        _type_constraint(problem.lhs_constraint("type")),
        _finite_constraint(problem.lhs_constraint("finite")),
        confirmed_rhs_finite,
        _numeric_constraint(problem.lhs_constraint("numeric")),
    )
    if plan.status == "unsupported":
        if plan.reason == "SAT finite-rhs witness could not be constructed":
            return _constructive_finite_rhs_false(problem)
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()
    proof = _validated_any_false(
        problem, plan.witnesses, "SAT finite-rhs witness could not be constructed"
    )
    if proof.status != "unsupported":
        return proof
    return _constructive_finite_rhs_false(problem)


def _constructive_finite_rhs_false(problem: DifferenceProblemProtocol) -> ProofResult:
    witness = build_ir_witness(
        problem.formula.lhs,
        problem.context,
    )
    if witness.status == "resource_exhausted":
        return ProofResult.resource_exhausted(witness.reason)
    if witness.status != "witness":
        return ProofResult.unsupported(
            witness.reason or "SAT finite-rhs witness could not be constructed"
        )
    return _validated_false(
        problem, witness.witness, "SAT finite-rhs constructive witness was rejected"
    )


def _prove_finite_complement_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    lhs_excluded = _finite_complement_excluded_values(
        problem.formula.lhs,
        problem.context,
    )
    rhs_excluded = _finite_complement_excluded_values(
        problem.formula.rhs,
        problem.context,
    )
    if rhs_excluded is None:
        return ProofResult.unsupported(
            "SAT finite-complement fragment requires finite negated schemas"
        )
    if lhs_excluded is None:
        return _validated_any_false(
            problem,
            rhs_excluded,
            "SAT finite-complement witness could not be constructed",
        )

    if all(_json_value_in(value, lhs_excluded) for value in rhs_excluded):
        return ProofResult.true()

    for value in rhs_excluded:
        if not _json_value_in(value, lhs_excluded):
            return _validated_false(
                problem, value, "SAT finite-complement witness was rejected"
            )
    return ProofResult.unsupported(
        "SAT finite-complement witness could not be constructed"
    )


def _prove_type_difference(problem: DifferenceProblemProtocol) -> ProofResult:
    lhs_constraint = _type_constraint(problem.lhs_constraint("type"))
    rhs_constraint = _type_constraint(problem.rhs_constraint("type"))
    plan = type_difference_plan_from_constraints(
        lhs_constraint,
        rhs_constraint,
    )
    if plan.status == "unsupported":
        if proof := _scalar_fact_unsupported(problem, plan.reason):
            return proof
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()
    if lhs_constraint is None or rhs_constraint is None:
        return _validated_false(problem, plan.witness, plan.rejected_reason)
    extra_atoms = lhs_constraint.atoms - rhs_constraint.atoms
    lhs_witness = build_ir_witness(
        problem.formula.lhs,
        problem.context,
    )
    witnesses = tuple(type_atom_witness(atom) for atom in sorted(extra_atoms)) + (
        (lhs_witness.witness,) if lhs_witness.has_witness else ()
    )
    return _validated_any_false(problem, witnesses, plan.rejected_reason)


def _prove_numeric_difference(problem: DifferenceProblemProtocol) -> ProofResult:
    lhs_numeric = _numeric_constraint(problem.lhs_constraint("numeric"))
    rhs_type = _type_constraint(problem.rhs_constraint("type"))
    if (
        lhs_numeric is not None
        and lhs_numeric.accepts_non_numeric
        and rhs_type is not None
        and not rhs_type.language_complete
        and problem.formula.rhs.semantics.has_non_numeric_assertions
    ):
        return ProofResult.unsupported(
            "SAT numeric fragment cannot prove unmodeled non-numeric right semantics"
        )
    plan = numeric_difference_plan_from_constraints(
        lhs_numeric,
        _numeric_constraint(problem.rhs_constraint("numeric")),
        context=problem.context,
        lhs_type=_type_constraint(problem.lhs_constraint("type")),
        rhs_type=rhs_type,
    )
    if isinstance(plan, ProofResult):
        return plan
    if plan.status == "unsupported":
        if proof := _scalar_fact_unsupported(problem, plan.reason):
            return proof
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()
    return _validated_false(problem, plan.witness, plan.rejected_reason)


def _prove_string_length_difference(problem: DifferenceProblemProtocol) -> ProofResult:
    plan = string_length_difference_plan_from_constraints(
        _string_length_constraint(problem.lhs_constraint("string-length")),
        _string_length_constraint(problem.rhs_constraint("string-length")),
    )
    if plan.status == "unsupported":
        if proof := _scalar_fact_unsupported(problem, plan.reason):
            return proof
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()
    return _validated_false(problem, plan.witness, plan.rejected_reason)


def _prove_string_language_difference(
    problem: DifferenceProblemProtocol,
) -> ProofResult:
    plan = string_language_difference_plan_from_constraints(
        _string_language_constraint(problem.lhs_constraint("string-language")),
        _string_language_constraint(problem.rhs_constraint("string-language")),
        context=problem.context,
    )
    if plan.status == "unsupported":
        if proof := _scalar_fact_unsupported(problem, plan.reason):
            return proof
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        return ProofResult.true()
    return _validated_false(problem, plan.witness, plan.rejected_reason)


def _prove_typed_scalar_difference(problem: DifferenceProblemProtocol) -> ProofResult:
    if _contains_static_reference(problem):
        return ProofResult.unsupported(
            "SAT typed-scalar fragment is deferred for static references"
        )
    if (
        problem.formula.lhs.semantics.has_object_or_array_assertions
        or problem.formula.rhs.semantics.has_object_or_array_assertions
    ):
        return ProofResult.unsupported(
            "SAT typed-scalar fragment excludes object and array assertions"
        )

    lhs_type = _type_constraint(problem.lhs_constraint("type"))
    rhs_type = _type_constraint(problem.rhs_constraint("type"))
    lhs_numeric = _numeric_constraint_for_typed_scalar(
        lhs_type,
        _numeric_constraint(problem.lhs_constraint("numeric")),
        has_numeric_assertions=problem.formula.lhs.semantics.has_numeric_assertions,
    )
    rhs_numeric = _numeric_constraint_for_typed_scalar(
        rhs_type,
        _numeric_constraint(problem.rhs_constraint("numeric")),
        has_numeric_assertions=problem.formula.rhs.semantics.has_numeric_assertions,
    )
    lhs_string = _string_language_constraint(problem.lhs_constraint("string-language"))
    rhs_string = _string_language_constraint(problem.rhs_constraint("string-language"))
    plan = typed_scalar_difference_plan_from_constraints(
        lhs_type,
        rhs_type,
        lhs_numeric,
        rhs_numeric,
        lhs_string,
        rhs_string,
        context=problem.context,
    )
    if isinstance(plan, ProofResult):
        return plan
    if plan.status == "unsupported":
        return ProofResult.unsupported(plan.reason)
    if plan.status == "proved_true":
        if (
            lhs_type is not None
            and rhs_type is not None
            and not rhs_type.language_complete
            and not all(
                _typed_scalar_rhs_atom_is_modeled(
                    problem,
                    atom,
                    lhs_numeric=problem.lhs_constraint("numeric"),
                    rhs_numeric=problem.rhs_constraint("numeric"),
                    lhs_string=problem.lhs_constraint("string-language"),
                    rhs_string=problem.rhs_constraint("string-language"),
                )
                for atom in lhs_type.atoms
            )
        ):
            return ProofResult.unsupported(
                "SAT typed-scalar fragment requires modeled right scalar semantics"
            )
        return ProofResult.true()
    return _validated_false(problem, plan.witness, plan.rejected_reason)


def _typed_scalar_rhs_atom_is_modeled(
    problem: DifferenceProblemProtocol,
    atom: str,
    *,
    lhs_numeric: NumericConstraint | None,
    rhs_numeric: NumericConstraint | None,
    lhs_string: StringLanguageConstraint | None,
    rhs_string: StringLanguageConstraint | None,
) -> bool:
    if problem.formula.rhs.covers_type_atom(atom):
        return True
    if atom in {"integer", "number"}:
        return lhs_numeric is not None and rhs_numeric is not None
    if atom == "string":
        return lhs_string is not None and rhs_string is not None
    return False


def _finite_constraint(value: Any) -> FiniteConstraint | None:
    return value if isinstance(value, FiniteConstraint) else None


def _type_constraint(value: Any) -> TypeConstraint | None:
    return value if isinstance(value, TypeConstraint) else None


def _numeric_constraint(value: Any) -> NumericConstraint | None:
    return value if isinstance(value, NumericConstraint) else None


def _string_length_constraint(value: Any) -> StringLengthConstraint | None:
    return value if isinstance(value, StringLengthConstraint) else None


def _string_language_constraint(value: Any) -> StringLanguageConstraint | None:
    return value if isinstance(value, StringLanguageConstraint) else None


def _numeric_constraint_for_typed_scalar(
    type_constraint: TypeConstraint | None,
    numeric_constraint: NumericConstraint | None,
    *,
    has_numeric_assertions: bool,
) -> NumericConstraint | None:
    if (
        numeric_constraint is not None
        or type_constraint is None
        or has_numeric_assertions
    ):
        return numeric_constraint

    numeric_atoms = type_constraint.atoms & {"integer", "number"}
    accepts_non_numeric = bool(type_constraint.atoms - {"integer", "number"})
    if not numeric_atoms:
        return NumericConstraint((), accepts_non_numeric=accepts_non_numeric)
    return NumericConstraint(
        (NumericAtomFact(integer_only="number" not in numeric_atoms),),
        accepts_non_numeric=accepts_non_numeric,
    )


def _finite_complement_excluded_values(
    ir: Any, context: Any
) -> tuple[Any, ...] | None:
    return finite_complement_excluded_values_for_ir(ir, context)


def _json_value_in(value: Any, values: tuple[Any, ...]) -> bool:
    key = json_semantic_key(value)
    return any(key == json_semantic_key(existing) for existing in values)

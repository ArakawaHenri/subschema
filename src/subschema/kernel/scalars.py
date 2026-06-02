"""
Scalar and finite-domain difference plans for SAT rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Any, Literal

from subschema.kernel.constraints import (
    FiniteConstraint,
    NumericConstraint,
    StringLanguageConstraint,
    StringLengthConstraint,
    TypeConstraint,
)
from subschema.kernel.contracts import ProofResult
from subschema.kernel.domains.numbers import NumericAtom, NumericShape
from subschema.kernel.domains.types import JSON_TYPE_ATOMS, witness_for_type_atom
from subschema.kernel.ir import LogicalSchemaIR
from subschema.kernel.symbolic import SAT, UNSAT, SymbolicSolver
from subschema.kernel.values import json_values_equal

if TYPE_CHECKING:
    from subschema.kernel.context import ProofContext

ScalarDifferencePlanStatus = Literal["proved_true", "unsupported", "witness"]
FiniteRhsDifferencePlanStatus = Literal["proved_true", "unsupported", "witnesses"]

_FINITE_RHS_WITNESS_VALUES = {
    "array": ([], [None], [0], [0, 1]),
    "boolean": (False, True),
    "integer": (0, 1, -1, 2),
    "null": (None,),
    "number": (0.5, -0.5, 1.5),
    "object": ({}, {"a": None}, {"a": 1}, {"foo": "a"}),
    "string": ("", "a", "aa", "b"),
}

__all__ = [
    "FiniteRhsDifferencePlan",
    "FiniteRhsDifferencePlanStatus",
    "ScalarDifferencePlan",
    "ScalarDifferencePlanStatus",
    "finite_rhs_difference_plan",
    "finite_rhs_difference_plan_from_constraints",
    "numeric_difference_plan",
    "numeric_difference_plan_from_constraints",
    "string_language_difference_plan",
    "string_language_difference_plan_from_constraints",
    "string_length_difference_plan",
    "string_length_difference_plan_from_constraints",
    "typed_scalar_difference_plan_from_constraints",
    "type_difference_plan",
    "type_difference_plan_from_constraints",
]


@dataclass(frozen=True)
class ScalarDifferencePlan:
    status: ScalarDifferencePlanStatus
    reason: str = ""
    witness: Any = None
    rejected_reason: str = ""

    @classmethod
    def true(cls) -> ScalarDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> ScalarDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def counterexample(cls, witness: Any, rejected_reason: str) -> ScalarDifferencePlan:
        return cls("witness", witness=witness, rejected_reason=rejected_reason)


@dataclass(frozen=True)
class FiniteRhsDifferencePlan:
    status: FiniteRhsDifferencePlanStatus
    reason: str = ""
    witnesses: tuple[Any, ...] = ()

    @classmethod
    def true(cls) -> FiniteRhsDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> FiniteRhsDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def candidates(cls, witnesses: tuple[Any, ...]) -> FiniteRhsDifferencePlan:
        if not witnesses:
            return cls.unsupported("SAT finite-rhs witness could not be constructed")
        return cls("witnesses", witnesses=witnesses)


def finite_rhs_difference_plan(
    lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
) -> FiniteRhsDifferencePlan:
    return finite_rhs_difference_plan_from_constraints(
        lhs.type_constraint,
        lhs.finite_constraint,
        rhs.finite_constraint,
        lhs.numeric_constraint,
    )


def finite_rhs_difference_plan_from_constraints(
    lhs_type: TypeConstraint | None,
    lhs_finite: FiniteConstraint | None,
    rhs_finite: FiniteConstraint | None,
    lhs_numeric: NumericConstraint | None = None,
) -> FiniteRhsDifferencePlan:
    if rhs_finite is None:
        return FiniteRhsDifferencePlan.unsupported(
            "SAT finite-rhs fragment requires finite right language"
        )
    if lhs_finite is not None:
        return FiniteRhsDifferencePlan.unsupported(
            "SAT finite-rhs fragment is handled by finite left language"
        )

    numeric_witness = _finite_rhs_numeric_witness(lhs_numeric, rhs_finite.values)
    if numeric_witness is not None:
        return FiniteRhsDifferencePlan.candidates((numeric_witness,))

    lhs_values = _finite_values_for_type_constraint(lhs_type)
    if lhs_values is not None:
        if all(
            any(_json_values_equal(value, rhs_value) for rhs_value in rhs_finite.values)
            for value in lhs_values
        ):
            return FiniteRhsDifferencePlan.true()
        return FiniteRhsDifferencePlan.candidates(
            tuple(
                value
                for value in lhs_values
                if all(
                    not _json_values_equal(value, rhs_value)
                    for rhs_value in rhs_finite.values
                )
            )
        )

    atoms = lhs_type.atoms if lhs_type is not None else JSON_TYPE_ATOMS
    witnesses = tuple(
        witness
        for atom in sorted(atoms)
        for witness in _finite_rhs_atom_witnesses(atom, rhs_finite.values)
    ) + _finite_rhs_generic_witnesses(rhs_finite.values)
    return FiniteRhsDifferencePlan.candidates(_dedupe_json_values(witnesses))


def type_difference_plan(
    lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
) -> ScalarDifferencePlan:
    return type_difference_plan_from_constraints(
        lhs.type_constraint, rhs.type_constraint
    )


def type_difference_plan_from_constraints(
    lhs_constraint: TypeConstraint | None,
    rhs_constraint: TypeConstraint | None,
) -> ScalarDifferencePlan:
    if lhs_constraint is None or rhs_constraint is None:
        return ScalarDifferencePlan.unsupported(
            "SAT type fragment requires exact type shapes"
        )
    lhs_shape = lhs_constraint.shape
    rhs_shape = rhs_constraint.shape
    if lhs_shape.is_subset_of(rhs_shape):
        if rhs_constraint.language_complete:
            return ScalarDifferencePlan.true()
        return ScalarDifferencePlan.unsupported(
            "SAT type fragment requires language-complete right type shape"
        )

    extra_atoms = lhs_shape.atoms - rhs_shape.atoms
    if not extra_atoms:
        return ScalarDifferencePlan.unsupported(
            "SAT type fragment could not construct a witness"
        )
    witness = witness_for_type_atom(sorted(extra_atoms)[0])
    return ScalarDifferencePlan.counterexample(
        witness, "SAT type witness was rejected by concrete validation"
    )


def typed_scalar_difference_plan_from_constraints(
    lhs_type: TypeConstraint | None,
    rhs_type: TypeConstraint | None,
    lhs_numeric: NumericConstraint | None,
    rhs_numeric: NumericConstraint | None,
    lhs_string: StringLanguageConstraint | None,
    rhs_string: StringLanguageConstraint | None,
    context: ProofContext | None = None,
) -> ScalarDifferencePlan | ProofResult:
    if lhs_type is None or rhs_type is None:
        return ScalarDifferencePlan.unsupported(
            "SAT typed-scalar fragment requires exact type shapes"
        )

    lhs_atoms = lhs_type.atoms
    rhs_atoms = rhs_type.atoms
    extra_atoms = lhs_atoms - rhs_atoms
    if extra_atoms:
        if extra_atoms & {"integer", "number"} and lhs_numeric is not None:
            witness = lhs_numeric.shape.witness_not_in(
                NumericShape((), accepts_non_numeric=True)
            )
            if witness is not None:
                return ScalarDifferencePlan.counterexample(
                    witness,
                    (
                        "SAT typed-scalar numeric type witness was rejected by "
                        "concrete validation"
                    ),
                )
        return ScalarDifferencePlan.counterexample(
            witness_for_type_atom(sorted(extra_atoms)[0]),
            "SAT typed-scalar type witness was rejected by concrete validation",
        )
    if not rhs_type.language_complete and rhs_numeric is None and rhs_string is None:
        return ScalarDifferencePlan.unsupported(
            "SAT typed-scalar fragment requires modeled right scalar semantics"
        )

    if lhs_atoms & {"integer", "number"}:
        if lhs_numeric is None and rhs_numeric is None:
            pass
        elif lhs_numeric is None or rhs_numeric is None:
            return ScalarDifferencePlan.unsupported(
                "SAT typed-scalar fragment requires exact numeric shapes"
            )
        else:
            numeric_plan = numeric_difference_plan_from_constraints(
                lhs_numeric,
                rhs_numeric,
                context=context,
                lhs_type=lhs_type,
                rhs_type=rhs_type,
            )
            if isinstance(numeric_plan, ProofResult):
                return numeric_plan
            if numeric_plan.status == "unsupported":
                return numeric_plan
            if numeric_plan.status == "witness":
                return ScalarDifferencePlan.counterexample(
                    numeric_plan.witness,
                    (
                        "SAT typed-scalar numeric witness was rejected by concrete "
                        "validation"
                    ),
                )

    if "string" in lhs_atoms:
        if lhs_string is None and rhs_string is None:
            pass
        elif lhs_string is None or rhs_string is None:
            return ScalarDifferencePlan.unsupported(
                "SAT typed-scalar fragment requires exact string-language shapes"
            )
        else:
            string_subset = lhs_string.shape.pattern.is_subset_of(
                rhs_string.shape.pattern
            )
            if isinstance(string_subset, ProofResult):
                return string_subset
            if not string_subset:
                witness = lhs_string.shape.witness_not_in(rhs_string.shape)
                if isinstance(witness, ProofResult):
                    return witness
                if witness is None:
                    return ScalarDifferencePlan.unsupported(
                        "SAT typed-scalar string witness could not be constructed"
                    )
                return ScalarDifferencePlan.counterexample(
                    witness,
                    (
                        "SAT typed-scalar string witness was rejected by concrete "
                        "validation"
                    ),
                )

    return ScalarDifferencePlan.true()


def numeric_difference_plan(
    lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
) -> ScalarDifferencePlan:
    return numeric_difference_plan_from_constraints(
        lhs.numeric_constraint, rhs.numeric_constraint
    )


def numeric_difference_plan_from_constraints(
    lhs_constraint: NumericConstraint | None,
    rhs_constraint: NumericConstraint | None,
    *,
    context: ProofContext | None = None,
    lhs_type: TypeConstraint | None = None,
    rhs_type: TypeConstraint | None = None,
) -> ScalarDifferencePlan | ProofResult:
    if lhs_constraint is None or rhs_constraint is None:
        return ScalarDifferencePlan.unsupported(
            "SAT numeric fragment requires exact numeric shapes"
        )
    lhs_shape = lhs_constraint.shape
    rhs_shape = rhs_constraint.shape

    if lhs_shape.accepts_non_numeric and not rhs_shape.accepts_non_numeric:
        return ScalarDifferencePlan.counterexample(
            "",
            "SAT numeric non-number witness was rejected by concrete validation",
        )
    if lhs_shape.accepts_non_numeric and not _nonnumeric_type_coverage_is_complete(
        lhs_type, rhs_type
    ):
        return ScalarDifferencePlan.unsupported(
            "SAT numeric fragment cannot prove non-numeric type coverage"
        )
    if not rhs_shape.normalized_atoms() and rhs_shape.accepts_non_numeric:
        return ScalarDifferencePlan.unsupported(
            "SAT numeric fragment defers pure type exclusion"
        )

    subset = lhs_shape.numeric_subset_of(rhs_shape)
    if subset is True:
        return ScalarDifferencePlan.true()

    if subset is False:
        witness = lhs_shape.witness_not_in(rhs_shape)
        if witness is not None:
            return ScalarDifferencePlan.counterexample(
                witness, "SAT numeric witness was rejected by concrete validation"
            )

    if context is not None:
        symbolic = _symbolic_numeric_difference_plan(lhs_shape, rhs_shape, context)
        if not isinstance(symbolic, ProofResult) and symbolic.status != "unsupported":
            return symbolic

    if subset is None:
        return ScalarDifferencePlan.unsupported(
            "SAT numeric union coverage could not be proven exactly"
        )

    return ScalarDifferencePlan.unsupported(
        "SAT numeric fragment could not construct a witness"
    )


def _symbolic_numeric_difference_plan(
    lhs_shape: Any,
    rhs_shape: Any,
    context: ProofContext,
) -> ScalarDifferencePlan | ProofResult:
    solver = SymbolicSolver(
        context, "numeric product", "numeric product exceeded proof work budget"
    )
    value = solver.real_var("number")
    lhs_expr = _numeric_shape_expr(solver, value, lhs_shape, "lhs")
    rhs_expr = _numeric_shape_expr(solver, value, rhs_shape, "rhs")
    solver.add(lhs_expr, solver.not_(rhs_expr))
    check = solver.check_with_work(
        units=max(
            len(lhs_shape.normalized_atoms()) + len(rhs_shape.normalized_atoms()), 1
        )
    )
    if isinstance(check, ProofResult):
        return check
    if check == SAT:
        witness_fraction = solver.model_real(solver.model(), "number")
        if _numeric_shape_allows_fractional_value(lhs_shape):
            fractional_witness = _symbolic_fractional_numeric_witness(
                lhs_shape, rhs_shape, context
            )
            if fractional_witness is not None:
                witness_fraction = fractional_witness
        witness = _json_number_from_fraction(witness_fraction)
        return ScalarDifferencePlan.counterexample(
            witness, "SAT numeric witness was rejected by concrete validation"
        )
    if check == UNSAT:
        return ScalarDifferencePlan.true()
    return ScalarDifferencePlan.unsupported(
        "SAT numeric symbolic solver returned unknown"
    )


def _symbolic_fractional_numeric_witness(
    lhs_shape: Any,
    rhs_shape: Any,
    context: ProofContext,
) -> Fraction | None:
    negative = _symbolic_fractional_numeric_witness_with_extra(
        lhs_shape,
        rhs_shape,
        context,
        prefer_negative=True,
    )
    if negative is not None:
        return negative
    return _symbolic_fractional_numeric_witness_with_extra(
        lhs_shape,
        rhs_shape,
        context,
        prefer_negative=False,
    )


def _symbolic_fractional_numeric_witness_with_extra(
    lhs_shape: Any,
    rhs_shape: Any,
    context: ProofContext,
    *,
    prefer_negative: bool,
) -> Fraction | None:
    solver = SymbolicSolver(
        context, "numeric product", "numeric product exceeded proof work budget"
    )
    value = solver.real_var("number")
    constraints = [
        _numeric_shape_expr(solver, value, lhs_shape, "lhs_fractional"),
        solver.not_(_numeric_shape_expr(solver, value, rhs_shape, "rhs_fractional")),
        solver.not_(solver.is_int(value)),
    ]
    if prefer_negative:
        constraints.append(solver.lt(value, solver.real_value(0)))
    solver.add(
        *constraints,
    )
    check = solver.check_with_work(units=1)
    if check == SAT:
        return solver.model_real(solver.model(), "number")
    return None


def _numeric_shape_allows_fractional_value(shape: Any) -> bool:
    return any(
        not atom.normalized().all_values_are_integer()
        for atom in shape.normalized_atoms()
    )


def _nonnumeric_type_coverage_is_complete(
    lhs_type: TypeConstraint | None,
    rhs_type: TypeConstraint | None,
) -> bool:
    if lhs_type is None or rhs_type is None:
        return False
    nonnumeric = JSON_TYPE_ATOMS - {"integer", "number"}
    return (lhs_type.atoms & nonnumeric) <= (rhs_type.atoms & nonnumeric)


def _numeric_shape_expr(
    solver: SymbolicSolver, value: Any, shape: Any, prefix: str
) -> Any:
    atoms = tuple(shape.normalized_atoms())
    return solver.or_(
        *(
            _numeric_atom_expr(solver, value, atom, f"{prefix}_{index}")
            for index, atom in enumerate(atoms)
        )
    )


def _numeric_atom_expr(
    solver: SymbolicSolver, value: Any, atom: Any, prefix: str
) -> Any:
    atom = atom.normalized()
    constraints = []
    if atom.integer_only:
        constraints.append(solver.integer_real(value, f"{prefix}_integer"))
    if atom.lower is not None:
        lower = solver.real_value(atom.lower)
        constraints.append(
            solver.ge(value, lower) if atom.lower_inclusive else solver.gt(value, lower)
        )
    if atom.upper is not None:
        upper = solver.real_value(atom.upper)
        constraints.append(
            solver.le(value, upper) if atom.upper_inclusive else solver.lt(value, upper)
        )
    if atom.multiple_of is not None:
        constraints.append(
            solver.multiple_of(value, atom.multiple_of, f"{prefix}_multiple")
        )
    return solver.and_(*constraints)


def _json_number_from_fraction(value: Fraction) -> int | float:
    if value.denominator == 1:
        return int(value)
    return float(value)


def string_length_difference_plan(
    lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
) -> ScalarDifferencePlan:
    return string_length_difference_plan_from_constraints(
        lhs.string_length_constraint, rhs.string_length_constraint
    )


def string_length_difference_plan_from_constraints(
    lhs_constraint: StringLengthConstraint | None,
    rhs_constraint: StringLengthConstraint | None,
) -> ScalarDifferencePlan:
    if lhs_constraint is None or rhs_constraint is None:
        return ScalarDifferencePlan.unsupported(
            "SAT string-length fragment requires exact string shapes"
        )
    lhs_shape = lhs_constraint.shape
    rhs_shape = rhs_constraint.shape
    if lhs_shape.accepts_non_string:
        return ScalarDifferencePlan.unsupported("left schema is not string-only")
    if lhs_shape.is_subset_of(rhs_shape):
        return ScalarDifferencePlan.true()

    witness = lhs_shape.witness_not_in(rhs_shape)
    if witness is None:
        return ScalarDifferencePlan.unsupported(
            "SAT string-length fragment could not construct a witness"
        )
    return ScalarDifferencePlan.counterexample(
        witness, "SAT string-length witness was rejected by concrete validation"
    )


def string_language_difference_plan(
    lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
) -> ScalarDifferencePlan:
    return string_language_difference_plan_from_constraints(
        lhs.string_language_constraint,
        rhs.string_language_constraint,
    )


def string_language_difference_plan_from_constraints(
    lhs_constraint: StringLanguageConstraint | None,
    rhs_constraint: StringLanguageConstraint | None,
    *,
    context: ProofContext | None = None,
) -> ScalarDifferencePlan:
    _ = context
    if lhs_constraint is None or rhs_constraint is None:
        return ScalarDifferencePlan.unsupported(
            "SAT string-language fragment requires exact language shapes"
        )
    lhs_shape = lhs_constraint.shape
    rhs_shape = rhs_constraint.shape
    if lhs_shape.accepts_non_string:
        return ScalarDifferencePlan.unsupported("left schema is not string-only")
    if lhs_shape.is_subset_of(rhs_shape):
        return ScalarDifferencePlan.true()

    witness = lhs_shape.witness_not_in(rhs_shape)
    if witness is None:
        return ScalarDifferencePlan.unsupported(
            "SAT string-language fragment could not construct a witness"
        )
    return ScalarDifferencePlan.counterexample(
        witness, "SAT string-language witness was rejected by concrete validation"
    )


def _finite_rhs_atom_witnesses(
    atom: str, rhs_values: tuple[Any, ...]
) -> tuple[Any, ...]:
    return tuple(
        value
        for value in _FINITE_RHS_WITNESS_VALUES[atom]
        if all(not _json_values_equal(value, rhs_value) for rhs_value in rhs_values)
    )


def _finite_rhs_generic_witnesses(rhs_values: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(
        value
        for atom in sorted(JSON_TYPE_ATOMS)
        for value in _FINITE_RHS_WITNESS_VALUES[atom]
        if all(not _json_values_equal(value, rhs_value) for rhs_value in rhs_values)
    )


def _finite_rhs_numeric_witness(
    lhs_numeric: NumericConstraint | None,
    rhs_values: tuple[Any, ...],
) -> int | float | None:
    if lhs_numeric is None:
        return None
    rhs_numeric = _numeric_shape_for_finite_values(rhs_values)
    witness = lhs_numeric.shape.witness_not_in(rhs_numeric)
    if witness is None or any(
        _json_values_equal(witness, value) for value in rhs_values
    ):
        return None
    return witness


def _numeric_shape_for_finite_values(values: tuple[Any, ...]) -> NumericShape:
    atoms = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        fraction = Fraction(value)
        atoms.append(
            NumericAtom(
                integer_only=False,
                lower=fraction,
                lower_inclusive=True,
                upper=fraction,
                upper_inclusive=True,
            )
        )
    return NumericShape(tuple(atoms), accepts_non_numeric=False)


def _finite_values_for_type_constraint(
    lhs_type: TypeConstraint | None,
) -> tuple[Any, ...] | None:
    if lhs_type is None:
        return None
    atoms = lhs_type.atoms
    values = []
    if "null" in atoms:
        values.append(None)
    if "boolean" in atoms:
        values.extend((False, True))
    if atoms <= {"null", "boolean"}:
        return tuple(values)
    return None


def _dedupe_json_values(values: tuple[Any, ...]) -> tuple[Any, ...]:
    deduped = []
    for value in values:
        if any(_json_values_equal(value, existing) for existing in deduped):
            continue
        deduped.append(value)
    return tuple(deduped)


def _json_values_equal(lhs: Any, rhs: Any) -> bool:
    return json_values_equal(lhs, rhs)

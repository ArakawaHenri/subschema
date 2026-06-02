"""
Internal symbolic-solver adapter.

Only this module imports z3. Domain code should consume this small wrapper so
solver dependency details and budget accounting stay centralized.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import TYPE_CHECKING, Any

import z3

from subschema.kernel.contracts import ProofResult

if TYPE_CHECKING:
    from collections.abc import Iterable

    from subschema.kernel.context import ProofContext


@dataclass
class SymbolicSolver:
    context: ProofContext
    work_kind: str
    exhausted_reason: str
    solver: Any = field(default_factory=z3.Solver)
    _bools: dict[str, Any] = field(default_factory=dict)
    _ints: dict[str, Any] = field(default_factory=dict)
    _reals: dict[str, Any] = field(default_factory=dict)

    def bool_var(self, name: str) -> Any:
        if name not in self._bools:
            self._bools[name] = z3.Bool(name)
        return self._bools[name]

    def bool_vars(self, names: Iterable[str]) -> dict[str, Any]:
        return {name: self.bool_var(name) for name in names}

    def int_var(self, name: str) -> Any:
        if name not in self._ints:
            self._ints[name] = z3.Int(name)
        return self._ints[name]

    def real_var(self, name: str) -> Any:
        if name not in self._reals:
            self._reals[name] = z3.Real(name)
        return self._reals[name]

    def add(self, *constraints: Any) -> None:
        self.solver.add(*constraints)

    def eq(self, lhs: Any, rhs: Any) -> Any:
        return lhs == rhs

    def ge(self, lhs: Any, rhs: Any) -> Any:
        return lhs >= rhs

    def gt(self, lhs: Any, rhs: Any) -> Any:
        return lhs > rhs

    def le(self, lhs: Any, rhs: Any) -> Any:
        return lhs <= rhs

    def lt(self, lhs: Any, rhs: Any) -> Any:
        return lhs < rhs

    def and_(self, *constraints: Any) -> Any:
        if not constraints:
            return z3.BoolVal(True)
        return z3.And(*constraints)

    def or_(self, *constraints: Any) -> Any:
        if not constraints:
            return z3.BoolVal(False)
        return z3.Or(*constraints)

    def not_(self, constraint: Any) -> Any:
        return z3.Not(constraint)

    def is_int(self, value: Any) -> Any:
        return z3.IsInt(value)

    def implies(self, lhs: Any, rhs: Any) -> Any:
        return z3.Implies(lhs, rhs)

    def exactly_one(self, constraints: Iterable[Any]) -> Any:
        return self.cardinality_eq(tuple(constraints), 1)

    def cardinality_ge(self, constraints: Iterable[Any], minimum: int) -> Any:
        constraints = tuple(constraints)
        if minimum <= 0:
            return z3.BoolVal(True)
        if minimum > len(constraints):
            return z3.BoolVal(False)
        return z3.PbGe([(constraint, 1) for constraint in constraints], minimum)

    def cardinality_le(self, constraints: Iterable[Any], maximum: int) -> Any:
        constraints = tuple(constraints)
        if maximum < 0:
            return z3.BoolVal(False)
        if maximum >= len(constraints):
            return z3.BoolVal(True)
        return z3.PbLe([(constraint, 1) for constraint in constraints], maximum)

    def cardinality_eq(self, constraints: Iterable[Any], count: int) -> Any:
        constraints = tuple(constraints)
        if count < 0 or count > len(constraints):
            return z3.BoolVal(False)
        return z3.PbEq([(constraint, 1) for constraint in constraints], count)

    def sum_bools(self, constraints: Iterable[Any]) -> Any:
        return z3.Sum([z3.If(constraint, 1, 0) for constraint in constraints])

    def finite_choice(self, name: str, values: Iterable[int]) -> Any:
        values = tuple(values)
        if any(isinstance(value, bool) for value in values):
            raise ValueError(
                "symbolic finite choices must be JSON integers, not booleans"
            )
        if any(not isinstance(value, int) for value in values):
            raise TypeError("symbolic finite choices must be integers")
        var = self.int_var(name)
        return self.or_(*(self.eq(var, value) for value in values))

    def integer_real(self, value: Any, name: str) -> Any:
        _ = name
        return self.is_int(value)

    def multiple_of(self, value: Any, multiple: Fraction, name: str) -> Any:
        _ = name
        return self.is_int(value / self.real_value(multiple))

    def real_value(self, value: Fraction | int) -> Any:
        if isinstance(value, bool):
            raise ValueError("symbolic real values must be JSON numbers, not booleans")
        fraction = value if isinstance(value, Fraction) else Fraction(value)
        return z3.Q(fraction.numerator, fraction.denominator)

    def check(self, *, units: int = 1) -> ProofResult | Any:
        exhausted = self.context.spend_work(
            units, self.work_kind, self.exhausted_reason
        )
        if exhausted is not None:
            return exhausted
        timeout = self.context.options.budgets.timeout_ms
        if timeout >= 0:
            self.solver.set(timeout=timeout)
        result = self.solver.check()
        if result == z3.unknown:
            reason = self.solver.reason_unknown()
            if "timeout" in reason.lower():
                return ProofResult.resource_exhausted(
                    f"{self.work_kind} exceeded timeout"
                )
            return ProofResult.unsupported(
                f"{self.work_kind} solver returned unknown: {reason or 'unknown'}"
            )
        return result

    def check_with_work(self, *, units: int = 1) -> ProofResult | Any:
        return self.check(units=units)

    def model(self) -> Any:
        return self.solver.model()

    def bool_value(self, model: Any, name: str) -> bool:
        value = model.evaluate(self.bool_var(name), model_completion=True)
        return z3.is_true(value)

    def model_bool_set(self, model: Any, names: Iterable[str]) -> frozenset[str]:
        return frozenset(name for name in names if self.bool_value(model, name))

    def model_int(self, model: Any, name: str) -> int:
        value = model.evaluate(self.int_var(name), model_completion=True)
        return value.as_long()

    def model_real(self, model: Any, name: str) -> Fraction:
        value = model.evaluate(self.real_var(name), model_completion=True)
        return self.z3_number_as_fraction(value)

    def z3_number_as_fraction(self, value: Any) -> Fraction:
        if hasattr(value, "as_long"):
            try:
                return Fraction(value.as_long())
            except (ValueError, z3.Z3Exception):
                pass
        if hasattr(value, "as_fraction"):
            return value.as_fraction()
        if hasattr(value, "numerator_as_long") and hasattr(
            value, "denominator_as_long"
        ):
            return Fraction(value.numerator_as_long(), value.denominator_as_long())
        decimal = value.as_decimal(50).rstrip("?")
        return Fraction(decimal)


SAT = z3.sat
UNSAT = z3.unsat

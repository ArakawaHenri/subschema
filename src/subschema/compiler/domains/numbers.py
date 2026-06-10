"""
Numeric interval and multipleOf reasoning for exact subschema proofs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, TypeGuard

from subschema.compiler.domains.types import (
    JSON_TYPE_ATOMS,
    type_overapproximation_for_schema,
)
from subschema.compiler.schemas import (
    IGNORED_SCHEMA_METADATA_KEYS,
    contains_reference_keyword,
    transparent_schema_target,
)
from subschema.dialects import Dialect

__all__ = [
    "NUMERIC_SCHEMA_KEYWORDS",
    "NumericAtom",
    "NumericShape",
    "numeric_shape_for_schema",
]

NUMERIC_SCHEMA_KEYWORDS = frozenset(
    {
        "allOf",
        "anyOf",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maximum",
        "minimum",
        "multipleOf",
        "not",
        "type",
    }
)

@dataclass(frozen=True)
class NumericShape:
    atoms: tuple[NumericAtom, ...]
    accepts_non_numeric: bool
    exact: bool = True

    def normalized_atoms(self) -> tuple[NumericAtom, ...]:
        return tuple(atom for atom in self.atoms if not atom.is_empty())

    def numeric_subset_of(self, other: NumericShape) -> bool | None:
        for atom in self.normalized_atoms():
            covered = atom.is_covered_by(other)
            if covered is True:
                continue
            if atom.witness_not_in(other) is not None:
                return False
            if covered is False:
                return False
            return None
        return True

    def witness_not_in(self, other: NumericShape) -> int | float | None:
        for atom in self.normalized_atoms():
            witness = atom.witness_not_in(other)
            if witness is not None:
                return witness
        return None

    def contains(self, value: Fraction) -> bool:
        return any(atom.contains(value) for atom in self.normalized_atoms())

    def intersect(self, other: NumericShape) -> NumericShape:
        atoms = [
            lhs.intersect(rhs)
            for lhs in self.normalized_atoms()
            for rhs in other.normalized_atoms()
        ]
        return NumericShape(
            tuple(atom for atom in atoms if not atom.is_empty()),
            self.accepts_non_numeric and other.accepts_non_numeric,
            self.exact and other.exact,
        )

    def union(self, other: NumericShape) -> NumericShape:
        return NumericShape(
            self.normalized_atoms() + other.normalized_atoms(),
            self.accepts_non_numeric or other.accepts_non_numeric,
            self.exact and other.exact,
        )


@dataclass(frozen=True)
class NumericAtom:
    integer_only: bool
    lower: Fraction | None = None
    lower_inclusive: bool = True
    upper: Fraction | None = None
    upper_inclusive: bool = True
    multiple_of: Fraction | None = None

    def normalized(self) -> NumericAtom:
        if not self.integer_only:
            return self

        lower = self.lower
        upper = self.upper
        if lower is not None:
            lower = _ceil_fraction(lower)
            if not self.lower_inclusive and lower == self.lower:
                lower += 1
        if upper is not None:
            upper = _floor_fraction(upper)
            if not self.upper_inclusive and upper == self.upper:
                upper -= 1

        return NumericAtom(
            integer_only=True,
            lower=lower,
            lower_inclusive=True,
            upper=upper,
            upper_inclusive=True,
            multiple_of=self.multiple_of,
        )

    def is_empty(self) -> bool:
        atom = self.normalized()
        if atom.lower is not None and atom.upper is not None:
            if atom.lower > atom.upper:
                return True
            if atom.lower == atom.upper and (
                not atom.lower_inclusive or not atom.upper_inclusive
            ):
                return True
        return atom.some_fraction() is None

    def is_subset_of(self, other: NumericAtom) -> bool:
        atom = self.normalized()
        other = other.normalized()
        if atom.is_empty():
            return True
        if other.is_empty():
            return False
        if other.integer_only and not atom.all_values_are_integer():
            return False
        if not atom.bounds_subset_of(other):
            return False
        return atom.multiple_subset_of(other)

    def is_covered_by(self, other: NumericShape) -> bool | None:
        atom = self.normalized()
        if atom.is_empty():
            return True
        if any(
            atom.is_subset_of(other_atom) for other_atom in other.normalized_atoms()
        ):
            return True
        finite_values = atom.finite_values(max_values=4096)
        if finite_values is not None:
            return all(other.contains(value) for value in finite_values)
        return atom.interval_covered_by(other)

    def all_values_are_integer(self) -> bool:
        if self.integer_only:
            return True
        return self.multiple_of is not None and self.multiple_of.denominator == 1

    def bounds_subset_of(self, other: NumericAtom) -> bool:
        if other.lower is not None:
            if self.lower is None:
                return False
            if self.lower < other.lower:
                return False
            if (
                self.lower == other.lower
                and not other.lower_inclusive
                and self.lower_inclusive
            ):
                return False
        if other.upper is not None:
            if self.upper is None:
                return False
            if self.upper > other.upper:
                return False
            if (
                self.upper == other.upper
                and not other.upper_inclusive
                and self.upper_inclusive
            ):
                return False
        return True

    def multiple_subset_of(self, other: NumericAtom) -> bool:
        if other.multiple_of is None:
            return True
        if self.multiple_of is None:
            return self.integer_only and _is_fraction_multiple(
                Fraction(1), other.multiple_of
            )
        return _is_fraction_multiple(self.multiple_of, other.multiple_of)

    def intersect(self, other: NumericAtom) -> NumericAtom:
        lower, lower_inclusive = _stronger_lower(
            self.lower,
            self.lower_inclusive,
            other.lower,
            other.lower_inclusive,
        )
        upper, upper_inclusive = _stronger_upper(
            self.upper,
            self.upper_inclusive,
            other.upper,
            other.upper_inclusive,
        )
        return NumericAtom(
            integer_only=self.integer_only or other.integer_only,
            lower=lower,
            lower_inclusive=lower_inclusive,
            upper=upper,
            upper_inclusive=upper_inclusive,
            multiple_of=_lcm_fraction(self.multiple_of, other.multiple_of),
        )

    def contains(self, value: Fraction) -> bool:
        atom = self.normalized()
        if atom.integer_only and value.denominator != 1:
            return False
        if atom.lower is not None:
            if value < atom.lower or (value == atom.lower and not atom.lower_inclusive):
                return False
        if atom.upper is not None:
            if value > atom.upper or (value == atom.upper and not atom.upper_inclusive):
                return False
        if atom.multiple_of is not None and not _is_fraction_multiple(
            value, atom.multiple_of
        ):
            return False
        return True

    def some_fraction(self) -> Fraction | None:
        for candidate in self.candidate_fractions():
            if self.contains(candidate):
                return candidate
        return None

    def witness_not_in(self, other: NumericShape) -> int | float | None:
        for candidate in self.candidate_fractions(other):
            if self.contains(candidate) and not other.contains(candidate):
                return _json_number(candidate)
        return None

    def candidate_fractions(self, other: NumericShape | None = None) -> list[Fraction]:
        atom = self.normalized()
        candidates = {Fraction(0), Fraction(1), Fraction(-1)}
        if not atom.integer_only:
            candidates.update({Fraction(1, 2), Fraction(-1, 2)})
        if atom.multiple_of is not None:
            for multiplier in range(-4, 5):
                candidates.add(atom.multiple_of * multiplier)
        for bound in (atom.lower, atom.upper):
            if bound is None:
                continue
            candidates.add(bound)
            candidates.add(bound + 1)
            candidates.add(bound - 1)
            if not atom.integer_only:
                candidates.add(bound + Fraction(1, 2))
                candidates.add(bound - Fraction(1, 2))
            if atom.multiple_of is not None:
                nearest_above = _first_multiple_at_or_above(bound, atom.multiple_of)
                nearest_below = _last_multiple_at_or_below(bound, atom.multiple_of)
                candidates.update(
                    {
                        nearest_above,
                        nearest_above + atom.multiple_of,
                        nearest_below,
                        nearest_below - atom.multiple_of,
                    }
                )
        if atom.lower is not None and atom.upper is not None:
            candidates.add((atom.lower + atom.upper) / 2)
        if other is not None:
            for other_atom in other.normalized_atoms():
                candidates.update(atom.boundary_candidates_for(other_atom))
                if other_atom.multiple_of is not None:
                    candidates.update(
                        atom.non_multiple_candidates_for(other_atom.multiple_of)
                    )
        return _ordered_numeric_candidates(
            candidates, prefer_fractional=not atom.integer_only
        )

    def boundary_candidates_for(self, other: NumericAtom) -> set[Fraction]:
        other = other.normalized()
        candidates: set[Fraction] = set()
        for bound in (other.lower, other.upper):
            if bound is None:
                continue
            candidates.add(bound)
            candidates.add(bound + 1)
            candidates.add(bound - 1)
            if not self.integer_only:
                candidates.add(bound + Fraction(1, 2))
                candidates.add(bound - Fraction(1, 2))
            if self.multiple_of is not None:
                nearest_above = _first_multiple_at_or_above(bound, self.multiple_of)
                nearest_below = _last_multiple_at_or_below(bound, self.multiple_of)
                candidates.update(
                    {
                        nearest_above,
                        nearest_above + self.multiple_of,
                        nearest_below,
                        nearest_below - self.multiple_of,
                    }
                )
        return candidates

    def non_multiple_candidates_for(self, multiple_of: Fraction) -> set[Fraction]:
        step = abs(multiple_of)
        if step == 0:
            return set()

        bases = {Fraction(0)}
        if self.lower is not None:
            bases.add(self.lower)
            bases.add(_first_multiple_at_or_above(self.lower, step))
        if self.upper is not None:
            bases.add(self.upper)
            bases.add(_last_multiple_at_or_below(self.upper, step))
        if self.lower is not None and self.upper is not None:
            bases.add((self.lower + self.upper) / 2)

        offsets = (step / 2, -step / 2, step / 3, -step / 3)
        return {base + offset for base in bases for offset in offsets}

    def finite_values(self, *, max_values: int) -> tuple[Fraction, ...] | None:
        atom = self.normalized()
        if atom.lower is None or atom.upper is None:
            return None
        if atom.integer_only:
            start = int(atom.lower)
            end = int(atom.upper)
            count = end - start + 1
            if count < 0 or count > max_values:
                return None
            return tuple(
                Fraction(value)
                for value in range(start, end + 1)
                if atom.contains(Fraction(value))
            )
        if atom.multiple_of is None:
            return None
        first = _first_multiple_at_or_above(atom.lower, atom.multiple_of)
        values = []
        value = first
        while value <= atom.upper:
            if atom.contains(value):
                values.append(value)
            if len(values) > max_values:
                return None
            value += atom.multiple_of
        return tuple(values)

    def interval_covered_by(self, other: NumericShape) -> bool | None:
        atom = self.normalized()
        if atom.multiple_of is not None:
            return None
        intervals = [
            interval
            for other_atom in other.normalized_atoms()
            if (interval := _coverage_interval_for(atom, other_atom)) is not None
        ]
        if not intervals:
            return False
        return _intervals_cover_atom(atom, intervals)


def numeric_shape_for_schema(
    schema: Any, dialect: Dialect, depth: int = 0
) -> NumericShape | None:
    if depth > 8:
        return None
    if schema is False:
        return NumericShape((), accepts_non_numeric=False)
    if schema is True:
        return NumericShape(
            (NumericAtom(integer_only=False),), accepts_non_numeric=True
        )
    if not isinstance(schema, dict):
        return None
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return None
    transparent_target = transparent_schema_target(schema)
    if transparent_target is not None:
        return numeric_shape_for_schema(transparent_target, dialect, depth + 1)
    if not _is_numeric_fragment_schema(schema):
        return None
    if any(
        keyword in schema
        for keyword in {"const", "enum", "oneOf", "if", "then", "else"}
    ):
        return None
    if "not" in schema and type_overapproximation_for_schema(schema["not"]) & {
        "integer",
        "number",
    }:
        return None

    shape = _local_numeric_shape(schema, dialect)
    if shape is None:
        return None
    if "not" in schema:
        shape = NumericShape(
            shape.atoms,
            shape.accepts_non_numeric,
            exact=not bool(
                type_overapproximation_for_schema(schema["not"])
                - {"integer", "number"}
            ),
        )

    for subschema in schema.get("allOf", []):
        branch = numeric_shape_for_schema(subschema, dialect, depth + 1)
        if branch is None:
            return None
        shape = shape.intersect(branch)

    if "anyOf" in schema:
        union_shape = NumericShape((), accepts_non_numeric=False)
        for subschema in schema["anyOf"]:
            branch = numeric_shape_for_schema(subschema, dialect, depth + 1)
            if branch is None:
                return None
            union_shape = union_shape.union(branch)
        shape = shape.intersect(union_shape)

    return shape


def _is_numeric_fragment_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in NUMERIC_SCHEMA_KEYWORDS:
            return False
        if key in {"allOf", "anyOf"} and not isinstance(value, list):
            return False
    return True


def _local_numeric_shape(
    schema: dict[str, Any], dialect: Dialect
) -> NumericShape | None:
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        types = {schema_type}
    elif isinstance(schema_type, list):
        if not all(isinstance(item, str) for item in schema_type):
            return None
        types = set(schema_type)
    elif schema_type is None:
        types = {"number"}
    else:
        return None

    numeric_types = types & {"number", "integer"}
    accepts_non_numeric = schema_type is None or bool(types - {"number", "integer"})
    exact = (
        not accepts_non_numeric
        or schema_type is None
        or JSON_TYPE_ATOMS - {"number", "integer"} <= types
    )
    if not numeric_types:
        return NumericShape((), accepts_non_numeric=accepts_non_numeric, exact=exact)

    if "number" in numeric_types:
        atom = NumericAtom(integer_only=False)
    elif "integer" in numeric_types:
        atom = NumericAtom(integer_only=True)
    else:
        return NumericShape((), accepts_non_numeric=accepts_non_numeric, exact=exact)

    applied_atom = _apply_numeric_keywords(atom, schema, dialect)
    if applied_atom is None:
        return None
    return NumericShape(
        (applied_atom,), accepts_non_numeric=accepts_non_numeric, exact=exact
    )


def _apply_numeric_keywords(
    atom: NumericAtom, schema: dict[str, Any], dialect: Dialect
) -> NumericAtom | None:
    lower = atom.lower
    lower_inclusive = atom.lower_inclusive
    upper = atom.upper
    upper_inclusive = atom.upper_inclusive

    if _is_number(schema.get("minimum")):
        lower, lower_inclusive = _stronger_lower(
            lower, lower_inclusive, _fraction(schema["minimum"]), True
        )
    if _is_number(schema.get("maximum")):
        upper, upper_inclusive = _stronger_upper(
            upper, upper_inclusive, _fraction(schema["maximum"]), True
        )

    exclusive_minimum = schema.get("exclusiveMinimum")
    if isinstance(exclusive_minimum, bool):
        if exclusive_minimum and _is_number(schema.get("minimum")):
            lower, lower_inclusive = _stronger_lower(
                lower,
                lower_inclusive,
                _fraction(schema["minimum"]),
                False,
            )
    elif _is_number(exclusive_minimum) and dialect is not Dialect.DRAFT4:
        lower, lower_inclusive = _stronger_lower(
            lower, lower_inclusive, _fraction(exclusive_minimum), False
        )

    exclusive_maximum = schema.get("exclusiveMaximum")
    if isinstance(exclusive_maximum, bool):
        if exclusive_maximum and _is_number(schema.get("maximum")):
            upper, upper_inclusive = _stronger_upper(
                upper,
                upper_inclusive,
                _fraction(schema["maximum"]),
                False,
            )
    elif _is_number(exclusive_maximum) and dialect is not Dialect.DRAFT4:
        upper, upper_inclusive = _stronger_upper(
            upper, upper_inclusive, _fraction(exclusive_maximum), False
        )

    multiple_of = atom.multiple_of
    if _is_number(schema.get("multipleOf")):
        schema_multiple_of = _fraction(schema["multipleOf"])
        multiple_of = _lcm_fraction(multiple_of, schema_multiple_of)

    return NumericAtom(
        integer_only=atom.integer_only,
        lower=lower,
        lower_inclusive=lower_inclusive,
        upper=upper,
        upper_inclusive=upper_inclusive,
        multiple_of=multiple_of,
    )


def _stronger_lower(
    lhs_value: Fraction | None,
    lhs_inclusive: bool,
    rhs_value: Fraction | None,
    rhs_inclusive: bool,
) -> tuple[Fraction | None, bool]:
    if lhs_value is None:
        return rhs_value, rhs_inclusive
    if rhs_value is None:
        return lhs_value, lhs_inclusive
    if lhs_value > rhs_value:
        return lhs_value, lhs_inclusive
    if rhs_value > lhs_value:
        return rhs_value, rhs_inclusive
    return lhs_value, lhs_inclusive and rhs_inclusive


def _stronger_upper(
    lhs_value: Fraction | None,
    lhs_inclusive: bool,
    rhs_value: Fraction | None,
    rhs_inclusive: bool,
) -> tuple[Fraction | None, bool]:
    if lhs_value is None:
        return rhs_value, rhs_inclusive
    if rhs_value is None:
        return lhs_value, lhs_inclusive
    if lhs_value < rhs_value:
        return lhs_value, lhs_inclusive
    if rhs_value < lhs_value:
        return rhs_value, rhs_inclusive
    return lhs_value, lhs_inclusive and rhs_inclusive


def _lcm_fraction(lhs: Fraction | None, rhs: Fraction | None) -> Fraction | None:
    if lhs is None:
        return rhs
    if rhs is None:
        return lhs
    return Fraction(
        math.lcm(lhs.numerator, rhs.numerator),
        math.gcd(lhs.denominator, rhs.denominator),
    )


def _coverage_interval_for(
    lhs: NumericAtom, rhs: NumericAtom
) -> tuple[int | None, int | None] | None:
    if not lhs.integer_only or lhs.multiple_of is not None:
        return None

    rhs = rhs.normalized()
    if rhs.multiple_of is not None and not _is_fraction_multiple(
        Fraction(1), rhs.multiple_of
    ):
        return None

    lower = None
    if rhs.lower is not None:
        lower_fraction = _ceil_fraction(rhs.lower)
        if not rhs.lower_inclusive and lower_fraction == rhs.lower:
            lower_fraction += 1
        lower = int(lower_fraction)
    upper = None
    if rhs.upper is not None:
        upper_fraction = _floor_fraction(rhs.upper)
        if not rhs.upper_inclusive and upper_fraction == rhs.upper:
            upper_fraction -= 1
        upper = int(upper_fraction)
    if lower is not None and upper is not None and lower > upper:
        return None
    return lower, upper


def _intervals_cover_atom(
    atom: NumericAtom, intervals: list[tuple[int | None, int | None]]
) -> bool:
    if not atom.integer_only:
        return False

    lhs = atom.normalized()
    target_start = None if lhs.lower is None else int(lhs.lower)
    target_end = None if lhs.upper is None else int(lhs.upper)
    current = target_start

    for start, end in sorted(
        intervals, key=lambda interval: (interval[0] is not None, interval[0] or 0)
    ):
        if current is None:
            if start is not None:
                return False
        elif start is not None and start > current:
            return False

        if end is None:
            return True
        current = end + 1 if current is None else max(current, end + 1)
        if target_end is not None and current > target_end:
            return True

    return target_end is not None and current is not None and current > target_end


def _is_fraction_multiple(value: Fraction, multiple_of: Fraction) -> bool:
    return (value / multiple_of).denominator == 1


def _ceil_fraction(value: Fraction) -> Fraction:
    return Fraction(math.ceil(value))


def _floor_fraction(value: Fraction) -> Fraction:
    return Fraction(math.floor(value))


def _first_multiple_at_or_above(value: Fraction, multiple_of: Fraction) -> Fraction:
    return multiple_of * math.ceil(value / multiple_of)


def _last_multiple_at_or_below(value: Fraction, multiple_of: Fraction) -> Fraction:
    return multiple_of * math.floor(value / multiple_of)


def _is_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _fraction(value: int | float) -> Fraction:
    return Fraction(str(value))


def _json_number(value: Fraction) -> int | float:
    if value.denominator == 1:
        return int(value)
    return float(value)


def _ordered_numeric_candidates(
    candidates: set[Fraction], *, prefer_fractional: bool
) -> list[Fraction]:
    return sorted(
        candidates,
        key=lambda value: (
            prefer_fractional and value.denominator == 1,
            abs(value),
            value,
        ),
    )

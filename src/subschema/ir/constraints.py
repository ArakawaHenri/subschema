"""
Typed assertion constraints compiled into SchemaIR.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Literal

from subschema.contracts import ProofResult
from subschema.ir.terms import SchemaTerm
from subschema.regex import RegexLanguage
from subschema.work_protocols import RegexWorkContext

JSON_TYPE_ATOMS = frozenset(
    {"null", "boolean", "integer", "number", "string", "array", "object"}
)

__all__ = [
    "ArrayAnyOfItemSchemasConstraint",
    "ArrayContainsConstraint",
    "ArrayContainsFragmentConstraint",
    "ArrayItemValuesFragmentConstraint",
    "ArrayItemModelConstraint",
    "ArrayLengthIntervalFact",
    "ArrayLengthConstraint",
    "ArrayTupleAnyOfDistributionConstraint",
    "ArrayUniquenessConstraint",
    "FiniteConstraint",
    "NumericConstraint",
    "NumericAtomFact",
    "ObjectClosedPropertiesConstraint",
    "ObjectDependentRequiredConstraint",
    "ObjectDependentRequiredEntry",
    "ObjectDependentSchemaPropertiesConstraint",
    "ObjectDependentSchemaProperty",
    "ObjectKeyValueConstraint",
    "ObjectKeyValuePattern",
    "ObjectKeyValueWitnessSkeleton",
    "ObjectKeyValueWitnessSlot",
    "ObjectPresenceLocalConstraint",
    "ObjectPresenceProductConstraint",
    "ObjectPropertyCountBoundsConstraint",
    "ObjectPropertyCountIntervalFact",
    "ObjectPropertyCountConstraint",
    "ObjectPropertyNamesConstraint",
    "ObjectPropertyValuesConstraint",
    "StringLanguageConstraint",
    "StringLengthIntervalFact",
    "StringLengthConstraint",
    "TypeConstraint",
    "type_atom_witness",
]


@dataclass(frozen=True)
class FiniteConstraint:
    values: tuple[Any, ...]
    requires_confirmation: bool = True


@dataclass(frozen=True)
class TypeConstraint:
    atoms: frozenset[str]
    language_complete: bool = True

    def is_subset_of(self, other: TypeConstraint) -> bool:
        return self.atoms <= other.atoms

    def witness_not_in(self, other: TypeConstraint) -> Any | None:
        for atom in sorted(self.atoms - other.atoms):
            return type_atom_witness(atom)
        return None

    def intersect(self, other: TypeConstraint) -> TypeConstraint:
        return TypeConstraint(self.atoms & other.atoms)

    def union(self, other: TypeConstraint) -> TypeConstraint:
        return TypeConstraint(self.atoms | other.atoms)

    def complement(self) -> TypeConstraint:
        return TypeConstraint(JSON_TYPE_ATOMS - self.atoms)


@dataclass(frozen=True)
class NumericAtomFact:
    integer_only: bool
    lower: Fraction | None = None
    lower_inclusive: bool = True
    upper: Fraction | None = None
    upper_inclusive: bool = True
    multiple_of: Fraction | None = None

    def normalized(self) -> NumericAtomFact:
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

        return NumericAtomFact(
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

    def is_subset_of(self, other: NumericAtomFact) -> bool:
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

    def is_covered_by(self, other: NumericConstraint) -> bool | None:
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

    def bounds_subset_of(self, other: NumericAtomFact) -> bool:
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

    def multiple_subset_of(self, other: NumericAtomFact) -> bool:
        if other.multiple_of is None:
            return True
        if self.multiple_of is None:
            return self.integer_only and _is_fraction_multiple(
                Fraction(1), other.multiple_of
            )
        return _is_fraction_multiple(self.multiple_of, other.multiple_of)

    def intersect(self, other: NumericAtomFact) -> NumericAtomFact:
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
        return NumericAtomFact(
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

    def witness_not_in(self, other: NumericConstraint) -> int | float | None:
        for candidate in self.candidate_fractions(other):
            if self.contains(candidate) and not other.contains(candidate):
                return _json_number(candidate)
        return None

    def candidate_fractions(
        self, other: NumericConstraint | None = None
    ) -> list[Fraction]:
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

    def boundary_candidates_for(self, other: NumericAtomFact) -> set[Fraction]:
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

    def interval_covered_by(self, other: NumericConstraint) -> bool | None:
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


@dataclass(frozen=True)
class NumericConstraint:
    atoms: tuple[NumericAtomFact, ...]
    accepts_non_numeric: bool
    exact: bool = True

    def normalized_atoms(self) -> tuple[NumericAtomFact, ...]:
        return tuple(atom for atom in self.atoms if not atom.is_empty())

    def numeric_subset_of(self, other: NumericConstraint) -> bool | None:
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

    def witness_not_in(self, other: NumericConstraint) -> int | float | None:
        for atom in self.normalized_atoms():
            witness = atom.witness_not_in(other)
            if witness is not None:
                return witness
        return None

    def contains(self, value: Fraction) -> bool:
        return any(atom.contains(value) for atom in self.normalized_atoms())

    def intersect(self, other: NumericConstraint) -> NumericConstraint:
        atoms = [
            lhs.intersect(rhs)
            for lhs in self.normalized_atoms()
            for rhs in other.normalized_atoms()
        ]
        return NumericConstraint(
            tuple(atom for atom in atoms if not atom.is_empty()),
            self.accepts_non_numeric and other.accepts_non_numeric,
            self.exact and other.exact,
        )

    def union(self, other: NumericConstraint) -> NumericConstraint:
        return NumericConstraint(
            self.normalized_atoms() + other.normalized_atoms(),
            self.accepts_non_numeric or other.accepts_non_numeric,
            self.exact and other.exact,
        )


@dataclass(frozen=True)
class StringLengthIntervalFact:
    lower: int = 0
    upper: int | None = None

    def is_empty(self) -> bool:
        return self.upper is not None and self.lower > self.upper

    def intersect(
        self, other: StringLengthIntervalFact
    ) -> StringLengthIntervalFact:
        lower = max(self.lower, other.lower)
        if self.upper is None:
            upper = other.upper
        elif other.upper is None:
            upper = self.upper
        else:
            upper = min(self.upper, other.upper)
        return StringLengthIntervalFact(lower, upper)


@dataclass(frozen=True)
class StringLengthConstraint:
    intervals: tuple[StringLengthIntervalFact, ...]
    accepts_non_string: bool
    exact: bool = True

    def normalized_intervals(self) -> tuple[StringLengthIntervalFact, ...]:
        return _merge_string_intervals(
            tuple(interval for interval in self.intervals if not interval.is_empty())
        )

    def is_subset_of(self, other: StringLengthConstraint) -> bool:
        if self.accepts_non_string and not other.accepts_non_string:
            return False
        return all(
            _string_interval_covered(interval, other.normalized_intervals())
            for interval in self.normalized_intervals()
        )

    def witness_not_in(self, other: StringLengthConstraint) -> str | None:
        for interval in self.normalized_intervals():
            length = _first_uncovered_string_length(
                interval, other.normalized_intervals()
            )
            if length is not None:
                return "a" * length
        return None

    def intersect(self, other: StringLengthConstraint) -> StringLengthConstraint:
        intervals = [
            lhs.intersect(rhs)
            for lhs in self.normalized_intervals()
            for rhs in other.normalized_intervals()
        ]
        return StringLengthConstraint(
            _merge_string_intervals(
                tuple(interval for interval in intervals if not interval.is_empty())
            ),
            self.accepts_non_string and other.accepts_non_string,
            self.exact and other.exact,
        )

    def union(self, other: StringLengthConstraint) -> StringLengthConstraint:
        return StringLengthConstraint(
            _merge_string_intervals(
                self.normalized_intervals() + other.normalized_intervals()
            ),
            self.accepts_non_string or other.accepts_non_string,
            self.exact and other.exact,
        )

    def complement(self) -> StringLengthConstraint:
        return StringLengthConstraint(
            _complement_string_intervals(self.normalized_intervals()),
            not self.accepts_non_string,
            self.exact,
        )

    def exact_complement(self) -> StringLengthConstraint | None:
        if not self.exact:
            return None
        return self.complement()


@dataclass(frozen=True)
class StringLanguageConstraint:
    pattern: RegexLanguage
    accepts_non_string: bool
    exact: bool = True

    def is_subset_of(
        self, other: StringLanguageConstraint, context: RegexWorkContext | None = None
    ) -> bool | ProofResult:
        if self.accepts_non_string and not other.accepts_non_string:
            return False
        return self.pattern.is_subset_of(other.pattern, context)

    def witness_not_in(
        self, other: StringLanguageConstraint, context: RegexWorkContext | None = None
    ) -> str | ProofResult | None:
        difference = self.pattern.difference(other.pattern, context)
        if isinstance(difference, ProofResult):
            return difference
        return _string_language_witness(difference, context)

    def intersect(self, other: StringLanguageConstraint) -> StringLanguageConstraint:
        return StringLanguageConstraint(
            _expect_regex_language(self.pattern.intersection(other.pattern)),
            self.accepts_non_string and other.accepts_non_string,
            self.exact and other.exact,
        )

    def union(self, other: StringLanguageConstraint) -> StringLanguageConstraint:
        return StringLanguageConstraint(
            _expect_regex_language(self.pattern.union(other.pattern)),
            self.accepts_non_string or other.accepts_non_string,
            self.exact and other.exact,
        )

    def complement(self) -> StringLanguageConstraint:
        return StringLanguageConstraint(
            _expect_regex_language(self.pattern.complement()),
            not self.accepts_non_string,
            self.exact,
        )

    def exact_complement(self) -> StringLanguageConstraint | None:
        if not self.exact:
            return None
        return self.complement()


@dataclass(frozen=True)
class ArrayLengthConstraint:
    intervals: tuple[ArrayLengthIntervalFact, ...]
    accepts_non_array: bool
    exact: bool = True

    def normalized_intervals(self) -> tuple[ArrayLengthIntervalFact, ...]:
        return _merge_array_intervals(
            tuple(interval for interval in self.intervals if not interval.is_empty())
        )

    def is_subset_of(self, other: ArrayLengthConstraint) -> bool:
        if self.accepts_non_array and not other.accepts_non_array:
            return False
        return all(
            _array_interval_covered(interval, other.normalized_intervals())
            for interval in self.normalized_intervals()
        )

    def witness_not_in(self, other: ArrayLengthConstraint) -> list[Any] | None:
        length = self.witness_length_not_in(other)
        if length is None:
            return None
        return [None] * length

    def witness_length_not_in(self, other: ArrayLengthConstraint) -> int | None:
        for interval in self.normalized_intervals():
            length = _first_uncovered_array_length(
                interval, other.normalized_intervals()
            )
            if length is not None:
                return length
        return None

    def intersect(self, other: ArrayLengthConstraint) -> ArrayLengthConstraint:
        intervals = [
            lhs.intersect(rhs)
            for lhs in self.normalized_intervals()
            for rhs in other.normalized_intervals()
        ]
        return ArrayLengthConstraint(
            _merge_array_intervals(
                tuple(interval for interval in intervals if not interval.is_empty())
            ),
            self.accepts_non_array and other.accepts_non_array,
            self.exact and other.exact,
        )

    def union(self, other: ArrayLengthConstraint) -> ArrayLengthConstraint:
        return ArrayLengthConstraint(
            _merge_array_intervals(
                self.normalized_intervals() + other.normalized_intervals()
            ),
            self.accepts_non_array or other.accepts_non_array,
            self.exact and other.exact,
        )

    def complement(self) -> ArrayLengthConstraint:
        return ArrayLengthConstraint(
            _complement_array_intervals(self.normalized_intervals()),
            not self.accepts_non_array,
            self.exact,
        )

    def exact_complement(self) -> ArrayLengthConstraint | None:
        if not self.exact:
            return None
        return self.complement()


@dataclass(frozen=True)
class ArrayLengthIntervalFact:
    lower: int = 0
    upper: int | None = None

    def is_empty(self) -> bool:
        return self.upper is not None and self.lower > self.upper

    def intersect(self, other: ArrayLengthIntervalFact) -> ArrayLengthIntervalFact:
        lower = max(self.lower, other.lower)
        if self.upper is None:
            upper = other.upper
        elif other.upper is None:
            upper = self.upper
        else:
            upper = min(self.upper, other.upper)
        return ArrayLengthIntervalFact(lower, upper)


@dataclass(frozen=True)
class ArrayAnyOfItemSchemasConstraint:
    item_terms: tuple[SchemaTerm, ...]


@dataclass(frozen=True)
class ArrayTupleAnyOfDistributionConstraint:
    branch_terms: tuple[SchemaTerm, ...]


@dataclass(frozen=True)
class ArrayContainsConstraint:
    minimum: int
    maximum: int | None
    marks_evaluated: bool
    term: SchemaTerm


@dataclass(frozen=True)
class ArrayContainsFragmentConstraint:
    lhs_supported: bool
    rhs_supported: bool


@dataclass(frozen=True)
class ArrayItemValuesFragmentConstraint:
    lhs_supported: bool
    rhs_supported: bool
    rhs_witness_supported: bool


@dataclass(frozen=True)
class ArrayItemModelConstraint:
    prefix_terms: tuple[SchemaTerm, ...] = field(
        default=(), compare=False, repr=False
    )
    tail_term: SchemaTerm | None = field(default=None, compare=False, repr=False)
    first_required_item_term: SchemaTerm | None = field(
        default=None, compare=False, repr=False
    )
    covering_all_item_terms: tuple[SchemaTerm, ...] | None = field(
        default=None, compare=False, repr=False
    )

    def term_at_index(self, index: int) -> SchemaTerm | None:
        if index < 0:
            return None
        if index < len(self.prefix_terms):
            return self.prefix_terms[index]
        return self.tail_term

    def candidate_indexes(self, required_length: int) -> tuple[int, ...] | None:
        if required_length <= 0:
            return ()
        indexes = list(range(min(required_length, len(self.prefix_terms))))
        if required_length > len(self.prefix_terms):
            if self.tail_term is None:
                return None
            indexes.append(len(self.prefix_terms))
        return tuple(indexes)


@dataclass(frozen=True)
class ArrayUniquenessConstraint:
    accepts_array: bool
    accepts_non_array: bool
    requires_unique_items: bool
    guarantees_unique_items: bool
    complete_uniqueness_fragment: bool = True


@dataclass(frozen=True)
class ObjectPropertyCountConstraint:
    intervals: tuple[ObjectPropertyCountIntervalFact, ...]
    accepts_non_object: bool
    exact: bool = True

    def normalized_intervals(self) -> tuple[ObjectPropertyCountIntervalFact, ...]:
        return _merge_object_property_count_intervals(
            tuple(interval for interval in self.intervals if not interval.is_empty())
        )

    def is_subset_of(self, other: ObjectPropertyCountConstraint) -> bool:
        if self.accepts_non_object and not other.accepts_non_object:
            return False
        return all(
            _object_property_count_interval_covered(
                interval, other.normalized_intervals()
            )
            for interval in self.normalized_intervals()
        )

    def witness_not_in(
        self, other: ObjectPropertyCountConstraint
    ) -> dict[str, None] | None:
        for interval in self.normalized_intervals():
            count = _first_uncovered_object_property_count(
                interval, other.normalized_intervals()
            )
            if count is not None:
                return {f"k{i}": None for i in range(count)}
        return None

    def intersect(
        self, other: ObjectPropertyCountConstraint
    ) -> ObjectPropertyCountConstraint:
        intervals = [
            lhs.intersect(rhs)
            for lhs in self.normalized_intervals()
            for rhs in other.normalized_intervals()
        ]
        return ObjectPropertyCountConstraint(
            _merge_object_property_count_intervals(
                tuple(interval for interval in intervals if not interval.is_empty())
            ),
            self.accepts_non_object and other.accepts_non_object,
            self.exact and other.exact,
        )

    def union(
        self, other: ObjectPropertyCountConstraint
    ) -> ObjectPropertyCountConstraint:
        return ObjectPropertyCountConstraint(
            _merge_object_property_count_intervals(
                self.normalized_intervals() + other.normalized_intervals()
            ),
            self.accepts_non_object or other.accepts_non_object,
            self.exact and other.exact,
        )

    def complement(self) -> ObjectPropertyCountConstraint:
        return ObjectPropertyCountConstraint(
            _complement_object_property_count_intervals(self.normalized_intervals()),
            not self.accepts_non_object,
            self.exact,
        )

    def exact_complement(self) -> ObjectPropertyCountConstraint | None:
        if not self.exact:
            return None
        return self.complement()


@dataclass(frozen=True)
class ObjectPropertyCountIntervalFact:
    lower: int = 0
    upper: int | None = None

    def is_empty(self) -> bool:
        return self.upper is not None and self.lower > self.upper

    def intersect(
        self, other: ObjectPropertyCountIntervalFact
    ) -> ObjectPropertyCountIntervalFact:
        lower = max(self.lower, other.lower)
        if self.upper is None:
            upper = other.upper
        elif other.upper is None:
            upper = self.upper
        else:
            upper = min(self.upper, other.upper)
        return ObjectPropertyCountIntervalFact(lower, upper)


@dataclass(frozen=True)
class ObjectPropertyCountBoundsConstraint:
    minimum: int = 0
    maximum: int | None = None
    has_explicit_bound: bool = False


@dataclass(frozen=True)
class ObjectPropertyNamesConstraint:
    keyspace_pattern: RegexLanguage
    required: frozenset[str]
    accepts_object: bool
    accepts_non_object: bool

    def object_is_inhabited(self) -> bool:
        return self.accepts_object and all(
            self.keyspace_pattern.matches(name) for name in self.required
        )

    def is_subset_of(self, other: ObjectPropertyNamesConstraint) -> bool:
        if self.accepts_non_object and not other.accepts_non_object:
            return False
        if not self.object_is_inhabited():
            return True
        if not other.accepts_object:
            return False
        if not other.required <= self.required:
            return False
        result = self.keyspace_pattern.is_subset_of(other.keyspace_pattern)
        return False if isinstance(result, ProofResult) else result

    def witness_not_in(self, other: ObjectPropertyNamesConstraint) -> Any | None:
        if self.accepts_non_object and not other.accepts_non_object:
            return type_atom_witness(next(iter(sorted(JSON_TYPE_ATOMS - {"object"}))))
        if not self.object_is_inhabited():
            return None
        if not other.accepts_object:
            return self._object_witness()
        if not other.required <= self.required:
            return self._object_witness()

        difference = self.keyspace_pattern.difference(other.keyspace_pattern)
        if isinstance(difference, ProofResult):
            return None
        bad_name = _string_language_witness(difference)
        if not isinstance(bad_name, str):
            return None
        return self._object_witness(extra_name=bad_name)

    def intersect(
        self, other: ObjectPropertyNamesConstraint
    ) -> ObjectPropertyNamesConstraint:
        return ObjectPropertyNamesConstraint(
            _expect_regex_language(
                self.keyspace_pattern.intersection(other.keyspace_pattern)
            ),
            self.required | other.required,
            self.accepts_object and other.accepts_object,
            self.accepts_non_object and other.accepts_non_object,
        )

    def _object_witness(self, extra_name: str | None = None) -> dict[str, None]:
        witness = dict.fromkeys(sorted(self.required))
        if extra_name is not None:
            witness[extra_name] = None
        return witness


@dataclass(frozen=True)
class ObjectPropertyValuesConstraint:
    required: frozenset[str]
    accepts_object: bool
    accepts_non_object: bool
    property_terms: dict[str, tuple[SchemaTerm, ...]] = field(
        default_factory=dict, compare=False, repr=False
    )

    @property
    def property_names(self) -> frozenset[str]:
        return frozenset(self.property_terms)

    def property_term_for(self, name: str) -> SchemaTerm | None:
        terms = self.property_terms.get(name, ())
        return None if not terms else SchemaTerm.all_of(terms)

    def intersect(
        self, other: ObjectPropertyValuesConstraint
    ) -> ObjectPropertyValuesConstraint:
        names = self.property_names | other.property_names
        property_terms = {}
        for name in names:
            terms = self.property_terms.get(name, ()) + other.property_terms.get(
                name, ()
            )
            if terms:
                property_terms[name] = terms
        return ObjectPropertyValuesConstraint(
            self.required | other.required,
            self.accepts_object and other.accepts_object,
            self.accepts_non_object and other.accepts_non_object,
            property_terms,
        )

    def object_witness(
        self,
        dialect: Any,
        override: tuple[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        names = set(self.required)
        if override is not None:
            names.add(override[0])

        witness = {}
        for name in sorted(names):
            if override is not None and name == override[0]:
                value = override[1]
            else:
                value = None
            witness[name] = value
        return witness


@dataclass(frozen=True)
class ObjectKeyValuePattern:
    text: str
    pattern: RegexLanguage
    term: SchemaTerm


@dataclass(frozen=True)
class ObjectKeyValueWitnessSlot:
    name: str
    term: SchemaTerm | None = field(default=None, compare=False, repr=False)
    literal_value: Any = field(default=None, compare=False, repr=False)
    has_literal_value: bool = field(default=False, compare=False, repr=False)


@dataclass(frozen=True)
class ObjectKeyValueWitnessSkeleton:
    slots: tuple[ObjectKeyValueWitnessSlot, ...]


@dataclass(frozen=True)
class ObjectKeyValueConstraint:
    properties: frozenset[str]
    patterns: tuple[ObjectKeyValuePattern, ...]
    keyspace_pattern: RegexLanguage | None
    required: frozenset[str]
    accepts_object: bool
    accepts_non_object: bool
    property_terms: dict[str, SchemaTerm] = field(
        default_factory=dict, compare=False, repr=False
    )
    additional_term: SchemaTerm | None = field(
        default=None, compare=False, repr=False
    )

    @property
    def has_value_constraints(self) -> bool:
        return (
            any(not _term_is_true(term) for term in self.property_terms.values())
            or any(not _term_is_true(pattern.term) for pattern in self.patterns)
            or not _term_is_true(self.additional_term)
        )

    def pattern_texts(self) -> frozenset[str]:
        return frozenset(pattern.text for pattern in self.patterns)

    def pattern_by_text(self, text: str) -> ObjectKeyValuePattern | None:
        for pattern in self.patterns:
            if pattern.text == text:
                return pattern
        return None

    def key_matches_pattern(self, name: str) -> bool:
        return any(pattern.pattern.matches(name) for pattern in self.patterns)

    def keyspace_allows(self, name: str) -> bool:
        return self.keyspace_pattern is None or self.keyspace_pattern.matches(name)

    def allows_key(self, name: str) -> bool:
        return self.keyspace_allows(name) and (
            name in self.properties
            or self.key_matches_pattern(name)
            or not _term_is_false(self.additional_term)
        )

    def value_term_for(self, name: str) -> SchemaTerm | None:
        if not self.allows_key(name):
            return SchemaTerm.false()
        terms = []
        if name in self.property_terms:
            terms.append(self.property_terms[name])
        terms.extend(
            pattern.term
            for pattern in self.patterns
            if pattern.term is not None and pattern.pattern.matches(name)
        )
        if (
            name not in self.properties
            and not self.key_matches_pattern(name)
            and self.additional_term is not None
        ):
            terms.append(self.additional_term)
        return None if not terms else SchemaTerm.all_of(tuple(terms))

    def object_is_inhabited(self) -> bool:
        return self.accepts_object and all(
            self.allows_key(name) for name in self.required
        )

    def witness_skeleton(
        self, override_name: str | None = None
    ) -> ObjectKeyValueWitnessSkeleton | None:
        names = set(self.required)
        if override_name is not None:
            names.add(override_name)
        return self.witness_skeleton_for_names(names)

    def witness_skeleton_for_names(
        self, names: set[str] | frozenset[str]
    ) -> ObjectKeyValueWitnessSkeleton | None:
        if not all(self.allows_key(name) for name in names):
            return None
        return ObjectKeyValueWitnessSkeleton(
            tuple(
                ObjectKeyValueWitnessSlot(
                    name,
                    self.value_term_for(name),
                )
                for name in sorted(names)
            )
        )


@dataclass(frozen=True)
class ObjectPresenceLocalConstraint:
    type_atoms: frozenset[str]
    property_names: frozenset[str]
    required: frozenset[str]
    additional_properties_false: bool
    dependent_required: tuple[tuple[str, frozenset[str]], ...]
    min_properties: int
    max_properties: int | None
    has_property_value_constraints: bool

    @property
    def names(self) -> frozenset[str]:
        names = set(self.required) | set(self.property_names)
        for trigger, dependencies in self.dependent_required:
            names.add(trigger)
            names.update(dependencies)
        return frozenset(names)

    @property
    def has_property_count_constraint(self) -> bool:
        return self.min_properties > 0 or self.max_properties is not None

    @property
    def has_upper_count_constraint(self) -> bool:
        return self.max_properties is not None

    def accepts(self, atom: str, present: frozenset[str]) -> bool:
        if atom not in self.type_atoms:
            return False
        if atom != "object":
            return True
        if not self.required <= present:
            return False
        if self.additional_properties_false and not present <= self.property_names:
            return False
        for trigger, dependencies in self.dependent_required:
            if trigger in present and not dependencies <= present:
                return False
        if len(present) < self.min_properties:
            return False
        if self.max_properties is not None and len(present) > self.max_properties:
            return False
        return True

    def symbolic_expr(self, variables: dict[str, Any], solver: Any) -> Any:
        if "object" not in self.type_atoms:
            return solver.or_()

        constraints: list[Any] = []
        constraints.extend(
            variables.get(name, solver.bool_var(name))
            for name in sorted(self.required)
        )

        if self.additional_properties_false:
            constraints.extend(
                solver.not_(variable)
                for name, variable in variables.items()
                if name not in self.property_names
            )

        for trigger, dependencies in self.dependent_required:
            dependency_vars = [
                variables.get(name, solver.bool_var(name))
                for name in sorted(dependencies)
            ]
            constraints.append(
                solver.implies(
                    variables.get(trigger, solver.bool_var(trigger)),
                    solver.and_(*dependency_vars),
                )
            )

        values = tuple(variables.values())
        constraints.append(solver.cardinality_ge(values, self.min_properties))
        if self.max_properties is not None:
            constraints.append(solver.cardinality_le(values, self.max_properties))
        return solver.and_(*constraints)


@dataclass(frozen=True)
class ObjectPresenceProductConstraint:
    kind: Literal["true", "false", "schema"]
    local: ObjectPresenceLocalConstraint | None = None
    all_of: tuple[ObjectPresenceProductConstraint, ...] = ()
    any_of: tuple[ObjectPresenceProductConstraint, ...] = ()
    one_of: tuple[ObjectPresenceProductConstraint, ...] = ()
    not_schema: ObjectPresenceProductConstraint | None = None
    dependent_schemas: tuple[tuple[str, ObjectPresenceProductConstraint], ...] = ()

    @classmethod
    def true(cls) -> ObjectPresenceProductConstraint:
        return cls("true")

    @classmethod
    def false(cls) -> ObjectPresenceProductConstraint:
        return cls("false")

    @classmethod
    def schema(
        cls,
        local: ObjectPresenceLocalConstraint,
        *,
        all_of: tuple[ObjectPresenceProductConstraint, ...] = (),
        any_of: tuple[ObjectPresenceProductConstraint, ...] = (),
        one_of: tuple[ObjectPresenceProductConstraint, ...] = (),
        not_schema: ObjectPresenceProductConstraint | None = None,
        dependent_schemas: tuple[tuple[str, ObjectPresenceProductConstraint], ...] = (),
    ) -> ObjectPresenceProductConstraint:
        return cls(
            "schema",
            local,
            all_of,
            any_of,
            one_of,
            not_schema,
            dependent_schemas,
        )

    @property
    def names(self) -> tuple[str, ...]:
        names: set[str] = set()
        self._collect_names(names)
        return tuple(sorted(names))

    @property
    def has_one_of(self) -> bool:
        return bool(self.one_of) or any(
            child.has_one_of for child in self._all_children()
        )

    @property
    def has_property_count_constraint(self) -> bool:
        return (
            self.local is not None
            and self.local.has_property_count_constraint
            or any(
                child.has_property_count_constraint for child in self._all_children()
            )
        )

    @property
    def has_upper_count_constraint(self) -> bool:
        return (
            self.local is not None
            and self.local.has_upper_count_constraint
            or (
                self.not_schema is not None
                and self.not_schema.local is not None
                and self.not_schema.local.min_properties > 0
            )
            or any(child.has_upper_count_constraint for child in self.all_of)
            or any(child.has_upper_count_constraint for child in self.any_of)
            or any(child.has_upper_count_constraint for child in self.one_of)
            or any(
                child.has_upper_count_constraint
                for _, child in self.dependent_schemas
            )
        )

    @property
    def has_unmodeled_value_constraints(self) -> bool:
        return (
            self.local is not None
            and self.local.has_property_value_constraints
            or any(
                child.has_unmodeled_value_constraints for child in self._all_children()
            )
        )

    @property
    def lhs_has_negative_value_constraints(self) -> bool:
        return (
            self.not_schema is not None
            and self.not_schema.has_unmodeled_value_constraints
            or any(
                child.lhs_has_negative_value_constraints
                for child in self.all_of + self.any_of + self.one_of
            )
        )

    def dependency_closed_present_names(
        self, seed: frozenset[str]
    ) -> frozenset[str]:
        names = set(seed)
        self._add_dependency_closed_names(names)
        return frozenset(names)

    def accepts(self, atom: str, present: frozenset[str]) -> bool | None:
        if self.kind == "true":
            return True
        if self.kind == "false":
            return False
        if self.local is None:
            return None

        local = self.local.accepts(atom, present)
        if not local:
            return False

        for child in self.all_of:
            branch = child.accepts(atom, present)
            if branch is None:
                return None
            if not branch:
                return False

        if self.any_of:
            branch_results = []
            for child in self.any_of:
                branch = child.accepts(atom, present)
                if branch is None:
                    return None
                branch_results.append(branch)
            if not any(branch_results):
                return False

        if self.one_of:
            branch_results = []
            for child in self.one_of:
                branch = child.accepts(atom, present)
                if branch is None:
                    return None
                branch_results.append(branch)
            if sum(branch_results) != 1:
                return False

        if atom == "object":
            for trigger, child in self.dependent_schemas:
                if trigger not in present:
                    continue
                branch = child.accepts(atom, present)
                if branch is None:
                    return None
                if not branch:
                    return False

        if self.not_schema is not None:
            negated = self.not_schema.accepts(atom, present)
            if negated is None:
                return None
            if negated:
                return False

        return True

    def symbolic_expr(self, variables: dict[str, Any], solver: Any) -> Any | None:
        if self.kind == "true":
            return solver.and_()
        if self.kind == "false":
            return solver.or_()
        if self.local is None:
            return None

        constraints = [self.local.symbolic_expr(variables, solver)]

        for child in self.all_of:
            branch = child.symbolic_expr(variables, solver)
            if branch is None:
                return None
            constraints.append(branch)

        if self.any_of:
            branches = []
            for child in self.any_of:
                branch = child.symbolic_expr(variables, solver)
                if branch is None:
                    return None
                branches.append(branch)
            constraints.append(solver.or_(*branches))

        if self.one_of:
            branches = []
            for child in self.one_of:
                branch = child.symbolic_expr(variables, solver)
                if branch is None:
                    return None
                branches.append(branch)
            constraints.append(solver.exactly_one(branches))

        for trigger, child in self.dependent_schemas:
            branch = child.symbolic_expr(variables, solver)
            if branch is None:
                return None
            constraints.append(
                solver.implies(
                    variables.get(trigger, solver.bool_var(trigger)),
                    branch,
                )
            )

        if self.not_schema is not None:
            negated = self.not_schema.symbolic_expr(variables, solver)
            if negated is None:
                return None
            constraints.append(solver.not_(negated))

        return solver.and_(*constraints)

    def _collect_names(self, names: set[str]) -> None:
        if self.local is not None:
            names.update(self.local.names)
        for trigger, child in self.dependent_schemas:
            names.add(trigger)
            child._collect_names(names)
        for child in self._all_children():
            child._collect_names(names)

    def _add_dependency_closed_names(self, names: set[str]) -> None:
        if self.local is not None:
            names.update(self.local.required)

        changed = True
        while changed:
            changed = False
            if self.local is not None:
                for trigger, dependencies in self.local.dependent_required:
                    if trigger not in names:
                        continue
                    for dependency in dependencies:
                        if dependency not in names:
                            names.add(dependency)
                            changed = True
            for trigger, child in self.dependent_schemas:
                if trigger not in names:
                    continue
                before = len(names)
                child._add_dependency_closed_names(names)
                if len(names) != before:
                    changed = True

    def _all_children(self) -> tuple[ObjectPresenceProductConstraint, ...]:
        children = self.all_of + self.any_of + self.one_of
        children += tuple(child for _, child in self.dependent_schemas)
        if self.not_schema is not None:
            children += (self.not_schema,)
        return children


@dataclass(frozen=True)
class ObjectClosedPropertiesConstraint:
    allowed_names: frozenset[str]
    keyspace_pattern: RegexLanguage | None
    required: frozenset[str]
    accepts_object: bool
    accepts_non_object: bool
    has_finite_keyspace: bool
    property_terms: dict[str, tuple[SchemaTerm, ...]] = field(
        default_factory=dict, compare=False, repr=False
    )
    pattern_property_terms: tuple[tuple[RegexLanguage, SchemaTerm], ...] = field(
        default=(), compare=False, repr=False
    )

    def object_is_inhabited(self) -> bool:
        return self.accepts_object and all(
            self.keyspace_accepts(name) for name in self.required
        )

    def keyspace_satisfies(self, other: ObjectClosedPropertiesConstraint) -> bool:
        if not other.required <= self.required:
            return False
        if self.has_finite_keyspace:
            return all(other.keyspace_accepts(name) for name in self.allowed_names)
        if other.has_finite_keyspace:
            return False
        if self.keyspace_pattern is None or other.keyspace_pattern is None:
            return False
        subset = self.keyspace_pattern.is_subset_of(other.keyspace_pattern)
        return subset is True

    def keyspace_witness_not_in(
        self,
        other: ObjectClosedPropertiesConstraint,
        dialect: Any,
    ) -> dict[str, Any] | None:
        if not other.required <= self.required:
            return self.object_witness(dialect)
        for name in sorted(self.allowed_names):
            if not other.keyspace_accepts(name):
                value = None
                return self.object_witness(dialect, override=(name, value))
        return None

    def property_term_for(self, name: str) -> SchemaTerm | None:
        terms = self.property_terms.get(name, ()) + tuple(
            term
            for pattern, term in self.pattern_property_terms
            if pattern.matches(name)
        )
        return None if not terms else SchemaTerm.all_of(terms)

    def intersect(
        self, other: ObjectClosedPropertiesConstraint
    ) -> ObjectClosedPropertiesConstraint:
        finite_keyspace = self.has_finite_keyspace or other.has_finite_keyspace
        explicit_names = self.allowed_names | other.allowed_names
        names = frozenset(
            name
            for name in explicit_names
            if self.keyspace_accepts(name) and other.keyspace_accepts(name)
        )
        property_terms = {}
        for name in names:
            terms = self.property_terms.get(name, ()) + other.property_terms.get(
                name, ()
            )
            if terms:
                property_terms[name] = terms
        return ObjectClosedPropertiesConstraint(
            names,
            _intersect_closed_keyspace_patterns(self, other, finite_keyspace),
            self.required | other.required,
            self.accepts_object and other.accepts_object,
            self.accepts_non_object and other.accepts_non_object,
            finite_keyspace,
            property_terms,
            self.pattern_property_terms + other.pattern_property_terms,
        )

    def object_witness(
        self,
        dialect: Any,
        override: tuple[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        names = set(self.required)
        if override is not None:
            names.add(override[0])
        if not all(self.keyspace_accepts(name) for name in names):
            return None

        witness = {}
        for name in sorted(names):
            value = (
                override[1]
                if override is not None and name == override[0]
                else None
            )
            witness[name] = value
        return witness

    def keyspace_accepts(self, name: str) -> bool:
        if self.has_finite_keyspace:
            return name in self.allowed_names
        if self.keyspace_pattern is None:
            return False
        return self.keyspace_pattern.matches(name)

@dataclass(frozen=True)
class ObjectDependentRequiredEntry:
    trigger: str
    dependencies: frozenset[str]


@dataclass(frozen=True)
class ObjectDependentRequiredConstraint:
    entries: tuple[ObjectDependentRequiredEntry, ...]


@dataclass(frozen=True)
class ObjectDependentSchemaProperty:
    trigger: str
    name: str
    term: SchemaTerm


@dataclass(frozen=True)
class ObjectDependentSchemaPropertiesConstraint:
    properties: tuple[ObjectDependentSchemaProperty, ...]


def type_atom_witness(atom: str) -> Any:
    if atom == "null":
        return None
    if atom == "boolean":
        return False
    if atom == "integer":
        return 0
    if atom == "number":
        return 0.5
    if atom == "string":
        return ""
    if atom == "array":
        return []
    if atom == "object":
        return {}
    return None


def _term_is_true(term: SchemaTerm | None) -> bool:
    return term is None or term.kind == "true"


def _term_is_false(term: SchemaTerm | None) -> bool:
    return term is not None and term.kind == "false"


def _intersect_closed_keyspace_patterns(
    lhs: ObjectClosedPropertiesConstraint,
    rhs: ObjectClosedPropertiesConstraint,
    finite_keyspace: bool,
) -> RegexLanguage | None:
    if finite_keyspace:
        return None
    if lhs.keyspace_pattern is None or rhs.keyspace_pattern is None:
        return None
    return _expect_regex_language(
        lhs.keyspace_pattern.intersection(rhs.keyspace_pattern)
    )


def _string_language_witness(
    pattern: Any, context: RegexWorkContext | None = None
) -> str | ProofResult | None:
    language = pattern if isinstance(pattern, RegexLanguage) else RegexLanguage(pattern)
    if language.is_empty():
        return None
    witness = language.witness(context)
    if isinstance(witness, ProofResult):
        return witness
    if witness is not None:
        return witness
    return None


def _expect_regex_language(value: RegexLanguage | ProofResult) -> RegexLanguage:
    if isinstance(value, ProofResult):
        raise ValueError(value.reason or "regex operation did not produce a language")
    return value


def _merge_string_intervals(
    intervals: tuple[StringLengthIntervalFact, ...],
) -> tuple[StringLengthIntervalFact, ...]:
    if not intervals:
        return ()

    ordered = sorted(intervals, key=lambda interval: interval.lower)
    merged: list[StringLengthIntervalFact] = []
    for interval in ordered:
        if interval.is_empty():
            continue
        if not merged:
            merged.append(interval)
            continue
        previous = merged[-1]
        if previous.upper is None:
            continue
        if interval.lower > previous.upper + 1:
            merged.append(interval)
            continue
        upper = None
        if interval.upper is None:
            upper = None
        else:
            upper = max(previous.upper, interval.upper)
        merged[-1] = StringLengthIntervalFact(previous.lower, upper)
    return tuple(merged)


def _string_interval_covered(
    interval: StringLengthIntervalFact,
    covering: tuple[StringLengthIntervalFact, ...],
) -> bool:
    target = interval
    for candidate in covering:
        if candidate.lower > target.lower:
            return False
        if candidate.upper is None:
            return True
        if target.upper is not None and candidate.upper >= target.upper:
            return True
        target = StringLengthIntervalFact(candidate.upper + 1, target.upper)
    return False


def _first_uncovered_string_length(
    interval: StringLengthIntervalFact,
    covering: tuple[StringLengthIntervalFact, ...],
) -> int | None:
    candidate = interval.lower
    for cover in covering:
        if cover.lower > candidate:
            return candidate
        if cover.upper is None:
            return None
        candidate = max(candidate, cover.upper + 1)
        if interval.upper is not None and candidate > interval.upper:
            return None
    return candidate


def _complement_string_intervals(
    intervals: tuple[StringLengthIntervalFact, ...],
) -> tuple[StringLengthIntervalFact, ...]:
    complement = []
    current = 0
    for interval in intervals:
        if current < interval.lower:
            complement.append(StringLengthIntervalFact(current, interval.lower - 1))
        if interval.upper is None:
            return tuple(complement)
        current = interval.upper + 1
    complement.append(StringLengthIntervalFact(current, None))
    return tuple(complement)


def _merge_array_intervals(
    intervals: tuple[ArrayLengthIntervalFact, ...],
) -> tuple[ArrayLengthIntervalFact, ...]:
    sorted_intervals = sorted(intervals, key=lambda interval: interval.lower)
    merged: list[ArrayLengthIntervalFact] = []
    for interval in sorted_intervals:
        if interval.is_empty():
            continue
        if not merged:
            merged.append(interval)
            continue
        previous = merged[-1]
        if previous.upper is None or interval.lower <= previous.upper + 1:
            upper = (
                None
                if previous.upper is None or interval.upper is None
                else max(previous.upper, interval.upper)
            )
            merged[-1] = ArrayLengthIntervalFact(previous.lower, upper)
        else:
            merged.append(interval)
    return tuple(merged)


def _array_interval_covered(
    interval: ArrayLengthIntervalFact,
    covering_intervals: tuple[ArrayLengthIntervalFact, ...],
) -> bool:
    remaining_start = interval.lower
    interval_end = interval.upper
    for covering in covering_intervals:
        if covering.upper is not None and covering.upper < remaining_start:
            continue
        if covering.lower > remaining_start:
            return False
        if covering.upper is None:
            return True
        remaining_start = covering.upper + 1
        if interval_end is not None and remaining_start > interval_end:
            return True
    return False


def _first_uncovered_array_length(
    interval: ArrayLengthIntervalFact,
    covering_intervals: tuple[ArrayLengthIntervalFact, ...],
) -> int | None:
    current = interval.lower
    for covering in covering_intervals:
        if covering.upper is not None and covering.upper < current:
            continue
        if covering.lower > current:
            return current
        if covering.upper is None:
            return None
        current = covering.upper + 1
        if interval.upper is not None and current > interval.upper:
            return None
    return current if interval.upper is None or current <= interval.upper else None


def _complement_array_intervals(
    intervals: tuple[ArrayLengthIntervalFact, ...],
) -> tuple[ArrayLengthIntervalFact, ...]:
    complements = []
    next_lower = 0
    for interval in intervals:
        if next_lower < interval.lower:
            complements.append(ArrayLengthIntervalFact(next_lower, interval.lower - 1))
        if interval.upper is None:
            return tuple(complements)
        next_lower = interval.upper + 1
    complements.append(ArrayLengthIntervalFact(next_lower, None))
    return tuple(complements)


def _merge_object_property_count_intervals(
    intervals: tuple[ObjectPropertyCountIntervalFact, ...],
) -> tuple[ObjectPropertyCountIntervalFact, ...]:
    sorted_intervals = sorted(intervals, key=lambda interval: interval.lower)
    merged: list[ObjectPropertyCountIntervalFact] = []
    for interval in sorted_intervals:
        if interval.is_empty():
            continue
        if not merged:
            merged.append(interval)
            continue
        previous = merged[-1]
        if previous.upper is None or interval.lower <= previous.upper + 1:
            upper = (
                None
                if previous.upper is None or interval.upper is None
                else max(previous.upper, interval.upper)
            )
            merged[-1] = ObjectPropertyCountIntervalFact(previous.lower, upper)
        else:
            merged.append(interval)
    return tuple(merged)


def _object_property_count_interval_covered(
    interval: ObjectPropertyCountIntervalFact,
    covering_intervals: tuple[ObjectPropertyCountIntervalFact, ...],
) -> bool:
    remaining_start = interval.lower
    interval_end = interval.upper
    for covering in covering_intervals:
        if covering.upper is not None and covering.upper < remaining_start:
            continue
        if covering.lower > remaining_start:
            return False
        if covering.upper is None:
            return True
        remaining_start = covering.upper + 1
        if interval_end is not None and remaining_start > interval_end:
            return True
    return False


def _first_uncovered_object_property_count(
    interval: ObjectPropertyCountIntervalFact,
    covering_intervals: tuple[ObjectPropertyCountIntervalFact, ...],
) -> int | None:
    current = interval.lower
    for covering in covering_intervals:
        if covering.upper is not None and covering.upper < current:
            continue
        if covering.lower > current:
            return current
        if covering.upper is None:
            return None
        current = covering.upper + 1
        if interval.upper is not None and current > interval.upper:
            return None
    return current if interval.upper is None or current <= interval.upper else None


def _complement_object_property_count_intervals(
    intervals: tuple[ObjectPropertyCountIntervalFact, ...],
) -> tuple[ObjectPropertyCountIntervalFact, ...]:
    complements = []
    next_lower = 0
    for interval in intervals:
        if next_lower < interval.lower:
            complements.append(
                ObjectPropertyCountIntervalFact(next_lower, interval.lower - 1)
            )
        if interval.upper is None:
            return tuple(complements)
        next_lower = interval.upper + 1
    complements.append(ObjectPropertyCountIntervalFact(next_lower, None))
    return tuple(complements)


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
    lhs: NumericAtomFact, rhs: NumericAtomFact
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
    atom: NumericAtomFact, intervals: list[tuple[int | None, int | None]]
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

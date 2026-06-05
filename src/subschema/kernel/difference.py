"""
Composite object/array difference models for SAT rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal

from subschema.dialects import Dialect
from subschema.kernel.constraints import (
    ArrayLengthConstraint,
    ArrayUniquenessConstraint,
    ObjectClosedPropertiesConstraint,
    ObjectPropertyCountConstraint,
    ObjectPropertyNamesConstraint,
    ObjectPropertyValuesConstraint,
)
from subschema.kernel.contracts import ProofResult
from subschema.kernel.domains.arrays import (
    ArrayShape,
    ArrayUniquenessShape,
    array_unique_items_requirement_for_schema,
)
from subschema.kernel.domains.numbers import numeric_shape_for_schema
from subschema.kernel.domains.objects import (
    ClosedObjectPropertiesShape,
    ObjectPropertyCountShape,
    ObjectPropertyNamesShape,
    ObjectPropertyValuesShape,
)
from subschema.kernel.domains.strings import string_language_witness
from subschema.kernel.domains.types import (
    JSON_TYPE_ATOMS,
    type_shape_for_schema,
    type_shape_for_type_keyword,
    witness_for_type_atom,
)
from subschema.kernel.evaluation import (
    EvaluatedItemSource,
    EvaluationTraceExpression,
)
from subschema.kernel.evaluation_traces import evaluation_trace_for_source
from subschema.kernel.finite import finite_values_for_schema
from subschema.kernel.ir import IRAssertionKind, LogicalSchemaIR
from subschema.kernel.references import ResourceGraph
from subschema.kernel.regex import RegexLanguage
from subschema.kernel.schemas import (
    IGNORED_SCHEMA_METADATA_KEYS,
    contains_reference_keyword,
    schema_is_true,
)
from subschema.kernel.symbolic import SAT, UNSAT, SymbolicSolver
from subschema.kernel.values import json_semantic_key
from subschema.kernel.witnesses import build_schema_witness

if TYPE_CHECKING:
    from subschema.kernel.context import ProofContext
    from subschema.kernel.sat import DifferenceProblem

ArrayItemSource = Literal["additionalItems", "contains", "items", "prefixItems"]
ArrayContainsPlanStatus = Literal[
    "proved_true", "resource_exhausted", "unsupported", "witness"
]
ArrayItemValueSource = Literal[
    "lhs-slot-rhs-tail",
    "lhs-tail-rhs-tail",
    "lhs-unconstrained-rhs-tail",
    "rhs-slot",
]
ArrayLengthPlanStatus = Literal[
    "proved_true", "resource_exhausted", "unsupported", "witness"
]
ArrayItemValuesPlanStatus = Literal[
    "obligations", "proved_true", "resource_exhausted", "unsupported", "witness"
]
ArrayUniquenessPlanStatus = Literal[
    "duplicate_witness", "proved_true", "resource_exhausted", "unsupported", "witness"
]
ArrayUnevaluatedItemsPlanStatus = Literal[
    "obligations", "proved_true", "resource_exhausted", "unsupported", "witness"
]
ObjectKeySource = Literal[
    "additionalProperties",
    "dependencies",
    "dependentSchemas",
    "patternProperties",
    "properties",
    "required",
]
ObjectPresencePlanStatus = Literal["ready", "resource_exhausted", "unsupported"]
ObjectPresenceWitnessSource = Literal["finite-keyspace", "multi-fresh", "non-object"]
ObjectPropertyCountPlanStatus = Literal[
    "proved_true", "resource_exhausted", "unsupported", "witness"
]
ObjectPropertyNamesPlanStatus = Literal["proved_true", "unsupported", "witness"]
ObjectPropertyValuesPlanStatus = Literal[
    "obligations", "proved_true", "unsupported", "witness"
]
ObjectUnevaluatedPropertiesPlanStatus = Literal[
    "obligations",
    "proved_true",
    "resource_exhausted",
    "unsupported",
    "witness",
]
ClosedObjectPlanStatus = Literal["obligations", "proved_true", "unsupported", "witness"]
ObjectKeyValuePlanStatus = Literal[
    "obligations", "proved_true", "resource_exhausted", "unsupported", "witness"
]

OBJECT_PRESENCE_PRODUCT_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "allOf",
        "anyOf",
        "dependencies",
        "dependentRequired",
        "dependentSchemas",
        "maxProperties",
        "minProperties",
        "not",
        "oneOf",
        "properties",
        "required",
        "type",
    }
)
def _array_length_constraint(value: Any) -> ArrayLengthConstraint | None:
    return value if isinstance(value, ArrayLengthConstraint) else None


def _array_uniqueness_constraint(value: Any) -> ArrayUniquenessConstraint | None:
    return value if isinstance(value, ArrayUniquenessConstraint) else None


def _object_property_count_constraint(
    value: Any,
) -> ObjectPropertyCountConstraint | None:
    return value if isinstance(value, ObjectPropertyCountConstraint) else None


def _object_property_names_constraint(
    value: Any,
) -> ObjectPropertyNamesConstraint | None:
    return value if isinstance(value, ObjectPropertyNamesConstraint) else None


def _object_property_values_constraint(
    value: Any,
) -> ObjectPropertyValuesConstraint | None:
    return value if isinstance(value, ObjectPropertyValuesConstraint) else None


def _object_closed_properties_constraint(
    value: Any,
) -> ObjectClosedPropertiesConstraint | None:
    return value if isinstance(value, ObjectClosedPropertiesConstraint) else None


@dataclass(frozen=True)
class ArraySlot:
    index: int
    schema: Any
    source: ArrayItemSource


@dataclass(frozen=True)
class ArrayTail:
    start_index: int
    schema: Any
    source: ArrayItemSource

    @property
    def closed(self) -> bool:
        return self.schema is False


@dataclass(frozen=True)
class ArrayContainsConstraint:
    schema: Any
    minimum: int
    maximum: int | None
    marks_evaluated: bool


@dataclass(frozen=True)
class ArrayContainsItemProof:
    index: int
    lhs_schema: Any


@dataclass(frozen=True)
class ArrayContainsMinViolationPlan:
    length: int
    item_proofs: tuple[ArrayContainsItemProof, ...]
    minimum: int


@dataclass(frozen=True)
class ArrayContainsMaxViolationPlan:
    length: int
    item_proofs: tuple[ArrayContainsItemProof, ...]
    target_matches: int


@dataclass(frozen=True)
class ArrayContainsDifferencePlan:
    status: ArrayContainsPlanStatus
    reason: str = ""
    rejected_reason: str = ""
    witness: Any | None = None
    witness_plan: ArrayWitnessPlan | None = None

    @classmethod
    def proved_true(cls) -> ArrayContainsDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> ArrayContainsDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def resource_exhausted(cls, reason: str) -> ArrayContainsDifferencePlan:
        return cls("resource_exhausted", reason=reason)

    @classmethod
    def literal_witness(
        cls,
        witness: Any,
        *,
        rejected_reason: str,
    ) -> ArrayContainsDifferencePlan:
        return cls("witness", witness=witness, rejected_reason=rejected_reason)

    @classmethod
    def planned_witness(
        cls,
        witness_plan: ArrayWitnessPlan,
        *,
        rejected_reason: str,
    ) -> ArrayContainsDifferencePlan:
        return cls(
            "witness", witness_plan=witness_plan, rejected_reason=rejected_reason
        )


@dataclass(frozen=True)
class ArrayLengthDifferencePlan:
    status: ArrayLengthPlanStatus
    reason: str = ""
    rejected_reason: str = ""
    witness: Any | None = None
    witness_skeleton: ArrayWitnessSkeleton | None = None
    witness_plan: ArrayWitnessPlan | None = None

    @classmethod
    def proved_true(cls) -> ArrayLengthDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> ArrayLengthDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def resource_exhausted(cls, reason: str) -> ArrayLengthDifferencePlan:
        return cls("resource_exhausted", reason=reason)

    @classmethod
    def literal_witness(
        cls,
        witness: Any,
        *,
        rejected_reason: str,
    ) -> ArrayLengthDifferencePlan:
        return cls("witness", witness=witness, rejected_reason=rejected_reason)

    @classmethod
    def skeleton_witness(
        cls,
        skeleton: ArrayWitnessSkeleton,
        *,
        rejected_reason: str,
    ) -> ArrayLengthDifferencePlan:
        return cls(
            "witness", witness_skeleton=skeleton, rejected_reason=rejected_reason
        )

    @classmethod
    def planned_witness(
        cls,
        witness_plan: ArrayWitnessPlan,
        *,
        rejected_reason: str,
    ) -> ArrayLengthDifferencePlan:
        return cls(
            "witness", witness_plan=witness_plan, rejected_reason=rejected_reason
        )


@dataclass(frozen=True)
class ArrayUnevaluatedItemObligation:
    index: int
    lhs_schema: Any
    rhs_schema: Any


@dataclass(frozen=True)
class ArrayUnevaluatedItemsDifferencePlan:
    status: ArrayUnevaluatedItemsPlanStatus
    reason: str = ""
    rejected_reason: str = ""
    witness_skeleton: ArrayWitnessSkeleton | None = None
    obligations: tuple[ArrayUnevaluatedItemObligation, ...] = ()

    @classmethod
    def proved_true(cls) -> ArrayUnevaluatedItemsDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> ArrayUnevaluatedItemsDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def resource_exhausted(cls, reason: str) -> ArrayUnevaluatedItemsDifferencePlan:
        return cls("resource_exhausted", reason=reason)

    @classmethod
    def skeleton_witness(
        cls,
        skeleton: ArrayWitnessSkeleton,
        *,
        rejected_reason: str,
    ) -> ArrayUnevaluatedItemsDifferencePlan:
        return cls(
            "witness", witness_skeleton=skeleton, rejected_reason=rejected_reason
        )

    @classmethod
    def obligation_plan(
        cls,
        obligations: tuple[ArrayUnevaluatedItemObligation, ...],
    ) -> ArrayUnevaluatedItemsDifferencePlan:
        return cls("obligations", obligations=obligations)


@dataclass(frozen=True)
class ArrayWitnessSlot:
    index: int
    schema: Any


@dataclass(frozen=True)
class ArrayWitnessOverride:
    index: int
    value: Any


@dataclass(frozen=True)
class ArrayWitnessSkeleton:
    length: int
    slots: tuple[ArrayWitnessSlot, ...]


@dataclass(frozen=True)
class ArrayWitnessPlan:
    skeleton: ArrayWitnessSkeleton
    overrides: tuple[ArrayWitnessOverride, ...] = ()


@dataclass(frozen=True)
class ArrayDuplicateWitnessPlan:
    skeleton: ArrayWitnessSkeleton
    first_index: int
    second_index: int
    duplicate_schema: Any
    overrides: tuple[ArrayWitnessOverride, ...] = ()


def materialize_array_witness_plan(
    plan: ArrayWitnessPlan | None,
    dialect: Dialect,
) -> list[Any] | None:
    if plan is None:
        return None
    return materialize_array_witness_skeleton(
        plan.skeleton,
        dialect,
        override={override.index: override.value for override in plan.overrides},
    )


def materialize_array_duplicate_witness_plan(
    plan: ArrayDuplicateWitnessPlan | None,
    dialect: Dialect,
) -> list[Any] | None:
    if plan is None:
        return None
    duplicate_found, duplicate_value = _concrete_witness_for_schema(
        plan.duplicate_schema, dialect
    )
    if not duplicate_found:
        return None
    return materialize_array_witness_skeleton(
        plan.skeleton,
        dialect,
        override={
            **{override.index: override.value for override in plan.overrides},
            plan.first_index: duplicate_value,
            plan.second_index: duplicate_value,
        },
    )


def materialize_array_witness_skeleton(
    skeleton: ArrayWitnessSkeleton | None,
    dialect: Dialect,
    *,
    override: tuple[int, Any] | dict[int, Any] | None = None,
) -> list[Any] | None:
    if skeleton is None:
        return None
    overrides = _array_witness_overrides(override)
    values = []
    value_cache: dict[str, tuple[bool, Any]] = {}
    for slot in skeleton.slots:
        if slot.index in overrides:
            values.append(overrides[slot.index])
            continue
        cache_key = repr(slot.schema)
        found, value = value_cache.get(cache_key, (False, None))
        if not found:
            found, value = _concrete_witness_for_schema(slot.schema, dialect)
            if not found:
                return None
            value_cache[cache_key] = (found, value)
        values.append(value)
    return values


def _array_witness_overrides(
    override: tuple[int, Any] | dict[int, Any] | None,
) -> dict[int, Any]:
    if override is None:
        return {}
    if isinstance(override, tuple):
        return {override[0]: override[1]}
    return dict(override)


def _array_contains_overrides(
    schema: Any,
    dialect: Dialect,
    count: int,
) -> tuple[ArrayWitnessOverride, ...] | None:
    found, value = _concrete_witness_for_schema(schema, dialect)
    if not found:
        return None
    return tuple(ArrayWitnessOverride(index, value) for index in range(count))


def _array_contains_overrides_for_max_violation(
    schema: Any,
    dialect: Dialect,
    count: int,
    *,
    distinct: bool,
) -> tuple[ArrayWitnessOverride, ...] | None:
    if not distinct:
        return _array_contains_overrides(schema, dialect, count)
    values = _distinct_concrete_witnesses_for_schema(schema, dialect, count)
    if values is None:
        return None
    return tuple(
        ArrayWitnessOverride(index, value) for index, value in enumerate(values)
    )


def _array_contains_nonmatching_overrides(
    plan: ArrayContainsMinViolationPlan,
    contains_schema: Any,
    dialect: Dialect,
) -> tuple[ArrayWitnessOverride, ...] | None:
    seen: set[str] = set()
    overrides = []
    for item_proof in plan.item_proofs:
        for value in _constructive_witness_values_excluding_schema(
            item_proof.lhs_schema,
            contains_schema,
            dialect,
        ):
            key = json_semantic_key(value)
            if key in seen:
                continue
            seen.add(key)
            overrides.append(ArrayWitnessOverride(item_proof.index, value))
            break
        else:
            return None
    return tuple(overrides)


def _constructive_witness_values_excluding_schema(
    schema: Any,
    excluded_schema: Any,
    dialect: Dialect,
) -> tuple[Any, ...]:
    excluded_finite = finite_values_for_schema(
        excluded_schema, ResourceGraph.build(excluded_schema, dialect=dialect)
    )
    if excluded_finite is not None:
        excluded_keys = {json_semantic_key(value) for value in excluded_finite}
        return tuple(
            value
            for value in _constructive_witness_values_for_schema(schema, dialect)
            if json_semantic_key(value) not in excluded_keys
        )

    excluded_type = type_shape_for_schema(excluded_schema)
    if excluded_type is None:
        return ()
    schema_type = type_shape_for_schema(schema)
    schema_atoms = schema_type.atoms if schema_type is not None else JSON_TYPE_ATOMS
    atoms = schema_atoms - excluded_type.atoms
    return tuple(witness_for_type_atom(atom) for atom in sorted(atoms))


def _array_unique_overrides_for_skeleton(
    skeleton: ArrayWitnessSkeleton,
    dialect: Dialect,
    base_overrides: tuple[ArrayWitnessOverride, ...],
) -> tuple[ArrayWitnessOverride, ...] | None:
    by_index = {override.index: override.value for override in base_overrides}
    seen = {json_semantic_key(value) for value in by_index.values()}
    overrides = list(base_overrides)

    for slot in skeleton.slots:
        if slot.index in by_index:
            continue
        for value in _constructive_witness_values_for_schema(slot.schema, dialect):
            key = json_semantic_key(value)
            if key in seen:
                continue
            seen.add(key)
            overrides.append(ArrayWitnessOverride(slot.index, value))
            break
        else:
            return None
    return tuple(overrides)


def _distinct_concrete_witnesses_for_schema(
    schema: Any,
    dialect: Dialect,
    count: int,
) -> tuple[Any, ...] | None:
    if count <= 0:
        return ()

    values = []
    seen = set()
    for value in _constructive_witness_values_for_schema(schema, dialect):
        key = json_semantic_key(value)
        if key in seen:
            continue
        seen.add(key)
        values.append(value)
        if len(values) == count:
            return tuple(values)
    return None


def _constructive_witness_values_for_schema(
    schema: Any, dialect: Dialect
) -> tuple[Any, ...]:
    if schema is True:
        return (None, False, True, 0, 1, "", "a", [], {}, [None], {"a": None})

    finite = finite_values_for_schema(
        schema, ResourceGraph.build(schema, dialect=dialect)
    )
    if finite:
        return tuple(finite)

    numeric = numeric_shape_for_schema(schema, dialect)
    if numeric is not None:
        values: list[Any] = []
        for atom in numeric.normalized_atoms():
            values.extend(
                _json_number_from_fraction(fraction)
                for fraction in atom.candidate_fractions()
                if atom.contains(fraction) and numeric.contains(fraction)
            )
        return tuple(values)

    single = build_schema_witness(schema, dialect)
    if single.has_witness:
        return (single.witness,)
    return ()


def _json_number_from_fraction(value: Any) -> int | float:
    if value.denominator == 1:
        return int(value)
    return float(value)


def _concrete_witness_for_schema(schema: Any, dialect: Dialect) -> tuple[bool, Any]:
    result = build_schema_witness(schema, dialect)
    if result.status == "witness":
        return True, result.witness
    return False, None


@dataclass(frozen=True)
class ArrayUniquenessDifferencePlan:
    status: ArrayUniquenessPlanStatus
    reason: str = ""
    rejected_reason: str = ""
    witness: Any | None = None
    witness_skeleton: ArrayWitnessSkeleton | None = None
    duplicate_plan: ArrayDuplicateWitnessPlan | None = None

    @classmethod
    def proved_true(cls) -> ArrayUniquenessDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> ArrayUniquenessDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def resource_exhausted(cls, reason: str) -> ArrayUniquenessDifferencePlan:
        return cls("resource_exhausted", reason=reason)

    @classmethod
    def literal_witness(
        cls,
        witness: Any,
        *,
        rejected_reason: str,
    ) -> ArrayUniquenessDifferencePlan:
        return cls("witness", witness=witness, rejected_reason=rejected_reason)

    @classmethod
    def skeleton_witness(
        cls,
        skeleton: ArrayWitnessSkeleton,
        *,
        rejected_reason: str,
    ) -> ArrayUniquenessDifferencePlan:
        return cls(
            "witness", witness_skeleton=skeleton, rejected_reason=rejected_reason
        )

    @classmethod
    def duplicate_witness(
        cls,
        duplicate_plan: ArrayDuplicateWitnessPlan,
        *,
        rejected_reason: str,
    ) -> ArrayUniquenessDifferencePlan:
        return cls(
            "duplicate_witness",
            duplicate_plan=duplicate_plan,
            rejected_reason=rejected_reason,
        )


@dataclass(frozen=True)
class ArrayItemValueObligation:
    index: int
    lhs_schema: Any
    rhs_schema: Any
    source: ArrayItemValueSource


@dataclass(frozen=True)
class ArrayItemValuesDifferencePlan:
    status: ArrayItemValuesPlanStatus
    reason: str = ""
    rejected_reason: str = ""
    witness: Any | None = None
    witness_skeleton: ArrayWitnessSkeleton | None = None
    witness_plan: ArrayWitnessPlan | None = None
    obligations: tuple[ArrayItemValueObligation, ...] = ()
    post_obligation_witness_skeleton: ArrayWitnessSkeleton | None = None
    post_obligation_witness_plan: ArrayWitnessPlan | None = None
    post_obligation_rejected_reason: str = ""

    @classmethod
    def proved_true(cls) -> ArrayItemValuesDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> ArrayItemValuesDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def resource_exhausted(cls, reason: str) -> ArrayItemValuesDifferencePlan:
        return cls("resource_exhausted", reason=reason)

    @classmethod
    def literal_witness(
        cls,
        witness: Any,
        *,
        rejected_reason: str,
    ) -> ArrayItemValuesDifferencePlan:
        return cls("witness", witness=witness, rejected_reason=rejected_reason)

    @classmethod
    def skeleton_witness(
        cls,
        skeleton: ArrayWitnessSkeleton,
        *,
        rejected_reason: str,
        witness_plan: ArrayWitnessPlan | None = None,
    ) -> ArrayItemValuesDifferencePlan:
        return cls(
            "witness",
            witness_skeleton=skeleton,
            witness_plan=witness_plan,
            rejected_reason=rejected_reason,
        )

    @classmethod
    def obligation_plan(
        cls,
        obligations: tuple[ArrayItemValueObligation, ...],
        *,
        post_obligation_witness_skeleton: ArrayWitnessSkeleton | None = None,
        post_obligation_witness_plan: ArrayWitnessPlan | None = None,
        post_obligation_rejected_reason: str = "",
    ) -> ArrayItemValuesDifferencePlan:
        return cls(
            "obligations",
            obligations=obligations,
            post_obligation_witness_skeleton=post_obligation_witness_skeleton,
            post_obligation_witness_plan=post_obligation_witness_plan,
            post_obligation_rejected_reason=post_obligation_rejected_reason,
        )


@dataclass(frozen=True)
class ArrayDifferenceModel:
    lhs: LogicalSchemaIR
    rhs: LogicalSchemaIR
    problem: DifferenceProblem | None = None
    lhs_length_constraint: ArrayLengthConstraint | None = None
    rhs_length_constraint: ArrayLengthConstraint | None = None
    rhs_length_with_item_values_constraint: ArrayLengthConstraint | None = None
    lhs_uniqueness_constraint: ArrayUniquenessConstraint | None = None
    rhs_uniqueness_constraint: ArrayUniquenessConstraint | None = None

    @classmethod
    def from_irs(
        cls, lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
    ) -> ArrayDifferenceModel:
        return cls(lhs, rhs)

    @classmethod
    def from_problem(cls, problem: DifferenceProblem) -> ArrayDifferenceModel:
        return cls(
            problem.formula.lhs,
            problem.formula.rhs,
            problem=problem,
        )

    def _lhs_constraint(self, kind: IRAssertionKind) -> Any | None:
        return None if self.problem is None else self.problem.lhs_constraint(kind)

    def _rhs_constraint(self, kind: IRAssertionKind) -> Any | None:
        return None if self.problem is None else self.problem.rhs_constraint(kind)

    @cached_property
    def lhs_length(self) -> ArrayShape | None:
        constraint = (
            self.lhs_length_constraint
            or _array_length_constraint(self._lhs_constraint("array-length-lhs"))
            or self.lhs.facts.array_length_lhs_constraint
        )
        return None if constraint is None else constraint.shape

    @cached_property
    def rhs_length(self) -> ArrayShape | None:
        constraint = (
            self.rhs_length_constraint
            or _array_length_constraint(self._rhs_constraint("array-length-rhs"))
            or self.rhs.facts.array_length_rhs_constraint
        )
        return None if constraint is None else constraint.shape

    @cached_property
    def rhs_length_with_item_values(self) -> ArrayShape | None:
        constraint = (
            self.rhs_length_with_item_values_constraint
            or _array_length_constraint(self._rhs_constraint("array-length-lhs"))
            or self.rhs.facts.array_length_lhs_constraint
        )
        return None if constraint is None else constraint.shape

    @cached_property
    def lhs_uniqueness(self) -> ArrayUniquenessShape | None:
        constraint = (
            self.lhs_uniqueness_constraint
            or _array_uniqueness_constraint(
                self._lhs_constraint("array-uniqueness-lhs")
            )
            or self.lhs.facts.array_uniqueness_lhs_constraint
        )
        return None if constraint is None else constraint.shape

    @cached_property
    def rhs_uniqueness(self) -> ArrayUniquenessShape | None:
        constraint = (
            self.rhs_uniqueness_constraint
            or _array_uniqueness_constraint(
                self._rhs_constraint("array-uniqueness-rhs")
            )
            or self.rhs.facts.array_uniqueness_rhs_constraint
        )
        if constraint is not None:
            return constraint.shape
        return array_unique_items_requirement_for_schema(self.rhs.schema)

    @cached_property
    def lhs_slots(self) -> tuple[ArraySlot, ...]:
        return _array_slots(self.lhs)

    @cached_property
    def rhs_slots(self) -> tuple[ArraySlot, ...]:
        return _array_slots(self.rhs)

    @cached_property
    def lhs_tail(self) -> ArrayTail | None:
        return _array_tail(self.lhs)

    @cached_property
    def rhs_tail(self) -> ArrayTail | None:
        return _array_tail(self.rhs)

    @cached_property
    def lhs_contains(self) -> ArrayContainsConstraint | None:
        return _array_contains(self.lhs)

    @cached_property
    def rhs_contains(self) -> ArrayContainsConstraint | None:
        return _array_contains(self.rhs)

    def unevaluated_items_difference_plan(
        self,
        *,
        budget: int = -1,
        expanded: bool = False,
    ) -> ArrayUnevaluatedItemsDifferencePlan:
        constraint = self.rhs.evaluation.unevaluated_items
        if constraint is None:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems difference requires unevaluatedItems"
            )
        rhs_trace = _rhs_evaluation_trace(self.lhs.schema, self.rhs, self.problem)
        if rhs_trace.is_resource_exhausted:
            return ArrayUnevaluatedItemsDifferencePlan.resource_exhausted(
                rhs_trace.resource_exhausted_reason
            )
        if not rhs_trace.is_supported:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                rhs_trace.unsupported_reason
            )
        if not _evaluated_item_sources_are_supported(rhs_trace.evaluated_item_sources):
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems difference defers non-structural "
                "evaluated item sources"
            )

        finite_lhs_plan = self._finite_lhs_unevaluated_items_difference_plan(
            rhs_trace.evaluated_item_sources,
            constraint.schema,
            budget=budget,
            expanded=expanded,
        )
        if finite_lhs_plan.status != "unsupported":
            return finite_lhs_plan
        if constraint.schema is not False:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT schema-valued unevaluatedItems witness requires finite "
                "left length facts"
            )

        unevaluated_index = _first_rhs_unevaluated_item_index_reachable(
            self, rhs_trace.evaluated_item_sources
        )
        if unevaluated_index is None:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems witness could not find a reachable "
                "unevaluated item"
            )

        skeleton = self.array_witness_skeleton(unevaluated_index + 1, budget=budget)
        if skeleton is None:
            if budget >= 0 and unevaluated_index + 1 > budget:
                return ArrayUnevaluatedItemsDifferencePlan.resource_exhausted(
                    "array witness exceeded proof work budget"
                )
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems witness could not be constructed"
            )
        return ArrayUnevaluatedItemsDifferencePlan.skeleton_witness(
            skeleton,
            rejected_reason="SAT unevaluatedItems witness was rejected",
        )

    def _finite_lhs_unevaluated_items_difference_plan(
        self,
        rhs_sources: tuple[Any, ...],
        unevaluated_schema: Any,
        *,
        budget: int = -1,
        expanded: bool = False,
    ) -> ArrayUnevaluatedItemsDifferencePlan:
        lhs_length = self.lhs_length
        if lhs_length is None:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems true proof requires exact left length facts"
            )
        if lhs_length.accepts_non_array:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems true proof currently requires an "
                "array-only left schema"
            )
        if not _rhs_all_of_unevaluated_items_true_fragment_supported(
            self.rhs.root.source.schema
        ):
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems true proof defers non-frontier right assertions"
            )

        upper_bound = self.array_length_upper_bound()
        if upper_bound is None:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems true proof requires a finite left "
                "length upper bound"
            )

        obligations = []
        for index in range(upper_bound):
            if self.first_lhs_length_reaching(index) is None:
                continue
            rhs_schema = _rhs_evaluated_item_schema_for_index(rhs_sources, index, self)
            if rhs_schema is None:
                if expanded and unevaluated_schema is False:
                    contains_obligation = (
                        self._expanded_contains_unevaluated_item_obligation(
                            index,
                            rhs_sources,
                        )
                    )
                    if contains_obligation is not None:
                        if self.problem is None:
                            return (
                                ArrayUnevaluatedItemsDifferencePlan.unsupported(
                                    "SAT unevaluatedItems expanded proof requires "
                                    "a proof context"
                                )
                            )
                        exhausted = self.problem.context.spend_work(
                            1,
                            "evaluation trace",
                            "evaluation trace exceeded proof work budget",
                        )
                        if exhausted is not None:
                            return (
                                ArrayUnevaluatedItemsDifferencePlan.resource_exhausted(
                                    exhausted.reason or ""
                                )
                            )
                        return ArrayUnevaluatedItemsDifferencePlan.obligation_plan(
                            (contains_obligation,)
                        )
                if unevaluated_schema is not False:
                    obligations.append(
                        ArrayUnevaluatedItemObligation(
                            index,
                            self.lhs_item_schema_at(index),
                            unevaluated_schema,
                        )
                    )
                    continue
                skeleton = self.array_witness_skeleton(index + 1, budget=budget)
                if skeleton is None:
                    if budget >= 0 and index + 1 > budget:
                        return ArrayUnevaluatedItemsDifferencePlan.resource_exhausted(
                            "array witness exceeded proof work budget"
                        )
                    return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                        "SAT unevaluatedItems finite-left witness could not be "
                        "constructed"
                    )
                return ArrayUnevaluatedItemsDifferencePlan.skeleton_witness(
                    skeleton,
                    rejected_reason=(
                        "SAT unevaluatedItems finite-left witness was rejected"
                    ),
                )

            obligations.append(
                ArrayUnevaluatedItemObligation(
                    index, self.lhs_item_schema_at(index), rhs_schema
                )
            )

        if obligations:
            return ArrayUnevaluatedItemsDifferencePlan.obligation_plan(
                tuple(obligations)
            )
        return ArrayUnevaluatedItemsDifferencePlan.proved_true()

    def _expanded_contains_unevaluated_item_obligation(
        self,
        index: int,
        rhs_sources: tuple[Any, ...],
    ) -> ArrayUnevaluatedItemObligation | None:
        if self.problem is None:
            return None
        contains_sources = tuple(
            source
            for source in rhs_sources
            if source.kind == "contains" and source.marks_contains_matches
        )
        if len(contains_sources) != 1:
            return None
        return ArrayUnevaluatedItemObligation(
            index,
            self.lhs_item_schema_at(index),
            contains_sources[0].schema,
        )

    def length_difference_plan(self, *, budget: int = -1) -> ArrayLengthDifferencePlan:
        lhs_shape = self.lhs_length
        rhs_shape = self.rhs_length
        if lhs_shape is None or rhs_shape is None:
            return ArrayLengthDifferencePlan.unsupported(
                "SAT array length difference requires exact length shapes"
            )

        if lhs_shape.accepts_non_array and not rhs_shape.accepts_non_array:
            return ArrayLengthDifferencePlan.literal_witness(
                "",
                rejected_reason=(
                    "SAT array non-array witness was rejected by concrete validation"
                ),
            )
        if lhs_shape.accepts_non_array:
            return ArrayLengthDifferencePlan.unsupported(
                "SAT array length true proof requires an array-only left schema"
            )
        if lhs_shape.is_subset_of(rhs_shape):
            if not self._length_true_proof_covers_rhs_uniqueness():
                return ArrayLengthDifferencePlan.unsupported(
                    "SAT array length true proof cannot prove right uniqueItems"
                )
            return ArrayLengthDifferencePlan.proved_true()
        if self.problem is not None:
            symbolic = self._symbolic_length_difference_plan(
                lhs_shape, rhs_shape, budget=budget
            )
            if symbolic.status != "unsupported":
                return symbolic

        witness_length = lhs_shape.witness_length_not_in(rhs_shape)
        if witness_length is None:
            return ArrayLengthDifferencePlan.unsupported(
                "SAT array length difference could not construct a witness"
            )
        if budget >= 0 and witness_length > budget:
            return ArrayLengthDifferencePlan.resource_exhausted(
                "array witness exceeded proof work budget"
            )
        skeleton = self.array_witness_skeleton(witness_length, budget=budget)
        if skeleton is None:
            return ArrayLengthDifferencePlan.unsupported(
                "SAT array length witness could not be populated"
            )
        witness_plan = self._array_length_witness_plan_with_lhs_contains(skeleton)
        if witness_plan is not None:
            return ArrayLengthDifferencePlan.planned_witness(
                witness_plan,
                rejected_reason=(
                    "SAT array length witness was rejected by concrete validation"
                ),
            )
        return ArrayLengthDifferencePlan.skeleton_witness(
            skeleton,
            rejected_reason=(
                "SAT array length witness was rejected by concrete validation"
            ),
        )

    def _symbolic_length_difference_plan(
        self,
        lhs_shape: ArrayShape,
        rhs_shape: ArrayShape,
        *,
        budget: int,
    ) -> ArrayLengthDifferencePlan:
        if self.problem is None:
            return ArrayLengthDifferencePlan.unsupported(
                "SAT array length symbolic product requires a proof context"
            )
        solver = SymbolicSolver(
            self.problem.context,
            "array product",
            "array product exceeded proof work budget",
        )
        length = solver.int_var("array_length")
        lhs_expr = _array_length_shape_symbolic_expr(lhs_shape, length, solver)
        rhs_expr = _array_length_shape_symbolic_expr(rhs_shape, length, solver)
        solver.add(solver.ge(length, 0), lhs_expr, solver.not_(rhs_expr))
        check = solver.check_with_work(
            units=max(
                len(lhs_shape.normalized_intervals())
                + len(rhs_shape.normalized_intervals()),
                1,
            )
        )
        if isinstance(check, ProofResult):
            if check.status == "resource_exhausted":
                return ArrayLengthDifferencePlan.resource_exhausted(check.reason or "")
            return ArrayLengthDifferencePlan.unsupported(
                check.reason or "SAT array length symbolic solver returned unknown"
            )
        if check == SAT:
            witness_length = solver.model_int(solver.model(), "array_length")
            if budget >= 0 and witness_length > budget:
                return ArrayLengthDifferencePlan.resource_exhausted(
                    "array witness exceeded proof work budget"
                )
            skeleton = self.array_witness_skeleton(witness_length, budget=budget)
            if skeleton is None:
                return ArrayLengthDifferencePlan.unsupported(
                    "SAT array length symbolic witness could not be populated"
                )
            witness_plan = self._array_length_witness_plan_with_lhs_contains(skeleton)
            if witness_plan is not None:
                return ArrayLengthDifferencePlan.planned_witness(
                    witness_plan,
                    rejected_reason=(
                        "SAT array length witness was rejected by concrete validation"
                    ),
                )
            return ArrayLengthDifferencePlan.skeleton_witness(
                skeleton,
                rejected_reason=(
                    "SAT array length witness was rejected by concrete validation"
                ),
            )
        if check == UNSAT:
            if not self._length_true_proof_covers_rhs_uniqueness():
                return ArrayLengthDifferencePlan.unsupported(
                    "SAT array length symbolic true proof cannot prove right "
                    "uniqueItems"
                )
            return ArrayLengthDifferencePlan.proved_true()
        return ArrayLengthDifferencePlan.unsupported(
            "SAT array length symbolic solver returned unknown"
        )

    def _length_true_proof_covers_rhs_uniqueness(self) -> bool:
        rhs_uniqueness = self.rhs_uniqueness
        if rhs_uniqueness is None or not rhs_uniqueness.requires_unique_items:
            return True
        lhs_uniqueness = self.lhs_uniqueness
        return lhs_uniqueness is not None and lhs_uniqueness.guarantees_unique_items

    def _array_length_witness_plan_with_lhs_contains(
        self,
        skeleton: ArrayWitnessSkeleton,
    ) -> ArrayWitnessPlan | None:
        if self.problem is None:
            return None
        overrides: list[ArrayWitnessOverride] = []
        if self.lhs_contains is not None and self.lhs_contains.minimum > 0:
            if skeleton.length < self.lhs_contains.minimum:
                return None
            contains_overrides = _array_contains_overrides(
                self.lhs_contains.schema,
                self.problem.dialect,
                self.lhs_contains.minimum,
            )
            if contains_overrides is None or any(
                override.index >= skeleton.length for override in contains_overrides
            ):
                return None
            overrides.extend(contains_overrides)

        if (
            self.lhs_uniqueness is not None
            and self.lhs_uniqueness.guarantees_unique_items
        ):
            unique_overrides = _array_unique_overrides_for_skeleton(
                skeleton,
                self.problem.dialect,
                tuple(overrides),
            )
            if unique_overrides is None:
                return None
            overrides = list(unique_overrides)

        return ArrayWitnessPlan(skeleton, tuple(overrides)) if overrides else None

    def minimum_contains_matches_guaranteed(
        self,
        contains_schema: Any,
        context: ProofContext,
    ) -> int | None:
        guaranteed = 0
        if self.lhs_contains is not None and _subschema_is_proved(
            self.lhs_contains.schema,
            contains_schema,
            context,
        ):
            guaranteed = max(guaranteed, self.lhs_contains.minimum)

        structural = self._minimum_structural_contains_matches(contains_schema, context)
        if structural is not None:
            guaranteed = max(guaranteed, structural)
        return guaranteed

    def maximum_contains_matches_possible(
        self,
        contains_schema: Any,
        context: ProofContext,
    ) -> int | None:
        upper_bounds = []
        length_upper = self.array_length_upper_bound()
        if length_upper is not None:
            upper_bounds.append(length_upper)
        structural = self._maximum_structural_contains_matches(contains_schema, context)
        if structural is not None:
            upper_bounds.append(structural)
        if (
            self.lhs_contains is not None
            and self.lhs_contains.maximum is not None
            and _subschema_is_proved(contains_schema, self.lhs_contains.schema, context)
        ):
            upper_bounds.append(self.lhs_contains.maximum)
        if not upper_bounds:
            return None
        return min(upper_bounds)

    def array_length_lower_bound(self) -> int | None:
        if self.lhs_length is None:
            return None
        intervals = self.lhs_length.normalized_intervals()
        if not intervals:
            return 0
        return min(interval.lower for interval in intervals)

    def array_length_upper_bound(self) -> int | None:
        if self.lhs_length is None:
            return None
        intervals = self.lhs_length.normalized_intervals()
        if not intervals:
            return 0
        if any(interval.upper is None for interval in intervals):
            return None
        return max(
            interval.upper for interval in intervals if interval.upper is not None
        )

    def first_lhs_length_reaching(self, index: int) -> int | None:
        if self.lhs_length is None:
            return None
        minimum_length = index + 1
        for interval in self.lhs_length.normalized_intervals():
            length = max(interval.lower, minimum_length)
            if interval.upper is None or length <= interval.upper:
                return length
        return None

    def lhs_item_schema_at(self, index: int) -> Any:
        return _array_item_schema_at(self.lhs_slots, self.lhs_tail, index)

    def first_lhs_array_length(self) -> int:
        if self.lhs_length is None:
            return 0
        intervals = self.lhs_length.normalized_intervals()
        return intervals[0].lower if intervals else 0

    def lhs_allows_length(self, length: int) -> bool:
        return self.lhs_length is None or _array_length_shape_allows(
            self.lhs_length, length
        )

    def array_witness_skeleton(
        self,
        length: int,
        *,
        budget: int = -1,
    ) -> ArrayWitnessSkeleton | None:
        if budget >= 0 and length > budget:
            return None
        return ArrayWitnessSkeleton(
            length,
            tuple(
                ArrayWitnessSlot(index, self.lhs_item_schema_at(index))
                for index in range(length)
            ),
        )

    def first_lhs_array_witness_skeleton(
        self, *, budget: int = -1
    ) -> ArrayWitnessSkeleton | None:
        return self.array_witness_skeleton(self.first_lhs_array_length(), budget=budget)

    def array_witness_skeleton_for_length_witness(
        self,
        length_witness: Any,
        *,
        budget: int = -1,
    ) -> ArrayWitnessSkeleton | None:
        if not isinstance(length_witness, list):
            return None
        return self.array_witness_skeleton(len(length_witness), budget=budget)

    def array_witness_skeleton_reaching(
        self,
        index: int,
        *,
        budget: int = -1,
    ) -> ArrayWitnessSkeleton | None:
        length = self.first_lhs_length_reaching(index)
        if length is None:
            return None
        return self.array_witness_skeleton(length, budget=budget)

    def array_witness_skeleton_reaching_budget_exhausted(
        self,
        index: int,
        *,
        budget: int = -1,
    ) -> bool:
        length = self.first_lhs_length_reaching(index)
        return budget >= 0 and length is not None and length > budget

    def array_witness_plan_with_override(
        self,
        index: int,
        value: Any,
        *,
        budget: int = -1,
    ) -> ArrayWitnessPlan | None:
        overrides = [ArrayWitnessOverride(index, value)]
        contains_matches_already_present = 0
        if (
            self.problem is not None
            and self.lhs_contains is not None
            and _subschema_is_proved(
                {"const": value}, self.lhs_contains.schema, self.problem.context
            )
        ):
            contains_matches_already_present = 1
        required_contains_matches = None
        if self.lhs_contains is not None:
            required_contains_matches = max(
                self.lhs_contains.minimum - contains_matches_already_present, 0
            )
        contains_slots = self._lhs_contains_required_overrides(
            excluded_indexes=frozenset({index}),
            required_matches=required_contains_matches,
        )
        if contains_slots is None:
            return None
        overrides.extend(contains_slots)
        length = self.first_lhs_length_reaching(
            max(override.index for override in overrides)
        )
        if length is None:
            return None
        skeleton = self.array_witness_skeleton(length, budget=budget)
        if skeleton is None:
            return None
        if (
            self.lhs_uniqueness is not None
            and self.lhs_uniqueness.guarantees_unique_items
        ):
            unique_overrides = _array_unique_overrides_for_skeleton(
                skeleton,
                self.problem.dialect
                if self.problem is not None
                else Dialect.DRAFT202012,
                tuple(overrides),
            )
            if unique_overrides is None:
                return None
            overrides = list(unique_overrides)
        return ArrayWitnessPlan(skeleton, tuple(overrides))

    def rhs_closed_tail_violation_skeleton(
        self, *, budget: int = -1
    ) -> ArrayWitnessSkeleton | None:
        length = self.rhs_closed_tail_violation_length()
        if length is None:
            return None
        return self.array_witness_skeleton(length, budget=budget)

    def uniqueness_duplicate_witness_plan(
        self, *, budget: int = -1
    ) -> ArrayDuplicateWitnessPlan | None:
        contains_plan = self._contains_compatible_duplicate_witness_plan(budget=budget)
        if contains_plan is not None:
            return contains_plan

        tail_plan = self._tail_duplicate_witness_plan(budget=budget)
        if tail_plan is not None:
            return tail_plan

        first_index = 0
        second_index = 1
        length = self.first_lhs_length_reaching(second_index)
        if length is None:
            # Length facts can be unavailable when uniqueness is the active
            # array fragment.  Concrete validation remains the final guard.
            length = second_index + 1
        skeleton = self.array_witness_skeleton(length, budget=budget)
        if skeleton is None:
            return None
        return ArrayDuplicateWitnessPlan(
            skeleton,
            first_index,
            second_index,
            _all_of_schema(
                (
                    self.lhs_item_schema_at(first_index),
                    self.lhs_item_schema_at(second_index),
                )
            ),
        )

    def _contains_compatible_duplicate_witness_plan(
        self, *, budget: int = -1
    ) -> ArrayDuplicateWitnessPlan | None:
        lhs_contains = self.lhs_contains
        if lhs_contains is None:
            return None
        contains_overrides = self._lhs_contains_required_overrides(
            excluded_indexes=frozenset()
        )
        if contains_overrides is None:
            return None
        first_index = len(contains_overrides)
        second_index = first_index + 1
        length = self.first_lhs_length_reaching(second_index)
        if length is None:
            return None
        skeleton = self.array_witness_skeleton(length, budget=budget)
        if skeleton is None:
            return None
        duplicate_parts = (
            self.lhs_item_schema_at(first_index),
            self.lhs_item_schema_at(second_index),
            {"not": lhs_contains.schema},
        )
        duplicate_schema = _all_of_schema(
            tuple(schema for schema in duplicate_parts if schema is not True)
        )
        return ArrayDuplicateWitnessPlan(
            skeleton,
            first_index,
            second_index,
            duplicate_schema,
            tuple(contains_overrides),
        )

    def _lhs_contains_required_overrides(
        self,
        *,
        excluded_indexes: frozenset[int],
        required_matches: int | None = None,
    ) -> tuple[ArrayWitnessOverride, ...] | None:
        lhs_contains = self.lhs_contains
        if lhs_contains is None:
            return ()
        count = lhs_contains.minimum if required_matches is None else required_matches
        if count <= 0:
            return ()
        if (
            lhs_contains.maximum is not None
            and lhs_contains.minimum > lhs_contains.maximum
        ):
            return None
        if self.problem is None:
            return None
        found, value = _concrete_witness_for_schema(
            lhs_contains.schema, self.problem.dialect
        )
        if not found:
            return None
        overrides: list[ArrayWitnessOverride] = []
        index = 0
        while len(overrides) < count:
            if index not in excluded_indexes:
                overrides.append(ArrayWitnessOverride(index, value))
            index += 1
        return tuple(overrides)

    def _tail_duplicate_witness_plan(
        self, *, budget: int = -1
    ) -> ArrayDuplicateWitnessPlan | None:
        if self.lhs_tail is None or self.lhs_tail.closed:
            return None
        first_index = self.lhs_tail.start_index
        second_index = first_index + 1
        length = self.first_lhs_length_reaching(second_index)
        if length is None:
            return None
        skeleton = self.array_witness_skeleton(length, budget=budget)
        if skeleton is None:
            return None
        return ArrayDuplicateWitnessPlan(
            skeleton,
            first_index,
            second_index,
            self.lhs_tail.schema,
        )

    def uniqueness_difference_plan(
        self, *, budget: int = -1
    ) -> ArrayUniquenessDifferencePlan:
        lhs_shape = self.lhs_uniqueness
        rhs_shape = self.rhs_uniqueness
        if rhs_shape is None:
            return ArrayUniquenessDifferencePlan.unsupported(
                "SAT array uniqueness difference requires exact uniqueness shapes"
            )
        if (
            lhs_shape is None
            and _schema_type_is_array_only(self.lhs.schema)
            and rhs_shape.requires_unique_items
        ):
            duplicate_plan = self.uniqueness_duplicate_witness_plan(budget=budget)
            if duplicate_plan is None:
                return ArrayUniquenessDifferencePlan.unsupported(
                    "SAT array uniqueness difference could not construct a "
                    "duplicate witness"
                )
            return ArrayUniquenessDifferencePlan.duplicate_witness(
                duplicate_plan,
                rejected_reason=(
                    "SAT array uniqueness duplicate witness was rejected "
                    "by concrete validation"
                ),
            )
        if lhs_shape is None:
            return ArrayUniquenessDifferencePlan.unsupported(
                "SAT array uniqueness difference requires exact uniqueness shapes"
            )

        if lhs_shape.accepts_non_array and not rhs_shape.accepts_non_array:
            return ArrayUniquenessDifferencePlan.literal_witness(
                "",
                rejected_reason=(
                    "SAT array uniqueness non-array witness was rejected "
                    "by concrete validation"
                ),
            )
        if not lhs_shape.accepts_array:
            return ArrayUniquenessDifferencePlan.proved_true()
        if not rhs_shape.accepts_array:
            skeleton = self.first_lhs_array_witness_skeleton(budget=budget)
            if skeleton is None:
                length = self.first_lhs_array_length()
                if budget >= 0 and length > budget:
                    return ArrayUniquenessDifferencePlan.resource_exhausted(
                        "array witness exceeded proof work budget"
                    )
                return ArrayUniquenessDifferencePlan.unsupported(
                    "SAT array uniqueness array witness could not be constructed"
                )
            return ArrayUniquenessDifferencePlan.skeleton_witness(
                skeleton,
                rejected_reason=(
                    "SAT array uniqueness array witness was rejected by "
                    "concrete validation"
                ),
            )
        if not rhs_shape.requires_unique_items or lhs_shape.guarantees_unique_items:
            if not rhs_shape.complete_uniqueness_fragment:
                return ArrayUniquenessDifferencePlan.unsupported(
                    "SAT array uniqueness true proof cannot prove right "
                    "non-uniqueness constraints"
                )
            return ArrayUniquenessDifferencePlan.proved_true()

        duplicate_plan = self.uniqueness_duplicate_witness_plan(budget=budget)
        if duplicate_plan is None:
            length = self.first_lhs_length_reaching(1) or 2
            if budget >= 0 and length > budget:
                return ArrayUniquenessDifferencePlan.resource_exhausted(
                    "array witness exceeded proof work budget"
                )
            return ArrayUniquenessDifferencePlan.unsupported(
                "SAT array uniqueness difference could not construct a "
                "duplicate witness"
            )
        return ArrayUniquenessDifferencePlan.duplicate_witness(
            duplicate_plan,
            rejected_reason=(
                "SAT array uniqueness duplicate witness was rejected by "
                "concrete validation"
            ),
        )

    def contains_difference_plan(
        self,
        context: ProofContext,
        *,
        budget: int = -1,
        expanded: bool = False,
    ) -> ArrayContainsDifferencePlan:
        rhs_contains = self.rhs_contains
        if rhs_contains is None:
            return ArrayContainsDifferencePlan.unsupported(
                "SAT array contains difference requires right contains constraint"
            )
        if not _schema_type_is_array_only(
            self.lhs.schema
        ) or not _schema_type_is_array_only(self.rhs.schema):
            return ArrayContainsDifferencePlan.unsupported(
                "SAT array contains difference requires array-only schemas"
            )

        if self.contains_empty_min_violation_possible(rhs_contains):
            return ArrayContainsDifferencePlan.literal_witness(
                [],
                rejected_reason="SAT array contains empty witness was rejected",
            )

        if self.lhs_contains is not None:
            contains_subproof = context.subproof(
                self.lhs_contains.schema,
                rhs_contains.schema,
            )
            if contains_subproof.status == "proved_false":
                return ArrayContainsDifferencePlan.literal_witness(
                    [contains_subproof.witness],
                    rejected_reason="SAT array contains schema witness was rejected",
                )

        lhs_min = self.minimum_contains_matches_guaranteed(rhs_contains.schema, context)
        if (
            rhs_contains.maximum is not None
            and lhs_min is not None
            and lhs_min > rhs_contains.maximum
        ):
            length = self.array_length_lower_bound()
            if length is None:
                if expanded:
                    expanded_max_violation, expanded_budget_exhausted = (
                        self._expanded_contains_max_violation_witness_plan_result(
                            rhs_contains,
                            context,
                            lhs_min,
                            budget=budget,
                        )
                    )
                    if expanded_budget_exhausted:
                        return ArrayContainsDifferencePlan.resource_exhausted(
                            "array product exceeded proof work budget"
                        )
                    if expanded_max_violation is not None:
                        return ArrayContainsDifferencePlan.planned_witness(
                            expanded_max_violation,
                            rejected_reason=(
                                "SAT array contains endeavor max violation "
                                "witness was rejected"
                            ),
                        )
                return ArrayContainsDifferencePlan.unsupported(
                    "SAT array contains max violation witness needs a lower "
                    "length bound"
                )
            exhausted = context.spend_work(
                max(length, 1),
                "array product",
                "array product exceeded proof work budget",
            )
            if exhausted is not None:
                return ArrayContainsDifferencePlan.resource_exhausted(
                    exhausted.reason or ""
                )
            if budget >= 0 and length > budget:
                return ArrayContainsDifferencePlan.resource_exhausted(
                    "array witness exceeded proof work budget"
                )
            skeleton = self.array_witness_skeleton(length, budget=budget)
            if skeleton is None:
                return ArrayContainsDifferencePlan.unsupported(
                    "SAT array contains max violation witness could not be constructed"
                )
            overrides: tuple[ArrayWitnessOverride, ...] = ()
            if self.lhs_contains is not None:
                contains_overrides = _array_contains_overrides(
                    self.lhs_contains.schema,
                    self.problem.dialect
                    if self.problem is not None
                    else Dialect.DRAFT202012,
                    min(length, lhs_min),
                )
                if contains_overrides is None:
                    return ArrayContainsDifferencePlan.unsupported(
                        "SAT array contains max violation witness could not "
                        "populate contains matches"
                    )
                overrides = contains_overrides
            return ArrayContainsDifferencePlan.planned_witness(
                ArrayWitnessPlan(skeleton, overrides),
                rejected_reason="SAT array contains max violation witness was rejected",
            )

        min_proved = rhs_contains.minimum == 0
        if not min_proved:
            min_proved = lhs_min is not None and lhs_min >= rhs_contains.minimum

        if not min_proved and self.lhs_contains is None:
            min_violation, min_violation_budget_exhausted = (
                self._contains_min_violation_witness_plan_result(
                    rhs_contains,
                    context,
                    budget=budget,
                )
            )
            if min_violation_budget_exhausted:
                return ArrayContainsDifferencePlan.resource_exhausted(
                    "array witness exceeded proof work budget"
                )
            if min_violation is not None:
                return ArrayContainsDifferencePlan.planned_witness(
                    min_violation,
                    rejected_reason=(
                        "SAT array contains min violation witness was rejected"
                    ),
                )

        if expanded and not min_proved:
            expanded_min_violation, expanded_budget_exhausted = (
                self._expanded_contains_min_violation_witness_plan_result(
                    rhs_contains,
                    context,
                    budget=budget,
                )
            )
            if expanded_budget_exhausted:
                return ArrayContainsDifferencePlan.resource_exhausted(
                    "array product exceeded proof work budget"
                )
            if expanded_min_violation is not None:
                return ArrayContainsDifferencePlan.planned_witness(
                    expanded_min_violation,
                    rejected_reason=(
                        "SAT array contains endeavor min violation witness was rejected"
                    ),
                )

        rhs_only_max_violation, rhs_only_budget_exhausted = (
            self._contains_rhs_only_max_violation_witness_plan_result(
                rhs_contains,
                context,
                budget=budget,
            )
        )
        if rhs_only_budget_exhausted:
            return ArrayContainsDifferencePlan.resource_exhausted(
                "array witness exceeded proof work budget"
            )
        if rhs_only_max_violation is not None:
            return ArrayContainsDifferencePlan.planned_witness(
                rhs_only_max_violation,
                rejected_reason=(
                    "SAT array contains rhs-only max violation witness was rejected"
                ),
            )

        max_violation, max_violation_budget_exhausted = (
            self._contains_max_violation_witness_plan_result(
                rhs_contains,
                context,
                budget=budget,
            )
        )
        if max_violation_budget_exhausted:
            return ArrayContainsDifferencePlan.resource_exhausted(
                "array witness exceeded proof work budget"
            )
        if max_violation is not None:
            return ArrayContainsDifferencePlan.planned_witness(
                max_violation,
                rejected_reason="SAT array contains max possible witness was rejected",
            )

        max_proved = rhs_contains.maximum is None
        if rhs_contains.maximum is not None:
            lhs_max = self.maximum_contains_matches_possible(
                rhs_contains.schema, context
            )
            max_proved = lhs_max is not None and lhs_max <= rhs_contains.maximum

        if min_proved and max_proved:
            return ArrayContainsDifferencePlan.proved_true()
        return ArrayContainsDifferencePlan.unsupported(
            "SAT array contains count bounds could not be proven exactly"
        )

    def _expanded_contains_min_violation_witness_plan_result(
        self,
        rhs_contains: ArrayContainsConstraint,
        context: ProofContext,
        *,
        budget: int = -1,
    ) -> tuple[ArrayWitnessPlan | None, bool]:
        if self.problem is None:
            return None, False
        lhs_contains = self.lhs_contains
        if lhs_contains is None or lhs_contains.minimum <= 0:
            return None, False
        if lhs_contains.minimum >= rhs_contains.minimum:
            return None, False

        length_lower_bound = self.array_length_lower_bound()
        length = max(
            lhs_contains.minimum,
            0 if length_lower_bound is None else length_lower_bound,
        )
        if length >= rhs_contains.minimum:
            return None, False
        units = max(length, 1)
        exhausted = context.spend_work(
            units,
            "array product",
            "array product exceeded proof work budget",
        )
        if exhausted is not None:
            return None, True

        skeleton = self.array_witness_skeleton(length, budget=budget)
        if skeleton is None:
            return None, budget >= 0 and length > budget
        overrides = _array_contains_overrides(
            lhs_contains.schema, self.problem.dialect, lhs_contains.minimum
        )
        if overrides is None:
            return None, False
        return ArrayWitnessPlan(skeleton, overrides), False

    def _expanded_contains_max_violation_witness_plan_result(
        self,
        rhs_contains: ArrayContainsConstraint,
        context: ProofContext,
        guaranteed_matches: int,
        *,
        budget: int = -1,
    ) -> tuple[ArrayWitnessPlan | None, bool]:
        lhs_contains = self.lhs_contains
        if lhs_contains is None or rhs_contains.maximum is None:
            return None, False
        if guaranteed_matches <= rhs_contains.maximum:
            return None, False

        length = guaranteed_matches
        exhausted = context.spend_work(
            max(length, 1),
            "array product",
            "array product exceeded proof work budget",
        )
        if exhausted is not None:
            return None, True

        skeleton = self.array_witness_skeleton(length, budget=budget)
        if skeleton is None:
            return None, budget >= 0 and length > budget
        if self.problem is None:
            return None, False
        overrides = _array_contains_overrides(
            lhs_contains.schema,
            self.problem.dialect,
            length,
        )
        if overrides is None:
            return None, False
        return ArrayWitnessPlan(skeleton, overrides), False

    def _contains_rhs_only_max_violation_witness_plan_result(
        self,
        rhs_contains: ArrayContainsConstraint,
        context: ProofContext,
        *,
        budget: int = -1,
    ) -> tuple[ArrayWitnessPlan | None, bool]:
        lhs_contains = self.lhs_contains
        if lhs_contains is None or rhs_contains.maximum is None or self.problem is None:
            return None, False

        required_lhs_matches = max(lhs_contains.minimum, 0)
        if (
            lhs_contains.maximum is not None
            and required_lhs_matches > lhs_contains.maximum
        ):
            return None, False

        target_rhs_matches = rhs_contains.maximum + 1
        extra_rhs_only_matches = target_rhs_matches - required_lhs_matches
        if extra_rhs_only_matches <= 0:
            return None, False

        rhs_only_values = _constructive_witness_values_excluding_schema(
            rhs_contains.schema,
            lhs_contains.schema,
            self.problem.dialect,
        )
        if not rhs_only_values:
            rhs_only_subproof = context.subproof(
                rhs_contains.schema, lhs_contains.schema
            )
            if (
                rhs_only_subproof.status != "proved_false"
                or rhs_only_subproof.witness is None
            ):
                return None, False
            rhs_only_values = (rhs_only_subproof.witness,)

        length = self.first_lhs_length_reaching(target_rhs_matches - 1)
        if length is None:
            return None, False

        skeleton = self.array_witness_skeleton(length, budget=budget)
        if skeleton is None:
            return None, budget >= 0 and length > budget

        distinct = (
            self.lhs_uniqueness is not None
            and self.lhs_uniqueness.guarantees_unique_items
        )
        lhs_overrides = _array_contains_overrides_for_max_violation(
            lhs_contains.schema,
            self.problem.dialect,
            required_lhs_matches,
            distinct=distinct,
        )
        if lhs_overrides is None:
            return None, False

        seen = {json_semantic_key(override.value) for override in lhs_overrides}
        extra_overrides: list[ArrayWitnessOverride] = []
        for value in rhs_only_values:
            key = json_semantic_key(value)
            if distinct and key in seen:
                continue
            seen.add(key)
            index = required_lhs_matches + len(extra_overrides)
            extra_overrides.append(ArrayWitnessOverride(index, value))
            if len(extra_overrides) == extra_rhs_only_matches:
                break
        if len(extra_overrides) < extra_rhs_only_matches:
            return None, False

        overrides = tuple(lhs_overrides) + tuple(extra_overrides)
        if distinct:
            unique_overrides = _array_unique_overrides_for_skeleton(
                skeleton, self.problem.dialect, overrides
            )
            if unique_overrides is None:
                return None, False
            overrides = unique_overrides
        return ArrayWitnessPlan(skeleton, overrides), False

    def contains_empty_min_violation_possible(
        self, rhs_contains: ArrayContainsConstraint
    ) -> bool:
        return (
            rhs_contains.minimum > 0
            and self.lhs_length is not None
            and _array_length_shape_allows(self.lhs_length, 0)
        )

    def contains_min_violation_plan(
        self,
        rhs_contains: ArrayContainsConstraint,
    ) -> ArrayContainsMinViolationPlan | None:
        if rhs_contains.minimum <= 0:
            return None
        length = self.array_length_lower_bound()
        if length is None or length <= 0:
            return None
        return ArrayContainsMinViolationPlan(
            length,
            tuple(
                ArrayContainsItemProof(index, self.lhs_item_schema_at(index))
                for index in range(length)
            ),
            rhs_contains.minimum,
        )

    def contains_max_violation_plan(
        self,
        rhs_contains: ArrayContainsConstraint,
    ) -> ArrayContainsMaxViolationPlan | None:
        if rhs_contains.maximum is None:
            return None
        target_matches = rhs_contains.maximum + 1
        if target_matches <= 0:
            return None
        length = self.first_lhs_length_reaching(target_matches - 1)
        if length is None:
            length = self._unique_items_only_lhs_length_reaching(target_matches - 1)
        if length is None:
            return None
        return ArrayContainsMaxViolationPlan(
            length,
            tuple(
                ArrayContainsItemProof(index, self.lhs_item_schema_at(index))
                for index in range(target_matches)
            ),
            target_matches,
        )

    def _unique_items_only_lhs_length_reaching(self, index: int) -> int | None:
        if not isinstance(self.lhs.schema, dict):
            return None
        if not _schema_has_only_keywords(
            self.lhs.schema, {"maxItems", "minItems", "type", "uniqueItems"}
        ):
            return None
        if self.lhs.schema.get("type") != "array":
            return None
        minimum = self.lhs.schema.get("minItems", 0)
        maximum = self.lhs.schema.get("maxItems")
        if not isinstance(minimum, int) or isinstance(minimum, bool):
            return None
        if maximum is not None and (
            not isinstance(maximum, int) or isinstance(maximum, bool)
        ):
            return None
        length = max(index + 1, minimum)
        if maximum is not None and length > maximum:
            return None
        return length

    def contains_min_violation_witness_plan(
        self,
        rhs_contains: ArrayContainsConstraint,
        context: ProofContext,
        *,
        budget: int = -1,
    ) -> ArrayWitnessPlan | None:
        plan, _budget_exhausted = self._contains_min_violation_witness_plan_result(
            rhs_contains,
            context,
            budget=budget,
        )
        return plan

    def _contains_min_violation_witness_plan_result(
        self,
        rhs_contains: ArrayContainsConstraint,
        context: ProofContext,
        *,
        budget: int = -1,
    ) -> tuple[ArrayWitnessPlan | None, bool]:
        plan = self.contains_min_violation_plan(rhs_contains)
        if plan is None:
            return None, False

        skeleton = self.array_witness_skeleton(plan.length, budget=budget)
        if skeleton is None:
            return None, budget >= 0 and plan.length > budget

        if (
            self.lhs_uniqueness is not None
            and self.lhs_uniqueness.guarantees_unique_items
        ):
            unique_overrides = _array_contains_nonmatching_overrides(
                plan,
                rhs_contains.schema,
                context.dialect,
            )
            if unique_overrides is not None:
                return ArrayWitnessPlan(skeleton, unique_overrides), False

        matching = 0
        overrides = []
        for item_proof in plan.item_proofs:
            proof = context.subproof(item_proof.lhs_schema, rhs_contains.schema)
            if proof.status == "proved_true":
                matching += 1
                continue
            if proof.status != "proved_false" or proof.witness is None:
                return None, False
            overrides.append(ArrayWitnessOverride(item_proof.index, proof.witness))

        if matching >= plan.minimum:
            return None, False
        return ArrayWitnessPlan(skeleton, tuple(overrides)), False

    def contains_max_violation_witness_plan(
        self,
        rhs_contains: ArrayContainsConstraint,
        context: ProofContext,
        *,
        budget: int = -1,
    ) -> ArrayWitnessPlan | None:
        plan, _budget_exhausted = self._contains_max_violation_witness_plan_result(
            rhs_contains,
            context,
            budget=budget,
        )
        return plan

    def _contains_max_violation_witness_plan_result(
        self,
        rhs_contains: ArrayContainsConstraint,
        context: ProofContext,
        *,
        budget: int = -1,
    ) -> tuple[ArrayWitnessPlan | None, bool]:
        plan = self.contains_max_violation_plan(rhs_contains)
        if plan is None:
            return None, False
        if (
            self.lhs_contains is not None
            and self.lhs_contains.maximum is not None
            and plan.target_matches > self.lhs_contains.maximum
            and _subschema_is_proved(
                rhs_contains.schema, self.lhs_contains.schema, context
            )
        ):
            return None, False

        if all(
            schema_is_true(item_proof.lhs_schema) for item_proof in plan.item_proofs
        ):
            distinct = (
                self.lhs_uniqueness is not None
                and self.lhs_uniqueness.guarantees_unique_items
            )
            overrides = _array_contains_overrides_for_max_violation(
                rhs_contains.schema,
                self.problem.dialect
                if self.problem is not None
                else Dialect.DRAFT202012,
                plan.target_matches,
                distinct=distinct,
            )
            if overrides is not None:
                skeleton = self.array_witness_skeleton(plan.length, budget=budget)
                if skeleton is None:
                    return None, budget >= 0 and plan.length > budget
                return ArrayWitnessPlan(skeleton, overrides), False

        for item_proof in plan.item_proofs:
            proof = context.subproof(item_proof.lhs_schema, rhs_contains.schema)
            if proof.status != "proved_true":
                return None, False

        skeleton = self.array_witness_skeleton(plan.length, budget=budget)
        if skeleton is None:
            return None, budget >= 0 and plan.length > budget
        return ArrayWitnessPlan(skeleton), False

    def has_rhs_item_value_constraints(self) -> bool:
        return any(not schema_is_true(slot.schema) for slot in self.rhs_slots) or (
            self.rhs_tail is not None and not schema_is_true(self.rhs_tail.schema)
        )

    def rhs_closed_tail_violation_length(self) -> int | None:
        if self.rhs_tail is None or not self.rhs_tail.closed:
            return None
        return self.first_lhs_length_reaching(self.rhs_tail.start_index)

    def item_value_obligations(self) -> tuple[ArrayItemValueObligation, ...]:
        obligations = []
        for slot in self.rhs_slots:
            if (
                schema_is_true(slot.schema)
                or self.first_lhs_length_reaching(slot.index) is None
            ):
                continue
            obligations.append(
                ArrayItemValueObligation(
                    slot.index,
                    self.lhs_item_schema_at(slot.index),
                    slot.schema,
                    "rhs-slot",
                )
            )

        rhs_tail = self.rhs_tail
        if rhs_tail is None or rhs_tail.closed or schema_is_true(rhs_tail.schema):
            return tuple(obligations)

        covered_slots = {slot.index for slot in self.lhs_slots}
        for slot in self.lhs_slots:
            if slot.index < rhs_tail.start_index:
                continue
            if self.first_lhs_length_reaching(slot.index) is None:
                continue
            obligations.append(
                ArrayItemValueObligation(
                    slot.index,
                    slot.schema,
                    rhs_tail.schema,
                    "lhs-slot-rhs-tail",
                )
            )

        unconstrained_index = self.first_lhs_unconstrained_index_under_rhs_tail(
            covered_slots
        )
        if unconstrained_index is not None:
            obligations.append(
                ArrayItemValueObligation(
                    unconstrained_index,
                    True,
                    rhs_tail.schema,
                    "lhs-unconstrained-rhs-tail",
                )
            )

        lhs_tail = self.lhs_tail
        if lhs_tail is not None and not lhs_tail.closed:
            tail_index = max(rhs_tail.start_index, lhs_tail.start_index)
            if self.first_lhs_length_reaching(tail_index) is not None:
                obligations.append(
                    ArrayItemValueObligation(
                        tail_index,
                        lhs_tail.schema,
                        rhs_tail.schema,
                        "lhs-tail-rhs-tail",
                    )
                )

        return tuple(obligations)

    def item_values_difference_plan(
        self,
        dialect: Dialect,
        *,
        budget: int = -1,
    ) -> ArrayItemValuesDifferencePlan:
        if not _is_array_item_values_fragment_schema(
            self.lhs.schema, dialect, allow_contains=True
        ):
            return ArrayItemValuesDifferencePlan.unsupported(
                "left schema is outside the SAT array item-values fragment"
            )
        if not _is_array_item_values_fragment_schema(
            self.rhs.schema, dialect, allow_contains=False
        ):
            return ArrayItemValuesDifferencePlan.unsupported(
                "right schema is outside the SAT array item-values fragment"
            )
        if not self.has_rhs_item_value_constraints():
            return ArrayItemValuesDifferencePlan.unsupported(
                "SAT array item-values difference requires right item constraints"
            )

        lhs_length = self.lhs_length
        rhs_length = self.rhs_length_with_item_values
        if lhs_length is None or rhs_length is None:
            return ArrayItemValuesDifferencePlan.unsupported(
                "SAT array item-values difference requires exact length facts"
            )

        if lhs_length.accepts_non_array and not rhs_length.accepts_non_array:
            return ArrayItemValuesDifferencePlan.literal_witness(
                "",
                rejected_reason="SAT array item-values non-array witness was rejected",
            )
        if not lhs_length.normalized_intervals():
            return ArrayItemValuesDifferencePlan.proved_true()
        if not rhs_length.normalized_intervals():
            skeleton = self.first_lhs_array_witness_skeleton(budget=budget)
            if skeleton is None:
                length = self.first_lhs_array_length()
                if budget >= 0 and length > budget:
                    return ArrayItemValuesDifferencePlan.resource_exhausted(
                        "array witness exceeded proof work budget"
                    )
                return ArrayItemValuesDifferencePlan.unsupported(
                    "SAT array item-values witness could not be constructed"
                )
            return ArrayItemValuesDifferencePlan.skeleton_witness(
                skeleton,
                witness_plan=self._array_length_witness_plan_with_lhs_contains(
                    skeleton
                ),
                rejected_reason="SAT array item-values array witness was rejected",
            )
        if not lhs_length.is_subset_of(rhs_length):
            length_witness = lhs_length.witness_not_in(rhs_length)
            if length_witness is None:
                return ArrayItemValuesDifferencePlan.unsupported(
                    "SAT array item-values length witness could not be constructed"
                )
            skeleton = self.array_witness_skeleton_for_length_witness(
                length_witness, budget=budget
            )
            if skeleton is None:
                if budget >= 0 and len(length_witness) > budget:
                    return ArrayItemValuesDifferencePlan.resource_exhausted(
                        "array witness exceeded proof work budget"
                    )
                return ArrayItemValuesDifferencePlan.unsupported(
                    "SAT array item-values length witness could not be populated"
                )
            return ArrayItemValuesDifferencePlan.skeleton_witness(
                skeleton,
                witness_plan=self._array_length_witness_plan_with_lhs_contains(
                    skeleton
                ),
                rejected_reason="SAT array item-values length witness was rejected",
            )

        obligations = self.item_value_obligations()
        if self.rhs_tail is not None and self.rhs_tail.closed:
            closed_tail_skeleton = self.rhs_closed_tail_violation_skeleton(
                budget=budget
            )
            closed_tail_length = self.rhs_closed_tail_violation_length()
            if closed_tail_skeleton is None and closed_tail_length is not None:
                if budget >= 0 and closed_tail_length > budget:
                    return ArrayItemValuesDifferencePlan.resource_exhausted(
                        "array witness exceeded proof work budget"
                    )
            if not obligations and closed_tail_skeleton is None:
                return ArrayItemValuesDifferencePlan.proved_true()
            closed_tail_plan = (
                None
                if closed_tail_skeleton is None
                else self._array_length_witness_plan_with_lhs_contains(
                    closed_tail_skeleton
                )
            )
            return ArrayItemValuesDifferencePlan.obligation_plan(
                obligations,
                post_obligation_witness_skeleton=closed_tail_skeleton,
                post_obligation_witness_plan=closed_tail_plan,
                post_obligation_rejected_reason=(
                    "SAT array item-values closed-tail witness was rejected"
                ),
            )
        if obligations:
            return ArrayItemValuesDifferencePlan.obligation_plan(obligations)
        return ArrayItemValuesDifferencePlan.proved_true()

    def first_lhs_unconstrained_index_under_rhs_tail(
        self, covered_slots: set[int]
    ) -> int | None:
        rhs_tail = self.rhs_tail
        if rhs_tail is None:
            return None

        start = rhs_tail.start_index
        lhs_tail = self.lhs_tail
        if lhs_tail is not None:
            for index in range(start, lhs_tail.start_index):
                if (
                    index not in covered_slots
                    and self.first_lhs_length_reaching(index) is not None
                ):
                    return index
            return None

        index = start
        while index in covered_slots:
            index += 1
        if self.first_lhs_length_reaching(index) is not None:
            return index
        return None

    def _minimum_structural_contains_matches(
        self,
        contains_schema: Any,
        context: ProofContext,
    ) -> int | None:
        minimum_items = self.array_length_lower_bound()
        if minimum_items is None:
            return None

        guaranteed = 0
        slots = {slot.index: slot for slot in self.lhs_slots}
        for index in range(minimum_items):
            slot = slots.get(index)
            if slot is not None:
                if _subschema_is_proved(slot.schema, contains_schema, context):
                    guaranteed += 1
                continue

            if self.lhs_tail is None or self.lhs_tail.closed:
                continue
            if _subschema_is_proved(self.lhs_tail.schema, contains_schema, context):
                guaranteed += 1
        return guaranteed

    def _maximum_structural_contains_matches(
        self,
        contains_schema: Any,
        context: ProofContext,
    ) -> int | None:
        finite_tail_upper = self._finite_tail_structural_contains_upper_bound(
            contains_schema, context
        )
        if finite_tail_upper is not None:
            return finite_tail_upper

        maximum_items = self.array_length_upper_bound()
        if maximum_items is None:
            return None
        budget = context.default_search_horizon
        if budget >= 0 and maximum_items > budget:
            return None

        non_matching_schema = _schema_negation(contains_schema)
        possible = 0
        for index in range(maximum_items):
            if self.first_lhs_length_reaching(index) is None:
                continue
            item_schema = self.lhs_item_schema_at(index)
            if _subschema_is_proved(item_schema, non_matching_schema, context):
                continue
            possible += 1
        return possible

    def _finite_tail_structural_contains_upper_bound(
        self,
        contains_schema: Any,
        context: ProofContext,
    ) -> int | None:
        lhs_tail = self.lhs_tail
        if lhs_tail is None:
            return None

        non_matching_schema = _schema_negation(contains_schema)
        if not lhs_tail.closed and not _subschema_is_proved(
            lhs_tail.schema, non_matching_schema, context
        ):
            return None

        possible = 0
        for index in range(lhs_tail.start_index):
            if self.first_lhs_length_reaching(index) is None:
                continue
            item_schema = self.lhs_item_schema_at(index)
            if _subschema_is_proved(item_schema, non_matching_schema, context):
                continue
            possible += 1
        return possible


@dataclass(frozen=True)
class ObjectKeyClass:
    kind: Literal["explicit", "pattern"]
    source: ObjectKeySource
    key: str


@dataclass(frozen=True)
class FreshPropertyClass:
    representative: str
    blocked_names: frozenset[str]


@dataclass(frozen=True)
class ObjectKeyUniverse:
    key_classes: tuple[ObjectKeyClass, ...]
    fresh: FreshPropertyClass | None
    lhs_closed_world: bool
    rhs_closed_world: bool

    @property
    def explicit_names(self) -> frozenset[str]:
        return frozenset(
            key_class.key
            for key_class in self.key_classes
            if key_class.kind == "explicit"
        )

    @property
    def pattern_names(self) -> frozenset[str]:
        return frozenset(
            key_class.key
            for key_class in self.key_classes
            if key_class.kind == "pattern"
        )

    @property
    def has_fresh_class(self) -> bool:
        return self.fresh is not None


@dataclass(frozen=True)
class ObjectPropertyValueObligation:
    name: str
    lhs_schema: Any
    rhs_schema: Any


@dataclass(frozen=True)
class ObjectPropertyValueWitnessSlot:
    name: str
    schema: Any


@dataclass(frozen=True)
class ObjectPropertyValueWitnessSkeleton:
    slots: tuple[ObjectPropertyValueWitnessSlot, ...]


def materialize_object_property_value_witness_skeleton(
    skeleton: ObjectPropertyValueWitnessSkeleton | None,
    dialect: Dialect,
    *,
    override: tuple[str, Any] | None = None,
) -> dict[str, Any] | None:
    if skeleton is None:
        return None

    witness = {}
    for slot in skeleton.slots:
        if override is not None and slot.name == override[0]:
            witness[slot.name] = override[1]
            continue
        found, value = _concrete_witness_for_schema(slot.schema, dialect)
        if not found:
            return None
        witness[slot.name] = value
    return witness


@dataclass(frozen=True)
class ObjectPropertyValuesDifferencePlan:
    status: ObjectPropertyValuesPlanStatus
    reason: str = ""
    rejected_reason: str = ""
    witness: Any | None = None
    witness_skeleton: ObjectPropertyValueWitnessSkeleton | None = None
    obligations: tuple[ObjectPropertyValueObligation, ...] = ()

    @classmethod
    def proved_true(cls) -> ObjectPropertyValuesDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> ObjectPropertyValuesDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def literal_witness(
        cls,
        witness: Any,
        *,
        rejected_reason: str,
    ) -> ObjectPropertyValuesDifferencePlan:
        return cls("witness", witness=witness, rejected_reason=rejected_reason)

    @classmethod
    def skeleton_witness(
        cls,
        skeleton: ObjectPropertyValueWitnessSkeleton,
        *,
        rejected_reason: str,
    ) -> ObjectPropertyValuesDifferencePlan:
        return cls(
            "witness", witness_skeleton=skeleton, rejected_reason=rejected_reason
        )

    @classmethod
    def obligation_plan(
        cls,
        obligations: tuple[ObjectPropertyValueObligation, ...],
    ) -> ObjectPropertyValuesDifferencePlan:
        return cls("obligations", obligations=obligations)


@dataclass(frozen=True)
class ObjectPropertyNamesRepairSlot:
    name: str
    schema: Any
    original_value: Any


@dataclass(frozen=True)
class ObjectPropertyNamesRepairSkeleton:
    slots: tuple[ObjectPropertyNamesRepairSlot, ...]


def materialize_object_property_names_repair_skeleton(
    skeleton: ObjectPropertyNamesRepairSkeleton | None,
    dialect: Dialect,
) -> dict[str, Any] | None:
    if skeleton is None:
        return None

    repaired = {}
    for slot in skeleton.slots:
        found, replacement = _concrete_witness_for_schema(slot.schema, dialect)
        repaired[slot.name] = replacement if found else slot.original_value
    return repaired


@dataclass(frozen=True)
class ObjectPropertyNamesDifferencePlan:
    status: ObjectPropertyNamesPlanStatus
    reason: str = ""
    witness: Any | None = None
    repair_skeleton: ObjectPropertyNamesRepairSkeleton | None = None

    @classmethod
    def proved_true(cls) -> ObjectPropertyNamesDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> ObjectPropertyNamesDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def witness_plan(
        cls,
        witness: Any,
        repair_skeleton: ObjectPropertyNamesRepairSkeleton | None,
    ) -> ObjectPropertyNamesDifferencePlan:
        return cls("witness", witness=witness, repair_skeleton=repair_skeleton)


@dataclass(frozen=True)
class ClosedObjectValueObligation:
    name: str
    lhs_schema: Any
    rhs_schema: Any


@dataclass(frozen=True)
class ClosedObjectWitnessSlot:
    name: str
    schema: Any


@dataclass(frozen=True)
class ClosedObjectWitnessSkeleton:
    slots: tuple[ClosedObjectWitnessSlot, ...]


def materialize_closed_object_witness_skeleton(
    skeleton: ClosedObjectWitnessSkeleton | None,
    dialect: Dialect,
    *,
    override: tuple[str, Any] | dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if skeleton is None:
        return None
    overrides = _object_witness_overrides(override)
    witness = {}
    for slot in skeleton.slots:
        if slot.name in overrides:
            witness[slot.name] = overrides[slot.name]
            continue
        found, value = _concrete_witness_for_schema(slot.schema, dialect)
        if not found:
            return None
        witness[slot.name] = value
    return witness


def _object_witness_overrides(
    override: tuple[str, Any] | dict[str, Any] | None,
) -> dict[str, Any]:
    if override is None:
        return {}
    if isinstance(override, tuple):
        return {override[0]: override[1]}
    return dict(override)


@dataclass(frozen=True)
class ClosedObjectDifferencePlan:
    status: ClosedObjectPlanStatus
    reason: str = ""
    rejected_reason: str = ""
    witness: Any | None = None
    witness_skeleton: ClosedObjectWitnessSkeleton | None = None
    obligations: tuple[ClosedObjectValueObligation, ...] = ()

    @classmethod
    def proved_true(cls) -> ClosedObjectDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> ClosedObjectDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def literal_witness(
        cls,
        witness: Any,
        *,
        rejected_reason: str,
    ) -> ClosedObjectDifferencePlan:
        return cls("witness", witness=witness, rejected_reason=rejected_reason)

    @classmethod
    def skeleton_witness(
        cls,
        skeleton: ClosedObjectWitnessSkeleton,
        *,
        rejected_reason: str,
    ) -> ClosedObjectDifferencePlan:
        return cls(
            "witness", witness_skeleton=skeleton, rejected_reason=rejected_reason
        )

    @classmethod
    def obligation_plan(
        cls,
        obligations: tuple[ClosedObjectValueObligation, ...],
    ) -> ClosedObjectDifferencePlan:
        return cls("obligations", obligations=obligations)


@dataclass(frozen=True)
class ObjectPresenceWitnessPlan:
    source: ObjectPresenceWitnessSource
    atom: str | None
    present: frozenset[str]

    def witness(self) -> Any:
        if self.atom is not None:
            return witness_for_type_atom(self.atom)
        return dict.fromkeys(sorted(self.present))


@dataclass(frozen=True)
class ObjectPresenceProductPlan:
    status: ObjectPresencePlanStatus
    reason: str = ""
    witness_plans: tuple[ObjectPresenceWitnessPlan, ...] = ()
    can_prove_true: bool = False

    @classmethod
    def ready(
        cls,
        witness_plans: tuple[ObjectPresenceWitnessPlan, ...],
        *,
        can_prove_true: bool,
    ) -> ObjectPresenceProductPlan:
        return cls("ready", witness_plans=witness_plans, can_prove_true=can_prove_true)

    @classmethod
    def unsupported(cls, reason: str) -> ObjectPresenceProductPlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def resource_exhausted(cls, reason: str) -> ObjectPresenceProductPlan:
        return cls("resource_exhausted", reason=reason)


@dataclass(frozen=True)
class ObjectKeyValuePattern:
    text: str
    pattern: Any
    schema: Any


@dataclass(frozen=True)
class ObjectKeyValueShape:
    properties: dict[str, Any]
    patterns: tuple[ObjectKeyValuePattern, ...]
    additional_schema: Any
    keyspace_pattern: Any | None
    required: frozenset[str]
    accepts_object: bool
    accepts_non_object: bool

    @property
    def has_value_constraints(self) -> bool:
        return (
            any(schema is not True for schema in self.properties.values())
            or any(pattern.schema is not True for pattern in self.patterns)
            or self.additional_schema is not True
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
            or self.additional_schema is not False
        )

    def value_schema_for(self, name: str) -> Any:
        if not self.allows_key(name):
            return False
        schemas = []
        if name in self.properties:
            schemas.append(self.properties[name])
        schemas.extend(
            pattern.schema for pattern in self.patterns if pattern.pattern.matches(name)
        )
        if name not in self.properties and not self.key_matches_pattern(name):
            schemas.append(self.additional_schema)
        return _all_of_schema(tuple(schema for schema in schemas if schema is not True))

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
                ObjectKeyValueWitnessSlot(name, self.value_schema_for(name))
                for name in sorted(names)
            )
        )


@dataclass(frozen=True)
class ObjectKeyValueObligation:
    name: str
    lhs_schema: Any
    rhs_schema: Any


@dataclass(frozen=True)
class ObjectKeyValueWitnessSlot:
    name: str
    schema: Any


@dataclass(frozen=True)
class ObjectKeyValueWitnessSkeleton:
    slots: tuple[ObjectKeyValueWitnessSlot, ...]


def materialize_object_key_value_witness_skeleton(
    skeleton: ObjectKeyValueWitnessSkeleton | None,
    dialect: Dialect,
    *,
    override: tuple[str, Any] | None = None,
) -> dict[str, Any] | None:
    if skeleton is None:
        return None

    witness = {}
    for slot in skeleton.slots:
        if override is not None and slot.name == override[0]:
            witness[slot.name] = override[1]
            continue
        found, value = _concrete_witness_for_schema(slot.schema, dialect)
        if not found:
            return None
        witness[slot.name] = value
    return witness


@dataclass(frozen=True)
class ObjectKeyValueDifferencePlan:
    status: ObjectKeyValuePlanStatus
    reason: str = ""
    rejected_reason: str = ""
    witness: Any | None = None
    witness_skeleton: ObjectKeyValueWitnessSkeleton | None = None
    obligations: tuple[ObjectKeyValueObligation, ...] = ()

    @classmethod
    def proved_true(cls) -> ObjectKeyValueDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> ObjectKeyValueDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def resource_exhausted(cls, reason: str) -> ObjectKeyValueDifferencePlan:
        return cls("resource_exhausted", reason=reason)

    @classmethod
    def literal_witness(
        cls,
        witness: Any,
        *,
        rejected_reason: str,
    ) -> ObjectKeyValueDifferencePlan:
        return cls("witness", witness=witness, rejected_reason=rejected_reason)

    @classmethod
    def skeleton_witness(
        cls,
        skeleton: ObjectKeyValueWitnessSkeleton,
        *,
        rejected_reason: str,
    ) -> ObjectKeyValueDifferencePlan:
        return cls(
            "witness", witness_skeleton=skeleton, rejected_reason=rejected_reason
        )

    @classmethod
    def obligation_plan(
        cls,
        obligations: tuple[ObjectKeyValueObligation, ...],
    ) -> ObjectKeyValueDifferencePlan:
        return cls("obligations", obligations=obligations)


@dataclass(frozen=True)
class ObjectUnevaluatedPropertyObligation:
    name: str
    lhs_schema: Any
    rhs_schema: Any
    witness_skeleton: ObjectKeyValueWitnessSkeleton | None


@dataclass(frozen=True)
class ObjectUnevaluatedPropertiesDifferencePlan:
    status: ObjectUnevaluatedPropertiesPlanStatus
    reason: str = ""
    rejected_reason: str = ""
    witness: Any | None = None
    witness_skeletons: tuple[ObjectKeyValueWitnessSkeleton, ...] = ()
    obligations: tuple[ObjectUnevaluatedPropertyObligation, ...] = ()

    @classmethod
    def proved_true(cls) -> ObjectUnevaluatedPropertiesDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> ObjectUnevaluatedPropertiesDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def resource_exhausted(
        cls, reason: str
    ) -> ObjectUnevaluatedPropertiesDifferencePlan:
        return cls("resource_exhausted", reason=reason)

    @classmethod
    def literal_witness(
        cls,
        witness: Any,
        *,
        rejected_reason: str,
    ) -> ObjectUnevaluatedPropertiesDifferencePlan:
        return cls("witness", witness=witness, rejected_reason=rejected_reason)

    @classmethod
    def skeleton_witnesses(
        cls,
        skeletons: tuple[ObjectKeyValueWitnessSkeleton, ...],
        *,
        rejected_reason: str,
    ) -> ObjectUnevaluatedPropertiesDifferencePlan:
        return cls(
            "witness", witness_skeletons=skeletons, rejected_reason=rejected_reason
        )

    @classmethod
    def obligation_plan(
        cls,
        obligations: tuple[ObjectUnevaluatedPropertyObligation, ...],
    ) -> ObjectUnevaluatedPropertiesDifferencePlan:
        return cls("obligations", obligations=obligations)


@dataclass(frozen=True)
class ObjectPropertyCountDifferencePlan:
    status: ObjectPropertyCountPlanStatus
    reason: str = ""
    rejected_reason: str = ""
    witness: Any | None = None

    @classmethod
    def proved_true(cls) -> ObjectPropertyCountDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(cls, reason: str) -> ObjectPropertyCountDifferencePlan:
        return cls("unsupported", reason=reason)

    @classmethod
    def resource_exhausted(cls, reason: str) -> ObjectPropertyCountDifferencePlan:
        return cls("resource_exhausted", reason=reason)

    @classmethod
    def literal_witness(
        cls,
        witness: Any,
        *,
        rejected_reason: str,
    ) -> ObjectPropertyCountDifferencePlan:
        return cls("witness", witness=witness, rejected_reason=rejected_reason)


@dataclass(frozen=True)
class ObjectDifferenceModel:
    lhs: LogicalSchemaIR
    rhs: LogicalSchemaIR
    problem: DifferenceProblem | None = None
    lhs_property_count_constraint: ObjectPropertyCountConstraint | None = None
    rhs_property_count_constraint: ObjectPropertyCountConstraint | None = None
    lhs_property_values_constraint: ObjectPropertyValuesConstraint | None = None
    rhs_property_values_constraint: ObjectPropertyValuesConstraint | None = None
    lhs_closed_properties_constraint: ObjectClosedPropertiesConstraint | None = None
    rhs_closed_properties_constraint: ObjectClosedPropertiesConstraint | None = None
    lhs_property_names_constraint: ObjectPropertyNamesConstraint | None = None
    rhs_property_names_constraint: ObjectPropertyNamesConstraint | None = None

    @classmethod
    def from_irs(
        cls, lhs: LogicalSchemaIR, rhs: LogicalSchemaIR
    ) -> ObjectDifferenceModel:
        return cls(lhs, rhs)

    @classmethod
    def from_problem(cls, problem: DifferenceProblem) -> ObjectDifferenceModel:
        return cls(
            problem.formula.lhs,
            problem.formula.rhs,
            problem=problem,
        )

    def _lhs_constraint(self, kind: IRAssertionKind) -> Any | None:
        return None if self.problem is None else self.problem.lhs_constraint(kind)

    def _rhs_constraint(self, kind: IRAssertionKind) -> Any | None:
        return None if self.problem is None else self.problem.rhs_constraint(kind)

    @cached_property
    def lhs_property_count(self) -> ObjectPropertyCountShape | None:
        constraint = (
            self.lhs_property_count_constraint
            or _object_property_count_constraint(
                self._lhs_constraint("object-property-count")
            )
            or self.lhs.facts.object_property_count_constraint
        )
        return None if constraint is None else constraint.shape

    @cached_property
    def rhs_property_count(self) -> ObjectPropertyCountShape | None:
        constraint = (
            self.rhs_property_count_constraint
            or _object_property_count_constraint(
                self._rhs_constraint("object-property-count")
            )
            or self.rhs.facts.object_property_count_constraint
        )
        return None if constraint is None else constraint.shape

    def property_count_difference_plan(self) -> ObjectPropertyCountDifferencePlan:
        lhs_shape = self.lhs_property_count
        rhs_shape = self.rhs_property_count
        if lhs_shape is None or rhs_shape is None:
            return ObjectPropertyCountDifferencePlan.unsupported(
                "SAT object property-count difference requires exact count shapes"
            )

        if lhs_shape.accepts_non_object and not rhs_shape.accepts_non_object:
            return ObjectPropertyCountDifferencePlan.literal_witness(
                "",
                rejected_reason=(
                    "SAT object non-object witness was rejected by concrete validation"
                ),
            )
        if self.problem is not None:
            symbolic = self._symbolic_property_count_difference_plan(
                lhs_shape, rhs_shape
            )
            if symbolic.status != "unsupported":
                return symbolic
        if lhs_shape.is_subset_of(rhs_shape):
            return ObjectPropertyCountDifferencePlan.proved_true()

        witness = lhs_shape.witness_not_in(rhs_shape)
        if witness is None:
            return ObjectPropertyCountDifferencePlan.unsupported(
                "SAT object property-count difference could not construct a witness"
            )
        keyspace_witness = self._property_count_witness_for_count(len(witness))
        if keyspace_witness is not None:
            witness = keyspace_witness
        elif self.lhs_key_values is not None:
            return ObjectPropertyCountDifferencePlan.unsupported(
                "SAT object property-count difference could not construct a "
                "keyspace-valid witness"
            )
        return ObjectPropertyCountDifferencePlan.literal_witness(
            witness,
            rejected_reason=(
                "SAT object property-count witness was rejected by concrete validation"
            ),
        )

    def _symbolic_property_count_difference_plan(
        self,
        lhs_shape: ObjectPropertyCountShape,
        rhs_shape: ObjectPropertyCountShape,
    ) -> ObjectPropertyCountDifferencePlan:
        if self.problem is None:
            return ObjectPropertyCountDifferencePlan.unsupported(
                "SAT object property-count symbolic product requires a proof context"
            )
        solver = SymbolicSolver(
            self.problem.context,
            "object product",
            "object product exceeded proof work budget",
        )
        count = solver.int_var("property_count")
        lhs_expr = _object_property_count_shape_symbolic_expr(lhs_shape, count, solver)
        rhs_expr = _object_property_count_shape_symbolic_expr(rhs_shape, count, solver)
        solver.add(solver.ge(count, 0), lhs_expr, solver.not_(rhs_expr))
        check = solver.check_with_work(units=1)
        if isinstance(check, ProofResult):
            if check.status == "resource_exhausted":
                return ObjectPropertyCountDifferencePlan.resource_exhausted(
                    check.reason or ""
                )
            return ObjectPropertyCountDifferencePlan.unsupported(
                check.reason
                or "SAT object property-count symbolic solver returned unknown"
            )
        if check == SAT:
            property_count = solver.model_int(solver.model(), "property_count")
            witness = self._property_count_witness_for_count(property_count)
            if witness is None:
                return ObjectPropertyCountDifferencePlan.unsupported(
                    "SAT object property-count symbolic witness could not satisfy "
                    "left keyspace"
                )
            return ObjectPropertyCountDifferencePlan.literal_witness(
                witness,
                rejected_reason=(
                    "SAT object property-count witness was rejected by "
                    "concrete validation"
                ),
            )
        if check == UNSAT:
            return ObjectPropertyCountDifferencePlan.proved_true()
        return ObjectPropertyCountDifferencePlan.unsupported(
            "SAT object property-count symbolic solver returned unknown"
        )

    def _property_count_witness_for_count(self, count: int) -> dict[str, Any] | None:
        if count < 0:
            return None
        lhs_shape = self.lhs_key_values
        if lhs_shape is None:
            return {f"k{i}": None for i in range(count)}
        if _object_key_value_shape_allows_unrestricted_keys(lhs_shape):
            return {f"k{i}": None for i in range(count)}
        names = _distinct_lhs_object_property_names(
            lhs_shape,
            count,
            None if self.problem is None else self.problem.context,
        )
        if names is None:
            return None
        return materialize_object_key_value_witness_skeleton(
            lhs_shape.witness_skeleton_for_names(frozenset(names)),
            self.problem.dialect if self.problem is not None else Dialect.DRAFT202012,
        )

    @cached_property
    def lhs_property_values(self) -> ObjectPropertyValuesShape | None:
        constraint = (
            self.lhs_property_values_constraint
            or _object_property_values_constraint(
                self._lhs_constraint("object-property-values")
            )
            or self.lhs.facts.object_property_values_constraint
        )
        return None if constraint is None else constraint.shape

    @cached_property
    def rhs_property_values(self) -> ObjectPropertyValuesShape | None:
        constraint = (
            self.rhs_property_values_constraint
            or _object_property_values_constraint(
                self._rhs_constraint("object-property-values")
            )
            or self.rhs.facts.object_property_values_constraint
        )
        return None if constraint is None else constraint.shape

    @cached_property
    def lhs_closed_properties(self) -> ClosedObjectPropertiesShape | None:
        constraint = (
            self.lhs_closed_properties_constraint
            or _object_closed_properties_constraint(
                self._lhs_constraint("object-closed-properties")
            )
            or self.lhs.facts.object_closed_properties_constraint
        )
        return None if constraint is None else constraint.shape

    @cached_property
    def rhs_closed_properties(self) -> ClosedObjectPropertiesShape | None:
        constraint = (
            self.rhs_closed_properties_constraint
            or _object_closed_properties_constraint(
                self._rhs_constraint("object-closed-properties")
            )
            or self.rhs.facts.object_closed_properties_constraint
        )
        return None if constraint is None else constraint.shape

    @cached_property
    def lhs_property_names(self) -> ObjectPropertyNamesShape | None:
        constraint = (
            self.lhs_property_names_constraint
            or _object_property_names_constraint(
                self._lhs_constraint("object-property-names")
            )
            or self.lhs.facts.object_property_names_constraint
        )
        return None if constraint is None else constraint.shape

    @cached_property
    def rhs_property_names(self) -> ObjectPropertyNamesShape | None:
        constraint = (
            self.rhs_property_names_constraint
            or _object_property_names_constraint(
                self._rhs_constraint("object-property-names")
            )
            or self.rhs.facts.object_property_names_constraint
        )
        return None if constraint is None else constraint.shape

    @cached_property
    def lhs_key_values(self) -> ObjectKeyValueShape | None:
        return object_key_value_shape_for_schema(self.lhs.schema)

    @cached_property
    def rhs_key_values(self) -> ObjectKeyValueShape | None:
        return object_key_value_shape_for_schema(self.rhs.schema)

    @cached_property
    def universe(self) -> ObjectKeyUniverse:
        return _object_key_universe(
            self.lhs,
            self.rhs,
            self.lhs_closed_properties,
            self.rhs_closed_properties,
        )

    def unevaluated_properties_difference_plan(
        self,
    ) -> ObjectUnevaluatedPropertiesDifferencePlan:
        constraint = self.rhs.evaluation.unevaluated_properties
        if constraint is None:
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties difference requires unevaluatedProperties"
            )
        rhs_trace = _rhs_evaluation_trace(self.lhs.schema, self.rhs, self.problem)
        if rhs_trace.is_resource_exhausted:
            return ObjectUnevaluatedPropertiesDifferencePlan.resource_exhausted(
                rhs_trace.resource_exhausted_reason
            )
        if not rhs_trace.is_supported:
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                rhs_trace.unsupported_reason
            )
        if not _evaluated_property_sources_are_supported(
            rhs_trace.evaluated_property_sources
        ):
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties difference defers non-local "
                "evaluated property sources"
            )

        lhs_shape = self.lhs_key_values
        if lhs_shape is None:
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties difference requires local left object shape"
            )
        if lhs_shape.accepts_non_object:
            return ObjectUnevaluatedPropertiesDifferencePlan.literal_witness(
                "",
                rejected_reason=(
                    "SAT unevaluatedProperties non-object witness was rejected"
                ),
            )
        if not lhs_shape.object_is_inhabited():
            return ObjectUnevaluatedPropertiesDifferencePlan.proved_true()

        closed_lhs_plan = self._closed_lhs_unevaluated_properties_difference_plan(
            lhs_shape,
            rhs_trace.evaluated_property_sources,
            constraint.schema,
        )
        if closed_lhs_plan.status != "unsupported":
            return closed_lhs_plan
        if constraint.schema is not False:
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT schema-valued unevaluatedProperties witness requires a "
                "finite closed left keyspace"
            )

        witness_name = _unevaluated_property_witness_name(
            lhs_shape,
            rhs_trace.evaluated_property_sources,
            self.problem.context if self.problem is not None else None,
        )
        if isinstance(witness_name, ProofResult):
            if witness_name.status == "resource_exhausted":
                return ObjectUnevaluatedPropertiesDifferencePlan.resource_exhausted(
                    witness_name.reason or "object product exceeded proof work budget"
                )
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                witness_name.reason
                or "SAT unevaluatedProperties witness could not be constructed"
            )
        if witness_name is not None:
            skeleton = lhs_shape.witness_skeleton(witness_name)
            if skeleton is None:
                return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                    "SAT unevaluatedProperties witness could not be constructed"
                )
            return ObjectUnevaluatedPropertiesDifferencePlan.skeleton_witnesses(
                (skeleton,),
                rejected_reason="SAT unevaluatedProperties witness was rejected",
            )
        return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
            "SAT unevaluatedProperties witness could not be constructed"
        )

    def _closed_lhs_unevaluated_properties_difference_plan(
        self,
        lhs_shape: ObjectKeyValueShape,
        rhs_sources: tuple[Any, ...],
        unevaluated_schema: Any,
    ) -> ObjectUnevaluatedPropertiesDifferencePlan:
        if lhs_shape.patterns or lhs_shape.additional_schema is not False:
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties true proof requires a finite "
                "closed left keyspace"
            )
        if not _rhs_all_of_unevaluated_properties_true_fragment_supported(
            self.rhs.root.source.schema
        ):
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties true proof defers non-frontier "
                "right assertions"
            )

        obligations = []
        for name in sorted(lhs_shape.properties):
            if not lhs_shape.allows_key(name):
                continue
            skeleton = lhs_shape.witness_skeleton(name)
            rhs_schema = _rhs_evaluated_property_schema_for_name(rhs_sources, name)
            if rhs_schema is None:
                if unevaluated_schema is not False:
                    obligations.append(
                        ObjectUnevaluatedPropertyObligation(
                            name,
                            lhs_shape.value_schema_for(name),
                            unevaluated_schema,
                            skeleton,
                        )
                    )
                    continue
                if skeleton is None:
                    return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                        "SAT unevaluatedProperties closed-left witness could "
                        "not be constructed"
                    )
                return ObjectUnevaluatedPropertiesDifferencePlan.skeleton_witnesses(
                    (skeleton,),
                    rejected_reason=(
                        "SAT unevaluatedProperties closed-left witness was rejected"
                    ),
                )
            obligations.append(
                ObjectUnevaluatedPropertyObligation(
                    name,
                    lhs_shape.value_schema_for(name),
                    rhs_schema,
                    skeleton,
                )
            )

        if obligations:
            return ObjectUnevaluatedPropertiesDifferencePlan.obligation_plan(
                tuple(obligations)
            )
        return ObjectUnevaluatedPropertiesDifferencePlan.proved_true()

    def finite_closed_lhs_names(self) -> tuple[str, ...] | None:
        if (
            self.lhs_closed_properties is None
            or not self.lhs_closed_properties.has_finite_keyspace
        ):
            return None
        return tuple(sorted(self.lhs_closed_properties.allowed_names))

    def closed_object_value_obligations(
        self,
    ) -> tuple[ClosedObjectValueObligation, ...] | None:
        if self.lhs_closed_properties is None or self.rhs_closed_properties is None:
            return None
        names = self.finite_closed_lhs_names()
        if names is None:
            return None
        lhs_closed = self.lhs_closed_properties
        rhs_closed = self.rhs_closed_properties
        obligations: list[ClosedObjectValueObligation] = []
        for name in sorted(
            names,
            key=lambda item: (
                contains_reference_keyword(
                    lhs_closed.property_schema_for(item),
                    {"$ref", "$recursiveRef"},
                )
                or contains_reference_keyword(
                    rhs_closed.property_schema_for(item),
                    {"$ref", "$recursiveRef"},
                ),
                item,
            ),
        ):
            rhs_schema = rhs_closed.property_schema_for(name)
            if not schema_is_true(rhs_schema):
                obligations.append(
                    ClosedObjectValueObligation(
                        name,
                        lhs_closed.property_schema_for(name),
                        rhs_schema,
                    )
                )
        return tuple(obligations)

    def closed_object_keyspace_witness_skeleton(
        self,
    ) -> ClosedObjectWitnessSkeleton | None:
        if self.lhs_closed_properties is None or self.rhs_closed_properties is None:
            return None
        if (
            not self.rhs_closed_properties.required
            <= self.lhs_closed_properties.required
        ):
            return self.closed_object_witness_skeleton()
        for name in self.finite_closed_lhs_names() or ():
            if not self.rhs_closed_properties.keyspace_accepts(name):
                return self.closed_object_witness_skeleton(name)
        return None

    def closed_object_witness_skeleton(
        self,
        override_name: str | None = None,
    ) -> ClosedObjectWitnessSkeleton | None:
        if self.lhs_closed_properties is None:
            return None
        names = set(self.lhs_closed_properties.required)
        if override_name is not None:
            names.add(override_name)
        if not all(self.lhs_closed_properties.keyspace_accepts(name) for name in names):
            return None
        return ClosedObjectWitnessSkeleton(
            tuple(
                ClosedObjectWitnessSlot(
                    name, self.lhs_closed_properties.property_schema_for(name)
                )
                for name in sorted(names)
            )
        )

    def closed_object_difference_plan(self) -> ClosedObjectDifferencePlan:
        lhs_shape = self.lhs_closed_properties
        rhs_shape = self.rhs_closed_properties
        if lhs_shape is None or rhs_shape is None:
            return ClosedObjectDifferencePlan.unsupported(
                "SAT closed-object difference requires exact closed-property shapes"
            )

        if lhs_shape.accepts_non_object and not rhs_shape.accepts_non_object:
            return ClosedObjectDifferencePlan.literal_witness(
                "",
                rejected_reason="SAT closed-object non-object witness was rejected",
            )
        if not lhs_shape.object_is_inhabited():
            return ClosedObjectDifferencePlan.proved_true()
        if not rhs_shape.accepts_object:
            skeleton = self.closed_object_witness_skeleton()
            if skeleton is None:
                return ClosedObjectDifferencePlan.unsupported(
                    "SAT closed-object witness could not be constructed"
                )
            return ClosedObjectDifferencePlan.skeleton_witness(
                skeleton,
                rejected_reason="SAT closed-object witness was rejected",
            )
        if not lhs_shape.keyspace_satisfies(rhs_shape):
            skeleton = self.closed_object_keyspace_witness_skeleton()
            if skeleton is None:
                return ClosedObjectDifferencePlan.unsupported(
                    "SAT closed-object keyspace witness could not be constructed"
                )
            return ClosedObjectDifferencePlan.skeleton_witness(
                skeleton,
                rejected_reason="SAT closed-object keyspace witness was rejected",
            )

        obligations = self.closed_object_value_obligations()
        if obligations is None:
            if (
                not rhs_shape.property_schemas
                and not rhs_shape.pattern_property_schemas
            ):
                return ClosedObjectDifferencePlan.proved_true()
            return ClosedObjectDifferencePlan.unsupported(
                "SAT closed-object difference requires finite left keyspace"
            )

        return ClosedObjectDifferencePlan.obligation_plan(obligations)

    @cached_property
    def presence_names(self) -> tuple[str, ...] | None:
        names = set(self.universe.explicit_names)
        if not _collect_object_presence_product_names(self.lhs.schema, names):
            return None
        if not _collect_object_presence_product_names(self.rhs.schema, names):
            return None
        if self.universe.fresh is not None:
            names.add(self.universe.fresh.representative)
        return tuple(sorted(names))

    def presence_accepts(
        self, schema: Any, atom: str, present: frozenset[str]
    ) -> bool | None:
        return _object_presence_product_accepts(schema, atom, present)

    def presence_product_can_prove_true(self) -> bool:
        if (
            self.rhs_key_values is not None
            and self.rhs_key_values.has_value_constraints
        ):
            return False
        if _object_presence_lhs_has_negative_value_constraints(
            self.lhs.schema
        ) or _object_presence_schema_has_unmodeled_value_constraints(self.rhs.schema):
            return False
        if self.universe.fresh is None:
            return True
        if (
            _object_presence_product_has_one_of(self.lhs.schema)
            or _object_presence_product_has_one_of(self.rhs.schema)
            or _object_schema_has_property_count_constraint(self.lhs.schema)
        ):
            return False
        return not _object_presence_product_has_upper_count_constraint(self.rhs.schema)

    def property_value_obligations(
        self,
    ) -> tuple[ObjectPropertyValueObligation, ...] | None:
        if self.lhs_property_values is None or self.rhs_property_values is None:
            return None
        obligations = []
        for name in sorted(self.rhs_property_values.property_names):
            rhs_schema = self.rhs_property_values.property_schema_for(name)
            if not schema_is_true(rhs_schema):
                obligations.append(
                    ObjectPropertyValueObligation(
                        name,
                        self.lhs_property_values.property_schema_for(name),
                        rhs_schema,
                    )
                )
        return tuple(obligations)

    def property_values_witness_skeleton(
        self,
        override_name: str | None = None,
    ) -> ObjectPropertyValueWitnessSkeleton | None:
        if self.lhs_property_values is None:
            return None
        names = set(self.lhs_property_values.required)
        if override_name is not None:
            names.add(override_name)
        return ObjectPropertyValueWitnessSkeleton(
            tuple(
                ObjectPropertyValueWitnessSlot(
                    name, self.lhs_property_values.property_schema_for(name)
                )
                for name in sorted(names)
            )
        )

    def property_values_difference_plan(self) -> ObjectPropertyValuesDifferencePlan:
        lhs_shape = self.lhs_property_values
        rhs_shape = self.rhs_property_values
        if lhs_shape is None or rhs_shape is None:
            return ObjectPropertyValuesDifferencePlan.unsupported(
                "SAT object property-values difference requires exact value shapes"
            )

        if lhs_shape.accepts_non_object and not rhs_shape.accepts_non_object:
            return ObjectPropertyValuesDifferencePlan.literal_witness(
                "",
                rejected_reason=(
                    "SAT object property-values non-object witness was rejected"
                ),
            )
        if not lhs_shape.accepts_object:
            return ObjectPropertyValuesDifferencePlan.proved_true()
        if not rhs_shape.accepts_object:
            skeleton = self.property_values_witness_skeleton()
            if skeleton is None:
                return ObjectPropertyValuesDifferencePlan.unsupported(
                    "SAT object property-values witness could not be constructed"
                )
            return ObjectPropertyValuesDifferencePlan.skeleton_witness(
                skeleton,
                rejected_reason="SAT object property-values witness was rejected",
            )
        if not rhs_shape.required <= lhs_shape.required:
            skeleton = self.property_values_witness_skeleton()
            if skeleton is None:
                return ObjectPropertyValuesDifferencePlan.unsupported(
                    "SAT object property-values required witness could not be "
                    "constructed"
                )
            return ObjectPropertyValuesDifferencePlan.skeleton_witness(
                skeleton,
                rejected_reason=(
                    "SAT object property-values required witness was rejected"
                ),
            )

        obligations = self.property_value_obligations()
        if obligations is None:
            return ObjectPropertyValuesDifferencePlan.unsupported(
                "SAT object property-values difference requires exact value obligations"
            )
        return ObjectPropertyValuesDifferencePlan.obligation_plan(obligations)

    def property_names_repair_skeleton(
        self, witness: Any
    ) -> ObjectPropertyNamesRepairSkeleton | None:
        if not isinstance(witness, dict) or self.lhs_key_values is None:
            return None

        slots = []
        for name, value in sorted(witness.items()):
            if not self.lhs_key_values.allows_key(name):
                return None
            slots.append(
                ObjectPropertyNamesRepairSlot(
                    name,
                    self.lhs_key_values.value_schema_for(name),
                    value,
                )
            )
        return ObjectPropertyNamesRepairSkeleton(tuple(slots))

    def property_names_difference_plan(self) -> ObjectPropertyNamesDifferencePlan:
        if _object_property_names_has_value_constraints(self.rhs.schema):
            return ObjectPropertyNamesDifferencePlan.unsupported(
                "SAT object propertyNames difference cannot ignore right "
                "property values"
            )

        if self.lhs_property_names is None or self.rhs_property_names is None:
            if self.lhs_property_names is None and self.rhs_property_names is not None:
                witness = self.dependency_property_names_witness(
                    self.rhs_property_names
                )
                if witness is not None:
                    return ObjectPropertyNamesDifferencePlan.witness_plan(witness, None)
            return ObjectPropertyNamesDifferencePlan.unsupported(
                "SAT object propertyNames difference requires exact keyspace shapes"
            )
        if self.lhs_property_names.is_subset_of(self.rhs_property_names):
            return ObjectPropertyNamesDifferencePlan.proved_true()

        witness = self.lhs_property_names.witness_not_in(self.rhs_property_names)
        if witness is None:
            return ObjectPropertyNamesDifferencePlan.unsupported(
                "SAT object propertyNames difference could not construct a witness"
            )
        return ObjectPropertyNamesDifferencePlan.witness_plan(
            witness,
            self.property_names_repair_skeleton(witness),
        )

    def dependency_property_names_witness(
        self,
        rhs_shape: ObjectPropertyNamesShape,
    ) -> dict[str, None] | None:
        if not rhs_shape.accepts_object:
            return None
        for name in _object_dependency_interesting_names(self.lhs.schema):
            present = frozenset({name})
            if self.presence_accepts(self.lhs.schema, "object", present) is not True:
                continue
            if rhs_shape.keyspace_pattern.matches(name):
                continue
            return {name: None}
        return None

    def presence_product_plan(self, budget: int) -> ObjectPresenceProductPlan:
        if self.presence_names is None:
            return ObjectPresenceProductPlan.unsupported(
                "SAT object presence product requires finite key universe"
            )

        witness_plans: list[ObjectPresenceWitnessPlan] = []
        for atom in sorted(JSON_TYPE_ATOMS - {"object"}):
            lhs_accepts = self.presence_accepts(self.lhs.schema, atom, frozenset())
            rhs_accepts = self.presence_accepts(self.rhs.schema, atom, frozenset())
            if lhs_accepts is None or rhs_accepts is None:
                return ObjectPresenceProductPlan.unsupported(
                    "SAT object presence product is outside the supported fragment"
                )
            if lhs_accepts and not rhs_accepts:
                witness_plans.append(
                    ObjectPresenceWitnessPlan("non-object", atom, frozenset())
                )

        symbolic = self._symbolic_presence_product_plan(budget)
        if symbolic.status == "resource_exhausted":
            return symbolic
        if symbolic.status == "unsupported":
            return symbolic
        witness_plans.extend(symbolic.witness_plans)

        return ObjectPresenceProductPlan.ready(
            tuple(witness_plans),
            can_prove_true=symbolic.can_prove_true,
        )

    def dependency_keyspace_witness_plan(self) -> ObjectPresenceProductPlan:
        witness_plans = []
        rhs_shape = self.rhs_key_values
        if rhs_shape is not None:
            for name in _object_dependency_interesting_names(self.lhs.schema):
                if rhs_shape.allows_key(name):
                    continue
                present = frozenset({name})
                if self.presence_accepts(self.lhs.schema, "object", present) is False:
                    continue
                witness_plans.append(
                    ObjectPresenceWitnessPlan("finite-keyspace", None, present)
                )

        for trigger, dependencies in _object_dependent_required_entries(
            self.rhs.schema
        ):
            if not dependencies:
                continue
            present = frozenset({trigger})
            if self.presence_accepts(self.lhs.schema, "object", present) is False:
                continue
            if self.presence_accepts(self.rhs.schema, "object", present) is not False:
                continue
            if self.lhs_key_values is not None and not self.lhs_key_values.allows_key(
                trigger
            ):
                continue
            witness_plans.append(
                ObjectPresenceWitnessPlan("finite-keyspace", None, present)
            )

        for trigger, dependencies in _object_dependent_schema_required_entries(
            self.rhs.schema
        ):
            if not dependencies:
                continue
            present = frozenset({trigger})
            if self.presence_accepts(self.lhs.schema, "object", present) is False:
                continue
            if self.presence_accepts(self.rhs.schema, "object", present) is not False:
                continue
            if self.lhs_key_values is not None and not self.lhs_key_values.allows_key(
                trigger
            ):
                continue
            witness_plans.append(
                ObjectPresenceWitnessPlan("finite-keyspace", None, present)
            )

        return ObjectPresenceProductPlan.ready(
            tuple(witness_plans), can_prove_true=False
        )

    def _symbolic_presence_product_plan(self, budget: int) -> ObjectPresenceProductPlan:
        if self.problem is None:
            return ObjectPresenceProductPlan.unsupported(
                "SAT object presence symbolic product requires a proof context"
            )
        names = self._symbolic_presence_names(budget)
        if names is None:
            return ObjectPresenceProductPlan.resource_exhausted(
                "object product exceeded proof work budget"
            )

        solver = SymbolicSolver(
            self.problem.context,
            "object product",
            "object product exceeded proof work budget",
        )
        variables = solver.bool_vars(names)
        lhs_expr = _object_presence_product_symbolic_expr(
            self.lhs.schema, variables, solver
        )
        rhs_expr = _object_presence_product_symbolic_expr(
            self.rhs.schema, variables, solver
        )
        if lhs_expr is None or rhs_expr is None:
            return ObjectPresenceProductPlan.unsupported(
                "SAT object presence product is outside the supported fragment"
            )

        solver.add(lhs_expr, solver.not_(rhs_expr))
        check = solver.check(units=max(len(names), 1))
        if isinstance(check, ProofResult):
            if check.status == "unsupported":
                return ObjectPresenceProductPlan.unsupported(
                    check.reason
                    or "SAT object presence symbolic solver returned unknown"
                )
            return ObjectPresenceProductPlan.resource_exhausted(check.reason or "")
        if check == SAT:
            model = solver.model()
            present = frozenset(
                name for name in names if solver.bool_value(model, name)
            )
            return ObjectPresenceProductPlan.ready(
                (ObjectPresenceWitnessPlan("finite-keyspace", None, present),),
                can_prove_true=False,
            )
        if check == UNSAT:
            return ObjectPresenceProductPlan.ready(
                (),
                can_prove_true=self._presence_product_can_prove_true_under_budget(
                    len(names)
                ),
            )
        return ObjectPresenceProductPlan.unsupported(
            "SAT object presence symbolic solver returned unknown"
        )

    def _symbolic_presence_names(self, budget: int) -> tuple[str, ...] | None:
        if self.presence_names is None:
            return None
        names = set(self.presence_names)
        if self.universe.fresh is not None:
            names.discard(self.universe.fresh.representative)
            rhs_upper = _object_schema_max_properties_bound(self.rhs.schema)
            lhs_upper = _object_property_count_upper_bound(self.lhs_property_count)
            if lhs_upper is None:
                lhs_upper = _object_schema_max_properties_bound(self.lhs.schema)
            target_size = 1
            if rhs_upper is not None:
                target_size = max(target_size, rhs_upper + 1 - len(names))
            if lhs_upper is not None:
                target_size = max(
                    target_size,
                    min(
                        lhs_upper, rhs_upper + 1 if rhs_upper is not None else lhs_upper
                    )
                    - len(names),
                )
            target_size = max(target_size, 1)
            fresh = _fresh_names(frozenset(names), target_size)
            names.update(fresh)
        if budget >= 0 and len(names) > budget:
            return None
        return tuple(sorted(names))

    def _presence_product_can_prove_true_under_budget(self, budget: int) -> bool:
        if self.presence_product_can_prove_true():
            return True
        if (
            self.rhs_key_values is not None
            and self.rhs_key_values.has_value_constraints
        ):
            return False

        upper = _object_property_count_upper_bound(self.lhs_property_count)
        if upper is None:
            upper = _object_schema_max_properties_bound(self.lhs.schema)
        return upper is not None and (budget < 0 or upper <= budget)

    def key_value_product_supported(
        self, budget: int, *, expanded: bool = False
    ) -> bool:
        if self.lhs_key_values is None or self.rhs_key_values is None:
            return False
        return _object_key_value_mixed_product_supported(
            self.lhs_key_values,
            self.rhs_key_values,
            budget,
            expanded=expanded,
        )

    def key_value_obligations(
        self,
        budget: int,
        *,
        expanded: bool = False,
        context: ProofContext | None = None,
    ) -> tuple[ObjectKeyValueObligation, ...] | None:
        if self.lhs_key_values is None or self.rhs_key_values is None:
            return None
        return _object_key_value_obligations(
            self.lhs_key_values,
            self.rhs_key_values,
            budget,
            expanded=expanded,
            context=context,
        )

    def key_value_witness_skeleton(
        self,
        override_name: str | None = None,
    ) -> ObjectKeyValueWitnessSkeleton | None:
        if self.lhs_key_values is None:
            return None
        return self.lhs_key_values.witness_skeleton(override_name)

    def dependency_closed_key_value_witness_skeleton(
        self,
        rhs_shape: ObjectKeyValueShape,
        context: ProofContext | None,
    ) -> ObjectKeyValueWitnessSkeleton | None:
        if _object_presence_schema_has_unmodeled_value_constraints(self.lhs.schema):
            return None
        if context is None:
            return None
        for name, rhs_schema in _object_key_value_candidate_value_constraints(
            rhs_shape, context
        ):
            if schema_is_true(rhs_schema):
                continue
            present = _object_dependency_closed_present_names(
                self.lhs.schema, frozenset({name})
            )
            if present is None:
                continue
            if self.presence_accepts(self.lhs.schema, "object", present) is not True:
                continue
            subproof = context.subproof(True, rhs_schema)
            if subproof.status == "proved_false" and subproof.witness is not None:
                bad_value_schema = {"const": subproof.witness}
            else:
                bad_value_schema = _schema_negation(rhs_schema)
                if not _concrete_witness_for_schema(bad_value_schema, context.dialect)[
                    0
                ]:
                    continue
            slots = tuple(
                ObjectKeyValueWitnessSlot(
                    present_name, bad_value_schema if present_name == name else True
                )
                for present_name in sorted(present)
            )
            return ObjectKeyValueWitnessSkeleton(slots)
        return None

    def required_omission_key_value_witness_skeleton(
        self,
        rhs_shape: ObjectKeyValueShape,
        budget: int,
        context: ProofContext | None,
    ) -> ObjectKeyValueWitnessSkeleton | None:
        lhs_shape = self.lhs_key_values
        if lhs_shape is None:
            return None
        missing_required = rhs_shape.required - lhs_shape.required
        if not missing_required:
            return None

        min_count = max(
            len(lhs_shape.required),
            _object_schema_min_properties_lower_bound(self.lhs.schema),
        )
        max_count = (
            budget if budget >= 0 else max(min_count + 4, len(rhs_shape.required) + 1)
        )
        for count in range(min_count, max_count + 1):
            names = _distinct_lhs_object_property_names(
                lhs_shape,
                count,
                context,
                blocked=missing_required,
            )
            if names is None:
                continue
            present = frozenset(names)
            lhs_accepts_present = self.presence_accepts(
                self.lhs.schema, "object", present
            )
            rhs_accepts_present = self.presence_accepts(
                self.rhs.schema, "object", present
            )
            if lhs_accepts_present is not False and (
                rhs_accepts_present is False or not rhs_shape.required <= present
            ):
                return lhs_shape.witness_skeleton_for_names(present)
        return None

    def key_value_difference_plan(
        self,
        budget: int,
        *,
        expanded: bool = False,
        context: ProofContext | None = None,
    ) -> ObjectKeyValueDifferencePlan:
        lhs_shape = self.lhs_key_values
        rhs_shape = self.rhs_key_values
        if lhs_shape is None or rhs_shape is None:
            if lhs_shape is None and rhs_shape is not None:
                skeleton = self.dependency_closed_key_value_witness_skeleton(
                    rhs_shape, context
                )
                if skeleton is not None:
                    return ObjectKeyValueDifferencePlan.skeleton_witness(
                        skeleton,
                        rejected_reason=(
                            "SAT object dependency key-value witness was rejected"
                        ),
                    )
            return ObjectKeyValueDifferencePlan.unsupported(
                "SAT object key-value difference requires local key-value shapes"
            )
        if not self.key_value_product_supported(budget, expanded=expanded):
            if _object_key_value_mixed_product_budget_exhausted(
                lhs_shape, rhs_shape, budget
            ):
                return ObjectKeyValueDifferencePlan.resource_exhausted(
                    "object product exceeded proof work budget"
                )
            return ObjectKeyValueDifferencePlan.unsupported(
                "SAT object key-value product defers complex "
                "explicit-property/pattern combinations"
            )
        if lhs_shape.accepts_non_object and not rhs_shape.accepts_non_object:
            return ObjectKeyValueDifferencePlan.literal_witness(
                "",
                rejected_reason="SAT object key-value non-object witness was rejected",
            )
        if not lhs_shape.object_is_inhabited():
            return ObjectKeyValueDifferencePlan.proved_true()
        if not rhs_shape.accepts_object:
            skeleton = self.key_value_witness_skeleton()
            if skeleton is None:
                return ObjectKeyValueDifferencePlan.unsupported(
                    "SAT object key-value witness could not be constructed"
                )
            return ObjectKeyValueDifferencePlan.skeleton_witness(
                skeleton,
                rejected_reason="SAT object key-value object witness was rejected",
            )
        missing_required_unresolved = False
        if not rhs_shape.required <= lhs_shape.required:
            present = frozenset(lhs_shape.required)
            lhs_accepts_present = self.presence_accepts(
                self.lhs.schema, "object", present
            )
            rhs_accepts_present = self.presence_accepts(
                self.rhs.schema, "object", present
            )
            if lhs_accepts_present is True and rhs_accepts_present is False:
                skeleton = self.key_value_witness_skeleton()
                if skeleton is None:
                    return ObjectKeyValueDifferencePlan.unsupported(
                        "SAT object key-value required witness could not be constructed"
                    )
                return ObjectKeyValueDifferencePlan.skeleton_witness(
                    skeleton,
                    rejected_reason=(
                        "SAT object key-value required witness was rejected"
                    ),
                )
            skeleton = self.required_omission_key_value_witness_skeleton(
                rhs_shape, budget, context
            )
            if skeleton is not None:
                return ObjectKeyValueDifferencePlan.skeleton_witness(
                    skeleton,
                    rejected_reason=(
                        "SAT object key-value required witness was rejected"
                    ),
                )
            missing_required_unresolved = True
        keyspace_witness = _object_key_value_keyspace_witness(
            lhs_shape, rhs_shape, context
        )
        if isinstance(keyspace_witness, ProofResult):
            if keyspace_witness.status == "resource_exhausted":
                return ObjectKeyValueDifferencePlan.resource_exhausted(
                    keyspace_witness.reason
                    or "object product exceeded proof work budget"
                )
            return ObjectKeyValueDifferencePlan.unsupported(
                keyspace_witness.reason
                or "SAT object key-value keyspace witness is unsupported"
            )
        if keyspace_witness is not None:
            skeleton = self.key_value_witness_skeleton(keyspace_witness)
            if skeleton is None:
                return ObjectKeyValueDifferencePlan.unsupported(
                    "SAT object key-value keyspace witness could not be constructed"
                )
            return ObjectKeyValueDifferencePlan.skeleton_witness(
                skeleton,
                rejected_reason="SAT object key-value keyspace witness was rejected",
            )
        if not rhs_shape.has_value_constraints:
            if _object_schema_has_property_count_constraint(self.rhs.schema):
                return ObjectKeyValueDifferencePlan.unsupported(
                    "SAT object key-value difference cannot prove property-count "
                    "constraints"
                )
            return ObjectKeyValueDifferencePlan.proved_true()

        direct_witness = _object_key_value_direct_false_witness_skeleton(
            lhs_shape, rhs_shape, context
        )
        if isinstance(direct_witness, ProofResult):
            if direct_witness.status == "resource_exhausted":
                return ObjectKeyValueDifferencePlan.resource_exhausted(
                    direct_witness.reason or "object product exceeded proof work budget"
                )
            return ObjectKeyValueDifferencePlan.unsupported(
                direct_witness.reason
                or "SAT object key-value direct witness is unsupported"
            )
        if direct_witness is not None:
            return ObjectKeyValueDifferencePlan.skeleton_witness(
                direct_witness,
                rejected_reason=(
                    "SAT object key-value direct pattern witness was rejected"
                ),
            )

        obligations = self.key_value_obligations(
            budget, expanded=expanded, context=context
        )
        if obligations is None:
            if expanded and context is not None and context.work_is_exhausted:
                return ObjectKeyValueDifferencePlan.resource_exhausted(
                    "object product exceeded proof work budget"
                )
            if _object_key_value_obligations_budget_exhausted(
                lhs_shape, rhs_shape, budget
            ):
                return ObjectKeyValueDifferencePlan.resource_exhausted(
                    "object product exceeded proof work budget"
                )
            return ObjectKeyValueDifferencePlan.unsupported(
                "SAT object key-value fragment requires matching "
                "pattern/additional classes"
            )
        obligations = tuple(
            obligation
            for obligation in obligations
            if not schema_is_true(obligation.rhs_schema)
        )
        if not obligations:
            if missing_required_unresolved:
                return ObjectKeyValueDifferencePlan.unsupported(
                    "SAT object key-value required omission could not be proven"
                )
            return ObjectKeyValueDifferencePlan.unsupported(
                "SAT object key-value difference found no decidable value obligations"
            )
        return ObjectKeyValueDifferencePlan.obligation_plan(obligations)


def object_key_value_shape_for_schema(schema: Any) -> ObjectKeyValueShape | None:
    if schema is True:
        return ObjectKeyValueShape(
            {},
            (),
            True,
            None,
            frozenset(),
            accepts_object=True,
            accepts_non_object=True,
        )
    if schema is False:
        return ObjectKeyValueShape(
            {},
            (),
            False,
            None,
            frozenset(),
            accepts_object=False,
            accepts_non_object=False,
        )
    if not isinstance(schema, dict):
        return None
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return None
    if not _is_object_key_value_fragment_schema(schema):
        return None

    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    keyspace_pattern = _object_key_value_property_names_pattern(schema)
    patterns = []
    for text, subschema in sorted(schema.get("patternProperties", {}).items()):
        pattern = RegexLanguage.maybe_from_json_regex(text)
        if pattern is None:
            return None
        patterns.append(ObjectKeyValuePattern(text, pattern, subschema))
    return ObjectKeyValueShape(
        dict(sorted(schema.get("properties", {}).items())),
        tuple(patterns),
        schema.get("additionalProperties", True),
        keyspace_pattern,
        frozenset(schema.get("required", [])),
        accepts_object="object" in type_shape.atoms,
        accepts_non_object=any(atom != "object" for atom in type_shape.atoms),
    )


def _is_object_key_value_fragment_schema(schema: dict[str, Any]) -> bool:
    allowed_keywords = {
        "additionalProperties",
        "maxProperties",
        "minProperties",
        "patternProperties",
        "properties",
        "propertyNames",
        "required",
        "type",
    }
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in allowed_keywords:
            return False
        if key == "properties" and not isinstance(value, dict):
            return False
        if key == "patternProperties":
            if not isinstance(value, dict):
                return False
            if any(
                not isinstance(pattern, str)
                or RegexLanguage.maybe_from_json_regex(pattern) is None
                for pattern in value
            ):
                return False
        if key == "additionalProperties" and not isinstance(value, bool | dict):
            return False
        if key == "propertyNames" and not _is_object_key_value_property_names_schema(
            value
        ):
            return False
        if key in {"maxProperties", "minProperties"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
        if key == "required" and (
            not isinstance(value, list)
            or not all(isinstance(name, str) for name in value)
        ):
            return False
    return True


def _is_object_key_value_property_names_schema(schema: Any) -> bool:
    if schema is True:
        return True
    if not isinstance(schema, dict):
        return False

    allowed_keywords = IGNORED_SCHEMA_METADATA_KEYS | {"pattern", "type"}
    if any(key not in allowed_keywords for key in schema):
        return False
    if "type" in schema and schema["type"] != "string":
        return False
    pattern = schema.get("pattern")
    return pattern is None or (
        isinstance(pattern, str)
        and RegexLanguage.maybe_from_json_regex(pattern) is not None
    )


def _object_key_value_property_names_pattern(schema: dict[str, Any]) -> Any | None:
    property_names = schema.get("propertyNames", True)
    if property_names is True:
        return None
    pattern = property_names.get("pattern")
    if pattern is None:
        return None
    return RegexLanguage.maybe_from_json_regex(pattern)


def _object_key_value_mixed_product_supported(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
    budget: int,
    *,
    expanded: bool = False,
) -> bool:
    has_explicit = bool(lhs.properties or rhs.properties)
    has_pattern = bool(lhs.patterns or rhs.patterns)
    if not (has_explicit and has_pattern):
        return True

    explicit_names = (
        set(lhs.properties)
        | set(rhs.properties)
        | set(lhs.required)
        | set(rhs.required)
    )
    partition_patterns = _object_key_value_partition_patterns(lhs, rhs)
    class_count = 1 << len(partition_patterns)
    if not expanded and budget >= 0 and len(explicit_names) + class_count > budget:
        return False

    value_schemas = [
        *lhs.properties.values(),
        *rhs.properties.values(),
        *(pattern.schema for pattern in lhs.patterns),
        *(pattern.schema for pattern in rhs.patterns),
        lhs.additional_schema,
        rhs.additional_schema,
    ]
    value_schema_supported = (
        _object_key_value_value_schema_is_expanded_product_safe
        if expanded
        else _object_key_value_value_schema_is_solver_local
    )
    return all(value_schema_supported(schema) for schema in value_schemas)


def _object_key_value_mixed_product_budget_exhausted(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
    budget: int,
) -> bool:
    has_explicit = bool(lhs.properties or rhs.properties)
    has_pattern = bool(lhs.patterns or rhs.patterns)
    if budget < 0 or not (has_explicit and has_pattern):
        return False

    explicit_names = (
        set(lhs.properties)
        | set(rhs.properties)
        | set(lhs.required)
        | set(rhs.required)
    )
    class_count = 1 << len(_object_key_value_partition_patterns(lhs, rhs))
    return len(explicit_names) + class_count > budget


def _object_key_value_value_schema_is_solver_local(schema: Any, depth: int = 0) -> bool:
    if depth > 8:
        return False
    if isinstance(schema, bool):
        return True
    if not isinstance(schema, dict):
        return False
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return False

    allowed_keywords = IGNORED_SCHEMA_METADATA_KEYS | {
        "allOf",
        "anyOf",
        "const",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maximum",
        "maxLength",
        "minimum",
        "minLength",
        "multipleOf",
        "not",
        "pattern",
        "type",
    }
    if any(key not in allowed_keywords for key in schema):
        return False

    schema_type = schema.get("type")
    if isinstance(schema_type, str) and schema_type in {"array", "object"}:
        return False
    if isinstance(schema_type, list) and any(
        item in {"array", "object"} for item in schema_type
    ):
        return False

    for key in ("allOf", "anyOf"):
        subschemas = schema.get(key, [])
        if not isinstance(subschemas, list):
            return False
        if not all(
            _object_key_value_value_schema_is_solver_local(subschema, depth + 1)
            for subschema in subschemas
        ):
            return False
    if "not" in schema and not _object_key_value_value_schema_is_solver_local(
        schema["not"], depth + 1
    ):
        return False
    return True


def _object_key_value_value_schema_is_expanded_product_safe(
    schema: Any, depth: int = 0
) -> bool:
    if depth > 8:
        return False
    if isinstance(schema, bool):
        return True
    if not isinstance(schema, dict):
        return False
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return False
    forbidden = {
        "$defs",
        "$id",
        "$schema",
        "$vocabulary",
        "format",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
    if any(key in forbidden for key in schema):
        return False
    return True


def _object_key_value_obligations(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
    budget: int,
    *,
    expanded: bool = False,
    context: ProofContext | None = None,
) -> tuple[ObjectKeyValueObligation, ...] | None:
    obligations = []
    names = (
        set(lhs.properties)
        | set(rhs.properties)
        | set(lhs.required)
        | set(rhs.required)
    )
    if expanded and context is not None:
        exhausted = context.spend_work(
            len(names),
            "object product",
            "object product exceeded proof work budget",
        )
        if exhausted is not None:
            return None
    elif budget >= 0 and len(names) > budget:
        return None

    for name in sorted(names):
        if not lhs.allows_key(name):
            continue
        rhs_schema = rhs.value_schema_for(name)
        if not schema_is_true(rhs_schema):
            obligations.append(
                ObjectKeyValueObligation(name, lhs.value_schema_for(name), rhs_schema)
            )

    pattern_obligations = _object_key_value_pattern_obligations(
        lhs,
        rhs,
        names,
        budget,
        expanded=expanded,
        context=context,
    )
    if pattern_obligations is None:
        return None
    obligations.extend(pattern_obligations)

    return tuple(obligations)


def _object_key_value_candidate_value_constraints(
    shape: ObjectKeyValueShape,
    context: ProofContext,
) -> tuple[tuple[str, Any], ...]:
    candidates = [
        (name, shape.value_schema_for(name)) for name in sorted(shape.properties)
    ]
    for pattern in shape.patterns:
        witness = string_language_witness(pattern.pattern, context)
        if isinstance(witness, str):
            candidates.append((witness, shape.value_schema_for(witness)))
    return tuple(candidates)


def _object_dependency_closed_present_names(
    schema: Any,
    seed: frozenset[str],
) -> frozenset[str] | None:
    if not isinstance(schema, dict):
        return seed
    names = set(seed)
    required = schema.get("required", [])
    if isinstance(required, list):
        names.update(name for name in required if isinstance(name, str))
    changed = True
    while changed:
        changed = False
        for trigger, dependencies in _object_dependent_required_entries(schema):
            if trigger not in names:
                continue
            for dependency in dependencies:
                if dependency not in names:
                    names.add(dependency)
                    changed = True
        dependent_schemas = schema.get("dependentSchemas", {})
        if isinstance(dependent_schemas, dict):
            for trigger, dependent_schema in dependent_schemas.items():
                if trigger not in names:
                    continue
                for dependency in _object_required_names_from_presence_schema(
                    dependent_schema
                ):
                    if dependency not in names:
                        names.add(dependency)
                        changed = True
    return frozenset(names)


def _object_required_names_from_presence_schema(schema: Any) -> frozenset[str]:
    if not isinstance(schema, dict):
        return frozenset()
    names = {name for name in schema.get("required", []) if isinstance(name, str)}
    for subschema in schema.get("allOf", []):
        names.update(_object_required_names_from_presence_schema(subschema))
    return frozenset(names)


def _object_key_value_pattern_obligations(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
    explicit_names: set[str],
    budget: int,
    *,
    expanded: bool = False,
    context: ProofContext | None = None,
) -> tuple[ObjectKeyValueObligation, ...] | None:
    lhs_patterns = {pattern.text: pattern for pattern in lhs.patterns}
    rhs_patterns = {pattern.text: pattern for pattern in rhs.patterns}
    pattern_map = _object_key_value_partition_patterns(lhs, rhs)
    pattern_texts = tuple(sorted(pattern_map))
    class_count = 1 << len(pattern_texts)
    if expanded and context is not None:
        exhausted = context.spend_work(
            class_count,
            "object product",
            "object product exceeded proof work budget",
        )
        if exhausted is not None:
            return None
    elif budget >= 0 and class_count + len(explicit_names) > budget:
        return None

    obligations = []
    for mask in range(class_count):
        included = frozenset(
            text for index, text in enumerate(pattern_texts) if mask & (1 << index)
        )
        lhs_matches = tuple(
            lhs_patterns[key[1]]
            for key in included
            if key[0] == "pattern" and key[1] in lhs_patterns
        )
        rhs_matches = tuple(
            rhs_patterns[key[1]]
            for key in included
            if key[0] == "pattern" and key[1] in rhs_patterns
        )
        lhs_keyspace_allows = (
            lhs.keyspace_pattern is None or _LHS_KEYSPACE_PARTITION in included
        )
        rhs_keyspace_allows = (
            rhs.keyspace_pattern is None or _RHS_KEYSPACE_PARTITION in included
        )

        lhs_allows = lhs_keyspace_allows and (
            bool(lhs_matches) or lhs.additional_schema is not False
        )
        if not lhs_allows:
            continue

        lhs_schema = _object_key_value_pattern_schema(
            lhs_matches, lhs.additional_schema
        )
        rhs_schema = (
            _object_key_value_pattern_schema(rhs_matches, rhs.additional_schema)
            if rhs_keyspace_allows
            else False
        )
        if schema_is_true(rhs_schema):
            continue

        pattern = RegexLanguage.all()
        for text in pattern_texts:
            branch = pattern_map[text]
            branch_pattern = branch if text in included else branch.complement()
            intersection = pattern.intersection(branch_pattern)
            if isinstance(intersection, ProofResult):
                return None
            pattern = intersection
            if pattern.is_empty():
                break
        if pattern.is_empty():
            continue

        representative = _object_key_pattern_witness_excluding(pattern, explicit_names)
        if representative is _EMPTY_KEY_CLASS:
            continue
        if representative is None:
            return None
        if not isinstance(representative, str):
            return None
        obligations.append(
            ObjectKeyValueObligation(representative, lhs_schema, rhs_schema)
        )
    return tuple(obligations)


def _object_key_value_direct_false_witness_skeleton(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
    context: ProofContext | None,
) -> ObjectKeyValueWitnessSkeleton | ProofResult | None:
    if context is None or context.endeavor_enabled:
        return None
    for name in _object_key_value_direct_witness_names(lhs, rhs, context):
        if not lhs.allows_key(name):
            continue
        lhs_schema = lhs.value_schema_for(name)
        rhs_schema = rhs.value_schema_for(name)
        if schema_is_true(rhs_schema):
            continue
        proof = context.subproof(lhs_schema, rhs_schema)
        if proof.status == "resource_exhausted":
            return proof
        if proof.status != "proved_false" or proof.witness is None:
            continue
        return _object_key_value_bad_value_skeleton(lhs, name, proof.witness)
    return None


def _object_key_value_direct_witness_names(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
    context: ProofContext,
) -> tuple[str, ...]:
    names: list[str] = []

    def add_witness(language: RegexLanguage | ProofResult) -> ProofResult | None:
        if isinstance(language, ProofResult):
            return language
        witness = string_language_witness(language, context)
        if isinstance(witness, ProofResult):
            return witness
        if isinstance(witness, str) and witness not in names:
            names.append(witness)
        return None

    for pattern in rhs.patterns + lhs.patterns:
        proof = add_witness(pattern.pattern)
        if proof is not None:
            return ()

    for lhs_pattern in lhs.patterns:
        for rhs_pattern in rhs.patterns:
            witness = lhs_pattern.pattern.intersection_witness(
                rhs_pattern.pattern, context
            )
            if isinstance(witness, ProofResult):
                return ()
            if isinstance(witness, str) and witness not in names:
                names.append(witness)

    return tuple(names)


def _object_key_value_bad_value_skeleton(
    lhs: ObjectKeyValueShape,
    name: str,
    bad_value: Any,
) -> ObjectKeyValueWitnessSkeleton | None:
    present = set(lhs.required)
    present.add(name)
    if not all(lhs.allows_key(present_name) for present_name in present):
        return None
    return ObjectKeyValueWitnessSkeleton(
        tuple(
            ObjectKeyValueWitnessSlot(
                present_name,
                {"const": bad_value}
                if present_name == name
                else lhs.value_schema_for(present_name),
            )
            for present_name in sorted(present)
        )
    )


def _object_key_value_obligations_budget_exhausted(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
    budget: int,
) -> bool:
    if budget < 0:
        return False

    names = (
        set(lhs.properties)
        | set(rhs.properties)
        | set(lhs.required)
        | set(rhs.required)
    )
    class_count = 1 << len(_object_key_value_partition_patterns(lhs, rhs))
    return class_count + len(names) > budget


_LHS_KEYSPACE_PARTITION = ("keyspace", "lhs")
_RHS_KEYSPACE_PARTITION = ("keyspace", "rhs")
_EMPTY_KEY_CLASS = object()


def _object_key_value_partition_patterns(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
) -> dict[tuple[str, str], Any]:
    pattern_map = {
        ("pattern", pattern.text): pattern.pattern for pattern in lhs.patterns
    }
    pattern_map.update(
        {("pattern", pattern.text): pattern.pattern for pattern in rhs.patterns}
    )
    if lhs.keyspace_pattern is not None:
        pattern_map[_LHS_KEYSPACE_PARTITION] = lhs.keyspace_pattern
    if rhs.keyspace_pattern is not None:
        pattern_map[_RHS_KEYSPACE_PARTITION] = rhs.keyspace_pattern
    return pattern_map


def _object_key_value_pattern_schema(
    matches: tuple[ObjectKeyValuePattern, ...],
    additional_schema: Any,
) -> Any:
    if not matches:
        return additional_schema
    return _all_of_schema(
        tuple(pattern.schema for pattern in matches if pattern.schema is not True)
    )


def _object_key_value_keyspace_witness(
    lhs: ObjectKeyValueShape,
    rhs: ObjectKeyValueShape,
    context: ProofContext | None,
) -> str | ProofResult | None:
    for name in sorted(set(lhs.properties) | set(lhs.required)):
        if lhs.allows_key(name) and not rhs.allows_key(name):
            return name

    if rhs.keyspace_pattern is None:
        return None

    for lhs_pattern in lhs.patterns:
        difference = lhs_pattern.pattern.intersection(rhs.keyspace_pattern.complement())
        if isinstance(difference, ProofResult):
            return difference
        if difference.is_empty():
            continue
        witness = string_language_witness(difference, context)
        if isinstance(witness, ProofResult):
            return witness
        if (
            isinstance(witness, str)
            and lhs.allows_key(witness)
            and not rhs.allows_key(witness)
        ):
            return witness

    if lhs.additional_schema is False:
        return None
    lhs_keyspace = (
        RegexLanguage.all() if lhs.keyspace_pattern is None else lhs.keyspace_pattern
    )
    difference = lhs_keyspace.intersection(rhs.keyspace_pattern.complement())
    if isinstance(difference, ProofResult):
        return difference
    if difference.is_empty():
        return None
    witness = string_language_witness(difference, context)
    if isinstance(witness, ProofResult):
        return witness
    if (
        isinstance(witness, str)
        and lhs.allows_key(witness)
        and not rhs.allows_key(witness)
    ):
        return witness
    return None


def _distinct_lhs_object_property_names(
    lhs: ObjectKeyValueShape,
    count: int,
    context: ProofContext | None,
    *,
    blocked: frozenset[str] = frozenset(),
) -> tuple[str, ...] | None:
    if count == 0:
        return ()

    names: list[str] = []

    def add(name: str) -> None:
        if name in blocked or name in names or not lhs.allows_key(name):
            return
        names.append(name)

    for name in sorted(lhs.required | frozenset(lhs.properties)):
        add(name)
        if len(names) >= count:
            return tuple(names)

    for pattern in lhs.patterns:
        language = _shape_keyspace_restricted_pattern(lhs, pattern.pattern, context)
        if isinstance(language, ProofResult):
            return None
        if language is None:
            continue
        while len(names) < count:
            key_candidate = _object_key_pattern_witness_excluding(
                language, set(names) | set(blocked)
            )
            if not isinstance(key_candidate, str):
                break
            before = len(names)
            add(key_candidate)
            if len(names) == before:
                break
        if len(names) >= count:
            return tuple(names)

    if lhs.additional_schema is not False:
        language = (
            RegexLanguage.all()
            if lhs.keyspace_pattern is None
            else lhs.keyspace_pattern
        )
        while len(names) < count:
            key_candidate = _object_key_pattern_witness_excluding(
                language, set(names) | set(blocked)
            )
            if not isinstance(key_candidate, str):
                break
            before = len(names)
            add(key_candidate)
            if len(names) == before:
                break

    return tuple(names) if len(names) >= count else None


def _object_key_value_shape_allows_unrestricted_keys(
    shape: ObjectKeyValueShape,
) -> bool:
    return (
        not shape.properties
        and not shape.patterns
        and shape.additional_schema is True
        and shape.keyspace_pattern is None
        and not shape.required
    )


def _shape_keyspace_restricted_pattern(
    shape: ObjectKeyValueShape,
    pattern: RegexLanguage,
    context: ProofContext | None,
) -> RegexLanguage | ProofResult | None:
    if shape.keyspace_pattern is None:
        return pattern
    intersection = pattern.intersection(shape.keyspace_pattern, context)
    if isinstance(intersection, ProofResult):
        return intersection
    if intersection.is_empty():
        return None
    return intersection


def _object_key_pattern_witness(pattern: Any) -> str | None:
    witness = string_language_witness(pattern)
    return witness if isinstance(witness, str) else None


def _object_key_pattern_witness_excluding(
    pattern: Any, excluded_names: set[str]
) -> str | object | None:
    witness = string_language_witness(pattern)
    if isinstance(witness, str) and witness not in excluded_names:
        return witness

    for seed in (
        "__fresh_property__",
        "fresh",
        "property",
        witness if isinstance(witness, str) else "",
    ):
        for index in range(len(excluded_names) + 1):
            fresh_name = f"{seed}{index}"
            if fresh_name not in excluded_names and pattern.matches(fresh_name):
                return fresh_name

    reduced = pattern
    for name in excluded_names:
        reduced = reduced.intersection(RegexLanguage.exact(name).complement())
        if isinstance(reduced, ProofResult):
            return None
        if reduced.is_empty():
            return _EMPTY_KEY_CLASS
    return _object_key_pattern_witness(reduced)


def _subschema_is_proved(lhs: Any, rhs: Any, context: ProofContext) -> bool:
    return context.subproof(lhs, rhs).status == "proved_true"


def _rhs_evaluation_trace(
    lhs_schema: Any,
    rhs: LogicalSchemaIR,
    problem: DifferenceProblem | None,
) -> EvaluationTraceExpression:
    return evaluation_trace_for_source(
        rhs.source,
        rhs.graph,
        lhs_schema=lhs_schema,
        context=None if problem is None else problem.context,
    )


def _evaluated_item_sources_are_supported(sources: tuple[Any, ...]) -> bool:
    return all(
        (
            source.kind in {"additionalItems", "items", "prefixItems"}
            and (source.index is not None or source.start_index is not None)
        )
        or (source.kind == "contains" and source.marks_contains_matches)
        for source in sources
    )


def _rhs_all_of_unevaluated_items_true_fragment_supported(
    schema: Any,
    depth: int = 0,
    *,
    is_root: bool = True,
) -> bool:
    if schema is True:
        return True
    if schema is False or depth > 16 or not isinstance(schema, dict):
        return False
    if _schema_is_pure_static_ref(schema):
        return True

    allowed_keywords = {
        "$defs",
        "allOf",
        "anyOf",
        "contains",
        "definitions",
        "else",
        "if",
        "items",
        "oneOf",
        "prefixItems",
        "then",
        "type",
    }
    if is_root:
        allowed_keywords.add("unevaluatedItems")
    if not _schema_has_only_keywords(schema, allowed_keywords):
        return False
    if not _schema_type_accepts_arrays(schema.get("type")):
        return False
    if "prefixItems" in schema and not isinstance(schema["prefixItems"], list):
        return False
    if "items" in schema and not isinstance(schema["items"], bool | dict):
        return False
    if "contains" in schema and not isinstance(schema["contains"], bool | dict):
        return False

    return _rhs_unevaluated_items_children_supported(schema, depth)


def _schema_type_accepts_arrays(type_keyword: Any) -> bool:
    if type_keyword is None:
        return True
    if isinstance(type_keyword, str):
        return type_keyword == "array"
    if isinstance(type_keyword, list):
        return "array" in type_keyword
    return False


def _rhs_unevaluated_items_children_supported(
    schema: dict[str, Any], depth: int
) -> bool:
    for keyword in ("allOf", "anyOf", "oneOf"):
        subschemas = schema.get(keyword, [])
        if not isinstance(subschemas, list):
            return False
        if not all(
            _rhs_unevaluated_items_branch_supported(keyword, subschema, depth)
            for subschema in subschemas
        ):
            return False
    for keyword in ("if", "then", "else"):
        subschema = schema.get(keyword)
        if (
            subschema is not None
            and not _rhs_all_of_unevaluated_items_true_fragment_supported(
                subschema,
                depth + 1,
                is_root=False,
            )
        ):
            return False
    return True


def _rhs_unevaluated_items_branch_supported(
    keyword: str, subschema: Any, depth: int
) -> bool:
    if subschema is False and keyword in {"anyOf", "oneOf"}:
        return True
    return _rhs_all_of_unevaluated_items_true_fragment_supported(
        subschema,
        depth + 1,
        is_root=False,
    )


def _rhs_evaluated_item_schema_for_index(
    sources: tuple[Any, ...],
    index: int,
    model: ArrayDifferenceModel | None = None,
) -> Any | None:
    schemas = [
        source.schema
        for source in sources
        if _rhs_evaluates_item_source_index(source, index, model)
    ]
    if not schemas:
        return None
    return _all_of_schema(tuple(schema for schema in schemas if schema is not True))


def _rhs_evaluates_item_source_index(
    source: EvaluatedItemSource,
    index: int,
    model: ArrayDifferenceModel | None = None,
) -> bool:
    if source.index is not None:
        return source.index == index
    if source.start_index is not None:
        return index >= source.start_index
    if source.kind == "contains" and model is not None:
        return _rhs_contains_source_guaranteed_for_index(source, index, model)
    return False


def _rhs_contains_source_guaranteed_for_index(
    source: EvaluatedItemSource, index: int, model: ArrayDifferenceModel
) -> bool:
    if not source.marks_contains_matches or model.problem is None:
        return False
    return _subschema_is_proved(
        model.lhs_item_schema_at(index),
        source.schema,
        model.problem.context,
    )


def _first_rhs_unevaluated_item_index_reachable(
    model: ArrayDifferenceModel,
    rhs_sources: tuple[Any, ...],
) -> int | None:
    upper_bound = model.array_length_upper_bound()
    limit = (
        upper_bound
        if upper_bound is not None
        else _first_unevaluated_item_probe_limit(rhs_sources)
    )
    for index in range(limit):
        if model.first_lhs_length_reaching(index) is None:
            continue
        if _rhs_evaluated_item_schema_for_index(rhs_sources, index, model) is None:
            return index
    return None


def _first_unevaluated_item_probe_limit(sources: tuple[Any, ...]) -> int:
    indexes = [
        source.index
        for source in sources
        if isinstance(source.index, int)
    ]
    starts = [
        source.start_index
        for source in sources
        if isinstance(source.start_index, int)
    ]
    return max([*indexes, *starts, 0]) + 2


def _evaluated_property_sources_are_supported(sources: tuple[Any, ...]) -> bool:
    for source in sources:
        if source.kind not in {"properties", "patternProperties"} or source.key is None:
            return False
        if (
            source.kind == "patternProperties"
            and RegexLanguage.maybe_from_json_regex(source.key) is None
        ):
            return False
    return True


def _rhs_all_of_unevaluated_properties_true_fragment_supported(
    schema: Any,
    depth: int = 0,
    *,
    is_root: bool = True,
) -> bool:
    if schema is True:
        return True
    if schema is False or depth > 16 or not isinstance(schema, dict):
        return False
    if _schema_is_pure_static_ref(schema):
        return True

    allowed_keywords = {
        "$defs",
        "allOf",
        "anyOf",
        "definitions",
        "else",
        "if",
        "oneOf",
        "patternProperties",
        "properties",
        "then",
        "type",
    }
    if is_root:
        allowed_keywords.add("unevaluatedProperties")
    if not _schema_has_only_keywords(schema, allowed_keywords):
        return False
    if not _schema_type_accepts_objects(schema.get("type")):
        return False

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return False
    pattern_properties = schema.get("patternProperties", {})
    if not isinstance(pattern_properties, dict):
        return False
    if any(
        RegexLanguage.maybe_from_json_regex(str(pattern)) is None
        for pattern in pattern_properties
    ):
        return False

    return _rhs_unevaluated_properties_children_supported(schema, depth)


def _schema_type_accepts_objects(type_keyword: Any) -> bool:
    if type_keyword is None:
        return True
    if isinstance(type_keyword, str):
        return type_keyword == "object"
    if isinstance(type_keyword, list):
        return "object" in type_keyword
    return False


def _rhs_unevaluated_properties_children_supported(
    schema: dict[str, Any], depth: int
) -> bool:
    for keyword in ("allOf", "anyOf", "oneOf"):
        subschemas = schema.get(keyword, [])
        if not isinstance(subschemas, list):
            return False
        if not all(
            _rhs_unevaluated_properties_branch_supported(keyword, subschema, depth)
            for subschema in subschemas
        ):
            return False
    for keyword in ("if", "then", "else"):
        subschema = schema.get(keyword)
        if (
            subschema is not None
            and not _rhs_all_of_unevaluated_properties_true_fragment_supported(
                subschema,
                depth + 1,
                is_root=False,
            )
        ):
            return False
    return True


def _rhs_unevaluated_properties_branch_supported(
    keyword: str, subschema: Any, depth: int
) -> bool:
    if subschema is False and keyword in {"anyOf", "oneOf"}:
        return True
    return _rhs_all_of_unevaluated_properties_true_fragment_supported(
        subschema,
        depth + 1,
        is_root=False,
    )


def _rhs_evaluated_property_schema_for_name(
    sources: tuple[Any, ...], name: str
) -> Any | None:
    schemas = [
        source.schema
        for source in sources
        if _rhs_evaluates_property_source_name(source, name)
    ]
    if not schemas:
        return None
    return _all_of_schema(tuple(schema for schema in schemas if schema is not True))


def _rhs_evaluates_property_name(sources: tuple[Any, ...], name: str) -> bool:
    return any(_rhs_evaluates_property_source_name(source, name) for source in sources)


def _unevaluated_property_witness_name(
    lhs_shape: ObjectKeyValueShape,
    rhs_sources: tuple[Any, ...],
    context: ProofContext | None,
) -> str | ProofResult | None:
    for name in sorted(set(lhs_shape.properties) | set(lhs_shape.required)):
        if lhs_shape.allows_key(name) and not _rhs_evaluates_property_name(
            rhs_sources, name
        ):
            return name

    pattern = (
        RegexLanguage.all()
        if lhs_shape.keyspace_pattern is None
        else lhs_shape.keyspace_pattern
    )
    excluded_names: set[str] = set()
    for source in rhs_sources:
        if source.kind == "properties" and source.key is not None:
            excluded_names.add(source.key)
        elif source.kind == "patternProperties" and source.key is not None:
            source_pattern = RegexLanguage.maybe_from_json_regex(source.key)
            if source_pattern is None:
                return ProofResult.unsupported(
                    "SAT unevaluatedProperties witness requires supported "
                    "evaluated property regex"
                )
            source_complement = source_pattern.complement()
            if isinstance(source_complement, ProofResult):
                return source_complement
            intersection = pattern.intersection(source_complement)
            if isinstance(intersection, ProofResult):
                return intersection
            pattern = intersection
            if pattern.is_empty():
                return None

    witness = string_language_witness(pattern, context)
    if isinstance(witness, ProofResult):
        return witness
    if (
        isinstance(witness, str)
        and witness not in excluded_names
        and lhs_shape.allows_key(witness)
    ):
        return witness

    alternate_witness = _object_key_pattern_witness_excluding(pattern, excluded_names)
    if isinstance(alternate_witness, str) and lhs_shape.allows_key(alternate_witness):
        return alternate_witness
    return None


def _rhs_evaluates_property_source_name(source: Any, name: str) -> bool:
    if source.kind == "properties" and source.key == name:
        return True
    if source.kind == "patternProperties" and source.key is not None:
        pattern = RegexLanguage.maybe_from_json_regex(source.key)
        return pattern is not None and pattern.matches(name)
    return False


def _schema_negation(schema: Any) -> Any:
    if schema is True:
        return False
    if schema is False:
        return True
    return {"not": schema}


def _array_slots(ir: LogicalSchemaIR) -> tuple[ArraySlot, ...]:
    slots = [
        ArraySlot(source.index, source.schema, source.kind)
        for source in ir.evaluation.item_sources
        if source.index is not None
    ]
    return tuple(sorted(slots, key=lambda slot: slot.index))


def _array_tail(ir: LogicalSchemaIR) -> ArrayTail | None:
    tails = [
        ArrayTail(source.start_index, source.schema, source.kind)
        for source in ir.evaluation.item_sources
        if source.start_index is not None
    ]
    if not tails:
        return None
    return sorted(tails, key=lambda tail: tail.start_index)[-1]


def _array_contains(ir: LogicalSchemaIR) -> ArrayContainsConstraint | None:
    if not isinstance(ir.schema, dict) or "contains" not in ir.schema:
        return None
    minimum = ir.schema.get("minContains", 1)
    maximum = ir.schema.get("maxContains")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool)
    ):
        return None

    contains_sources = [
        source for source in ir.evaluation.item_sources if source.kind == "contains"
    ]
    marks_evaluated = any(source.marks_contains_matches for source in contains_sources)
    return ArrayContainsConstraint(
        ir.schema["contains"], minimum, maximum, marks_evaluated
    )


def _is_array_item_values_fragment_schema(
    schema: Any, dialect: Dialect, *, allow_contains: bool = False
) -> bool:
    if isinstance(schema, bool):
        return True
    if not isinstance(schema, dict):
        return False

    allowed_keywords = {
        "additionalItems",
        "items",
        "maxItems",
        "minItems",
        "prefixItems",
        "type",
        "uniqueItems",
    }
    if allow_contains:
        allowed_keywords = allowed_keywords | {"contains", "maxContains", "minContains"}
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in allowed_keywords:
            return False
        if key in {"minItems", "maxItems"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
        if key in {"minContains", "maxContains"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
        if key == "contains" and not isinstance(value, bool | dict):
            return False
        if key == "uniqueItems" and not isinstance(value, bool):
            return False
        if key == "prefixItems" and (
            dialect is not Dialect.DRAFT202012 or not isinstance(value, list)
        ):
            return False
        if key == "items":
            if dialect is Dialect.DRAFT202012:
                if not isinstance(value, bool | dict):
                    return False
            elif not isinstance(value, bool | dict | list):
                return False
        if key == "additionalItems" and not isinstance(value, bool | dict):
            return False
    return True


def _schema_type_is_array_only(schema: Any) -> bool:
    return isinstance(schema, dict) and schema.get("type") == "array"


def _schema_has_only_keywords(schema: dict[str, Any], keywords: set[str]) -> bool:
    return all(key in keywords or key in IGNORED_SCHEMA_METADATA_KEYS for key in schema)


def _schema_is_pure_static_ref(schema: dict[str, Any]) -> bool:
    return {key for key in schema if key not in IGNORED_SCHEMA_METADATA_KEYS} == {
        "$ref"
    }


def _array_item_schema_at(
    slots: tuple[ArraySlot, ...], tail: ArrayTail | None, index: int
) -> Any:
    for slot in slots:
        if slot.index == index:
            return slot.schema
    if tail is not None and index >= tail.start_index:
        return tail.schema
    return True


def _array_length_shape_allows(shape: ArrayShape, length: int) -> bool:
    return any(
        interval.lower <= length
        and (interval.upper is None or length <= interval.upper)
        for interval in shape.normalized_intervals()
    )


def _array_length_shape_symbolic_expr(
    shape: ArrayShape, length: Any, solver: SymbolicSolver
) -> Any:
    return solver.or_(
        *(
            _closed_nonnegative_interval_symbolic_expr(
                interval.lower, interval.upper, length, solver
            )
            for interval in shape.normalized_intervals()
        )
    )


def _object_property_count_shape_symbolic_expr(
    shape: ObjectPropertyCountShape,
    count: Any,
    solver: SymbolicSolver,
) -> Any:
    return solver.or_(
        *(
            _closed_nonnegative_interval_symbolic_expr(
                interval.lower, interval.upper, count, solver
            )
            for interval in shape.normalized_intervals()
        )
    )


def _closed_nonnegative_interval_symbolic_expr(
    lower: int,
    upper: int | None,
    value: Any,
    solver: SymbolicSolver,
) -> Any:
    constraints = [solver.ge(value, lower)]
    if upper is not None:
        constraints.append(solver.le(value, upper))
    return solver.and_(*constraints)


def _object_key_universe(
    lhs: LogicalSchemaIR,
    rhs: LogicalSchemaIR,
    lhs_closed: ClosedObjectPropertiesShape | None,
    rhs_closed: ClosedObjectPropertiesShape | None,
) -> ObjectKeyUniverse:
    key_classes = sorted(
        {
            *_object_key_classes(lhs),
            *_object_key_classes(rhs),
        },
        key=lambda key_class: (key_class.kind, key_class.source, key_class.key),
    )
    explicit_names = frozenset(
        key_class.key for key_class in key_classes if key_class.kind == "explicit"
    )
    lhs_closed_world = lhs_closed is not None and lhs_closed.has_finite_keyspace
    rhs_closed_world = rhs_closed is not None and rhs_closed.has_finite_keyspace
    fresh = (
        None
        if lhs_closed_world and rhs_closed_world
        else FreshPropertyClass(_fresh_name(explicit_names), explicit_names)
    )
    return ObjectKeyUniverse(
        tuple(key_classes), fresh, lhs_closed_world, rhs_closed_world
    )


def _object_key_classes(ir: LogicalSchemaIR) -> set[ObjectKeyClass]:
    key_classes: set[ObjectKeyClass] = set()
    for source in ir.evaluation.property_sources:
        if source.kind == "properties" and source.key is not None:
            key_classes.add(ObjectKeyClass("explicit", "properties", source.key))
        elif source.kind == "patternProperties" and source.key is not None:
            key_classes.add(ObjectKeyClass("pattern", "patternProperties", source.key))
        elif (
            source.kind in {"dependencies", "dependentSchemas"}
            and source.key is not None
        ):
            key_classes.add(ObjectKeyClass("explicit", source.kind, source.key))

    schema = ir.schema
    if isinstance(schema, dict):
        for required in schema.get("required", []):
            if isinstance(required, str):
                key_classes.add(ObjectKeyClass("explicit", "required", required))
    return key_classes


def _object_dependency_interesting_names(schema: Any) -> tuple[str, ...]:
    names = set()
    for trigger, dependencies in _object_dependent_required_entries(schema):
        names.add(trigger)
        names.update(dependencies)
    for trigger, dependencies in _object_dependent_schema_required_entries(schema):
        names.add(trigger)
        names.update(dependencies)
    return tuple(sorted(names))


def _object_dependent_required_entries(
    schema: Any,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(schema, dict):
        return ()
    entries = []
    for keyword in ("dependentRequired", "dependencies"):
        value = schema.get(keyword)
        if not isinstance(value, dict):
            continue
        for trigger, dependencies in value.items():
            if not isinstance(trigger, str):
                continue
            if not isinstance(dependencies, list) or not all(
                isinstance(name, str) for name in dependencies
            ):
                continue
            entries.append((trigger, tuple(dependencies)))
    return tuple(entries)


def _object_dependent_schema_required_entries(
    schema: Any,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(schema, dict):
        return ()
    entries = []
    dependent_schemas = schema.get("dependentSchemas", {})
    if not isinstance(dependent_schemas, dict):
        return ()
    for trigger, dependent_schema in dependent_schemas.items():
        if not isinstance(trigger, str):
            continue
        dependencies = tuple(
            sorted(_object_required_names_from_presence_schema(dependent_schema))
        )
        if dependencies:
            entries.append((trigger, dependencies))
    return tuple(entries)


def _collect_object_presence_product_names(
    schema: Any, names: set[str], depth: int = 0
) -> bool:
    if depth > 16:
        return False
    if isinstance(schema, bool):
        return True
    if not isinstance(schema, dict):
        return False
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return False
    if not _is_object_presence_product_schema(schema):
        return False

    for name in schema.get("required", []):
        names.add(name)
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        names.update(name for name in properties if isinstance(name, str))
    for trigger, dependencies in schema.get("dependentRequired", {}).items():
        names.add(trigger)
        names.update(dependencies)
    for trigger, dependencies in schema.get("dependencies", {}).items():
        names.add(trigger)
        names.update(dependencies)
    for trigger, dependent_schema in schema.get("dependentSchemas", {}).items():
        names.add(trigger)
        if not _collect_object_presence_product_names(
            dependent_schema, names, depth + 1
        ):
            return False

    for keyword in ("allOf", "anyOf", "oneOf"):
        for subschema in schema.get(keyword, []):
            if not _collect_object_presence_product_names(subschema, names, depth + 1):
                return False
    if "not" in schema and not _collect_object_presence_product_names(
        schema["not"], names, depth + 1
    ):
        return False
    return True


def _object_presence_product_accepts(
    schema: Any,
    atom: str,
    present: frozenset[str],
    depth: int = 0,
) -> bool | None:
    if depth > 16:
        return None
    if schema is True:
        return True
    if schema is False:
        return False
    if not isinstance(schema, dict):
        return None
    if not _is_object_presence_product_schema(schema):
        return None

    local = _local_object_presence_product_accepts(schema, atom, present)
    if local is None or not local:
        return local

    for subschema in schema.get("allOf", []):
        branch = _object_presence_product_accepts(subschema, atom, present, depth + 1)
        if branch is None:
            return None
        if not branch:
            return False

    if "anyOf" in schema:
        branch_results = []
        for subschema in schema["anyOf"]:
            branch = _object_presence_product_accepts(
                subschema, atom, present, depth + 1
            )
            if branch is None:
                return None
            branch_results.append(branch)
        if not any(branch_results):
            return False

    if "oneOf" in schema:
        branch_results = []
        for subschema in schema["oneOf"]:
            branch = _object_presence_product_accepts(
                subschema, atom, present, depth + 1
            )
            if branch is None:
                return None
            branch_results.append(branch)
        if sum(branch_results) != 1:
            return False

    if atom == "object":
        for trigger, dependent_schema in schema.get("dependentSchemas", {}).items():
            if trigger not in present:
                continue
            branch = _object_presence_product_accepts(
                dependent_schema, atom, present, depth + 1
            )
            if branch is None:
                return None
            if not branch:
                return False

    if "not" in schema:
        negated = _object_presence_product_accepts(
            schema["not"], atom, present, depth + 1
        )
        if negated is None:
            return None
        if negated:
            return False

    return True


def _object_presence_product_symbolic_expr(
    schema: Any,
    variables: dict[str, Any],
    solver: SymbolicSolver,
    depth: int = 0,
) -> Any | None:
    if depth > 16:
        return None
    if schema is True:
        return solver.and_()
    if schema is False:
        return solver.or_()
    if not isinstance(schema, dict):
        return None
    if not _is_object_presence_product_schema(schema):
        return None

    local = _local_object_presence_product_symbolic_expr(schema, variables, solver)
    if local is None:
        return None
    constraints = [local]

    for subschema in schema.get("allOf", []):
        branch = _object_presence_product_symbolic_expr(
            subschema, variables, solver, depth + 1
        )
        if branch is None:
            return None
        constraints.append(branch)

    if "anyOf" in schema:
        branches = []
        for subschema in schema["anyOf"]:
            branch = _object_presence_product_symbolic_expr(
                subschema, variables, solver, depth + 1
            )
            if branch is None:
                return None
            branches.append(branch)
        constraints.append(solver.or_(*branches))

    if "oneOf" in schema:
        branches = []
        for subschema in schema["oneOf"]:
            branch = _object_presence_product_symbolic_expr(
                subschema, variables, solver, depth + 1
            )
            if branch is None:
                return None
            branches.append(branch)
        constraints.append(solver.exactly_one(branches))

    for trigger, dependent_schema in schema.get("dependentSchemas", {}).items():
        if not isinstance(trigger, str):
            return None
        branch = _object_presence_product_symbolic_expr(
            dependent_schema, variables, solver, depth + 1
        )
        if branch is None:
            return None
        constraints.append(
            solver.implies(variables.get(trigger, solver.bool_var(trigger)), branch)
        )

    if "not" in schema:
        negated = _object_presence_product_symbolic_expr(
            schema["not"], variables, solver, depth + 1
        )
        if negated is None:
            return None
        constraints.append(solver.not_(negated))

    return solver.and_(*constraints)


def _local_object_presence_product_symbolic_expr(
    schema: dict[str, Any],
    variables: dict[str, Any],
    solver: SymbolicSolver,
) -> Any | None:
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    if "object" not in type_shape.atoms:
        return solver.or_()

    constraints = []
    for name in schema.get("required", []):
        if not isinstance(name, str):
            return None
        constraints.append(variables.get(name, solver.bool_var(name)))

    if schema.get("additionalProperties") is False:
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return None
        allowed = frozenset(name for name in properties if isinstance(name, str))
        constraints.extend(
            solver.not_(variable)
            for name, variable in variables.items()
            if name not in allowed
        )

    for trigger, dependencies in schema.get("dependentRequired", {}).items():
        if not isinstance(trigger, str):
            return None
        dependency_vars = [
            variables.get(name, solver.bool_var(name)) for name in dependencies
        ]
        constraints.append(
            solver.implies(
                variables.get(trigger, solver.bool_var(trigger)),
                solver.and_(*dependency_vars),
            )
        )

    for trigger, dependencies in schema.get("dependencies", {}).items():
        if not isinstance(trigger, str):
            return None
        dependency_vars = [
            variables.get(name, solver.bool_var(name)) for name in dependencies
        ]
        constraints.append(
            solver.implies(
                variables.get(trigger, solver.bool_var(trigger)),
                solver.and_(*dependency_vars),
            )
        )

    minimum = schema.get("minProperties", 0)
    maximum = schema.get("maxProperties")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool)
    ):
        return None
    values = tuple(variables.values())
    constraints.append(solver.cardinality_ge(values, minimum))
    if maximum is not None:
        constraints.append(solver.cardinality_le(values, maximum))
    return solver.and_(*constraints)


def _object_property_count_upper_bound(
    shape: ObjectPropertyCountShape | None,
) -> int | None:
    if shape is None:
        return None
    intervals = shape.normalized_intervals()
    if not intervals or any(interval.upper is None for interval in intervals):
        return None
    return max(interval.upper for interval in intervals if interval.upper is not None)


def _object_schema_max_properties_bound(schema: Any, depth: int = 0) -> int | None:
    if depth > 16 or not isinstance(schema, dict):
        return None

    bounds = []
    maximum = schema.get("maxProperties")
    if isinstance(maximum, int) and not isinstance(maximum, bool):
        bounds.append(maximum)

    negated = schema.get("not")
    if isinstance(negated, dict):
        minimum = negated.get("minProperties")
        if isinstance(minimum, int) and not isinstance(minimum, bool) and minimum > 0:
            bounds.append(minimum - 1)

    for subschema in schema.get("allOf", []):
        bound = _object_schema_max_properties_bound(subschema, depth + 1)
        if bound is not None:
            bounds.append(bound)

    for keyword in ("anyOf", "oneOf"):
        value = schema.get(keyword)
        if not isinstance(value, list):
            continue
        branch_bounds: list[int] = []
        for subschema in value:
            bound = _object_schema_max_properties_bound(subschema, depth + 1)
            if bound is None:
                branch_bounds = []
                break
            branch_bounds.append(bound)
        if branch_bounds:
            bounds.append(max(branch_bounds))

    return min(bounds) if bounds else None


def _object_schema_min_properties_lower_bound(schema: Any, depth: int = 0) -> int:
    if depth > 16 or not isinstance(schema, dict):
        return 0
    bounds = []
    minimum = schema.get("minProperties")
    if isinstance(minimum, int) and not isinstance(minimum, bool):
        bounds.append(minimum)
    bounds.extend(
        _object_schema_min_properties_lower_bound(subschema, depth + 1)
        for subschema in schema.get("allOf", [])
    )
    return max(bounds, default=0)


def _object_schema_has_property_count_constraint(schema: Any, depth: int = 0) -> bool:
    if depth > 16 or not isinstance(schema, dict):
        return False
    if "minProperties" in schema or "maxProperties" in schema:
        return True
    if (
        "not" in schema
        and isinstance(schema["not"], dict)
        and _object_schema_has_property_count_constraint(schema["not"], depth + 1)
    ):
        return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        value = schema.get(keyword)
        if isinstance(value, list) and any(
            _object_schema_has_property_count_constraint(subschema, depth + 1)
            for subschema in value
        ):
            return True
    for dependent_schema in schema.get("dependentSchemas", {}).values():
        if _object_schema_has_property_count_constraint(dependent_schema, depth + 1):
            return True
    return False


def _object_presence_schema_has_unmodeled_value_constraints(
    schema: Any, depth: int = 0
) -> bool:
    if depth > 16 or not isinstance(schema, dict):
        return False
    properties = schema.get("properties")
    if isinstance(properties, dict) and any(
        subschema is not True for subschema in properties.values()
    ):
        return True
    for dependent_schema in schema.get("dependentSchemas", {}).values():
        if _object_presence_schema_has_unmodeled_value_constraints(
            dependent_schema, depth + 1
        ):
            return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        value = schema.get(keyword)
        if isinstance(value, list) and any(
            _object_presence_schema_has_unmodeled_value_constraints(
                subschema, depth + 1
            )
            for subschema in value
        ):
            return True
    if "not" in schema and _object_presence_schema_has_unmodeled_value_constraints(
        schema["not"], depth + 1
    ):
        return True
    return False


def _object_presence_lhs_has_negative_value_constraints(
    schema: Any, depth: int = 0
) -> bool:
    if depth > 16 or not isinstance(schema, dict):
        return False
    if "not" in schema and _object_presence_schema_has_unmodeled_value_constraints(
        schema["not"], depth + 1
    ):
        return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        value = schema.get(keyword)
        if isinstance(value, list) and any(
            _object_presence_lhs_has_negative_value_constraints(subschema, depth + 1)
            for subschema in value
        ):
            return True
    return False


def _local_object_presence_product_accepts(
    schema: dict[str, Any],
    atom: str,
    present: frozenset[str],
) -> bool | None:
    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    if atom not in type_shape.atoms:
        return False
    if atom != "object":
        return True

    required = frozenset(schema.get("required", []))
    if not required <= present:
        return False

    if schema.get("additionalProperties") is False:
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return None
        allowed = frozenset(name for name in properties if isinstance(name, str))
        if not present <= allowed:
            return False

    for trigger, dependencies in schema.get("dependentRequired", {}).items():
        if trigger in present and not frozenset(dependencies) <= present:
            return False

    for trigger, dependencies in schema.get("dependencies", {}).items():
        if trigger in present and not frozenset(dependencies) <= present:
            return False

    minimum = schema.get("minProperties", 0)
    maximum = schema.get("maxProperties")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        return None
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool)
    ):
        return None
    if len(present) < minimum:
        return False
    if maximum is not None and len(present) > maximum:
        return False
    return True


def _is_object_presence_product_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key not in OBJECT_PRESENCE_PRODUCT_KEYWORDS:
            return False
        if key in {"allOf", "anyOf", "oneOf"} and not isinstance(value, list):
            return False
        if key == "not" and not isinstance(value, bool | dict):
            return False
        if key == "properties" and not isinstance(value, dict):
            return False
        if key == "additionalProperties" and value is not False:
            return False
        if key == "required" and not _is_string_array(value):
            return False
        if key == "dependentRequired" and not _is_string_array_map(value):
            return False
        if key == "dependencies" and not _is_string_array_map(value):
            return False
        if key == "dependentSchemas" and not _is_presence_schema_map(value):
            return False
        if key in {"minProperties", "maxProperties"} and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
    return True


def _is_string_array(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_string_array_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(name, str) and _is_string_array(dependencies)
        for name, dependencies in value.items()
    )


def _is_presence_schema_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(name, str)
        and isinstance(dependent_schema, bool | dict)
        and _collect_object_presence_product_names(dependent_schema, set())
        for name, dependent_schema in value.items()
    )


def _object_presence_product_has_upper_count_constraint(
    schema: Any, depth: int = 0
) -> bool:
    if depth > 16 or not isinstance(schema, dict):
        return False
    if "maxProperties" in schema:
        return True
    if (
        "not" in schema
        and isinstance(schema["not"], dict)
        and "minProperties" in schema["not"]
    ):
        return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        value = schema.get(keyword)
        if isinstance(value, list) and any(
            _object_presence_product_has_upper_count_constraint(subschema, depth + 1)
            for subschema in value
        ):
            return True
    for dependent_schema in schema.get("dependentSchemas", {}).values():
        if _object_presence_product_has_upper_count_constraint(
            dependent_schema, depth + 1
        ):
            return True
    return False


def _object_presence_product_has_one_of(schema: Any, depth: int = 0) -> bool:
    if depth > 16:
        return False
    if isinstance(schema, list):
        return any(
            _object_presence_product_has_one_of(item, depth + 1) for item in schema
        )
    if not isinstance(schema, dict):
        return False
    if "oneOf" in schema:
        return True
    return any(
        _object_presence_product_has_one_of(value, depth + 1)
        for key, value in schema.items()
        if key in {"allOf", "anyOf", "not", "if", "then", "else", "dependentSchemas"}
    )


def _object_property_names_has_value_constraints(schema: Any) -> bool:
    if isinstance(schema, bool):
        return False
    if not isinstance(schema, dict):
        return True
    properties = schema.get("properties")
    if isinstance(properties, dict) and any(
        subschema is not True for subschema in properties.values()
    ):
        return True
    pattern_properties = schema.get("patternProperties")
    return isinstance(pattern_properties, dict) and any(
        subschema is not True for subschema in pattern_properties.values()
    )


def _all_of_schema(schemas: tuple[Any, ...]) -> Any:
    if not schemas:
        return True
    if len(schemas) == 1:
        return schemas[0]
    return {"allOf": list(schemas)}


def _fresh_name(blocked_names: frozenset[str]) -> str:
    names = _fresh_names(blocked_names, 1)
    if names:
        return names[0]
    raise AssertionError(
        "fresh property representative generation should always terminate"
    )


def _fresh_names(blocked_names: frozenset[str], count: int) -> tuple[str, ...]:
    names = []
    for index in range(len(blocked_names) + count + 8):
        name = "__fresh_property__" if index == 0 else f"__fresh_property_{index}__"
        if name not in blocked_names:
            names.append(name)
        if len(names) == count:
            return tuple(names)
    raise AssertionError(
        "fresh property representative generation should always terminate"
    )

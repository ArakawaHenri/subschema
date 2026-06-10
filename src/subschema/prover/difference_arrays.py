"""
Array difference models and witness materialization.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Any, Literal

from subschema.contracts import ProofResult
from subschema.dialects import Dialect
from subschema.ir import IRAssertionKind, LogicalSchemaIR, SchemaNode
from subschema.ir.constraints import (
    JSON_TYPE_ATOMS,
    ArrayContainsConstraint,
    ArrayLengthConstraint,
    ArrayUniquenessConstraint,
    type_atom_witness,
)
from subschema.ir.evaluation import (
    EvaluatedItemSource,
    EvaluationTraceExpression,
    EvaluationTracePath,
)
from subschema.ir.terms import SchemaTerm
from subschema.prover.confirmation import confirm_term_valid
from subschema.prover.evaluation_traces import evaluation_trace_for_node
from subschema.prover.finite import (
    finite_values_for_ir,
    inhabited_finite_values_for_ir,
    inhabited_finite_values_for_term,
)
from subschema.prover.protocols import (
    DifferenceProblemProtocol,
    ProofContextProtocol,
)
from subschema.prover.witnesses import build_term_witness
from subschema.symbolic import SAT, UNSAT, SymbolicSolver
from subschema.values import json_semantic_key

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
    "conditioned_obligations",
    "obligations",
    "proved_true",
    "resource_exhausted",
    "unsupported",
    "witness",
]


def _array_length_constraint(value: Any) -> ArrayLengthConstraint | None:
    return value if isinstance(value, ArrayLengthConstraint) else None


def _array_uniqueness_constraint(value: Any) -> ArrayUniquenessConstraint | None:
    return value if isinstance(value, ArrayUniquenessConstraint) else None


@dataclass(frozen=True)
class ArraySlot:
    index: int
    source: ArrayItemSource
    term: SchemaTerm | None = None


@dataclass(frozen=True)
class ArrayTail:
    start_index: int
    source: ArrayItemSource
    term: SchemaTerm | None = None

    @property
    def closed(self) -> bool:
        return _term_is_false(self.term)


@dataclass(frozen=True)
class ArrayContainsItemProof:
    index: int
    lhs_term: SchemaTerm | None = None


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
    lhs_term: SchemaTerm | None = None
    rhs_term: SchemaTerm | None = None


@dataclass(frozen=True)
class ArrayUnevaluatedItemsDifferencePlan:
    status: ArrayUnevaluatedItemsPlanStatus
    reason: str = ""
    rejected_reason: str = ""
    witness_skeleton: ArrayWitnessSkeleton | None = None
    obligations: tuple[ArrayUnevaluatedItemObligation, ...] = ()
    conditioned_paths: tuple[EvaluationTracePath, ...] = ()
    unsupported_priority: int = 0

    @classmethod
    def proved_true(cls) -> ArrayUnevaluatedItemsDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(
        cls, reason: str, *, unsupported_priority: int = 0
    ) -> ArrayUnevaluatedItemsDifferencePlan:
        return cls(
            "unsupported", reason=reason, unsupported_priority=unsupported_priority
        )

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

    @classmethod
    def conditioned_obligation_plan(
        cls,
        paths: tuple[EvaluationTracePath, ...],
        *,
        reason: str,
    ) -> ArrayUnevaluatedItemsDifferencePlan:
        return cls(
            "conditioned_obligations",
            reason=reason,
            conditioned_paths=paths,
            unsupported_priority=10,
        )


@dataclass(frozen=True)
class ArrayWitnessSlot:
    index: int
    term: SchemaTerm | None = None


@dataclass(frozen=True)
class ArrayWitnessOverride:
    index: int
    value: Any


@dataclass(frozen=True)
class ArrayWitnessSkeleton:
    length: int
    slots: tuple[ArrayWitnessSlot, ...]
    ir: LogicalSchemaIR | None = None


@dataclass(frozen=True)
class ArrayWitnessPlan:
    skeleton: ArrayWitnessSkeleton
    overrides: tuple[ArrayWitnessOverride, ...] = ()


@dataclass(frozen=True)
class ArrayDuplicateWitnessPlan:
    skeleton: ArrayWitnessSkeleton
    first_index: int
    second_index: int
    duplicate_term: SchemaTerm | None
    overrides: tuple[ArrayWitnessOverride, ...] = ()


def materialize_array_witness_plan(
    plan: ArrayWitnessPlan | None,
    dialect: Dialect,
    *,
    context: ProofContextProtocol | None = None,
) -> list[Any] | None:
    if plan is None:
        return None
    return materialize_array_witness_skeleton(
        plan.skeleton,
        dialect,
        override={override.index: override.value for override in plan.overrides},
        context=context,
    )


def materialize_array_duplicate_witness_plan(
    plan: ArrayDuplicateWitnessPlan | None,
    dialect: Dialect,
    *,
    context: ProofContextProtocol | None = None,
) -> list[Any] | None:
    if plan is None:
        return None
    duplicate_found, duplicate_value = _concrete_witness_for_child_term(
        plan.duplicate_term, plan.skeleton.ir, context
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
        context=context,
    )


def materialize_array_witness_skeleton(
    skeleton: ArrayWitnessSkeleton | None,
    dialect: Dialect,
    *,
    override: tuple[int, Any] | dict[int, Any] | None = None,
    context: ProofContextProtocol | None = None,
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
        if slot.term is None:
            return None
        cache_key = repr(slot.term)
        found, value = value_cache.get(cache_key, (False, None))
        if not found:
            found, value = _concrete_witness_for_child_term(
                slot.term, skeleton.ir, context
            )
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
    count: int,
    *,
    term: SchemaTerm | None = None,
    ir: LogicalSchemaIR | None = None,
    context: ProofContextProtocol | None = None,
) -> tuple[ArrayWitnessOverride, ...] | None:
    found, value = _concrete_witness_for_child_term(term, ir, context)
    if not found:
        return None
    return tuple(ArrayWitnessOverride(index, value) for index in range(count))


def _array_contains_overrides_for_max_violation(
    count: int,
    *,
    distinct: bool,
    term: SchemaTerm | None = None,
    ir: LogicalSchemaIR | None = None,
    context: ProofContextProtocol | None = None,
) -> tuple[ArrayWitnessOverride, ...] | None:
    if not distinct:
        return _array_contains_overrides(
            count, term=term, ir=ir, context=context
        )
    values = _distinct_concrete_witnesses_for_child_term(term, ir, context, count)
    if values is None:
        return None
    return tuple(
        ArrayWitnessOverride(index, value) for index, value in enumerate(values)
    )


def _array_contains_nonmatching_overrides(
    plan: ArrayContainsMinViolationPlan,
    lhs_ir: LogicalSchemaIR | None,
    contains_term: SchemaTerm | None,
    contains_ir: LogicalSchemaIR | None,
    context: ProofContextProtocol | None,
) -> tuple[ArrayWitnessOverride, ...] | None:
    seen: set[str] = set()
    overrides = []
    for item_proof in plan.item_proofs:
        values = _constructive_witness_values_excluding_terms(
            item_proof.lhs_term,
            lhs_ir,
            contains_term,
            contains_ir,
            context,
        )
        for value in values:
            key = json_semantic_key(value)
            if key in seen:
                continue
            seen.add(key)
            overrides.append(ArrayWitnessOverride(item_proof.index, value))
            break
        else:
            return None
    return tuple(overrides)


def _constructive_witness_values_excluding_terms(
    term: SchemaTerm | None,
    ir: LogicalSchemaIR | None,
    excluded_term: SchemaTerm | None,
    excluded_ir: LogicalSchemaIR | None,
    context: ProofContextProtocol | None,
) -> tuple[Any, ...]:
    if term is None or ir is None or excluded_term is None or excluded_ir is None:
        return ()

    excluded_finite = _finite_values_for_term(excluded_term, excluded_ir)
    if excluded_finite is not None:
        excluded_keys = {json_semantic_key(value) for value in excluded_finite}
        return tuple(
            value
            for value in _constructive_witness_values_for_child_term(
                term, ir, context
            )
            if json_semantic_key(value) not in excluded_keys
        )

    excluded_type = _type_constraint_for_term(excluded_term, excluded_ir)
    if excluded_type is None:
        return ()
    schema_type = _type_constraint_for_term(term, ir)
    schema_atoms = schema_type.atoms if schema_type is not None else JSON_TYPE_ATOMS
    atoms = schema_atoms - excluded_type.atoms
    return tuple(type_atom_witness(atom) for atom in sorted(atoms))


def _array_unique_overrides_for_skeleton(
    skeleton: ArrayWitnessSkeleton,
    dialect: Dialect,
    context: ProofContextProtocol | None,
    base_overrides: tuple[ArrayWitnessOverride, ...],
) -> tuple[ArrayWitnessOverride, ...] | None:
    by_index = {override.index: override.value for override in base_overrides}
    seen = {json_semantic_key(value) for value in by_index.values()}
    overrides = list(base_overrides)

    for slot in skeleton.slots:
        if slot.index in by_index:
            continue
        values = _constructive_witness_values_for_child_term(
            slot.term, skeleton.ir, context
        )
        for value in values:
            key = json_semantic_key(value)
            if key in seen:
                continue
            seen.add(key)
            overrides.append(ArrayWitnessOverride(slot.index, value))
            break
        else:
            return None
    return tuple(overrides)


def _distinct_concrete_witnesses_for_child_term(
    term: SchemaTerm | None,
    ir: LogicalSchemaIR | None,
    context: ProofContextProtocol | None,
    count: int,
) -> tuple[Any, ...] | None:
    if count <= 0:
        return ()

    values = []
    seen = set()
    for value in _constructive_witness_values_for_child_term(term, ir, context):
        key = json_semantic_key(value)
        if key in seen:
            continue
        seen.add(key)
        values.append(value)
        if len(values) == count:
            return tuple(values)
    return None


def _constructive_witness_values_for_child_term(
    term: SchemaTerm | None,
    ir: LogicalSchemaIR | None,
    context: ProofContextProtocol | None,
) -> tuple[Any, ...]:
    if term is None or ir is None or context is None:
        return ()

    if term.kind == "true":
        return (None, False, True, 0, 1, "", "a", [], {}, [None], {"a": None})

    if term.kind == "false":
        return ()

    if term.kind == "node":
        if term.ref is None:
            return ()
        node = ir.node_for_ref(term.ref)
        if node is None:
            return ()
        child_ir = ir.with_root(node)
        finite = inhabited_finite_values_for_ir(child_ir, context)
        if finite:
            return tuple(finite)

        numeric = child_ir.numeric_constraint
        if numeric is not None:
            values: list[Any] = []
            for atom in numeric.normalized_atoms():
                values.extend(
                    _json_number_from_fraction(fraction)
                    for fraction in atom.candidate_fractions()
                    if atom.contains(fraction) and numeric.contains(fraction)
                )
            return tuple(values)

    single = build_term_witness(term, ir, context)
    if single.has_witness:
        return (single.witness,)
    return ()


def _finite_values_for_term(
    term: SchemaTerm | None,
    ir: LogicalSchemaIR | None,
) -> tuple[Any, ...] | None:
    if term is None or ir is None:
        return None
    match term.kind:
        case "false":
            return ()
        case "node":
            if term.ref is None:
                return None
            node = ir.node_for_ref(term.ref)
            if node is None:
                return None
            values = finite_values_for_ir(ir.with_root(node))
            return None if values is None else tuple(values)
        case _:
            return None


def _type_constraint_for_term(
    term: SchemaTerm | None,
    ir: LogicalSchemaIR | None,
) -> Any | None:
    if term is None or ir is None or term.kind != "node" or term.ref is None:
        return None
    node = ir.node_for_ref(term.ref)
    return None if node is None else ir.with_root(node).type_constraint


def _json_number_from_fraction(value: Any) -> int | float:
    if value.denominator == 1:
        return int(value)
    return float(value)


def _concrete_witness_for_child_term(
    term: SchemaTerm | None,
    ir: LogicalSchemaIR | None,
    context: ProofContextProtocol | None,
) -> tuple[bool, Any]:
    if term is None or ir is None or context is None:
        return False, None
    result = build_term_witness(term, ir, context)
    return result.has_witness, result.witness


def _term_confirms_value(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
    value: Any,
    context: ProofContextProtocol,
) -> bool:
    return confirm_term_valid(term, ir, value, context).status == "confirmed"


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
    source: ArrayItemValueSource
    lhs_term: SchemaTerm | None = None
    rhs_term: SchemaTerm | None = None


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
    problem: DifferenceProblemProtocol | None = None
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
    def from_problem(cls, problem: DifferenceProblemProtocol) -> ArrayDifferenceModel:
        return cls(
            _ir_rooted_at_term(problem.formula.lhs_term, problem.formula.lhs),
            _ir_rooted_at_term(problem.formula.rhs_term, problem.formula.rhs),
            problem=problem,
        )

    def _lhs_constraint(self, kind: IRAssertionKind) -> Any | None:
        return None if self.problem is None else self.problem.lhs_constraint(kind)

    def _rhs_constraint(self, kind: IRAssertionKind) -> Any | None:
        return None if self.problem is None else self.problem.rhs_constraint(kind)

    def _lhs_exactness_unsupported_reason(
        self,
        kind: IRAssertionKind,
        reason: str,
    ) -> str | None:
        if self.problem is None:
            return None
        proof = self.problem.lhs_require_exact(kind, reason)
        return None if proof is None else proof.reason or reason

    def _rhs_exactness_unsupported_reason(
        self,
        kind: IRAssertionKind,
        reason: str,
    ) -> str | None:
        if self.problem is None:
            return None
        proof = self.problem.rhs_require_exact(kind, reason)
        return None if proof is None else proof.reason or reason

    @cached_property
    def lhs_length(self) -> ArrayLengthConstraint | None:
        return (
            self.lhs_length_constraint
            or _array_length_constraint(self._lhs_constraint("array-length-lhs"))
            or self.lhs.semantics.array_length_lhs_constraint
        )

    @cached_property
    def rhs_length(self) -> ArrayLengthConstraint | None:
        return (
            self.rhs_length_constraint
            or _array_length_constraint(self._rhs_constraint("array-length-rhs"))
            or self.rhs.semantics.array_length_rhs_constraint
        )

    @cached_property
    def rhs_length_with_item_values(self) -> ArrayLengthConstraint | None:
        return (
            self.rhs_length_with_item_values_constraint
            or _array_length_constraint(self._rhs_constraint("array-length-lhs"))
            or self.rhs.semantics.array_length_lhs_constraint
        )

    @cached_property
    def lhs_uniqueness(self) -> ArrayUniquenessConstraint | None:
        return (
            self.lhs_uniqueness_constraint
            or _array_uniqueness_constraint(
                self._lhs_constraint("array-uniqueness-lhs")
            )
            or self.lhs.semantics.array_uniqueness_lhs_constraint
        )

    @cached_property
    def rhs_uniqueness(self) -> ArrayUniquenessConstraint | None:
        return (
            self.rhs_uniqueness_constraint
            or _array_uniqueness_constraint(
                self._rhs_constraint("array-uniqueness-rhs")
            )
            or self.rhs.semantics.array_uniqueness_rhs_constraint
        )

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
        return self.lhs.array_contains_constraint

    @cached_property
    def rhs_contains(self) -> ArrayContainsConstraint | None:
        return self.rhs.array_contains_constraint

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
        rhs_trace = _rhs_evaluation_trace(self.lhs, self.rhs, self.problem)
        if rhs_trace.is_resource_exhausted:
            return ArrayUnevaluatedItemsDifferencePlan.resource_exhausted(
                rhs_trace.resource_exhausted_reason
            )
        if not rhs_trace.is_supported:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                rhs_trace.unsupported_reason,
                unsupported_priority=rhs_trace.unsupported_priority,
            )
        if rhs_trace.has_conditioned_paths:
            if expanded:
                conditioned_plan = (
                    self._conditioned_unevaluated_items_difference_plan(
                        rhs_trace.paths,
                        constraint.term,
                    )
                )
                if conditioned_plan.status != "unsupported":
                    return conditioned_plan
            return ArrayUnevaluatedItemsDifferencePlan.conditioned_obligation_plan(
                rhs_trace.paths,
                reason=(
                    "SAT unevaluatedItems difference defers branch-conditioned "
                    "evaluation trace paths"
                ),
            )
        if not _evaluated_item_sources_are_supported(rhs_trace.evaluated_item_sources):
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems difference defers non-structural "
                "evaluated item sources"
            )

        finite_lhs_plan = self._finite_lhs_unevaluated_items_difference_plan(
            rhs_trace.evaluated_item_sources,
            constraint.term,
            budget=budget,
            expanded=expanded,
        )
        if finite_lhs_plan.status != "unsupported":
            return finite_lhs_plan
        if not _term_is_false(constraint.term):
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
        rhs_sources: tuple[EvaluatedItemSource, ...],
        unevaluated_term: SchemaTerm | None,
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
        if not self.rhs.array_unevaluated_items_true_fragment_supported:
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
            rhs_term = _rhs_evaluated_item_term_for_index(rhs_sources, index, self)
            if rhs_term is None:
                if expanded and _term_is_false(unevaluated_term):
                    contains_obligation = (
                        self._expanded_contains_unevaluated_item_obligation(
                            index,
                            rhs_sources,
                        )
                    )
                    if contains_obligation is not None:
                        if self.problem is None:
                            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                                "SAT unevaluatedItems expanded proof requires "
                                "a proof context"
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
                if not _term_is_false(unevaluated_term):
                    obligations.append(
                        ArrayUnevaluatedItemObligation(
                            index,
                            self.lhs_item_term_at(index),
                            unevaluated_term,
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
                    index,
                    self.lhs_item_term_at(index),
                    rhs_term,
                )
            )

        if obligations:
            return ArrayUnevaluatedItemsDifferencePlan.obligation_plan(
                tuple(obligations)
            )
        return ArrayUnevaluatedItemsDifferencePlan.proved_true()

    def _conditioned_unevaluated_items_difference_plan(
        self,
        paths: tuple[EvaluationTracePath, ...],
        unevaluated_term: SchemaTerm | None,
    ) -> ArrayUnevaluatedItemsDifferencePlan:
        if self.problem is None:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems conditioned proof requires a proof context"
            )
        if not self.problem.context.allows_expensive_proof("evaluation_trace"):
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems conditioned proof requires endeavor mode"
            )
        if unevaluated_term is None:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems conditioned proof requires an unevaluated term"
            )
        if not self.rhs.array_unevaluated_items_true_fragment_supported:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems conditioned proof defers non-frontier "
                "right assertions"
            )

        lhs_length = self.lhs_length
        if lhs_length is None:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems conditioned proof requires exact left "
                "length facts"
            )
        if lhs_length.accepts_non_array:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems conditioned proof currently requires an "
                "array-only left schema"
            )
        upper_bound = self.array_length_upper_bound()
        if upper_bound is None:
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems conditioned proof requires a finite left "
                "length upper bound"
            )

        exhausted = self.problem.context.spend_work(
            _conditioned_item_product_work_units(self, paths, upper_bound),
            "evaluation trace",
            "evaluation trace exceeded proof work budget",
        )
        if exhausted is not None:
            return ArrayUnevaluatedItemsDifferencePlan.resource_exhausted(
                exhausted.reason or ""
            )
        if not _conditioned_item_paths_cover_lhs(
            self,
            paths,
            upper_bound,
            unevaluated_term,
            self.problem.context,
        ):
            return ArrayUnevaluatedItemsDifferencePlan.unsupported(
                "SAT unevaluatedItems conditioned proof requires typed selector "
                "coverage facts"
            )
        return ArrayUnevaluatedItemsDifferencePlan.proved_true()

    def _expanded_contains_unevaluated_item_obligation(
        self,
        index: int,
        rhs_sources: tuple[EvaluatedItemSource, ...],
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
            self.lhs_item_term_at(index),
            contains_sources[0].term,
        )

    def length_difference_plan(self, *, budget: int = -1) -> ArrayLengthDifferencePlan:
        lhs_shape = self.lhs_length
        rhs_shape = self.rhs_length
        if lhs_shape is None or rhs_shape is None:
            if lhs_shape is not None and rhs_shape is None:
                witness_plan = self._length_witness_plan_against_rhs_shape(
                    lhs_shape,
                    self.rhs_length_with_item_values,
                    budget=budget,
                )
                if witness_plan is not None:
                    return witness_plan
            if lhs_shape is None and (
                reason := self._lhs_exactness_unsupported_reason(
                    "array-length-lhs",
                    "SAT array length difference requires exact length shapes",
                )
            ):
                return ArrayLengthDifferencePlan.unsupported(reason)
            if rhs_shape is None and (
                reason := self._rhs_exactness_unsupported_reason(
                    "array-length-rhs",
                    "SAT array length difference requires exact length shapes",
                )
            ):
                return ArrayLengthDifferencePlan.unsupported(reason)
            return ArrayLengthDifferencePlan.unsupported(
                "SAT array length difference requires exact length shapes"
            )

        witness_plan = self._length_witness_plan_against_rhs_shape(
            lhs_shape,
            rhs_shape,
            budget=budget,
        )
        if witness_plan is not None:
            return witness_plan
        if lhs_shape.accepts_non_array:
            return ArrayLengthDifferencePlan.unsupported(
                "SAT array length true proof requires an array-only left schema"
            )
        if lhs_shape.is_subset_of(rhs_shape):
            if not rhs_shape.exact:
                if reason := self._rhs_exactness_unsupported_reason(
                    "array-length-rhs",
                    "SAT array length true proof requires exact right length semantics",
                ):
                    return ArrayLengthDifferencePlan.unsupported(reason)
                return ArrayLengthDifferencePlan.unsupported(
                    "SAT array length true proof requires exact right length semantics"
                )
            if not self._length_true_proof_covers_rhs_uniqueness():
                return ArrayLengthDifferencePlan.unsupported(
                    "SAT array length true proof cannot prove right uniqueItems"
                )
            return ArrayLengthDifferencePlan.proved_true()
        return ArrayLengthDifferencePlan.unsupported(
            "SAT array length difference could not construct a witness"
        )

    def _length_witness_plan_against_rhs_shape(
        self,
        lhs_shape: ArrayLengthConstraint,
        rhs_shape: ArrayLengthConstraint | None,
        *,
        budget: int,
    ) -> ArrayLengthDifferencePlan | None:
        if rhs_shape is None:
            return None
        if lhs_shape.accepts_non_array and not rhs_shape.accepts_non_array:
            return ArrayLengthDifferencePlan.literal_witness(
                "",
                rejected_reason=(
                    "SAT array non-array witness was rejected by concrete validation"
                ),
            )
        if lhs_shape.is_subset_of(rhs_shape):
            return None
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
        lhs_shape: ArrayLengthConstraint,
        rhs_shape: ArrayLengthConstraint,
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
            if not rhs_shape.exact:
                if reason := self._rhs_exactness_unsupported_reason(
                    "array-length-rhs",
                    "SAT array length symbolic true proof requires exact right "
                    "length semantics",
                ):
                    return ArrayLengthDifferencePlan.unsupported(reason)
                return ArrayLengthDifferencePlan.unsupported(
                    "SAT array length symbolic true proof requires exact right "
                    "length semantics"
                )
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
                self.lhs_contains.minimum,
                term=self.lhs_contains.term,
                ir=self.lhs,
                context=self.problem.context,
            )
            if contains_overrides is None or any(
                override.index >= skeleton.length for override in contains_overrides
            ):
                return None
            overrides.extend(contains_overrides)

        if self.lhs_contains is not None and self.lhs_contains.maximum is not None:
            matching_indexes = {override.index for override in overrides}
            for slot in skeleton.slots:
                if slot.index in matching_indexes:
                    continue
                values = _constructive_witness_values_excluding_terms(
                    slot.term,
                    skeleton.ir,
                    self.lhs_contains.term,
                    self.lhs,
                    self.problem.context,
                )
                if not values:
                    return None
                overrides.append(ArrayWitnessOverride(slot.index, values[0]))

        if (
            self.lhs_uniqueness is not None
            and self.lhs_uniqueness.guarantees_unique_items
        ):
            unique_overrides = _array_unique_overrides_for_skeleton(
                skeleton,
                self.problem.dialect,
                self.problem.context,
                tuple(overrides),
            )
            if unique_overrides is None:
                return None
            overrides = list(unique_overrides)

        return ArrayWitnessPlan(skeleton, tuple(overrides)) if overrides else None

    def minimum_contains_matches_guaranteed(
        self,
        contains: ArrayContainsConstraint,
        context: ProofContextProtocol,
    ) -> int | None:
        guaranteed = 0
        if self.lhs_contains is not None and _subschema_is_proved_by_terms(
            self.lhs_contains.term, self.lhs, contains.term, self.rhs, context
        ):
            guaranteed = max(guaranteed, self.lhs_contains.minimum)

        structural = self._minimum_structural_contains_matches(contains, context)
        if structural is not None:
            guaranteed = max(guaranteed, structural)
        return guaranteed

    def maximum_contains_matches_possible(
        self,
        contains: ArrayContainsConstraint,
        context: ProofContextProtocol,
    ) -> int | None:
        upper_bounds = []
        length_upper = self.array_length_upper_bound()
        if length_upper is not None:
            upper_bounds.append(length_upper)
        structural = self._maximum_structural_contains_matches(contains, context)
        if structural is not None:
            upper_bounds.append(structural)
        if (
            self.lhs_contains is not None
            and self.lhs_contains.maximum is not None
            and _subschema_is_proved_by_terms(
                contains.term, self.rhs, self.lhs_contains.term, self.lhs, context
            )
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

    def lhs_item_term_at(self, index: int) -> SchemaTerm | None:
        return _array_item_term_at(self.lhs_slots, self.lhs_tail, index)

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
                ArrayWitnessSlot(
                    index,
                    self.lhs_item_term_at(index),
                )
                for index in range(length)
            ),
            self.lhs,
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
            and self.lhs_contains.term is not None
            and _term_confirms_value(
                self.lhs_contains.term,
                self.lhs,
                value,
                self.problem.context,
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
                self.problem.context if self.problem is not None else None,
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
            _all_of_terms_available(
                (
                    self.lhs_item_term_at(first_index),
                    self.lhs_item_term_at(second_index),
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
        contains_term = lhs_contains.term
        return ArrayDuplicateWitnessPlan(
            skeleton,
            first_index,
            second_index,
            _all_of_terms_available(
                (
                    self.lhs_item_term_at(first_index),
                    self.lhs_item_term_at(second_index),
                    None if contains_term is None else SchemaTerm.not_(contains_term),
                )
            ),
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
        found, value = _concrete_witness_for_child_term(
            lhs_contains.term, self.lhs, self.problem.context
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
            self.lhs_tail.term,
        )

    def uniqueness_difference_plan(
        self, *, budget: int = -1
    ) -> ArrayUniquenessDifferencePlan:
        lhs_shape = self.lhs_uniqueness
        rhs_shape = self.rhs_uniqueness
        if rhs_shape is None:
            if reason := self._rhs_exactness_unsupported_reason(
                "array-uniqueness-rhs",
                "SAT array uniqueness difference requires exact uniqueness shapes",
            ):
                return ArrayUniquenessDifferencePlan.unsupported(reason)
            return ArrayUniquenessDifferencePlan.unsupported(
                "SAT array uniqueness difference requires exact uniqueness shapes"
            )
        if (
            lhs_shape is None
            and self.lhs.accepts_only_type("array")
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
            if reason := self._lhs_exactness_unsupported_reason(
                "array-uniqueness-lhs",
                "SAT array uniqueness difference requires exact uniqueness shapes",
            ):
                return ArrayUniquenessDifferencePlan.unsupported(reason)
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
            if lhs_shape.accepts_non_array:
                return ArrayUniquenessDifferencePlan.unsupported(
                    "SAT array uniqueness true proof cannot prove non-array values"
                )
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
            if lhs_shape.accepts_non_array:
                return ArrayUniquenessDifferencePlan.unsupported(
                    "SAT array uniqueness true proof cannot prove non-array values"
                )
            if not rhs_shape.complete_uniqueness_fragment:
                if reason := self._rhs_exactness_unsupported_reason(
                    "array-uniqueness-rhs",
                    "SAT array uniqueness true proof cannot prove right "
                    "non-uniqueness constraints",
                ):
                    return ArrayUniquenessDifferencePlan.unsupported(reason)
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
        context: ProofContextProtocol,
        *,
        budget: int = -1,
        expanded: bool = False,
    ) -> ArrayContainsDifferencePlan:
        rhs_contains = self.rhs_contains
        if rhs_contains is None:
            return ArrayContainsDifferencePlan.unsupported(
                "SAT array contains difference requires right contains constraint"
            )
        if not self.lhs.array_contains_fragment_constraint.lhs_supported:
            return ArrayContainsDifferencePlan.unsupported(
                "left schema is outside the SAT array contains fragment"
            )
        if not self.rhs.array_contains_fragment_constraint.rhs_supported:
            return ArrayContainsDifferencePlan.unsupported(
                "right schema is outside the SAT array contains fragment"
            )
        lhs_array_only = self.lhs.accepts_only_type("array")
        rhs_array_only = self.rhs.accepts_only_type("array")
        if not lhs_array_only or not rhs_array_only:
            return ArrayContainsDifferencePlan.unsupported(
                "SAT array contains difference requires array-only schemas"
            )

        if self.contains_empty_min_violation_possible(rhs_contains):
            return ArrayContainsDifferencePlan.literal_witness(
                [],
                rejected_reason="SAT array contains empty witness was rejected",
            )

        if self.lhs_contains is not None:
            contains_subproof = _subproof_terms_required(
                self.lhs_contains.term,
                self.lhs,
                rhs_contains.term,
                self.rhs,
                context,
            )
            if contains_subproof.status == "proved_false":
                return ArrayContainsDifferencePlan.literal_witness(
                    [contains_subproof.witness],
                    rejected_reason="SAT array contains schema witness was rejected",
                )

        lhs_min = self.minimum_contains_matches_guaranteed(rhs_contains, context)
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
                    min(length, lhs_min),
                    term=self.lhs_contains.term,
                    ir=self.lhs,
                    context=self.problem.context if self.problem is not None else None,
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
            lhs_max = self.maximum_contains_matches_possible(rhs_contains, context)
            max_proved = lhs_max is not None and lhs_max <= rhs_contains.maximum

        if min_proved and max_proved:
            return ArrayContainsDifferencePlan.proved_true()
        return ArrayContainsDifferencePlan.unsupported(
            "SAT array contains count bounds could not be proven exactly"
        )

    def _expanded_contains_min_violation_witness_plan_result(
        self,
        rhs_contains: ArrayContainsConstraint,
        context: ProofContextProtocol,
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
            lhs_contains.minimum,
            term=lhs_contains.term,
            ir=self.lhs,
            context=self.problem.context,
        )
        if overrides is None:
            return None, False
        return ArrayWitnessPlan(skeleton, overrides), False

    def _expanded_contains_max_violation_witness_plan_result(
        self,
        rhs_contains: ArrayContainsConstraint,
        context: ProofContextProtocol,
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
            length,
            term=lhs_contains.term,
            ir=self.lhs,
            context=self.problem.context,
        )
        if overrides is None:
            return None, False
        return ArrayWitnessPlan(skeleton, overrides), False

    def _contains_rhs_only_max_violation_witness_plan_result(
        self,
        rhs_contains: ArrayContainsConstraint,
        context: ProofContextProtocol,
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

        rhs_only_values = _constructive_witness_values_excluding_terms(
            rhs_contains.term,
            self.rhs,
            lhs_contains.term,
            self.lhs,
            context,
        )
        if not rhs_only_values:
            rhs_only_subproof = _subproof_terms_required(
                rhs_contains.term,
                self.rhs,
                lhs_contains.term,
                self.lhs,
                context,
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
            required_lhs_matches,
            distinct=distinct,
            term=lhs_contains.term,
            ir=self.lhs,
            context=context,
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
                skeleton, self.problem.dialect, context, overrides
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
                ArrayContainsItemProof(
                    index,
                    self.lhs_item_term_at(index),
                )
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
            return None
        return ArrayContainsMaxViolationPlan(
            length,
            tuple(
                ArrayContainsItemProof(
                    index,
                    self.lhs_item_term_at(index),
                )
                for index in range(target_matches)
            ),
            target_matches,
        )

    def contains_min_violation_witness_plan(
        self,
        rhs_contains: ArrayContainsConstraint,
        context: ProofContextProtocol,
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
        context: ProofContextProtocol,
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
                self.lhs,
                rhs_contains.term,
                self.rhs,
                context,
            )
            if unique_overrides is not None:
                return ArrayWitnessPlan(skeleton, unique_overrides), False

        matching = 0
        overrides = []
        for item_proof in plan.item_proofs:
            proof = _array_contains_item_subproof(
                self, item_proof, rhs_contains, context
            )
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
        context: ProofContextProtocol,
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
        context: ProofContextProtocol,
        *,
        budget: int = -1,
    ) -> tuple[ArrayWitnessPlan | None, bool]:
        plan = self.contains_max_violation_plan(rhs_contains)
        if plan is None:
            return None, False
        if budget >= 0 and plan.length > budget:
            return None, True
        if (
            self.lhs_contains is not None
            and self.lhs_contains.maximum is not None
            and plan.target_matches > self.lhs_contains.maximum
            and _subschema_is_proved_terms(
                self,
                rhs_contains.term,
                self.lhs_contains.term,
                context,
            )
        ):
            return None, False

        if all(_term_is_true(item_proof.lhs_term) for item_proof in plan.item_proofs):
            distinct = (
                self.lhs_uniqueness is not None
                and self.lhs_uniqueness.guarantees_unique_items
            )
            overrides = _array_contains_overrides_for_max_violation(
                plan.target_matches,
                distinct=distinct,
                term=rhs_contains.term,
                ir=self.rhs,
                context=self.problem.context if self.problem is not None else None,
            )
            if overrides is not None:
                skeleton = self.array_witness_skeleton(plan.length, budget=budget)
                if skeleton is None:
                    return None, budget >= 0 and plan.length > budget
                return ArrayWitnessPlan(skeleton, overrides), False

        for item_proof in plan.item_proofs:
            proof = _array_contains_item_subproof(
                self, item_proof, rhs_contains, context
            )
            if proof.status != "proved_true":
                return None, False

        skeleton = self.array_witness_skeleton(plan.length, budget=budget)
        if skeleton is None:
            return None, budget >= 0 and plan.length > budget
        return ArrayWitnessPlan(skeleton), False

    def has_rhs_item_value_constraints(self) -> bool:
        return any(not _term_is_true(slot.term) for slot in self.rhs_slots) or (
            self.rhs_tail is not None and not _term_is_true(self.rhs_tail.term)
        )

    def rhs_closed_tail_violation_length(self) -> int | None:
        if self.rhs_tail is None or not self.rhs_tail.closed:
            return None
        return self.first_lhs_length_reaching(self.rhs_tail.start_index)

    def item_value_obligations(self) -> tuple[ArrayItemValueObligation, ...]:
        obligations = []
        for slot in self.rhs_slots:
            if (
                _term_is_true(slot.term)
                or self.first_lhs_length_reaching(slot.index) is None
            ):
                continue
            obligations.append(
                ArrayItemValueObligation(
                    slot.index,
                    "rhs-slot",
                    self.lhs_item_term_at(slot.index),
                    slot.term,
                )
            )

        rhs_tail = self.rhs_tail
        if rhs_tail is None or rhs_tail.closed or _term_is_true(rhs_tail.term):
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
                    "lhs-slot-rhs-tail",
                    slot.term,
                    rhs_tail.term,
                )
            )

        unconstrained_index = self.first_lhs_unconstrained_index_under_rhs_tail(
            covered_slots
        )
        if unconstrained_index is not None:
            obligations.append(
                ArrayItemValueObligation(
                    unconstrained_index,
                    "lhs-unconstrained-rhs-tail",
                    SchemaTerm.true(),
                    rhs_tail.term,
                )
            )

        lhs_tail = self.lhs_tail
        if lhs_tail is not None and not lhs_tail.closed:
            tail_index = max(rhs_tail.start_index, lhs_tail.start_index)
            if self.first_lhs_length_reaching(tail_index) is not None:
                obligations.append(
                    ArrayItemValueObligation(
                        tail_index,
                        "lhs-tail-rhs-tail",
                        lhs_tail.term,
                        rhs_tail.term,
                    )
                )

        return tuple(obligations)

    def item_values_difference_plan(
        self,
        *,
        budget: int = -1,
    ) -> ArrayItemValuesDifferencePlan:
        lhs_fragment = self.lhs.array_item_values_fragment_constraint
        rhs_fragment = self.rhs.array_item_values_fragment_constraint
        if not lhs_fragment.lhs_supported:
            return ArrayItemValuesDifferencePlan.unsupported(
                "left schema is outside the SAT array item-values fragment"
            )
        if not rhs_fragment.rhs_witness_supported:
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
                return self._item_values_true_plan()
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
        return self._item_values_true_plan()

    def _item_values_true_plan(self) -> ArrayItemValuesDifferencePlan:
        if self.rhs.array_item_values_fragment_constraint.rhs_supported:
            return ArrayItemValuesDifferencePlan.proved_true()
        return ArrayItemValuesDifferencePlan.unsupported(
            "right schema is outside the SAT array item-values true fragment"
        )

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
        contains: ArrayContainsConstraint,
        context: ProofContextProtocol,
    ) -> int | None:
        minimum_items = self.array_length_lower_bound()
        if minimum_items is None:
            return None

        guaranteed = 0
        slots = {slot.index: slot for slot in self.lhs_slots}
        for index in range(minimum_items):
            slot = slots.get(index)
            if slot is not None:
                if _subschema_is_proved_by_terms(
                    slot.term, self.lhs, contains.term, self.rhs, context
                ):
                    guaranteed += 1
                continue

            if self.lhs_tail is None or self.lhs_tail.closed:
                continue
            if _subschema_is_proved_by_terms(
                self.lhs_tail.term, self.lhs, contains.term, self.rhs, context
            ):
                guaranteed += 1
        return guaranteed

    def _maximum_structural_contains_matches(
        self,
        contains: ArrayContainsConstraint,
        context: ProofContextProtocol,
    ) -> int | None:
        finite_tail_upper = self._finite_tail_structural_contains_upper_bound(
            contains, context
        )
        if finite_tail_upper is not None:
            return finite_tail_upper

        maximum_items = self.array_length_upper_bound()
        if maximum_items is None:
            return None
        budget = context.default_search_horizon
        if budget >= 0 and maximum_items > budget:
            return None

        non_matching_term = (
            None if contains.term is None else SchemaTerm.not_(contains.term)
        )
        possible = 0
        for index in range(maximum_items):
            if self.first_lhs_length_reaching(index) is None:
                continue
            item_term = self.lhs_item_term_at(index)
            if _subschema_is_proved_by_terms(
                item_term, self.lhs, non_matching_term, self.rhs, context
            ):
                continue
            possible += 1
        return possible

    def _finite_tail_structural_contains_upper_bound(
        self,
        contains: ArrayContainsConstraint,
        context: ProofContextProtocol,
    ) -> int | None:
        lhs_tail = self.lhs_tail
        if lhs_tail is None:
            return None

        non_matching_term = (
            None if contains.term is None else SchemaTerm.not_(contains.term)
        )
        if not lhs_tail.closed and not _subschema_is_proved_by_terms(
            lhs_tail.term, self.lhs, non_matching_term, self.rhs, context
        ):
            return None

        possible = 0
        for index in range(lhs_tail.start_index):
            if self.first_lhs_length_reaching(index) is None:
                continue
            item_term = self.lhs_item_term_at(index)
            if _subschema_is_proved_by_terms(
                item_term, self.lhs, non_matching_term, self.rhs, context
            ):
                continue
            possible += 1
        return possible


def _subproof_terms_required(
    lhs_term: SchemaTerm | None,
    lhs_ir: LogicalSchemaIR,
    rhs_term: SchemaTerm | None,
    rhs_ir: LogicalSchemaIR,
    context: ProofContextProtocol,
) -> ProofResult:
    if lhs_term is None or rhs_term is None:
        return ProofResult.unsupported("array child proof requires schema terms")
    return context.subproof_terms(lhs_term, lhs_ir, rhs_term, rhs_ir)


def _subschema_is_proved_by_terms(
    lhs_term: SchemaTerm | None,
    lhs_ir: LogicalSchemaIR,
    rhs_term: SchemaTerm | None,
    rhs_ir: LogicalSchemaIR,
    context: ProofContextProtocol,
) -> bool | None:
    if lhs_term is None or rhs_term is None:
        return None
    proof = context.subproof_terms(lhs_term, lhs_ir, rhs_term, rhs_ir)
    if proof.status == "unsupported":
        return None
    return proof.status == "proved_true"


def _subschema_is_proved_terms(
    model: ArrayDifferenceModel,
    lhs_term: SchemaTerm | None,
    rhs_term: SchemaTerm | None,
    context: ProofContextProtocol,
) -> bool:
    if model.problem is None:
        return False
    return (
        _subschema_is_proved_by_terms(
            lhs_term, model.lhs, rhs_term, model.rhs, context
        )
        is True
    )


def _array_contains_item_subproof(
    model: ArrayDifferenceModel,
    item_proof: ArrayContainsItemProof,
    rhs_contains: ArrayContainsConstraint,
    context: ProofContextProtocol,
) -> ProofResult:
    if item_proof.lhs_term is None or rhs_contains.term is None:
        return ProofResult.unsupported(
            "array contains item proof requires schema terms"
        )
    return context.subproof_terms(
        item_proof.lhs_term,
        model.lhs,
        rhs_contains.term,
        model.rhs,
    )


def _rhs_evaluation_trace(
    lhs: LogicalSchemaIR,
    rhs: LogicalSchemaIR,
    problem: DifferenceProblemProtocol | None,
) -> EvaluationTraceExpression:
    return evaluation_trace_for_node(
        rhs.root,
        rhs,
        lhs_term=lhs.root_term,
        lhs_ir=lhs,
        context=None if problem is None else problem.context,
    )


def _conditioned_item_paths_cover_lhs(
    model: ArrayDifferenceModel,
    paths: tuple[EvaluationTracePath, ...],
    upper_bound: int,
    unevaluated_term: SchemaTerm,
    context: ProofContextProtocol,
) -> bool:
    for candidate in model.lhs.semantics.array_selector_candidates:
        lhs_values = inhabited_finite_values_for_term(
            candidate.term,
            model.lhs,
            context,
        )
        if not lhs_values:
            continue
        if _conditioned_item_paths_cover_lhs_selector(
            model,
            paths,
            upper_bound,
            unevaluated_term,
            candidate.index,
            tuple(lhs_values),
            context,
        ):
            return True
    return False


def _conditioned_item_product_work_units(
    model: ArrayDifferenceModel,
    paths: tuple[EvaluationTracePath, ...],
    upper_bound: int,
) -> int:
    candidates = len(model.lhs.semantics.array_selector_candidates)
    reachable_indexes = sum(
        1
        for index in range(upper_bound)
        if model.first_lhs_length_reaching(index) is not None
    )
    return max(1, candidates) * max(1, len(paths)) * max(1, reachable_indexes)


def _conditioned_item_paths_cover_lhs_selector(
    model: ArrayDifferenceModel,
    paths: tuple[EvaluationTracePath, ...],
    upper_bound: int,
    unevaluated_term: SchemaTerm,
    selector_index: int,
    lhs_values: tuple[Any, ...],
    context: ProofContextProtocol,
) -> bool:
    uncovered = {json_semantic_key(value) for value in lhs_values}
    if not uncovered:
        return False
    for path in paths:
        selector_term = _rhs_evaluated_item_term_for_index(
            path.item_sources, selector_index, model
        )
        if selector_term is None:
            return False
        branch_values = inhabited_finite_values_for_term(
            selector_term,
            model.rhs,
            context,
        )
        if not branch_values:
            return False
        branch_keys = {json_semantic_key(value) for value in branch_values}
        if not _conditioned_array_path_uses_supported_branch_shape(
            path,
            model.rhs,
            selector_index,
            tuple(branch_values),
            context,
        ):
            return False
        uncovered -= branch_keys
        if not _conditioned_item_path_covers_lhs_horizon(
            model,
            path,
            upper_bound,
            unevaluated_term,
            selector_index,
            context,
        ):
            return False
    return not uncovered


def _conditioned_item_path_covers_lhs_horizon(
    model: ArrayDifferenceModel,
    path: EvaluationTracePath,
    upper_bound: int,
    unevaluated_term: SchemaTerm,
    selector_index: int,
    context: ProofContextProtocol,
) -> bool:
    if not _evaluated_item_sources_are_supported(path.item_sources):
        return False
    for index in range(upper_bound):
        if model.first_lhs_length_reaching(index) is None:
            continue
        rhs_term = _rhs_evaluated_item_term_for_index(path.item_sources, index, model)
        if rhs_term is None:
            rhs_term = unevaluated_term
        if index != selector_index:
            proof = _subproof_terms_required(
                model.lhs_item_term_at(index),
                model.lhs,
                rhs_term,
                model.rhs,
                context,
            )
            if proof.status != "proved_true":
                return False
    return True


def _conditioned_array_path_uses_supported_branch_shape(
    path: EvaluationTracePath,
    ir: LogicalSchemaIR,
    selector_index: int,
    branch_values: tuple[Any, ...],
    context: ProofContextProtocol,
) -> bool:
    node = _condition_node(path.condition, ir)
    if node is None:
        return _negated_condition_excludes_array_selector_values(
            path.condition,
            ir,
            selector_index,
            branch_values,
            context,
        )
    return _array_condition_shape_is_supported(node)


def _negated_condition_excludes_array_selector_values(
    condition: SchemaTerm,
    ir: LogicalSchemaIR,
    selector_index: int,
    branch_values: tuple[Any, ...],
    context: ProofContextProtocol,
) -> bool:
    if condition.kind != "not" or len(condition.children) != 1:
        return False
    node = _condition_node(condition.children[0], ir)
    if node is None or not _array_condition_shape_is_supported(node):
        return False
    item_model = node.semantics.array_item_model_constraint
    if item_model is None:
        return False
    for index, term in enumerate(item_model.prefix_terms):
        if index != selector_index and not _term_is_true(term):
            return False
    condition_term = item_model.term_at_index(selector_index)
    if condition_term is None:
        return False
    condition_values = inhabited_finite_values_for_term(
        condition_term,
        ir,
        context,
    )
    if not condition_values:
        return False
    condition_keys = {json_semantic_key(value) for value in condition_values}
    branch_keys = {json_semantic_key(value) for value in branch_values}
    return branch_keys.isdisjoint(condition_keys)


def _condition_node(condition: SchemaTerm, ir: LogicalSchemaIR) -> SchemaNode | None:
    if condition.kind != "node" or condition.ref is None:
        return None
    return ir.node_for_ref(condition.ref)


def _array_condition_shape_is_supported(node: SchemaNode) -> bool:
    return node.semantics.vocabulary.semantic_keywords <= {"prefixItems", "type"}


def _evaluated_item_sources_are_supported(
    sources: tuple[EvaluatedItemSource, ...],
) -> bool:
    return all(
        (
            source.kind in {"additionalItems", "items", "prefixItems"}
            and (source.index is not None or source.start_index is not None)
        )
        or (source.kind == "contains" and source.marks_contains_matches)
        for source in sources
    )


def _rhs_evaluated_item_term_for_index(
    sources: tuple[EvaluatedItemSource, ...],
    index: int,
    model: ArrayDifferenceModel | None = None,
) -> SchemaTerm | None:
    terms = [
        source.term
        for source in sources
        if source.term is not None
        and _rhs_evaluates_item_source_index(source, index, model)
    ]
    if not terms:
        return None
    return SchemaTerm.all_of(tuple(terms))


def _rhs_evaluates_item_source_index(
    source: EvaluatedItemSource,
    index: int,
    model: ArrayDifferenceModel | None = None,
) -> bool:
    if _term_is_false(source.term):
        return False
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
    return _subschema_is_proved_terms(
        model,
        model.lhs_item_term_at(index),
        source.term,
        model.problem.context,
    )


def _first_rhs_unevaluated_item_index_reachable(
    model: ArrayDifferenceModel,
    rhs_sources: tuple[EvaluatedItemSource, ...],
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
        if _rhs_evaluated_item_term_for_index(rhs_sources, index, model) is None:
            return index
    return None


def _first_unevaluated_item_probe_limit(
    sources: tuple[EvaluatedItemSource, ...],
) -> int:
    indexes = [source.index for source in sources if isinstance(source.index, int)]
    starts = [
        source.start_index for source in sources if isinstance(source.start_index, int)
    ]
    return max([*indexes, *starts, 0]) + 2


def _all_of_terms_available(terms: tuple[SchemaTerm | None, ...]) -> SchemaTerm | None:
    if any(term is None for term in terms):
        return None
    meaningful = []
    for term in terms:
        if term is None:
            continue
        if term.kind == "false":
            return SchemaTerm.false()
        if term.kind == "true":
            continue
        meaningful.append(term)
    return SchemaTerm.all_of(tuple(meaningful))


def _term_is_true(term: SchemaTerm | None) -> bool:
    return term is not None and term.kind == "true"


def _term_is_false(term: SchemaTerm | None) -> bool:
    return term is not None and term.kind == "false"


def _array_slots(ir: LogicalSchemaIR) -> tuple[ArraySlot, ...]:
    item_model = ir.array_item_model_constraint
    slots = [
        ArraySlot(
            source.index,
            source.kind,
            None if item_model is None else item_model.term_at_index(source.index),
        )
        for source in ir.evaluation.item_sources
        if source.index is not None
    ]
    return tuple(sorted(slots, key=lambda slot: slot.index))


def _array_tail(ir: LogicalSchemaIR) -> ArrayTail | None:
    item_model = ir.array_item_model_constraint
    tails = [
        ArrayTail(
            source.start_index,
            source.kind,
            None
            if item_model is None
            else item_model.term_at_index(source.start_index),
        )
        for source in ir.evaluation.item_sources
        if source.start_index is not None
    ]
    if not tails:
        return None
    return sorted(tails, key=lambda tail: tail.start_index)[-1]


def _array_item_term_at(
    slots: tuple[ArraySlot, ...], tail: ArrayTail | None, index: int
) -> SchemaTerm | None:
    for slot in slots:
        if slot.index == index:
            return slot.term
    if tail is not None and index >= tail.start_index:
        return tail.term
    return SchemaTerm.true()


def _ir_rooted_at_term(term: SchemaTerm | None, ir: LogicalSchemaIR) -> LogicalSchemaIR:
    if term is None or term.kind != "node" or term.ref is None:
        return ir
    node = ir.node_for_ref(term.ref)
    if node is None or not node.semantics.has_static_reference_boundary:
        return ir
    return ir.with_root(node)


def _array_length_shape_allows(shape: ArrayLengthConstraint, length: int) -> bool:
    return any(
        interval.lower <= length
        and (interval.upper is None or length <= interval.upper)
        for interval in shape.normalized_intervals()
    )


def _array_length_shape_symbolic_expr(
    shape: ArrayLengthConstraint, length: Any, solver: SymbolicSolver
) -> Any:
    return solver.or_(
        *(
            _closed_nonnegative_interval_symbolic_expr(
                interval.lower, interval.upper, length, solver
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

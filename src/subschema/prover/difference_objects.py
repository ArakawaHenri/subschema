"""
Object difference models and witness materialization.
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
    ObjectClosedPropertiesConstraint,
    ObjectKeyValueConstraint,
    ObjectKeyValuePattern,
    ObjectKeyValueWitnessSkeleton,
    ObjectKeyValueWitnessSlot,
    ObjectPresenceProductConstraint,
    ObjectPropertyCountConstraint,
    ObjectPropertyNamesConstraint,
    ObjectPropertyValuesConstraint,
    type_atom_witness,
)
from subschema.ir.evaluation import (
    EvaluatedPropertySource,
    EvaluationTraceExpression,
    EvaluationTracePath,
)
from subschema.ir.terms import SchemaTerm
from subschema.prover.evaluation_traces import evaluation_trace_for_node
from subschema.prover.finite import inhabited_finite_values_for_term
from subschema.prover.protocols import (
    DifferenceProblemProtocol,
    ProofContextProtocol,
)
from subschema.prover.witnesses import build_term_witness
from subschema.regex import RegexLanguage
from subschema.symbolic import SAT, UNSAT, SymbolicSolver
from subschema.values import json_semantic_key

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
    "conditioned_obligations",
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
OBJECT_KEY_VALUE_LHS_KEYSPACE_PARTITION = ("keyspace", "lhs")
OBJECT_KEY_VALUE_RHS_KEYSPACE_PARTITION = ("keyspace", "rhs")
_OBJECT_TRUE_PROOF_NON_OBJECT_REASON = (
    "SAT object true proof cannot prove non-object values"
)


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


def _object_true_proof_blocked_by_non_object_lhs(shape: Any) -> bool:
    return bool(getattr(shape, "accepts_non_object", False))


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
    lhs_term: SchemaTerm | None = None
    rhs_term: SchemaTerm | None = None


@dataclass(frozen=True)
class ObjectPropertyValueWitnessSlot:
    name: str
    term: SchemaTerm | None = None


@dataclass(frozen=True)
class ObjectPropertyValueWitnessSkeleton:
    slots: tuple[ObjectPropertyValueWitnessSlot, ...]
    ir: LogicalSchemaIR | None = None


def materialize_object_property_value_witness_skeleton(
    skeleton: ObjectPropertyValueWitnessSkeleton | None,
    dialect: Dialect,
    *,
    override: tuple[str, Any] | None = None,
    context: ProofContextProtocol | None = None,
) -> dict[str, Any] | None:
    if skeleton is None:
        return None

    witness = {}
    for slot in skeleton.slots:
        if override is not None and slot.name == override[0]:
            witness[slot.name] = override[1]
            continue
        found, value = _concrete_witness_for_child_term(
            slot.term, skeleton.ir, context
        )
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
    original_value: Any
    term: SchemaTerm | None = None


@dataclass(frozen=True)
class ObjectPropertyNamesRepairSkeleton:
    slots: tuple[ObjectPropertyNamesRepairSlot, ...]
    ir: LogicalSchemaIR | None = None


def materialize_object_property_names_repair_skeleton(
    skeleton: ObjectPropertyNamesRepairSkeleton | None,
    dialect: Dialect,
    *,
    context: ProofContextProtocol | None = None,
) -> dict[str, Any] | None:
    if skeleton is None:
        return None

    repaired = {}
    for slot in skeleton.slots:
        found, replacement = _concrete_witness_for_child_term(
            slot.term, skeleton.ir, context
        )
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
    lhs_term: SchemaTerm | None = None
    rhs_term: SchemaTerm | None = None


@dataclass(frozen=True)
class ClosedObjectWitnessSlot:
    name: str
    term: SchemaTerm | None = None


@dataclass(frozen=True)
class ClosedObjectWitnessSkeleton:
    slots: tuple[ClosedObjectWitnessSlot, ...]
    ir: LogicalSchemaIR | None = None


def materialize_closed_object_witness_skeleton(
    skeleton: ClosedObjectWitnessSkeleton | None,
    dialect: Dialect,
    *,
    override: tuple[str, Any] | dict[str, Any] | None = None,
    context: ProofContextProtocol | None = None,
) -> dict[str, Any] | None:
    if skeleton is None:
        return None
    overrides = _object_witness_overrides(override)
    witness = {}
    for slot in skeleton.slots:
        if slot.name in overrides:
            witness[slot.name] = overrides[slot.name]
            continue
        found, value = _concrete_witness_for_child_term(
            slot.term, skeleton.ir, context
        )
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
            return type_atom_witness(self.atom)
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
class ObjectKeyValueObligation:
    name: str
    lhs_term: SchemaTerm | None = None
    rhs_term: SchemaTerm | None = None


def materialize_object_key_value_witness_skeleton(
    skeleton: ObjectKeyValueWitnessSkeleton | None,
    dialect: Dialect,
    *,
    override: tuple[str, Any] | None = None,
    context: ProofContextProtocol | None = None,
    ir: LogicalSchemaIR | None = None,
) -> dict[str, Any] | None:
    if skeleton is None:
        return None

    witness = {}
    for slot in skeleton.slots:
        if override is not None and slot.name == override[0]:
            witness[slot.name] = override[1]
            continue
        if slot.has_literal_value:
            witness[slot.name] = slot.literal_value
            continue
        found, value = _concrete_witness_for_child_term(slot.term, ir, context)
        if not found:
            return None
        witness[slot.name] = value
    return witness


def _concrete_witness_for_child_term(
    term: SchemaTerm | None,
    ir: LogicalSchemaIR | None,
    context: ProofContextProtocol | None,
) -> tuple[bool, Any]:
    if term is None or ir is None or context is None:
        return False, None
    result = build_term_witness(term, ir, context)
    return result.has_witness, result.witness


def _object_value_term_is_true(term: SchemaTerm | None) -> bool:
    return term is None or term.kind == "true"


def _object_value_term_is_false(term: SchemaTerm | None) -> bool:
    return term is not None and term.kind == "false"


def _term_is_false(term: SchemaTerm | None) -> bool:
    return term is not None and term.kind == "false"


def _ir_rooted_at_term(term: SchemaTerm | None, ir: LogicalSchemaIR) -> LogicalSchemaIR:
    if term is None or term.kind != "node" or term.ref is None:
        return ir
    node = ir.node_for_ref(term.ref)
    if node is None or not node.semantics.has_static_reference_boundary:
        return ir
    return ir.with_root(node)


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
    witness_skeleton: ObjectKeyValueWitnessSkeleton | None
    lhs_term: SchemaTerm | None = None
    rhs_term: SchemaTerm | None = None


@dataclass(frozen=True)
class ObjectUnevaluatedPropertiesDifferencePlan:
    status: ObjectUnevaluatedPropertiesPlanStatus
    reason: str = ""
    rejected_reason: str = ""
    witness: Any | None = None
    witness_skeletons: tuple[ObjectKeyValueWitnessSkeleton, ...] = ()
    obligations: tuple[ObjectUnevaluatedPropertyObligation, ...] = ()
    conditioned_paths: tuple[EvaluationTracePath, ...] = ()
    unsupported_priority: int = 0

    @classmethod
    def proved_true(cls) -> ObjectUnevaluatedPropertiesDifferencePlan:
        return cls("proved_true")

    @classmethod
    def unsupported(
        cls, reason: str, *, unsupported_priority: int = 0
    ) -> ObjectUnevaluatedPropertiesDifferencePlan:
        return cls(
            "unsupported", reason=reason, unsupported_priority=unsupported_priority
        )

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

    @classmethod
    def conditioned_obligation_plan(
        cls,
        paths: tuple[EvaluationTracePath, ...],
        *,
        reason: str,
    ) -> ObjectUnevaluatedPropertiesDifferencePlan:
        return cls(
            "conditioned_obligations",
            reason=reason,
            conditioned_paths=paths,
            unsupported_priority=10,
        )


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
    problem: DifferenceProblemProtocol | None = None
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
    def from_problem(cls, problem: DifferenceProblemProtocol) -> ObjectDifferenceModel:
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
    def lhs_property_count(self) -> ObjectPropertyCountConstraint | None:
        return (
            self.lhs_property_count_constraint
            or _object_property_count_constraint(
                self._lhs_constraint("object-property-count")
            )
            or self.lhs.semantics.object_property_count_constraint
        )

    @cached_property
    def rhs_property_count(self) -> ObjectPropertyCountConstraint | None:
        return (
            self.rhs_property_count_constraint
            or _object_property_count_constraint(
                self._rhs_constraint("object-property-count")
            )
            or self.rhs.semantics.object_property_count_constraint
        )

    def property_count_difference_plan(self) -> ObjectPropertyCountDifferencePlan:
        lhs_shape = self.lhs_property_count
        rhs_shape = self.rhs_property_count
        if lhs_shape is None or rhs_shape is None:
            if lhs_shape is None and (
                reason := self._lhs_exactness_unsupported_reason(
                    "object-property-count",
                    "SAT object property-count difference requires exact count shapes",
                )
            ):
                return ObjectPropertyCountDifferencePlan.unsupported(reason)
            if rhs_shape is None and (
                reason := self._rhs_exactness_unsupported_reason(
                    "object-property-count",
                    "SAT object property-count difference requires exact count shapes",
                )
            ):
                return ObjectPropertyCountDifferencePlan.unsupported(reason)
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
            if lhs_shape.accepts_non_object:
                return ObjectPropertyCountDifferencePlan.unsupported(
                    "SAT object property-count true proof cannot prove non-object "
                    "values"
                )
            if not rhs_shape.exact:
                if reason := self._rhs_exactness_unsupported_reason(
                    "object-property-count",
                    "SAT object property-count true proof requires exact right "
                    "count semantics",
                ):
                    return ObjectPropertyCountDifferencePlan.unsupported(reason)
                return ObjectPropertyCountDifferencePlan.unsupported(
                    "SAT object property-count true proof requires exact right "
                    "count semantics"
                )
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
        lhs_shape: ObjectPropertyCountConstraint,
        rhs_shape: ObjectPropertyCountConstraint,
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
            if lhs_shape.accepts_non_object:
                return ObjectPropertyCountDifferencePlan.unsupported(
                    "SAT object property-count true proof cannot prove non-object "
                    "values"
                )
            if not rhs_shape.exact:
                if reason := self._rhs_exactness_unsupported_reason(
                    "object-property-count",
                    "SAT object property-count true proof requires exact right "
                    "count semantics",
                ):
                    return ObjectPropertyCountDifferencePlan.unsupported(reason)
                return ObjectPropertyCountDifferencePlan.unsupported(
                    "SAT object property-count true proof requires exact right "
                    "count semantics"
                )
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
        if _object_key_value_allows_unrestricted_keys(lhs_shape):
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
    def lhs_property_values(self) -> ObjectPropertyValuesConstraint | None:
        return (
            self.lhs_property_values_constraint
            or _object_property_values_constraint(
                self._lhs_constraint("object-property-values")
            )
            or self.lhs.semantics.object_property_values_constraint
        )

    @cached_property
    def rhs_property_values(self) -> ObjectPropertyValuesConstraint | None:
        return (
            self.rhs_property_values_constraint
            or _object_property_values_constraint(
                self._rhs_constraint("object-property-values")
            )
            or self.rhs.semantics.object_property_values_constraint
        )

    @cached_property
    def lhs_closed_properties(self) -> ObjectClosedPropertiesConstraint | None:
        return (
            self.lhs_closed_properties_constraint
            or _object_closed_properties_constraint(
                self._lhs_constraint("object-closed-properties")
            )
            or self.lhs.semantics.object_closed_properties_constraint
        )

    @cached_property
    def rhs_closed_properties(self) -> ObjectClosedPropertiesConstraint | None:
        return (
            self.rhs_closed_properties_constraint
            or _object_closed_properties_constraint(
                self._rhs_constraint("object-closed-properties")
            )
            or self.rhs.semantics.object_closed_properties_constraint
        )

    @cached_property
    def lhs_property_names(self) -> ObjectPropertyNamesConstraint | None:
        return (
            self.lhs_property_names_constraint
            or _object_property_names_constraint(
                self._lhs_constraint("object-property-names")
            )
            or self.lhs.semantics.object_property_names_constraint
        )

    @cached_property
    def rhs_property_names(self) -> ObjectPropertyNamesConstraint | None:
        return (
            self.rhs_property_names_constraint
            or _object_property_names_constraint(
                self._rhs_constraint("object-property-names")
            )
            or self.rhs.semantics.object_property_names_constraint
        )

    @cached_property
    def lhs_key_values(self) -> ObjectKeyValueConstraint | None:
        return self.lhs.object_key_value_constraint

    @cached_property
    def rhs_key_values(self) -> ObjectKeyValueConstraint | None:
        return self.rhs.object_key_value_constraint

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
        rhs_trace = _rhs_evaluation_trace(self.lhs, self.rhs, self.problem)
        if rhs_trace.is_resource_exhausted:
            return ObjectUnevaluatedPropertiesDifferencePlan.resource_exhausted(
                rhs_trace.resource_exhausted_reason
            )
        if not rhs_trace.is_supported:
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                rhs_trace.unsupported_reason,
                unsupported_priority=rhs_trace.unsupported_priority,
            )
        if rhs_trace.has_conditioned_paths:
            conditioned_plan = self._conditioned_unevaluated_properties_difference_plan(
                rhs_trace.paths,
                constraint.term,
            )
            if conditioned_plan.status != "unsupported":
                return conditioned_plan
            return (
                ObjectUnevaluatedPropertiesDifferencePlan.conditioned_obligation_plan(
                    rhs_trace.paths,
                    reason=(
                        "SAT unevaluatedProperties difference defers "
                        "branch-conditioned evaluation trace paths"
                    ),
                )
            )
        rhs_property_sources = _supported_evaluated_property_sources(
            rhs_trace.evaluated_property_sources,
            constraint.term,
        )
        if rhs_property_sources is None:
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
            if _object_true_proof_blocked_by_non_object_lhs(lhs_shape):
                return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                    _OBJECT_TRUE_PROOF_NON_OBJECT_REASON
                )
            return ObjectUnevaluatedPropertiesDifferencePlan.proved_true()

        closed_lhs_plan = self._closed_lhs_unevaluated_properties_difference_plan(
            lhs_shape,
            rhs_property_sources,
            constraint.term,
        )
        if closed_lhs_plan.status != "unsupported":
            return closed_lhs_plan
        if not _term_is_false(constraint.term):
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT schema-valued unevaluatedProperties witness requires a "
                "finite closed left keyspace",
                unsupported_priority=10,
            )

        witness_name = _unevaluated_property_witness_name(
            lhs_shape,
            rhs_property_sources,
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
        lhs_shape: ObjectKeyValueConstraint,
        rhs_sources: tuple[EvaluatedPropertySource, ...],
        unevaluated_term: SchemaTerm | None,
    ) -> ObjectUnevaluatedPropertiesDifferencePlan:
        if lhs_shape.patterns or not _object_value_term_is_false(
            lhs_shape.additional_term
        ):
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties true proof requires a finite "
                "closed left keyspace"
            )
        if not self.rhs.object_unevaluated_properties_true_fragment_supported:
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties true proof defers non-frontier "
                "right assertions"
            )

        obligations = []
        for name in sorted(lhs_shape.properties):
            if not lhs_shape.allows_key(name):
                continue
            skeleton = lhs_shape.witness_skeleton(name)
            rhs_term = _rhs_evaluated_property_term_for_name(rhs_sources, name)
            if rhs_term is None:
                if not _term_is_false(unevaluated_term):
                    obligations.append(
                        ObjectUnevaluatedPropertyObligation(
                            name,
                            skeleton,
                            lhs_shape.value_term_for(name),
                            unevaluated_term,
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
                    skeleton,
                    lhs_shape.value_term_for(name),
                    rhs_term,
                )
            )

        if obligations:
            return ObjectUnevaluatedPropertiesDifferencePlan.obligation_plan(
                tuple(obligations)
            )
        if _object_true_proof_blocked_by_non_object_lhs(lhs_shape):
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                _OBJECT_TRUE_PROOF_NON_OBJECT_REASON
            )
        return ObjectUnevaluatedPropertiesDifferencePlan.proved_true()

    def _conditioned_unevaluated_properties_difference_plan(
        self,
        paths: tuple[EvaluationTracePath, ...],
        unevaluated_term: SchemaTerm | None,
    ) -> ObjectUnevaluatedPropertiesDifferencePlan:
        if self.problem is None:
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties conditioned proof requires a proof context"
            )
        if not self.problem.context.allows_expensive_proof("evaluation_trace"):
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties conditioned proof requires endeavor mode"
            )
        if unevaluated_term is None:
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties conditioned proof requires an "
                "unevaluated term"
            )
        if not self.rhs.object_unevaluated_properties_true_fragment_supported:
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties conditioned proof defers non-frontier "
                "right assertions"
            )

        lhs_shape = self.lhs_key_values
        if lhs_shape is None:
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties conditioned proof requires local left "
                "object shape"
            )
        if lhs_shape.accepts_non_object:
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties conditioned proof currently requires an "
                "object-only left schema"
            )
        if lhs_shape.patterns or not _object_value_term_is_false(
            lhs_shape.additional_term
        ):
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties conditioned proof requires a finite "
                "closed left keyspace"
            )

        exhausted = self.problem.context.spend_work(
            _conditioned_property_product_work_units(self, paths, lhs_shape),
            "evaluation trace",
            "evaluation trace exceeded proof work budget",
        )
        if exhausted is not None:
            return ObjectUnevaluatedPropertiesDifferencePlan.resource_exhausted(
                exhausted.reason or ""
            )
        if not _conditioned_property_paths_cover_lhs(
            self,
            paths,
            lhs_shape,
            unevaluated_term,
            self.problem.context,
        ):
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                "SAT unevaluatedProperties conditioned proof requires typed "
                "selector coverage facts"
            )
        if _object_true_proof_blocked_by_non_object_lhs(lhs_shape):
            return ObjectUnevaluatedPropertiesDifferencePlan.unsupported(
                _OBJECT_TRUE_PROOF_NON_OBJECT_REASON
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
        context: ProofContextProtocol | None = None,
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
                _schema_or_term_has_static_reference_boundary(
                    lhs_closed.property_term_for(item),
                    self.lhs,
                ),
                _schema_or_term_has_static_reference_boundary(
                    rhs_closed.property_term_for(item),
                    self.rhs,
                ),
                item,
            ),
        ):
            rhs_term = rhs_closed.property_term_for(name)
            if not _object_value_term_is_true(rhs_term):
                obligations.append(
                    ClosedObjectValueObligation(
                        name,
                        lhs_closed.property_term_for(name),
                        rhs_term,
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
                    name,
                    self.lhs_closed_properties.property_term_for(name),
                )
                for name in sorted(names)
            ),
            self.lhs,
        )

    def closed_object_witness_skeleton_for_names(
        self,
        names: frozenset[str],
    ) -> ClosedObjectWitnessSkeleton | None:
        if self.lhs_closed_properties is None:
            return None
        all_names = set(self.lhs_closed_properties.required) | set(names)
        if not all(
            self.lhs_closed_properties.keyspace_accepts(name) for name in all_names
        ):
            return None
        return ClosedObjectWitnessSkeleton(
            tuple(
                ClosedObjectWitnessSlot(
                    name,
                    self.lhs_closed_properties.property_term_for(name),
                )
                for name in sorted(all_names)
            ),
            self.lhs,
        )

    def closed_object_difference_plan(
        self, context: ProofContextProtocol | None = None
    ) -> ClosedObjectDifferencePlan:
        lhs_shape = self.lhs_closed_properties
        rhs_shape = self.rhs_closed_properties
        if lhs_shape is None or rhs_shape is None:
            if lhs_shape is None and (
                reason := self._lhs_exactness_unsupported_reason(
                    "object-closed-properties",
                    "SAT closed-object difference requires exact closed-property "
                    "shapes",
                )
            ):
                return ClosedObjectDifferencePlan.unsupported(reason)
            if rhs_shape is None and (
                reason := self._rhs_exactness_unsupported_reason(
                    "object-closed-properties",
                    "SAT closed-object difference requires exact closed-property "
                    "shapes",
                )
            ):
                return ClosedObjectDifferencePlan.unsupported(reason)
            return ClosedObjectDifferencePlan.unsupported(
                "SAT closed-object difference requires exact closed-property shapes"
            )

        if lhs_shape.accepts_non_object and not rhs_shape.accepts_non_object:
            return ClosedObjectDifferencePlan.literal_witness(
                "",
                rejected_reason="SAT closed-object non-object witness was rejected",
            )
        if not lhs_shape.object_is_inhabited():
            if _object_true_proof_blocked_by_non_object_lhs(lhs_shape):
                return ClosedObjectDifferencePlan.unsupported(
                    _OBJECT_TRUE_PROOF_NON_OBJECT_REASON
                )
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

        obligations = self.closed_object_value_obligations(context)
        if obligations is None:
            rhs_upper = _object_property_count_upper_bound(self.rhs_property_count)
            if rhs_upper is not None:
                names = self._rhs_property_count_violation_names(rhs_upper, context)
                if names is not None:
                    skeleton = self.closed_object_witness_skeleton_for_names(names)
                    if skeleton is not None:
                        return ClosedObjectDifferencePlan.skeleton_witness(
                            skeleton,
                            rejected_reason=(
                                "SAT closed-object property-count witness was "
                                "rejected"
                            ),
                        )
                return ClosedObjectDifferencePlan.unsupported(
                    "SAT closed-object difference cannot prove property-count "
                    "constraints"
                )
            if (
                not rhs_shape.property_terms
                and not rhs_shape.pattern_property_terms
            ):
                if _object_true_proof_blocked_by_non_object_lhs(lhs_shape):
                    return ClosedObjectDifferencePlan.unsupported(
                        _OBJECT_TRUE_PROOF_NON_OBJECT_REASON
                    )
                return ClosedObjectDifferencePlan.proved_true()
            return ClosedObjectDifferencePlan.unsupported(
                "SAT closed-object difference requires finite left keyspace"
            )

        return ClosedObjectDifferencePlan.obligation_plan(obligations)

    @cached_property
    def presence_names(self) -> tuple[str, ...] | None:
        lhs_presence = self.lhs_presence_product
        rhs_presence = self.rhs_presence_product
        if lhs_presence is None or rhs_presence is None:
            return None
        name_set = set(self.universe.explicit_names)
        name_set.update(lhs_presence.names)
        name_set.update(rhs_presence.names)
        if self.universe.fresh is not None:
            name_set.add(self.universe.fresh.representative)
        return tuple(sorted(name_set))

    @property
    def lhs_presence_product(self) -> ObjectPresenceProductConstraint | None:
        return self.lhs.object_presence_product_constraint

    @property
    def rhs_presence_product(self) -> ObjectPresenceProductConstraint | None:
        return self.rhs.object_presence_product_constraint

    def presence_accepts(
        self, ir: LogicalSchemaIR, atom: str, present: frozenset[str]
    ) -> bool | None:
        presence = ir.object_presence_product_constraint
        return None if presence is None else presence.accepts(atom, present)

    def presence_product_can_prove_true(self) -> bool:
        if (
            self.rhs_key_values is not None
            and self.rhs_key_values.has_value_constraints
        ):
            return False
        if (
            _object_property_count_upper_bound(self.rhs_property_count) is not None
            and self.lhs_key_values is not None
            and (
                self.lhs_key_values.patterns
                or self.lhs_key_values.keyspace_pattern is not None
            )
        ):
            return False
        lhs_presence = self.lhs_presence_product
        rhs_presence = self.rhs_presence_product
        if lhs_presence is None or rhs_presence is None:
            return False
        if (
            lhs_presence.lhs_has_negative_value_constraints
            or rhs_presence.has_unmodeled_value_constraints
        ):
            return False
        if self.universe.fresh is None:
            return True
        if (
            lhs_presence.has_one_of
            or rhs_presence.has_one_of
            or lhs_presence.has_property_count_constraint
        ):
            return False
        return not rhs_presence.has_upper_count_constraint

    def property_value_obligations(
        self,
    ) -> tuple[ObjectPropertyValueObligation, ...] | None:
        if self.lhs_property_values is None or self.rhs_property_values is None:
            return None
        obligations = []
        for name in sorted(self.rhs_property_values.property_names):
            rhs_term = self.rhs_property_values.property_term_for(name)
            if not _object_value_term_is_true(rhs_term):
                obligations.append(
                    ObjectPropertyValueObligation(
                        name,
                        self.lhs_property_values.property_term_for(name),
                        rhs_term,
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
                    name,
                    self.lhs_property_values.property_term_for(name),
                )
                for name in sorted(names)
            ),
            self.lhs,
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
            if _object_true_proof_blocked_by_non_object_lhs(lhs_shape):
                return ObjectPropertyValuesDifferencePlan.unsupported(
                    _OBJECT_TRUE_PROOF_NON_OBJECT_REASON
                )
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
                    value,
                    self.lhs_key_values.value_term_for(name),
                )
            )
        return ObjectPropertyNamesRepairSkeleton(tuple(slots), self.lhs)

    def property_names_difference_plan(self) -> ObjectPropertyNamesDifferencePlan:
        if self.rhs.object_property_names_has_value_constraints:
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
            if _object_true_proof_blocked_by_non_object_lhs(self.lhs_property_names):
                return ObjectPropertyNamesDifferencePlan.unsupported(
                    _OBJECT_TRUE_PROOF_NON_OBJECT_REASON
                )
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
        rhs_shape: ObjectPropertyNamesConstraint,
    ) -> dict[str, None] | None:
        if not rhs_shape.accepts_object:
            return None
        for name in _object_dependency_interesting_names(self.lhs):
            present = frozenset({name})
            if self.presence_accepts(self.lhs, "object", present) is not True:
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
            lhs_accepts = self.presence_accepts(self.lhs, atom, frozenset())
            rhs_accepts = self.presence_accepts(self.rhs, atom, frozenset())
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
            for name in _object_dependency_interesting_names(self.lhs):
                if rhs_shape.allows_key(name):
                    continue
                present = frozenset({name})
                if self.presence_accepts(self.lhs, "object", present) is False:
                    continue
                witness_plans.append(
                    ObjectPresenceWitnessPlan("finite-keyspace", None, present)
                )

        rhs_dependent_required = self.rhs.semantics.object_dependent_required_constraint
        for entry in (
            () if rhs_dependent_required is None else rhs_dependent_required.entries
        ):
            trigger = entry.trigger
            if not entry.dependencies:
                continue
            present = frozenset({trigger})
            if self.presence_accepts(self.lhs, "object", present) is False:
                continue
            if self.presence_accepts(self.rhs, "object", present) is not False:
                continue
            if self.lhs_key_values is not None and not self.lhs_key_values.allows_key(
                trigger
            ):
                continue
            witness_plans.append(
                ObjectPresenceWitnessPlan("finite-keyspace", None, present)
            )

        rhs_dependent_schema_entries = _object_dependent_schema_required_entries(
            self.rhs
        )
        for trigger, dependencies in rhs_dependent_schema_entries:
            if not dependencies:
                continue
            present = frozenset({trigger})
            if self.presence_accepts(self.lhs, "object", present) is False:
                continue
            if self.presence_accepts(self.rhs, "object", present) is not False:
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
        lhs_presence = self.lhs_presence_product
        rhs_presence = self.rhs_presence_product
        if lhs_presence is None or rhs_presence is None:
            return ObjectPresenceProductPlan.unsupported(
                "SAT object presence product is outside the supported fragment"
            )
        lhs_expr = lhs_presence.symbolic_expr(variables, solver)
        rhs_expr = rhs_presence.symbolic_expr(variables, solver)
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
            rhs_upper = _object_property_count_upper_bound(self.rhs_property_count)
            lhs_upper = _object_property_count_upper_bound(self.lhs_property_count)
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
        return upper is not None and (budget < 0 or upper <= budget)

    def _rhs_property_count_violation_names(
        self,
        rhs_upper: int,
        context: ProofContextProtocol | None,
    ) -> frozenset[str] | None:
        lhs_upper = _object_property_count_upper_bound(self.lhs_property_count)
        if lhs_upper is not None and lhs_upper <= rhs_upper:
            return None
        lhs_shape = self.lhs_key_values
        if lhs_shape is None:
            return None
        names = _distinct_lhs_object_property_names(
            lhs_shape,
            rhs_upper + 1,
            context,
        )
        return None if names is None else frozenset(names)

    def key_value_product_supported(
        self, budget: int, *, expanded: bool = False
    ) -> bool:
        if self.lhs_key_values is None or self.rhs_key_values is None:
            return False
        return object_key_value_mixed_product_supported(
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
        context: ProofContextProtocol | None = None,
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
        rhs_shape: ObjectKeyValueConstraint,
        context: ProofContextProtocol | None,
    ) -> ObjectKeyValueWitnessSkeleton | None:
        lhs_presence = self.lhs_presence_product
        if lhs_presence is None or lhs_presence.has_unmodeled_value_constraints:
            return None
        if context is None:
            return None
        for name, rhs_term in _object_key_value_candidate_value_constraints(
            rhs_shape, context
        ):
            if _object_value_term_is_true(rhs_term):
                continue
            present = lhs_presence.dependency_closed_present_names(frozenset({name}))
            if self.presence_accepts(self.lhs, "object", present) is not True:
                continue
            subproof = _subproof_terms_required(
                SchemaTerm.true(),
                self.lhs,
                rhs_term,
                self.rhs,
                context,
            )
            if subproof.status == "proved_false" and subproof.witness is not None:
                bad_value = subproof.witness
            else:
                continue
            slots = tuple(
                ObjectKeyValueWitnessSlot(
                    present_name,
                    SchemaTerm.true(),
                    bad_value if present_name == name else None,
                    present_name == name,
                )
                for present_name in sorted(present)
            )
            return ObjectKeyValueWitnessSkeleton(slots)
        return None

    def required_omission_key_value_witness_skeleton(
        self,
        rhs_shape: ObjectKeyValueConstraint,
        budget: int,
        context: ProofContextProtocol | None,
    ) -> ObjectKeyValueWitnessSkeleton | None:
        lhs_shape = self.lhs_key_values
        if lhs_shape is None:
            return None
        missing_required = rhs_shape.required - lhs_shape.required
        if not missing_required:
            return None

        min_count = max(
            len(lhs_shape.required),
            _object_property_count_lower_bound(self.lhs_property_count),
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
            lhs_accepts_present = self.presence_accepts(self.lhs, "object", present)
            rhs_accepts_present = self.presence_accepts(self.rhs, "object", present)
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
        context: ProofContextProtocol | None = None,
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
            if object_key_value_mixed_product_budget_exhausted(
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
            if _object_true_proof_blocked_by_non_object_lhs(lhs_shape):
                return ObjectKeyValueDifferencePlan.unsupported(
                    _OBJECT_TRUE_PROOF_NON_OBJECT_REASON
                )
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
            lhs_accepts_present = self.presence_accepts(self.lhs, "object", present)
            rhs_accepts_present = self.presence_accepts(self.rhs, "object", present)
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
            rhs_presence = self.rhs_presence_product
            rhs_upper = _object_property_count_upper_bound(self.rhs_property_count)
            if rhs_upper is not None:
                names = self._rhs_property_count_violation_names(rhs_upper, context)
                if names is not None:
                    skeleton = lhs_shape.witness_skeleton_for_names(names)
                    if skeleton is not None:
                        return ObjectKeyValueDifferencePlan.skeleton_witness(
                            skeleton,
                            rejected_reason=(
                                "SAT object key-value property-count witness was "
                                "rejected"
                            ),
                        )
                return ObjectKeyValueDifferencePlan.unsupported(
                    "SAT object key-value difference cannot prove property-count "
                    "constraints"
                )
            if rhs_presence is not None and rhs_presence.has_property_count_constraint:
                return ObjectKeyValueDifferencePlan.unsupported(
                    "SAT object key-value difference cannot prove property-count "
                    "constraints"
                )
            if _object_true_proof_blocked_by_non_object_lhs(lhs_shape):
                return ObjectKeyValueDifferencePlan.unsupported(
                    _OBJECT_TRUE_PROOF_NON_OBJECT_REASON
                )
            return ObjectKeyValueDifferencePlan.proved_true()

        direct_witness = _object_key_value_direct_false_witness_skeleton(
            lhs_shape, rhs_shape, self.lhs, self.rhs, context
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
            if object_key_value_obligations_budget_exhausted(
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
            if not _object_value_term_is_true(obligation.rhs_term)
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


def _object_key_value_obligations(
    lhs: ObjectKeyValueConstraint,
    rhs: ObjectKeyValueConstraint,
    budget: int,
    *,
    expanded: bool = False,
    context: ProofContextProtocol | None = None,
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
        rhs_term = rhs.value_term_for(name)
        if not _object_value_term_is_true(rhs_term):
            obligations.append(
                ObjectKeyValueObligation(
                    name,
                    lhs.value_term_for(name),
                    rhs_term,
                )
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


def object_key_value_mixed_product_supported(
    lhs: ObjectKeyValueConstraint,
    rhs: ObjectKeyValueConstraint,
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
    class_count = 1 << len(object_key_value_partition_patterns(lhs, rhs))
    return expanded or budget < 0 or len(explicit_names) + class_count <= budget


def object_key_value_mixed_product_budget_exhausted(
    lhs: ObjectKeyValueConstraint,
    rhs: ObjectKeyValueConstraint,
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
    class_count = 1 << len(object_key_value_partition_patterns(lhs, rhs))
    return len(explicit_names) + class_count > budget


def object_key_value_obligations_budget_exhausted(
    lhs: ObjectKeyValueConstraint,
    rhs: ObjectKeyValueConstraint,
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
    class_count = 1 << len(object_key_value_partition_patterns(lhs, rhs))
    return class_count + len(names) > budget


def object_key_value_partition_patterns(
    lhs: ObjectKeyValueConstraint,
    rhs: ObjectKeyValueConstraint,
) -> dict[tuple[str, str], RegexLanguage]:
    patterns = {
        ("pattern", pattern.text): pattern.pattern for pattern in lhs.patterns
    }
    patterns.update(
        {("pattern", pattern.text): pattern.pattern for pattern in rhs.patterns}
    )
    if lhs.keyspace_pattern is not None:
        patterns[OBJECT_KEY_VALUE_LHS_KEYSPACE_PARTITION] = lhs.keyspace_pattern
    if rhs.keyspace_pattern is not None:
        patterns[OBJECT_KEY_VALUE_RHS_KEYSPACE_PARTITION] = rhs.keyspace_pattern
    return patterns


def _object_key_value_allows_unrestricted_keys(
    shape: ObjectKeyValueConstraint,
) -> bool:
    return (
        not shape.properties
        and not shape.patterns
        and _object_value_term_is_true(shape.additional_term)
        and shape.keyspace_pattern is None
        and not shape.required
    )


def _object_key_value_candidate_value_constraints(
    shape: ObjectKeyValueConstraint,
    context: ProofContextProtocol,
) -> tuple[tuple[str, SchemaTerm | None], ...]:
    candidates = [
        (name, shape.value_term_for(name))
        for name in sorted(shape.properties)
    ]
    for pattern in shape.patterns:
        witness = _regex_witness(pattern.pattern, context)
        if isinstance(witness, str):
            candidates.append(
                (
                    witness,
                    shape.value_term_for(witness),
                )
            )
    return tuple(candidates)


def _object_key_value_pattern_obligations(
    lhs: ObjectKeyValueConstraint,
    rhs: ObjectKeyValueConstraint,
    explicit_names: set[str],
    budget: int,
    *,
    expanded: bool = False,
    context: ProofContextProtocol | None = None,
) -> tuple[ObjectKeyValueObligation, ...] | None:
    lhs_patterns = {pattern.text: pattern for pattern in lhs.patterns}
    rhs_patterns = {pattern.text: pattern for pattern in rhs.patterns}
    pattern_map = object_key_value_partition_patterns(lhs, rhs)
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
            lhs.keyspace_pattern is None
            or OBJECT_KEY_VALUE_LHS_KEYSPACE_PARTITION in included
        )
        rhs_keyspace_allows = (
            rhs.keyspace_pattern is None
            or OBJECT_KEY_VALUE_RHS_KEYSPACE_PARTITION in included
        )

        lhs_allows = lhs_keyspace_allows and (
            bool(lhs_matches)
            or not _object_value_term_is_false(lhs.additional_term)
        )
        if not lhs_allows:
            continue

        lhs_term = _object_key_value_pattern_term(lhs_matches, lhs.additional_term)
        rhs_term = (
            _object_key_value_pattern_term(rhs_matches, rhs.additional_term)
            if rhs_keyspace_allows
            else SchemaTerm.false()
        )
        if _object_value_term_is_true(rhs_term):
            continue

        pattern = RegexLanguage.all()
        for text in pattern_texts:
            branch = pattern_map[text]
            branch_pattern = branch if text in included else branch.complement()
            if isinstance(branch_pattern, ProofResult):
                return None
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
            ObjectKeyValueObligation(
                representative,
                lhs_term,
                rhs_term,
            )
        )
    return tuple(obligations)


def _object_key_value_direct_false_witness_skeleton(
    lhs: ObjectKeyValueConstraint,
    rhs: ObjectKeyValueConstraint,
    lhs_ir: LogicalSchemaIR,
    rhs_ir: LogicalSchemaIR,
    context: ProofContextProtocol | None,
) -> ObjectKeyValueWitnessSkeleton | ProofResult | None:
    if context is None or context.endeavor_enabled:
        return None
    for name in _object_key_value_direct_witness_names(lhs, rhs, context):
        if not lhs.allows_key(name):
            continue
        rhs_term = rhs.value_term_for(name)
        if _object_value_term_is_true(rhs_term):
            continue
        proof = _subproof_terms_required(
            lhs.value_term_for(name),
            lhs_ir,
            rhs.value_term_for(name),
            rhs_ir,
            context,
        )
        if proof.status == "resource_exhausted":
            return proof
        if proof.status != "proved_false" or proof.witness is None:
            continue
        return _object_key_value_bad_value_skeleton(lhs, name, proof.witness)
    return None


def _object_key_value_direct_witness_names(
    lhs: ObjectKeyValueConstraint,
    rhs: ObjectKeyValueConstraint,
    context: ProofContextProtocol,
) -> tuple[str, ...]:
    names: list[str] = []

    def add_witness(language: RegexLanguage | ProofResult) -> ProofResult | None:
        if isinstance(language, ProofResult):
            return language
        witness = _regex_witness(language, context)
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
    lhs: ObjectKeyValueConstraint,
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
                    SchemaTerm.true()
                    if present_name == name
                    else lhs.value_term_for(present_name),
                bad_value if present_name == name else None,
                present_name == name,
            )
            for present_name in sorted(present)
        )
    )


_EMPTY_KEY_CLASS = object()


def _object_key_value_pattern_term(
    matches: tuple[ObjectKeyValuePattern, ...],
    additional_term: SchemaTerm | None,
) -> SchemaTerm | None:
    terms: list[SchemaTerm] = []
    for pattern in matches:
        if pattern.term is None:
            return None
        if pattern.term.kind == "false":
            return SchemaTerm.false()
        if pattern.term.kind != "true":
            terms.append(pattern.term)
    if not matches:
        return additional_term
    return SchemaTerm.all_of(tuple(terms))


def _object_key_value_keyspace_witness(
    lhs: ObjectKeyValueConstraint,
    rhs: ObjectKeyValueConstraint,
    context: ProofContextProtocol | None,
) -> str | ProofResult | None:
    for name in sorted(set(lhs.properties) | set(lhs.required)):
        if lhs.allows_key(name) and not rhs.allows_key(name):
            return name

    if rhs.keyspace_pattern is None:
        return None

    for lhs_pattern in lhs.patterns:
        rhs_complement = rhs.keyspace_pattern.complement()
        if isinstance(rhs_complement, ProofResult):
            return rhs_complement
        difference = lhs_pattern.pattern.intersection(rhs_complement)
        if isinstance(difference, ProofResult):
            return difference
        if difference.is_empty():
            continue
        witness = _regex_witness(difference, context)
        if isinstance(witness, ProofResult):
            return witness
        if (
            isinstance(witness, str)
            and lhs.allows_key(witness)
            and not rhs.allows_key(witness)
        ):
            return witness

    if _object_value_term_is_false(lhs.additional_term):
        return None
    lhs_keyspace = (
        RegexLanguage.all() if lhs.keyspace_pattern is None else lhs.keyspace_pattern
    )
    rhs_complement = rhs.keyspace_pattern.complement()
    if isinstance(rhs_complement, ProofResult):
        return rhs_complement
    difference = lhs_keyspace.intersection(rhs_complement)
    if isinstance(difference, ProofResult):
        return difference
    if difference.is_empty():
        return None
    witness = _regex_witness(difference, context)
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
    lhs: ObjectKeyValueConstraint,
    count: int,
    context: ProofContextProtocol | None,
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

    if not _object_value_term_is_false(lhs.additional_term):
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


def _shape_keyspace_restricted_pattern(
    shape: ObjectKeyValueConstraint,
    pattern: RegexLanguage,
    context: ProofContextProtocol | None,
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
    witness = _regex_witness(pattern, None)
    return witness if isinstance(witness, str) else None


def _regex_witness(
    pattern: Any, context: ProofContextProtocol | None
) -> str | ProofResult | None:
    language = pattern if isinstance(pattern, RegexLanguage) else RegexLanguage(pattern)
    if language.is_empty():
        return None
    return language.witness(context)


def _object_key_pattern_witness_excluding(
    pattern: Any, excluded_names: set[str]
) -> str | object | None:
    witness = _regex_witness(pattern, None)
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


def _subproof_terms_required(
    lhs_term: SchemaTerm | None,
    lhs_ir: LogicalSchemaIR,
    rhs_term: SchemaTerm | None,
    rhs_ir: LogicalSchemaIR,
    context: ProofContextProtocol,
) -> ProofResult:
    if lhs_term is None or rhs_term is None:
        return ProofResult.unsupported("object child proof requires schema terms")
    return context.subproof_terms(lhs_term, lhs_ir, rhs_term, rhs_ir)


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


def _supported_evaluated_property_sources(
    sources: tuple[EvaluatedPropertySource, ...],
    unevaluated_term: SchemaTerm | None,
) -> tuple[EvaluatedPropertySource, ...] | None:
    supported: list[EvaluatedPropertySource] = []
    for source in sources:
        if (
            source.kind == "additionalProperties"
            and _term_is_false(source.term)
            and _term_is_false(unevaluated_term)
        ):
            continue
        if source.kind not in {"properties", "patternProperties"}:
            return None
        if source.key is None:
            return None
        if (
            source.kind == "patternProperties"
            and RegexLanguage.maybe_from_json_regex(source.key) is None
        ):
            return None
        supported.append(source)
    return tuple(supported)


def _conditioned_property_paths_cover_lhs(
    model: ObjectDifferenceModel,
    paths: tuple[EvaluationTracePath, ...],
    lhs_shape: ObjectKeyValueConstraint,
    unevaluated_term: SchemaTerm | None,
    context: ProofContextProtocol,
) -> bool:
    if unevaluated_term is None:
        return False
    for candidate in model.lhs.semantics.object_selector_candidates:
        lhs_values = inhabited_finite_values_for_term(
            candidate.term,
            model.lhs,
            context,
        )
        if not lhs_values:
            continue
        if _conditioned_property_paths_cover_lhs_selector(
            model,
            paths,
            lhs_shape,
            unevaluated_term,
            candidate.name,
            tuple(lhs_values),
            context,
        ):
            return True
    return False


def _conditioned_property_product_work_units(
    model: ObjectDifferenceModel,
    paths: tuple[EvaluationTracePath, ...],
    lhs_shape: ObjectKeyValueConstraint,
) -> int:
    candidates = len(model.lhs.semantics.object_selector_candidates)
    keys = sum(1 for name in lhs_shape.properties if lhs_shape.allows_key(name))
    return max(1, candidates) * max(1, len(paths)) * max(1, keys)


def _conditioned_property_paths_cover_lhs_selector(
    model: ObjectDifferenceModel,
    paths: tuple[EvaluationTracePath, ...],
    lhs_shape: ObjectKeyValueConstraint,
    unevaluated_term: SchemaTerm,
    selector_name: str,
    lhs_values: tuple[Any, ...],
    context: ProofContextProtocol,
) -> bool:
    uncovered = {json_semantic_key(value) for value in lhs_values}
    if not uncovered:
        return False
    for path in paths:
        supported = _supported_evaluated_property_sources(
            path.property_sources,
            unevaluated_term,
        )
        if supported is None:
            return False
        selector_term = _rhs_evaluated_property_term_for_name(
            supported,
            selector_name,
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
        if not _conditioned_object_path_uses_supported_branch_shape(
            path,
            model.rhs,
            lhs_shape,
            selector_name,
            tuple(branch_values),
            context,
        ):
            return False
        uncovered -= branch_keys
        if not _conditioned_property_path_covers_lhs_keyspace(
            model,
            lhs_shape,
            supported,
            unevaluated_term,
            selector_name,
            context,
        ):
            return False
    return not uncovered


def _conditioned_property_path_covers_lhs_keyspace(
    model: ObjectDifferenceModel,
    lhs_shape: ObjectKeyValueConstraint,
    sources: tuple[EvaluatedPropertySource, ...],
    unevaluated_term: SchemaTerm,
    selector_name: str,
    context: ProofContextProtocol,
) -> bool:
    for name in sorted(lhs_shape.properties):
        if not lhs_shape.allows_key(name):
            continue
        rhs_term = _rhs_evaluated_property_term_for_name(sources, name)
        if rhs_term is None:
            rhs_term = unevaluated_term
        if name == selector_name:
            continue
        proof = _subproof_terms_required(
            lhs_shape.value_term_for(name),
            model.lhs,
            rhs_term,
            model.rhs,
            context,
        )
        if proof.status != "proved_true":
            return False
    return True


def _conditioned_object_path_uses_supported_branch_shape(
    path: EvaluationTracePath,
    ir: LogicalSchemaIR,
    lhs_shape: ObjectKeyValueConstraint,
    selector_name: str,
    branch_values: tuple[Any, ...],
    context: ProofContextProtocol,
) -> bool:
    node = _condition_node(path.condition, ir)
    if node is None:
        return _negated_condition_excludes_object_selector_values(
            path.condition,
            ir,
            lhs_shape,
            selector_name,
            branch_values,
            context,
        )
    if not _object_condition_shape_is_supported(node):
        return False
    condition_shape = node.semantics.object_key_value_constraint
    if condition_shape is None:
        return False
    source_names = set(_property_source_names(path.property_sources))
    return (
        condition_shape.required <= lhs_shape.required
        and condition_shape.required <= source_names
    )


def _negated_condition_excludes_object_selector_values(
    condition: SchemaTerm,
    ir: LogicalSchemaIR,
    lhs_shape: ObjectKeyValueConstraint,
    selector_name: str,
    branch_values: tuple[Any, ...],
    context: ProofContextProtocol,
) -> bool:
    if condition.kind != "not" or len(condition.children) != 1:
        return False
    node = _condition_node(condition.children[0], ir)
    if node is None or not _object_condition_shape_is_supported(node):
        return False
    condition_shape = node.semantics.object_key_value_constraint
    if condition_shape is None or condition_shape.patterns:
        return False
    if selector_name not in lhs_shape.required:
        return False
    if not condition_shape.properties <= {selector_name}:
        return False
    if not condition_shape.required <= {selector_name}:
        return False
    condition_term = condition_shape.value_term_for(selector_name)
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


def _object_condition_shape_is_supported(node: SchemaNode) -> bool:
    return not (
        node.semantics.vocabulary.semantic_keywords - {"properties", "required", "type"}
    )


def _property_source_names(
    sources: tuple[EvaluatedPropertySource, ...],
) -> tuple[str, ...]:
    return tuple(
        source.key
        for source in sources
        if source.kind == "properties" and source.key is not None
    )


def _rhs_evaluated_property_term_for_name(
    sources: tuple[EvaluatedPropertySource, ...], name: str
) -> SchemaTerm | None:
    terms = [
        source.term
        for source in sources
        if source.term is not None and _rhs_evaluates_property_source_name(source, name)
    ]
    if not terms:
        return None
    return SchemaTerm.all_of(tuple(terms))


def _rhs_evaluates_property_name(
    sources: tuple[EvaluatedPropertySource, ...], name: str
) -> bool:
    return any(_rhs_evaluates_property_source_name(source, name) for source in sources)


def _unevaluated_property_witness_name(
    lhs_shape: ObjectKeyValueConstraint,
    rhs_sources: tuple[EvaluatedPropertySource, ...],
    context: ProofContextProtocol | None,
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

    witness = _regex_witness(pattern, context)
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
    if _term_is_false(source.term):
        return False
    if source.kind == "properties" and source.key == name:
        return True
    if source.kind == "patternProperties" and source.key is not None:
        pattern = RegexLanguage.maybe_from_json_regex(source.key)
        return pattern is not None and pattern.matches(name)
    return False


def _object_property_count_shape_symbolic_expr(
    shape: ObjectPropertyCountConstraint,
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
    lhs_closed: ObjectClosedPropertiesConstraint | None,
    rhs_closed: ObjectClosedPropertiesConstraint | None,
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

    if ir.object_key_value_constraint is not None:
        for required in ir.object_key_value_constraint.required:
            key_classes.add(ObjectKeyClass("explicit", "required", required))
    return key_classes


def _schema_or_term_has_static_reference_boundary(
    term: SchemaTerm | None,
    ir: LogicalSchemaIR,
) -> bool:
    if term is not None:
        term_result = _term_has_static_reference_boundary(term, ir)
        if term_result is not None:
            return term_result
    return True


def _term_has_static_reference_boundary(
    term: SchemaTerm,
    ir: LogicalSchemaIR,
) -> bool | None:
    match term.kind:
        case "true" | "false":
            return False
        case "node":
            if term.ref is None:
                return None
            node = ir.node_for_ref(term.ref)
            return (
                None
                if node is None
                else node.semantics.has_static_reference_boundary
            )
        case "not":
            if len(term.children) != 1:
                return None
            return _term_has_static_reference_boundary(term.children[0], ir)
        case "all_of" | "any_of" | "one_of":
            found = False
            for child in term.children:
                child_result = _term_has_static_reference_boundary(child, ir)
                if child_result is None:
                    return None
                found = found or child_result
            return found


def _object_dependency_interesting_names(ir: LogicalSchemaIR) -> tuple[str, ...]:
    names = set()
    dependent_required = ir.semantics.object_dependent_required_constraint
    if dependent_required is not None:
        for entry in dependent_required.entries:
            names.add(entry.trigger)
            names.update(entry.dependencies)
    for trigger, dependencies in _object_dependent_schema_required_entries(ir):
        names.add(trigger)
        names.update(dependencies)
    return tuple(sorted(names))


def _object_dependent_schema_required_entries(
    ir: LogicalSchemaIR,
) -> tuple[tuple[str, frozenset[str]], ...]:
    constraint = ir.semantics.object_dependent_schema_required_constraint
    if constraint is None:
        return ()
    return tuple(
        (entry.trigger, entry.dependencies)
        for entry in sorted(constraint.entries, key=lambda item: item.trigger)
    )


def _object_property_count_lower_bound(
    shape: ObjectPropertyCountConstraint | None,
) -> int:
    if shape is None:
        return 0
    intervals = shape.normalized_intervals()
    if not intervals:
        return 0
    return min(interval.lower for interval in intervals)


def _object_property_count_upper_bound(
    shape: ObjectPropertyCountConstraint | None,
) -> int | None:
    if shape is None:
        return None
    intervals = shape.normalized_intervals()
    if not intervals or any(interval.upper is None for interval in intervals):
        return None
    return max(interval.upper for interval in intervals if interval.upper is not None)


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

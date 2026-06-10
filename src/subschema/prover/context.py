"""
Proof context, policy, and budget state for the prover.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import subschema.prover.driver as proof_driver
from subschema.contracts import (
    ExpensiveProofKind,
    ProofOptions,
    ProofResult,
    ProofWorkMeter,
    UnsupportedCategory,
    UnsupportedDiagnostic,
)
from subschema.dialects import Dialect
from subschema.ir import LogicalSchemaIR
from subschema.ir.terms import SchemaTerm
from subschema.json_data import ensure_json_value
from subschema.values import stable_key

_EXPENSIVE_PROOF_WORK_LABELS: dict[ExpensiveProofKind, str] = {
    "array_product": "array product",
    "branch_product": "branch expansion",
    "evaluation_trace": "evaluation trace",
    "object_product": "object product",
    "regex_product": "regex product",
}

_DEFAULT_CONSTRUCTIVE_WITNESS_HORIZON = 4096
_RECURSIVE_CYCLE_CATEGORY: UnsupportedCategory = "recursive-reference"

RecursiveSubproofCycleKind = Literal["IR", "term"]
RecursiveSubproofCyclePolarity = Literal["positive", "negative"]


@dataclass(frozen=True)
class RecursiveSubproofCycle:
    kind: RecursiveSubproofCycleKind
    polarity: RecursiveSubproofCyclePolarity
    cache_key: tuple[Any, ...]

    @property
    def reason(self) -> str:
        return f"{self.polarity} recursive {self.kind} subproof cycle is unsupported"

    def unsupported_result(self) -> ProofResult:
        return ProofResult.unsupported(
            self.reason,
            diagnostics=UnsupportedDiagnostic(
                _RECURSIVE_CYCLE_CATEGORY,
                self.reason,
            ),
        )


@dataclass
class ProofContext:
    dialect: Dialect
    options: ProofOptions = field(default_factory=ProofOptions)
    resources: Mapping[str, Any] = field(default_factory=dict)
    subproof_cache: dict[tuple[Any, ...], ProofResult] = field(default_factory=dict)
    active_subproof_keys: set[tuple[Any, ...]] = field(default_factory=set)
    cache: dict[tuple[object, ...], object] = field(default_factory=dict)
    work_meter: ProofWorkMeter = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.options, ProofOptions):
            raise TypeError("options must be a ProofOptions instance")
        if not isinstance(self.resources, Mapping):
            raise TypeError("resources must be a mapping")
        for uri, schema in self.resources.items():
            if not isinstance(uri, str):
                raise TypeError("resource registry keys must be strings")
            ensure_json_value(schema, label=f"resource {uri!r}")
        self.resources = {
            uri: copy.deepcopy(schema) for uri, schema in self.resources.items()
        }
        self.work_meter = ProofWorkMeter(self.proof_work_limit)

    def subproof_ir(
        self,
        lhs: LogicalSchemaIR,
        rhs: LogicalSchemaIR,
    ) -> ProofResult:
        key = self._subproof_ir_cache_key(lhs, rhs)
        if key not in self.subproof_cache:
            if key in self.active_subproof_keys:
                return RecursiveSubproofCycle(
                    "IR",
                    "positive",
                    key,
                ).unsupported_result()
            exhausted = self.consume_branch_expansion(
                "branch expansion exceeded proof work budget"
            )
            if exhausted is not None:
                return exhausted
            self.active_subproof_keys.add(key)
            try:
                self.subproof_cache[key] = proof_driver.prove_ir_subschema_with_context(
                    self,
                    lhs,
                    rhs,
                )
            finally:
                self.active_subproof_keys.discard(key)
        return self.subproof_cache[key]

    def subproof_term(
        self,
        lhs: SchemaTerm,
        rhs: SchemaTerm,
        ir: LogicalSchemaIR,
    ) -> ProofResult:
        return self.subproof_terms(lhs, ir, rhs, ir)

    def subproof_terms(
        self,
        lhs: SchemaTerm,
        lhs_ir: LogicalSchemaIR,
        rhs: SchemaTerm,
        rhs_ir: LogicalSchemaIR,
    ) -> ProofResult:
        key = self._subproof_terms_cache_key(lhs, lhs_ir, rhs, rhs_ir)
        if key not in self.subproof_cache:
            if key in self.active_subproof_keys:
                return RecursiveSubproofCycle(
                    "term",
                    _recursive_term_cycle_polarity(lhs, rhs),
                    key,
                ).unsupported_result()
            exhausted = self.consume_branch_expansion(
                "branch expansion exceeded proof work budget"
            )
            if exhausted is not None:
                return exhausted
            self.active_subproof_keys.add(key)
            try:
                self.subproof_cache[key] = (
                    proof_driver.prove_terms_subschema_with_context(
                        self,
                        lhs,
                        lhs_ir,
                        rhs,
                        rhs_ir,
                    )
                )
            finally:
                self.active_subproof_keys.discard(key)
        return self.subproof_cache[key]

    def _subproof_ir_cache_key(
        self,
        lhs: LogicalSchemaIR,
        rhs: LogicalSchemaIR,
    ) -> tuple[Any, ...]:
        return (
            self.dialect,
            *self.proof_policy_identity,
            self.resource_registry_identity,
            "ir",
            lhs.document.cache_identity,
            lhs.root_ref,
            rhs.document.cache_identity,
            rhs.root_ref,
        )

    def _subproof_term_cache_key(
        self,
        lhs: SchemaTerm,
        rhs: SchemaTerm,
        ir: LogicalSchemaIR,
    ) -> tuple[Any, ...]:
        return self._subproof_terms_cache_key(lhs, ir, rhs, ir)

    def _subproof_terms_cache_key(
        self,
        lhs: SchemaTerm,
        lhs_ir: LogicalSchemaIR,
        rhs: SchemaTerm,
        rhs_ir: LogicalSchemaIR,
    ) -> tuple[Any, ...]:
        return (
            self.dialect,
            *self.proof_policy_identity,
            self.resource_registry_identity,
            "terms",
            lhs_ir.document.cache_identity,
            lhs_ir.root_ref,
            lhs,
            rhs_ir.document.cache_identity,
            rhs_ir.root_ref,
            rhs,
        )

    def cache_get(self, namespace: str, key: tuple[Any, ...]) -> object | None:
        return self.cache.get(self._cache_key(namespace, key))

    def cache_set(self, namespace: str, key: tuple[Any, ...], value: object) -> None:
        self.cache[self._cache_key(namespace, key)] = value

    def _cache_key(self, namespace: str, key: tuple[Any, ...]) -> tuple[object, ...]:
        return (namespace, *(_cache_key_part(part) for part in key))

    def consume_branch_expansion(self, reason: str) -> ProofResult | None:
        return self.spend_work(1, "branch expansion", reason)

    def spend_work(
        self, units: int, kind: str, reason: str | None = None
    ) -> ProofResult | None:
        return self.work_meter.spend(units, kind, reason)

    def allows_expensive_proof(self, kind: ExpensiveProofKind) -> bool:
        self.proof_work_label(kind)
        return self.endeavor_enabled

    def enter_expensive_proof(
        self,
        kind: ExpensiveProofKind,
        *,
        units: int = 0,
        reason: str | None = None,
    ) -> ProofResult | None:
        if not self.allows_expensive_proof(kind):
            return self.expensive_proof_required(kind)
        return self.spend_work(units, self.proof_work_label(kind), reason)

    def expensive_proof_required(self, kind: ExpensiveProofKind) -> ProofResult:
        return ProofResult.unsupported(
            f"{self.proof_work_label(kind)} requires endeavor proof"
        )

    def proof_work_label(self, kind: ExpensiveProofKind) -> str:
        return _EXPENSIVE_PROOF_WORK_LABELS[kind]

    @property
    def default_search_horizon(self) -> int:
        if self.endeavor_enabled:
            return self.proof_work_limit
        return _DEFAULT_CONSTRUCTIVE_WITNESS_HORIZON

    @property
    def solver_timeout_ms(self) -> int:
        if self.endeavor_enabled:
            return self.options.budgets.timeout_ms
        return -1

    @property
    def endeavor_enabled(self) -> bool:
        return self.options.endeavor

    @property
    def proof_work_limit(self) -> int:
        if self.options.endeavor:
            return self.options.budgets.max_work
        return -1

    @property
    def proof_policy_identity(self) -> tuple[object, ...]:
        return (
            self.endeavor_enabled,
            self.proof_work_limit,
            self.solver_timeout_ms,
        )

    @property
    def resource_registry_identity(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (uri, stable_key(schema))
            for uri, schema in sorted(self.resources.items())
        )

    @property
    def work_is_exhausted(self) -> bool:
        return self.work_meter.exhausted


def _cache_key_part(part: Any) -> object:
    try:
        hash(part)
    except TypeError:
        return stable_key(part)
    return part


def _recursive_term_cycle_polarity(
    lhs: SchemaTerm,
    rhs: SchemaTerm,
) -> RecursiveSubproofCyclePolarity:
    if _term_contains_complement(lhs) or _term_contains_complement(rhs):
        return "negative"
    return "positive"


def _term_contains_complement(term: SchemaTerm) -> bool:
    if term.kind == "not":
        return True
    return any(_term_contains_complement(child) for child in term.children)

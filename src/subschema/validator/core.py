"""
Concrete JSON Schema validation helpers used by prover checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache, lru_cache
from typing import Any, Literal, NoReturn, Protocol, assert_never, cast
from urllib.parse import quote, urldefrag

import jsonschema
import jsonschema_rs
from jsonschema.exceptions import SchemaError

from subschema.dialects import (
    ANNOTATION_KEYWORDS,
    DEFAULT_DIALECT,
    Dialect,
    dialect_from_schema,
    strip_inactive_keywords_for_dialect,
)
from subschema.json_data import (
    ensure_json_value,
    strict_json_dumps,
    strict_json_loads,
)
from subschema.provenance import SchemaSource
from subschema.validator.normalization import (
    SCHEMA_ARRAY_KEYWORDS,
    SCHEMA_MAP_KEYWORDS,
    SCHEMA_VALUE_KEYWORDS,
    normalize_boolean_schemas,
)

ValidationOperation = Literal[
    "schema_check",
    "instance_valid",
    "difference_confirm",
    "regex_check",
]
ValidationBackendKind = Literal[
    "jsonschema_rs",
    "python_jsonschema",
    "unsupported",
]
ValidationOutcomeStatus = Literal["valid", "invalid", "unsupported"]

_SOURCE_DOCUMENT_URI = "urn:subschema:document"


class ValidationUnsupportedError(Exception):
    """Raised when a concrete validation backend cannot compile a schema."""


class InstanceValidator(Protocol):
    def is_valid(self, instance: Any) -> bool: ...


@dataclass(frozen=True)
class PlannedSchema:
    source: SchemaSource
    dialect: Dialect
    backend_kind: ValidationBackendKind
    backend_schema: Any = None
    backend_schema_key: str | None = None
    backend_registry_key: str | None = None
    unsupported_reason: str = ""

    def __post_init__(self) -> None:
        if self.backend_kind == "unsupported":
            if not self.unsupported_reason:
                raise ValueError("unsupported planned schema requires a reason")
            return
        if self.unsupported_reason:
            raise ValueError("supported planned schema cannot carry unsupported reason")
        if self.backend_schema_key is None:
            raise ValueError("supported planned schema requires a cache key")

    @classmethod
    def unsupported(cls, source: SchemaSource, reason: str) -> PlannedSchema:
        return cls(
            source=source,
            dialect=source.dialect,
            backend_kind="unsupported",
            unsupported_reason=reason,
        )

    @property
    def is_supported(self) -> bool:
        return self.backend_kind != "unsupported"


@dataclass(frozen=True)
class UnsupportedValidationPlan:
    reason: str


@dataclass(frozen=True)
class SchemaCheckPlan:
    operation: Literal["schema_check"]
    source: SchemaSource
    dialect: Dialect
    normalize_booleans: bool = True


@dataclass(frozen=True)
class RegexCheckPlan:
    operation: Literal["regex_check"]
    schema: PlannedSchema


@dataclass(frozen=True)
class InstanceValidationPlan:
    operation: Literal["instance_valid"]
    schema: PlannedSchema


@dataclass(frozen=True)
class DifferenceConfirmationPlan:
    operation: Literal["difference_confirm"]
    lhs: PlannedSchema
    rhs: PlannedSchema


ValidationPlan = (
    UnsupportedValidationPlan
    | SchemaCheckPlan
    | RegexCheckPlan
    | InstanceValidationPlan
    | DifferenceConfirmationPlan
)


@dataclass(frozen=True)
class ValidationOutcome:
    status: ValidationOutcomeStatus
    reason: str = ""

    @classmethod
    def valid(cls) -> ValidationOutcome:
        return cls("valid")

    @classmethod
    def invalid(cls, reason: str = "") -> ValidationOutcome:
        return cls("invalid", reason)

    @classmethod
    def unsupported(cls, reason: str) -> ValidationOutcome:
        return cls("unsupported", reason)


@dataclass(frozen=True)
class ValidationBackend:
    dialect: Dialect

    def is_valid(self, schema: Any, instance: Any) -> bool:
        return _validation_outcome_as_bool_or_raise(
            validate_source_instance(SchemaSource.root(schema, self.dialect), instance)
        )

    def validates_difference(
        self, lhs_schema: Any, rhs_schema: Any, witness: Any
    ) -> bool:
        return _validation_outcome_as_bool_or_raise(
            validate_source_difference(
                SchemaSource.root(lhs_schema, self.dialect),
                SchemaSource.root(rhs_schema, self.dialect),
                witness,
            )
        )

    def validator_for_schema(self, schema: Any) -> InstanceValidator:
        plan = _build_instance_plan(SchemaSource.root(schema, self.dialect))
        return _validator_for_planned_schema(plan.schema)


@cache
def validation_backend_for(dialect: Dialect) -> ValidationBackend:
    return ValidationBackend(dialect)


def _raise_validation_unsupported(err: Exception) -> NoReturn:
    raise ValidationUnsupportedError(str(err)) from err


def _raise_validation_unsupported_reason(reason: str) -> NoReturn:
    raise ValidationUnsupportedError(reason)


def _validation_outcome_as_bool_or_raise(outcome: ValidationOutcome) -> bool:
    if outcome.status == "valid":
        return True
    if outcome.status == "invalid":
        return False
    _raise_validation_unsupported_reason(outcome.reason)


def validate_schema_for_dialect(schema: Any, dialect: Dialect) -> None:
    ensure_json_value(schema, label="schema")
    outcome = validate_schema_source(SchemaSource.root(schema, dialect))
    if outcome.status == "valid":
        return
    raise SchemaError(outcome.reason)


def validate_raw_schema_for_dialect(schema: Any, dialect: Dialect) -> None:
    ensure_json_value(schema, label="schema")
    outcome = validate_schema_source(
        SchemaSource.root(schema, dialect), normalize_booleans=False
    )
    if outcome.status == "valid":
        return
    raise SchemaError(outcome.reason)


def validate_schema_source(
    source: SchemaSource, *, normalize_booleans: bool = True
) -> ValidationOutcome:
    plan = _build_schema_check_plan(source, normalize_booleans=normalize_booleans)
    return _execute_validation_plan(plan)


def validate_source_instance(
    source: SchemaSource, instance: Any
) -> ValidationOutcome:
    plan = _build_instance_plan(source)
    return _execute_validation_plan(plan, instance)


def validate_source_difference(
    lhs_source: SchemaSource,
    rhs_source: SchemaSource,
    witness: Any,
) -> ValidationOutcome:
    plan = _build_difference_plan(lhs_source, rhs_source)
    return _execute_validation_plan(plan, witness)


def _build_schema_check_plan(
    source: SchemaSource, *, normalize_booleans: bool
) -> SchemaCheckPlan | UnsupportedValidationPlan:
    if not source.is_root_schema:
        return UnsupportedValidationPlan(
            reason="validation requires root schema source",
        )
    ensure_json_value(source.schema, label="schema")
    return SchemaCheckPlan(
        operation="schema_check",
        source=source,
        dialect=source.dialect,
        normalize_booleans=normalize_booleans,
    )


def _build_regex_check_plan(source: SchemaSource) -> RegexCheckPlan:
    return RegexCheckPlan(
        operation="regex_check",
        schema=_planned_schema_for_source(source),
    )


def _build_instance_plan(source: SchemaSource) -> InstanceValidationPlan:
    return InstanceValidationPlan(
        operation="instance_valid",
        schema=_planned_schema_for_source(source),
    )


def _build_difference_plan(
    lhs_source: SchemaSource, rhs_source: SchemaSource
) -> DifferenceConfirmationPlan | UnsupportedValidationPlan:
    if lhs_source.dialect is not rhs_source.dialect:
        return UnsupportedValidationPlan(
            reason="validation requires matching dialects",
        )
    return DifferenceConfirmationPlan(
        operation="difference_confirm",
        lhs=_planned_schema_for_source(lhs_source),
        rhs=_planned_schema_for_source(rhs_source),
    )


def _planned_schema_for_source(source: SchemaSource) -> PlannedSchema:
    if source.is_root_schema:
        return _planned_root_schema_for_source(source)
    return _planned_non_root_schema_for_source(source)


def _planned_root_schema_for_source(source: SchemaSource) -> PlannedSchema:
    ensure_json_value(source.schema, label="schema")
    if _resources_have_dialect_transition(source):
        return PlannedSchema.unsupported(
            source,
            "validation with external resource dialect transitions is unsupported",
        )
    backend_kind, backend_schema = _backend_schema_for_source(source)
    if backend_kind == "python_jsonschema" and source.resources:
        return PlannedSchema.unsupported(
            source,
            "python jsonschema validation with external resources is unsupported",
        )
    return PlannedSchema(
        source=source,
        dialect=source.dialect,
        backend_kind=backend_kind,
        backend_schema=backend_schema,
        backend_schema_key=_json_cache_key(backend_schema),
        backend_registry_key=_backend_registry_key_for_source(source),
    )


def _planned_non_root_schema_for_source(source: SchemaSource) -> PlannedSchema:
    if not source.has_document_context:
        return PlannedSchema.unsupported(source, "validation requires source document")
    ensure_json_value(source.document_root, label="source document")
    if source.document_dialect is not source.dialect:
        return PlannedSchema.unsupported(
            source,
            "validation requires source validator backend",
        )
    if _resources_have_dialect_transition(source):
        return PlannedSchema.unsupported(
            source,
            "validation with external resource dialect transitions is unsupported",
        )
    resource_root = _source_resource_root_schema(source)
    if resource_root is None:
        return PlannedSchema.unsupported(
            source,
            "validation requires source document",
        )
    if _resource_has_dialect_transition(resource_root, source.dialect):
        return PlannedSchema.unsupported(
            source,
            "validation requires source validator backend",
        )
    wrapper_schema = _source_reference_wrapper_schema(source)
    if wrapper_schema is None:
        return PlannedSchema.unsupported(
            source,
            "validation requires source validator backend",
        )
    return PlannedSchema(
        source=source,
        dialect=source.dialect,
        backend_kind="jsonschema_rs",
        backend_schema=wrapper_schema,
        backend_schema_key=_json_cache_key(wrapper_schema),
        backend_registry_key=_backend_registry_key_for_source(source),
    )


def _backend_schema_for_source(
    source: SchemaSource,
) -> tuple[Literal["jsonschema_rs", "python_jsonschema"], Any]:
    schema = source.schema
    dialect = source.dialect
    if _has_embedded_dialect_transition(schema, dialect):
        return "python_jsonschema", schema
    active_schema = strip_inactive_keywords_for_dialect(schema, dialect)
    normalized = normalize_for_validation(active_schema)
    return "jsonschema_rs", normalized


def _backend_registry_resources_for_source(
    source: SchemaSource,
) -> tuple[tuple[str, Any], ...]:
    resources = dict(source.resources)
    if not source.is_root_schema:
        resource_root = _source_resource_root_schema(source)
        resource_uri = _source_resource_uri(source)
        if resource_root is not None and resource_uri is not None:
            resources[resource_uri] = resource_root
    return tuple(
        sorted(
            (
                uri,
                normalize_for_validation(
                    strip_inactive_keywords_for_dialect(schema, source.dialect)
                ),
            )
            for uri, schema in resources.items()
        )
    )


def _backend_registry_key_for_source(source: SchemaSource) -> str | None:
    resources = _backend_registry_resources_for_source(source)
    if not resources:
        return None
    return _json_cache_key([[uri, schema] for uri, schema in resources])


def _resources_have_dialect_transition(source: SchemaSource) -> bool:
    return any(
        _resource_has_dialect_transition(resource_schema, source.dialect)
        for _, resource_schema in source.resources
    )


def _resource_has_dialect_transition(schema: Any, root_dialect: Dialect) -> bool:
    if isinstance(schema, dict):
        try:
            declared = dialect_from_schema(schema)
        except Exception:
            return True
        if declared is not None and declared is not root_dialect:
            return True
    return _has_embedded_dialect_transition(schema, root_dialect)


def _source_reference_wrapper_schema(source: SchemaSource) -> dict[str, str] | None:
    ref = _source_reference_uri(source)
    if ref is None:
        return None
    return {"$ref": ref}


def _source_resource_uri(source: SchemaSource) -> str | None:
    uri = source.resource_uri or _SOURCE_DOCUMENT_URI
    base, fragment = urldefrag(uri)
    if fragment:
        return base or _SOURCE_DOCUMENT_URI
    return base


def _source_reference_uri(source: SchemaSource) -> str | None:
    uri = source.resource_uri or _SOURCE_DOCUMENT_URI
    base, fragment = urldefrag(uri)
    resource_uri = _source_resource_uri(source)
    if resource_uri is None:
        return None
    if fragment:
        return f"{base or resource_uri}#{fragment}"
    return _join_uri_fragment(resource_uri, _effective_resource_pointer(source))


def _source_resource_root_schema(source: SchemaSource) -> Any | None:
    if source.document_root is None:
        return None
    pointer = _source_resource_root_pointer(source)
    if pointer is None:
        return None
    return _resolve_pointer_parts(source.document_root, pointer)


def _source_resource_root_pointer(source: SchemaSource) -> tuple[str, ...] | None:
    document_pointer = _effective_document_pointer(source)
    resource_pointer = _effective_resource_pointer(source)
    if not resource_pointer:
        return document_pointer
    if len(resource_pointer) > len(document_pointer):
        return None
    if document_pointer[-len(resource_pointer) :] != resource_pointer:
        return None
    return document_pointer[: -len(resource_pointer)]


def _effective_document_pointer(source: SchemaSource) -> tuple[str, ...]:
    return source.document_pointer or source.pointer


def _effective_resource_pointer(source: SchemaSource) -> tuple[str, ...]:
    if source.resource_pointer:
        return source.resource_pointer
    if source.resource_uri:
        return ()
    return _effective_document_pointer(source)


def _join_uri_fragment(uri: str, pointer: tuple[str, ...]) -> str | None:
    base, fragment = urldefrag(uri)
    if fragment:
        return uri if not pointer else None
    if not pointer:
        return base
    return f"{base}#{quote(_json_pointer(pointer), safe='/~')}"


def _json_pointer(pointer: tuple[str, ...]) -> str:
    return "/" + "/".join(_escape_json_pointer_part(part) for part in pointer)


def _escape_json_pointer_part(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def _resolve_pointer_parts(schema: Any, pointer: tuple[str, ...]) -> Any | None:
    current = schema
    for part in pointer:
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return None
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def _execute_validation_plan(
    plan: ValidationPlan, instance: Any = None
) -> ValidationOutcome:
    if isinstance(plan, UnsupportedValidationPlan):
        return ValidationOutcome.unsupported(plan.reason)
    if isinstance(plan, SchemaCheckPlan):
        return _execute_schema_check_plan(plan)
    if isinstance(plan, RegexCheckPlan):
        return _execute_regex_check_plan(plan)
    if isinstance(plan, InstanceValidationPlan):
        return _execute_instance_plan(plan, instance)
    if isinstance(plan, DifferenceConfirmationPlan):
        return _execute_difference_plan(plan, instance)
    assert_never(plan)


def _execute_schema_check_plan(plan: SchemaCheckPlan) -> ValidationOutcome:
    try:
        _validate_schema_resource_for_dialect(
            plan.source.schema,
            plan.dialect,
            is_root=True,
            normalize_booleans=plan.normalize_booleans,
        )
    except SchemaError as err:
        return ValidationOutcome.invalid(str(err))
    except Exception as err:
        return ValidationOutcome.unsupported(str(err))
    return ValidationOutcome.valid()


def _execute_regex_check_plan(plan: RegexCheckPlan) -> ValidationOutcome:
    unsupported = _unsupported_planned_schema_outcome(plan.schema)
    if unsupported is not None:
        return unsupported
    try:
        _validator_for_planned_schema(plan.schema)
    except ValidationUnsupportedError as err:
        return ValidationOutcome.unsupported(str(err))
    except Exception as err:
        return ValidationOutcome.unsupported(str(err))
    return ValidationOutcome.valid()


def _execute_instance_plan(
    plan: InstanceValidationPlan, instance: Any
) -> ValidationOutcome:
    unsupported = _unsupported_planned_schema_outcome(plan.schema)
    if unsupported is not None:
        return unsupported
    normalized_or_outcome = _normalized_instance_or_outcome(instance)
    if isinstance(normalized_or_outcome, ValidationOutcome):
        return normalized_or_outcome
    try:
        validator = _validator_for_planned_schema(plan.schema)
        return (
            ValidationOutcome.valid()
            if validator.is_valid(normalized_or_outcome)
            else ValidationOutcome.invalid()
        )
    except ValidationUnsupportedError as err:
        return ValidationOutcome.unsupported(str(err))
    except RecursionError:
        return ValidationOutcome.unsupported(
            "schema validation exceeded the supported depth"
        )
    except Exception as err:
        return ValidationOutcome.unsupported(str(err))


def _execute_difference_plan(
    plan: DifferenceConfirmationPlan, witness: Any
) -> ValidationOutcome:
    lhs_unsupported = _unsupported_planned_schema_outcome(plan.lhs)
    if lhs_unsupported is not None:
        return lhs_unsupported
    rhs_unsupported = _unsupported_planned_schema_outcome(plan.rhs)
    if rhs_unsupported is not None:
        return rhs_unsupported
    normalized_or_outcome = _normalized_instance_or_outcome(witness)
    if isinstance(normalized_or_outcome, ValidationOutcome):
        return normalized_or_outcome
    try:
        lhs_validator = _validator_for_planned_schema(plan.lhs)
        rhs_validator = _validator_for_planned_schema(plan.rhs)
        lhs_valid = lhs_validator.is_valid(normalized_or_outcome)
        if lhs_valid and not rhs_validator.is_valid(normalized_or_outcome):
            return ValidationOutcome.valid()
        return ValidationOutcome.invalid()
    except ValidationUnsupportedError as err:
        return ValidationOutcome.unsupported(str(err))
    except RecursionError:
        return ValidationOutcome.unsupported(
            "schema validation exceeded the supported depth"
        )
    except Exception as err:
        return ValidationOutcome.unsupported(str(err))


def _normalized_instance_or_outcome(instance: Any) -> Any | ValidationOutcome:
    try:
        return normalize_instance_for_validation(instance)
    except ValueError:
        return ValidationOutcome.invalid("instance is not valid JSON data")


def _unsupported_planned_schema_outcome(
    planned_schema: PlannedSchema,
) -> ValidationOutcome | None:
    if planned_schema.is_supported:
        return None
    return ValidationOutcome.unsupported(planned_schema.unsupported_reason)


def _validator_for_planned_schema(planned_schema: PlannedSchema) -> InstanceValidator:
    if planned_schema.backend_kind == "unsupported":
        _raise_validation_unsupported_reason(planned_schema.unsupported_reason)
    schema = planned_schema.backend_schema
    key = planned_schema.backend_schema_key
    if planned_schema.backend_kind == "python_jsonschema":
        return _validator_from_python_jsonschema(planned_schema.dialect, schema, key)
    return _validator_from_jsonschema_rs(
        planned_schema.dialect,
        schema,
        key,
        planned_schema.backend_registry_key,
    )


def _validator_from_jsonschema_rs(
    dialect: Dialect,
    schema: Any,
    key: str | None,
    registry_key: str | None,
) -> InstanceValidator:
    try:
        if key is None:
            registry_resources = (
                None
                if registry_key is None
                else _registry_resources_from_key(registry_key)
            )
            return _compile_jsonschema_rs_validator(dialect, schema, registry_resources)
        return _compiled_jsonschema_rs_validator(dialect, key, registry_key)
    except Exception as err:
        _raise_validation_unsupported(err)


def _validator_from_python_jsonschema(
    dialect: Dialect, schema: Any, key: str | None
) -> InstanceValidator:
    try:
        if key is None:
            return _compile_python_jsonschema_validator(dialect, schema)
        return _compiled_python_jsonschema_validator(dialect, key)
    except Exception as err:
        _raise_validation_unsupported(err)


def _validate_schema_resource_for_dialect(
    schema: Any,
    dialect: Dialect,
    *,
    is_root: bool,
    normalize_booleans: bool = True,
) -> None:
    if isinstance(schema, dict):
        resource_dialect = dialect_from_schema(schema) or dialect
    else:
        resource_dialect = dialect
    normalized = normalize_boolean_schemas(schema) if normalize_booleans else schema
    metaschema_input = _schema_for_metaschema_validation(
        normalized,
        resource_dialect,
        is_root=is_root,
        normalize_booleans=normalize_booleans,
    )
    _python_validator_for_dialect(resource_dialect).check_schema(
        metaschema_input,
        format_checker=None,
    )
    _validate_supported_regex_keywords(normalized, resource_dialect)


def _schema_for_metaschema_validation(
    schema: Any,
    dialect: Dialect,
    *,
    is_root: bool,
    normalize_booleans: bool,
) -> Any:
    if isinstance(schema, dict):
        if not is_root and "$schema" in schema:
            embedded_dialect = dialect_from_schema(schema)
            if embedded_dialect is not None and embedded_dialect is not dialect:
                _validate_schema_resource_for_dialect(
                    schema,
                    embedded_dialect,
                    is_root=True,
                    normalize_booleans=normalize_booleans,
                )
                return {}
        return {
            key: _schema_child_for_metaschema_validation(
                key, value, dialect, normalize_booleans
            )
            for key, value in schema.items()
        }
    return schema


def _schema_child_for_metaschema_validation(
    key: str,
    value: Any,
    dialect: Dialect,
    normalize_booleans: bool,
) -> Any:
    if key in SCHEMA_VALUE_KEYWORDS:
        return _schema_for_metaschema_validation(
            value,
            dialect,
            is_root=False,
            normalize_booleans=normalize_booleans,
        )
    if key in SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
        return [
            _schema_for_metaschema_validation(
                item,
                dialect,
                is_root=False,
                normalize_booleans=normalize_booleans,
            )
            for item in value
        ]
    if key in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
        if key == "dependencies":
            return {
                name: _schema_for_metaschema_validation(
                    dependency,
                    dialect,
                    is_root=False,
                    normalize_booleans=normalize_booleans,
                )
                if isinstance(dependency, dict | bool)
                else dependency
                for name, dependency in value.items()
            }
        return {
            name: _schema_for_metaschema_validation(
                subschema,
                dialect,
                is_root=False,
                normalize_booleans=normalize_booleans,
            )
            for name, subschema in value.items()
        }
    return value


def _validate_supported_regex_keywords(
    schema: Any, dialect: Dialect, path: tuple[str, ...] = ()
) -> None:
    if isinstance(schema, dict):
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            _validate_supported_regex(pattern, dialect, path + ("pattern",))
        pattern_properties = schema.get("patternProperties")
        if isinstance(pattern_properties, dict):
            for pattern_text in pattern_properties:
                _validate_supported_regex(
                    str(pattern_text),
                    dialect,
                    path + ("patternProperties", str(pattern_text)),
                )
        for key, value in schema.items():
            if key in SCHEMA_VALUE_KEYWORDS:
                _validate_supported_regex_keywords(value, dialect, path + (key,))
                continue
            if key in SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
                for index, item in enumerate(value):
                    _validate_supported_regex_keywords(
                        item, dialect, path + (key, str(index))
                    )
                continue
            if key in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
                if key == "dependencies":
                    for name, dependency in value.items():
                        if isinstance(dependency, dict | bool):
                            _validate_supported_regex_keywords(
                                dependency, dialect, path + (key, str(name))
                            )
                    continue
                for name, subschema in value.items():
                    _validate_supported_regex_keywords(
                        subschema, dialect, path + (key, str(name))
                    )
        return
    if isinstance(schema, list):
        for index, item in enumerate(schema):
            _validate_supported_regex_keywords(item, dialect, path + (str(index),))


def _validate_supported_regex(
    pattern: str, dialect: Dialect, path: tuple[str, ...]
) -> None:
    outcome = _execute_validation_plan(
        _build_regex_check_plan(
            SchemaSource.root({"type": "string", "pattern": pattern}, dialect)
        )
    )
    if outcome.status == "valid":
        return
    location = "/" + "/".join(path) if path else "<root>"
    raise SchemaError(f"invalid regex at {location}: {pattern!r}: {outcome.reason}")


def normalize_for_validation(schema: Any) -> Any:
    key = _json_cache_key(schema)
    if key is None:
        return _normalize_for_validation_uncached(schema)
    return _normalize_for_validation_key(key)


def _normalize_for_validation_uncached(schema: Any) -> Any:
    schema = normalize_boolean_schemas(schema)
    if isinstance(schema, list):
        return [_normalize_for_validation_uncached(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    normalized: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "const":
            normalized["enum"] = [value]
        elif key in ANNOTATION_KEYWORDS:
            continue
        elif key in SCHEMA_VALUE_KEYWORDS:
            normalized[key] = _normalize_for_validation_uncached(value)
        elif key in SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
            normalized[key] = [
                _normalize_for_validation_uncached(item) for item in value
            ]
        elif key in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            normalized[key] = {
                name: _normalize_for_validation_uncached(subschema)
                for name, subschema in value.items()
            }
        else:
            normalized[key] = value
    return normalized


@lru_cache(maxsize=32768)
def _normalize_for_validation_key(schema_key: str) -> Any:
    return _normalize_for_validation_uncached(strict_json_loads(schema_key))


@lru_cache(maxsize=32768)
def _compiled_jsonschema_rs_validator(
    dialect: Dialect,
    schema_key: str,
    registry_key: str | None,
) -> InstanceValidator:
    return _compile_jsonschema_rs_validator(
        dialect,
        _normalize_for_validation_key(schema_key),
        None if registry_key is None else _registry_resources_from_key(registry_key),
    )


def _compile_jsonschema_rs_validator(
    dialect: Dialect,
    schema: Any,
    registry_resources: Any | None = None,
) -> InstanceValidator:
    validator_cls = {
        Dialect.DRAFT4: jsonschema_rs.Draft4Validator,
        Dialect.DRAFT6: jsonschema_rs.Draft6Validator,
        Dialect.DRAFT7: jsonschema_rs.Draft7Validator,
        Dialect.DRAFT201909: jsonschema_rs.Draft201909Validator,
        Dialect.DRAFT202012: jsonschema_rs.Draft202012Validator,
    }[dialect]
    if registry_resources:
        registry = jsonschema_rs.Registry(
            registry_resources,
            draft=_jsonschema_rs_draft(dialect),
        )
        return cast(InstanceValidator, validator_cls(schema, registry=registry))
    return cast(InstanceValidator, validator_cls(schema))


def _registry_resources_from_key(registry_key: str) -> tuple[tuple[str, Any], ...]:
    return tuple((uri, schema) for uri, schema in strict_json_loads(registry_key))


def _jsonschema_rs_draft(dialect: Dialect) -> Any:
    return {
        Dialect.DRAFT4: jsonschema_rs.Draft4,
        Dialect.DRAFT6: jsonschema_rs.Draft6,
        Dialect.DRAFT7: jsonschema_rs.Draft7,
        Dialect.DRAFT201909: jsonschema_rs.Draft201909,
        Dialect.DRAFT202012: jsonschema_rs.Draft202012,
    }[dialect]


@lru_cache(maxsize=4096)
def _compiled_python_jsonschema_validator(
    dialect: Dialect, schema_key: str
) -> InstanceValidator:
    return _compile_python_jsonschema_validator(dialect, strict_json_loads(schema_key))


def _compile_python_jsonschema_validator(
    dialect: Dialect, schema: Any
) -> InstanceValidator:
    return cast(
        InstanceValidator,
        _python_validator_for_dialect(dialect)(normalize_boolean_schemas(schema)),
    )


def _python_validator_for_dialect(dialect: Dialect) -> type[Any]:
    return {
        Dialect.DRAFT4: jsonschema.Draft4Validator,
        Dialect.DRAFT6: jsonschema.Draft6Validator,
        Dialect.DRAFT7: jsonschema.Draft7Validator,
        Dialect.DRAFT201909: jsonschema.Draft201909Validator,
        Dialect.DRAFT202012: jsonschema.Draft202012Validator,
    }[dialect]


def _has_embedded_dialect_transition(schema: Any, root_dialect: Dialect) -> bool:
    return _has_embedded_dialect_transition_at(schema, root_dialect, is_root=True)


def _has_embedded_dialect_transition_at(
    schema: Any, root_dialect: Dialect, *, is_root: bool
) -> bool:
    if isinstance(schema, dict):
        if not is_root and "$schema" in schema:
            try:
                if validator_for_schema_dialect(schema) is not root_dialect:
                    return True
            except Exception:
                return True
        for key, value in schema.items():
            if key in SCHEMA_VALUE_KEYWORDS:
                if _has_embedded_dialect_transition_at(
                    value, root_dialect, is_root=False
                ):
                    return True
                continue
            if key in SCHEMA_ARRAY_KEYWORDS and isinstance(value, list):
                if any(
                    _has_embedded_dialect_transition_at(
                        item, root_dialect, is_root=False
                    )
                    for item in value
                ):
                    return True
                continue
            if key in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
                if key == "dependencies":
                    dependencies = (
                        dependency
                        for dependency in value.values()
                        if isinstance(dependency, dict | bool)
                    )
                    if any(
                        _has_embedded_dialect_transition_at(
                            dependency, root_dialect, is_root=False
                        )
                        for dependency in dependencies
                    ):
                        return True
                    continue
                if any(
                    _has_embedded_dialect_transition_at(
                        item, root_dialect, is_root=False
                    )
                    for item in value.values()
                ):
                    return True
        return False
    if isinstance(schema, list):
        return any(
            _has_embedded_dialect_transition_at(value, root_dialect, is_root=False)
            for value in schema
        )
    return False


def validator_for_schema_dialect(schema: dict[str, Any]) -> Dialect:
    return dialect_from_schema(schema) or DEFAULT_DIALECT


def normalize_instance_for_validation(instance: Any) -> Any:
    ensure_json_value(instance, label="instance")
    return _normalize_instance_for_validation_uncached(instance)


def _normalize_instance_for_validation_uncached(instance: Any) -> Any:
    if isinstance(instance, bool):
        return instance
    if isinstance(instance, float) and instance.is_integer():
        return int(instance)
    if isinstance(instance, dict):
        return {
            key: _normalize_instance_for_validation_uncached(value)
            for key, value in instance.items()
        }
    if isinstance(instance, list):
        return [_normalize_instance_for_validation_uncached(item) for item in instance]
    return instance


def _json_cache_key(value: Any) -> str | None:
    try:
        return strict_json_dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None

"""
Concrete JSON Schema validation helpers used by proof-kernel checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache, lru_cache
from typing import Any, Protocol, cast

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
from subschema.kernel.json_data import (
    ensure_json_value,
    strict_json_dumps,
    strict_json_loads,
)
from subschema.kernel.normalization import (
    SCHEMA_ARRAY_KEYWORDS,
    SCHEMA_MAP_KEYWORDS,
    SCHEMA_VALUE_KEYWORDS,
    normalize_boolean_schemas,
)


class ValidationUnsupportedError(Exception):
    """Raised when a concrete validation backend cannot compile a schema."""


class InstanceValidator(Protocol):
    def is_valid(self, instance: Any) -> bool: ...


@dataclass(frozen=True)
class ValidationBackend:
    dialect: Dialect

    def is_valid(self, schema: Any, instance: Any) -> bool:
        try:
            normalized_instance = normalize_instance_for_validation(instance)
        except ValueError:
            return False
        validator = self.validator_for_schema(schema)
        return validator.is_valid(normalized_instance)

    def validates_difference(
        self, lhs_schema: Any, rhs_schema: Any, witness: Any
    ) -> bool:
        try:
            normalized_instance = normalize_instance_for_validation(witness)
        except ValueError:
            return False
        lhs_validator = self.validator_for_schema(lhs_schema)
        rhs_validator = self.validator_for_schema(rhs_schema)
        lhs_valid = lhs_validator.is_valid(normalized_instance)
        return lhs_valid and not rhs_validator.is_valid(normalized_instance)

    def validator_for_schema(self, schema: Any) -> InstanceValidator:
        ensure_json_value(schema, label="schema")
        if _has_embedded_dialect_transition(schema, self.dialect):
            key = _json_cache_key(schema)
            if key is None:
                return _compile_python_jsonschema_validator(self.dialect, schema)
            return _compiled_python_jsonschema_validator(self.dialect, key)
        active_schema = strip_inactive_keywords_for_dialect(schema, self.dialect)
        normalized = normalize_for_validation(active_schema)
        key = _json_cache_key(normalized)
        try:
            if key is None:
                return _compile_jsonschema_rs_validator(self.dialect, normalized)
            return _compiled_jsonschema_rs_validator(self.dialect, key)
        except Exception as err:
            raise ValidationUnsupportedError(str(err)) from err


@cache
def validation_backend_for(dialect: Dialect) -> ValidationBackend:
    return ValidationBackend(dialect)


def validate_schema_for_dialect(schema: Any, dialect: Dialect) -> None:
    ensure_json_value(schema, label="schema")
    _validate_schema_resource_for_dialect(schema, dialect, is_root=True)


def validate_raw_schema_for_dialect(schema: Any, dialect: Dialect) -> None:
    ensure_json_value(schema, label="schema")
    _validate_schema_resource_for_dialect(
        schema, dialect, is_root=True, normalize_booleans=False
    )


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
    try:
        _compile_jsonschema_rs_validator(
            dialect, {"type": "string", "pattern": pattern}
        )
        return
    except Exception as err:
        error = err
    location = "/" + "/".join(path) if path else "<root>"
    raise SchemaError(f"invalid regex at {location}: {pattern!r}") from error


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
    dialect: Dialect, schema_key: str
) -> InstanceValidator:
    return _compile_jsonschema_rs_validator(
        dialect, _normalize_for_validation_key(schema_key)
    )


def _compile_jsonschema_rs_validator(
    dialect: Dialect, schema: Any
) -> InstanceValidator:
    validator_cls = {
        Dialect.DRAFT4: jsonschema_rs.Draft4Validator,
        Dialect.DRAFT6: jsonschema_rs.Draft6Validator,
        Dialect.DRAFT7: jsonschema_rs.Draft7Validator,
        Dialect.DRAFT201909: jsonschema_rs.Draft201909Validator,
        Dialect.DRAFT202012: jsonschema_rs.Draft202012Validator,
    }[dialect]
    return cast(InstanceValidator, validator_cls(schema))


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

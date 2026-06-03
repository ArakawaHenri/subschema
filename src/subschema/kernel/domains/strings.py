"""
String length reasoning for exact subschema proofs.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from subschema.kernel.contracts import ProofResult
from subschema.kernel.domains.types import type_shape_for_type_keyword
from subschema.kernel.json_data import strict_json_loads
from subschema.kernel.regex import RegexLanguage
from subschema.kernel.schemas import (
    IGNORED_SCHEMA_METADATA_KEYS,
    contains_reference_keyword,
)
from subschema.kernel.values import stable_key

if TYPE_CHECKING:
    from subschema.kernel.context import ProofContext

STRING_SCHEMA_KEYWORDS = frozenset(
    {"allOf", "anyOf", "maxLength", "minLength", "not", "type"}
)

STRING_LANGUAGE_SCHEMA_KEYWORDS = frozenset(
    {
        "allOf",
        "anyOf",
        "const",
        "enum",
        "maxLength",
        "minLength",
        "not",
        "pattern",
        "type",
    }
)

_SCHEMA_SHAPE_CACHE_SIZE = 4096

__all__ = [
    "STRING_SCHEMA_KEYWORDS",
    "STRING_LANGUAGE_SCHEMA_KEYWORDS",
    "StringLengthInterval",
    "StringLanguageShape",
    "StringShape",
    "drop_string_pattern_keywords",
    "string_length_fragments_are_disjoint",
    "string_language_fragments_are_disjoint",
    "string_language_shape_for_schema",
    "string_language_witness",
    "string_shape_for_schema",
]
@dataclass(frozen=True)
class StringShape:
    intervals: tuple[StringLengthInterval, ...]
    accepts_non_string: bool

    def normalized_intervals(self) -> tuple[StringLengthInterval, ...]:
        return _merge_string_intervals(
            tuple(interval for interval in self.intervals if not interval.is_empty())
        )

    def is_subset_of(self, other: StringShape) -> bool:
        if self.accepts_non_string and not other.accepts_non_string:
            return False
        return all(
            _string_interval_covered(interval, other.normalized_intervals())
            for interval in self.normalized_intervals()
        )

    def witness_not_in(self, other: StringShape) -> str | None:
        for interval in self.normalized_intervals():
            length = _first_uncovered_string_length(
                interval, other.normalized_intervals()
            )
            if length is not None:
                return "a" * length
        return None

    def intersect(self, other: StringShape) -> StringShape:
        intervals = [
            lhs.intersect(rhs)
            for lhs in self.normalized_intervals()
            for rhs in other.normalized_intervals()
        ]
        return StringShape(
            _merge_string_intervals(
                tuple(interval for interval in intervals if not interval.is_empty())
            ),
            self.accepts_non_string and other.accepts_non_string,
        )

    def union(self, other: StringShape) -> StringShape:
        return StringShape(
            _merge_string_intervals(
                self.normalized_intervals() + other.normalized_intervals()
            ),
            self.accepts_non_string or other.accepts_non_string,
        )

    def complement(self) -> StringShape:
        return StringShape(
            _complement_string_intervals(self.normalized_intervals()),
            not self.accepts_non_string,
        )


@dataclass(frozen=True)
class StringLengthInterval:
    lower: int = 0
    upper: int | None = None

    def is_empty(self) -> bool:
        return self.upper is not None and self.lower > self.upper

    def intersect(self, other: StringLengthInterval) -> StringLengthInterval:
        lower = max(self.lower, other.lower)
        if self.upper is None:
            upper = other.upper
        elif other.upper is None:
            upper = self.upper
        else:
            upper = min(self.upper, other.upper)
        return StringLengthInterval(lower, upper)


def string_shape_for_schema(schema: Any, depth: int = 0) -> StringShape | None:
    cache_key = _cacheable_schema_key(schema)
    if cache_key is None:
        return _string_shape_for_schema_uncached(schema, depth)
    return _string_shape_for_schema_cached(cache_key, depth)


@lru_cache(maxsize=_SCHEMA_SHAPE_CACHE_SIZE)
def _string_shape_for_schema_cached(schema_key: str, depth: int) -> StringShape | None:
    return _string_shape_for_schema_uncached(strict_json_loads(schema_key), depth)


def _string_shape_for_schema_uncached(
    schema: Any, depth: int = 0
) -> StringShape | None:
    if depth > 16:
        return None
    if schema is True:
        return StringShape((StringLengthInterval(),), accepts_non_string=True)
    if schema is False:
        return StringShape((), accepts_non_string=False)
    if not isinstance(schema, dict):
        return None
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return None
    if not _is_string_length_fragment_schema(schema):
        return None

    shape = _local_string_shape(schema)
    if shape is None:
        return None

    for subschema in schema.get("allOf", []):
        branch = string_shape_for_schema(subschema, depth + 1)
        if branch is None:
            return None
        shape = shape.intersect(branch)

    if "anyOf" in schema:
        any_shape = StringShape((), accepts_non_string=False)
        for subschema in schema["anyOf"]:
            branch = string_shape_for_schema(subschema, depth + 1)
            if branch is None:
                return None
            any_shape = any_shape.union(branch)
        shape = shape.intersect(any_shape)

    if "not" in schema:
        negated = string_shape_for_schema(schema["not"], depth + 1)
        if negated is None:
            return None
        if (
            shape.accepts_non_string
            and negated.accepts_non_string
            and not _schema_accepts_all_non_strings_for_string_constraints(
                schema["not"]
            )
        ):
            return None
        shape = shape.intersect(negated.complement())

    return shape


@dataclass(frozen=True)
class StringLanguageShape:
    pattern: RegexLanguage
    accepts_non_string: bool

    def is_subset_of(
        self, other: StringLanguageShape, context: ProofContext | None = None
    ) -> bool | ProofResult:
        if self.accepts_non_string and not other.accepts_non_string:
            return False
        return self.pattern.is_subset_of(other.pattern, context)

    def witness_not_in(
        self, other: StringLanguageShape, context: ProofContext | None = None
    ) -> str | ProofResult | None:
        difference = self.pattern.difference(other.pattern, context)
        if isinstance(difference, ProofResult):
            return difference
        return string_language_witness(difference, context)

    def intersect(self, other: StringLanguageShape) -> StringLanguageShape:
        return StringLanguageShape(
            _expect_regex_language(self.pattern.intersection(other.pattern)),
            self.accepts_non_string and other.accepts_non_string,
        )

    def union(self, other: StringLanguageShape) -> StringLanguageShape:
        return StringLanguageShape(
            _expect_regex_language(self.pattern.union(other.pattern)),
            self.accepts_non_string or other.accepts_non_string,
        )

    def complement(self) -> StringLanguageShape:
        return StringLanguageShape(
            _expect_regex_language(self.pattern.complement()),
            not self.accepts_non_string,
        )


def string_language_shape_for_schema(
    schema: Any, depth: int = 0
) -> StringLanguageShape | None:
    cache_key = _cacheable_schema_key(schema)
    if cache_key is None:
        return _string_language_shape_for_schema_uncached(schema, depth)
    return _string_language_shape_for_schema_cached(cache_key, depth)


@lru_cache(maxsize=_SCHEMA_SHAPE_CACHE_SIZE)
def _string_language_shape_for_schema_cached(
    schema_key: str, depth: int
) -> StringLanguageShape | None:
    return _string_language_shape_for_schema_uncached(
        strict_json_loads(schema_key), depth
    )


def _string_language_shape_for_schema_uncached(
    schema: Any, depth: int = 0
) -> StringLanguageShape | None:
    if depth > 16:
        return None
    if schema is True:
        return StringLanguageShape(RegexLanguage.all(), accepts_non_string=True)
    if schema is False:
        return StringLanguageShape(RegexLanguage.empty(), accepts_non_string=False)
    if not isinstance(schema, dict):
        return None
    if contains_reference_keyword(schema, {"$ref", "$recursiveRef", "$dynamicRef"}):
        return None
    if not _is_string_language_fragment_schema(schema):
        return None

    shape = _local_string_language_shape(schema)
    if shape is None:
        return None

    for subschema in schema.get("allOf", []):
        branch = string_language_shape_for_schema(subschema, depth + 1)
        if branch is None:
            return None
        shape = shape.intersect(branch)

    if "anyOf" in schema:
        any_shape = StringLanguageShape(RegexLanguage.empty(), accepts_non_string=False)
        for subschema in schema["anyOf"]:
            branch = string_language_shape_for_schema(subschema, depth + 1)
            if branch is None:
                return None
            any_shape = any_shape.union(branch)
        shape = shape.intersect(any_shape)

    if "not" in schema:
        negated = string_language_shape_for_schema(schema["not"], depth + 1)
        if negated is None:
            return None
        if (
            shape.accepts_non_string
            and negated.accepts_non_string
            and not _schema_accepts_all_non_strings_for_string_constraints(
                schema["not"]
            )
        ):
            return None
        shape = shape.intersect(negated.complement())

    return shape


def string_length_fragments_are_disjoint(lhs: Any, rhs: Any) -> bool:
    if _contains_pattern_negation(lhs) or _contains_pattern_negation(rhs):
        return False
    lhs_shape = string_shape_for_schema(drop_string_pattern_keywords(lhs))
    rhs_shape = string_shape_for_schema(drop_string_pattern_keywords(rhs))
    if lhs_shape is None or rhs_shape is None:
        return False
    if lhs_shape.accepts_non_string or rhs_shape.accepts_non_string:
        return False
    return all(
        lhs_interval.intersect(rhs_interval).is_empty()
        for lhs_interval in lhs_shape.normalized_intervals()
        for rhs_interval in rhs_shape.normalized_intervals()
    )


def string_language_fragments_are_disjoint(lhs: Any, rhs: Any) -> bool:
    lhs_shape = string_language_shape_for_schema(lhs)
    rhs_shape = string_language_shape_for_schema(rhs)
    if lhs_shape is None or rhs_shape is None:
        return False
    if lhs_shape.accepts_non_string or rhs_shape.accepts_non_string:
        return False
    disjoint = lhs_shape.pattern.is_disjoint_from(rhs_shape.pattern)
    return False if isinstance(disjoint, ProofResult) else disjoint


def _contains_pattern_negation(schema: Any) -> bool:
    if isinstance(schema, list):
        return any(_contains_pattern_negation(item) for item in schema)
    if not isinstance(schema, dict):
        return False
    negated = schema.get("not")
    if negated is not None and _contains_pattern_keyword(negated):
        return True
    return any(
        _contains_pattern_negation(value)
        for key, value in schema.items()
        if key in {"allOf", "anyOf", "oneOf", "if", "then", "else"}
    )


def _contains_pattern_keyword(schema: Any) -> bool:
    if isinstance(schema, list):
        return any(_contains_pattern_keyword(item) for item in schema)
    if not isinstance(schema, dict):
        return False
    return "pattern" in schema or any(
        _contains_pattern_keyword(value)
        for key, value in schema.items()
        if key in {"allOf", "anyOf", "oneOf", "not", "if", "then", "else"}
    )


def _schema_accepts_all_non_strings_for_string_constraints(schema: Any) -> bool:
    if schema is True:
        return True
    if schema is False or not isinstance(schema, dict):
        return False

    local_string_keywords = {"maxLength", "minLength", "pattern"}
    has_local_string_constraint = False
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key in local_string_keywords:
            has_local_string_constraint = True
            continue
        if key == "allOf" and isinstance(value, list):
            if all(
                _schema_accepts_all_non_strings_for_string_constraints(item)
                for item in value
            ):
                continue
            return False
        if key == "anyOf" and isinstance(value, list):
            if any(
                _schema_accepts_all_non_strings_for_string_constraints(item)
                for item in value
            ):
                continue
            return False
        return False
    return has_local_string_constraint


def drop_string_pattern_keywords(schema: Any) -> Any:
    if isinstance(schema, list):
        return [drop_string_pattern_keywords(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {
        key: drop_string_pattern_keywords(value)
        for key, value in schema.items()
        if key != "pattern"
    }


def string_language_witness(
    pattern: Any, context: ProofContext | None = None
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


def _cacheable_schema_key(schema: Any) -> str | None:
    key = stable_key(schema)
    try:
        strict_json_loads(key)
    except (TypeError, ValueError):
        return None
    return key


def _is_string_length_fragment_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key in STRING_SCHEMA_KEYWORDS:
            if key in {"allOf", "anyOf"} and not isinstance(value, list):
                return False
            if key in {"minLength", "maxLength"} and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                return False
            continue
        return False
    return True


def _is_string_language_fragment_schema(schema: dict[str, Any]) -> bool:
    for key, value in schema.items():
        if key in IGNORED_SCHEMA_METADATA_KEYS:
            continue
        if key in STRING_LANGUAGE_SCHEMA_KEYWORDS:
            if key in {"allOf", "anyOf"} and not isinstance(value, list):
                return False
            if key in {"minLength", "maxLength"} and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                return False
            if key == "pattern" and not isinstance(value, str):
                return False
            if key == "const" and not isinstance(value, str):
                return False
            if key == "enum" and not isinstance(value, list):
                return False
            continue
        return False
    return True


def _local_string_shape(schema: dict[str, Any]) -> StringShape | None:
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        types = {schema_type}
        accepts_non_string = schema_type != "string"
    elif isinstance(schema_type, list):
        if not all(isinstance(item, str) for item in schema_type):
            return None
        types = set(schema_type)
        accepts_non_string = any(item != "string" for item in types)
    elif schema_type is None:
        types = {"string"}
        accepts_non_string = True
    else:
        return None

    if "string" not in types:
        return StringShape((), accepts_non_string=accepts_non_string)

    lower = schema.get("minLength", 0)
    upper = schema.get("maxLength")
    if not isinstance(lower, int) or isinstance(lower, bool):
        return None
    if upper is not None and (not isinstance(upper, int) or isinstance(upper, bool)):
        return None
    return StringShape(
        (StringLengthInterval(lower, upper),), accepts_non_string=accepts_non_string
    )


def _local_string_language_shape(schema: dict[str, Any]) -> StringLanguageShape | None:
    finite_shape = _finite_string_language_shape(schema)
    if finite_shape is not None:
        return finite_shape

    type_shape = type_shape_for_type_keyword(schema.get("type"))
    if type_shape is None:
        return None
    accepts_non_string = any(atom != "string" for atom in type_shape.atoms)
    if "string" not in type_shape.atoms:
        return StringLanguageShape(
            RegexLanguage.empty(), accepts_non_string=accepts_non_string
        )

    lower = schema.get("minLength", 0)
    upper = schema.get("maxLength")
    has_length_constraint = lower != 0 or upper is not None
    if has_length_constraint:
        pattern = _regex_language_for_length_range(lower, upper)
        if pattern is None:
            return None
    else:
        pattern = RegexLanguage.all()

    if "pattern" in schema:
        schema_pattern = RegexLanguage.maybe_from_json_regex(schema["pattern"])
        if schema_pattern is None:
            return None
        if has_length_constraint:
            pattern = _expect_regex_language(pattern.intersection(schema_pattern))
        else:
            pattern = schema_pattern

    return StringLanguageShape(pattern, accepts_non_string=accepts_non_string)


def _finite_string_language_shape(schema: dict[str, Any]) -> StringLanguageShape | None:
    if "const" in schema:
        values: tuple[Any, ...] | None = (schema["const"],)
    elif "enum" in schema:
        values = tuple(schema["enum"]) if isinstance(schema["enum"], list) else None
    else:
        return None
    if values is None:
        return None
    pattern = RegexLanguage.empty()
    accepts_non_string = False
    for value in values:
        if not isinstance(value, str):
            accepts_non_string = True
            continue
        try:
            exact_pattern = RegexLanguage.exact(value)
        except Exception:
            return None
        next_pattern = pattern.union(exact_pattern)
        if isinstance(next_pattern, ProofResult):
            return None
        pattern = next_pattern
    return StringLanguageShape(pattern, accepts_non_string=accepts_non_string)


def _expect_regex_language(value: RegexLanguage | ProofResult) -> RegexLanguage:
    if isinstance(value, ProofResult):
        raise TypeError("unexpected regex proof result in unbudgeted shape operation")
    return value


def _merge_string_intervals(
    intervals: tuple[StringLengthInterval, ...],
) -> tuple[StringLengthInterval, ...]:
    sorted_intervals = sorted(intervals, key=lambda interval: interval.lower)
    merged: list[StringLengthInterval] = []
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
            merged[-1] = StringLengthInterval(previous.lower, upper)
        else:
            merged.append(interval)
    return tuple(merged)


def _string_interval_covered(
    interval: StringLengthInterval,
    covering_intervals: tuple[StringLengthInterval, ...],
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


def _first_uncovered_string_length(
    interval: StringLengthInterval,
    covering_intervals: tuple[StringLengthInterval, ...],
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


def _complement_string_intervals(
    intervals: tuple[StringLengthInterval, ...],
) -> tuple[StringLengthInterval, ...]:
    complements = []
    next_lower = 0
    for interval in intervals:
        if next_lower < interval.lower:
            complements.append(StringLengthInterval(next_lower, interval.lower - 1))
        if interval.upper is None:
            return tuple(complements)
        next_lower = interval.upper + 1
    complements.append(StringLengthInterval(next_lower, None))
    return tuple(complements)


@lru_cache(maxsize=_SCHEMA_SHAPE_CACHE_SIZE)
def _regex_language_for_length_range(
    lower: int, upper: int | None
) -> RegexLanguage | None:
    return RegexLanguage.from_length_range(lower, upper)

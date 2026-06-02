"""
Typed assertion constraints compiled into SchemaIR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from subschema.kernel.domains.arrays import ArrayShape, ArrayUniquenessShape
from subschema.kernel.domains.numbers import NumericShape
from subschema.kernel.domains.objects import (
    ClosedObjectPropertiesShape,
    ObjectPropertyCountShape,
    ObjectPropertyNamesShape,
    ObjectPropertyValuesShape,
)
from subschema.kernel.domains.strings import StringLanguageShape, StringShape
from subschema.kernel.domains.types import TypeShape

__all__ = [
    "ArrayLengthConstraint",
    "ArrayUniquenessConstraint",
    "FiniteConstraint",
    "NumericConstraint",
    "ObjectClosedPropertiesConstraint",
    "ObjectPropertyCountConstraint",
    "ObjectPropertyNamesConstraint",
    "ObjectPropertyValuesConstraint",
    "StringLanguageConstraint",
    "StringLengthConstraint",
    "TypeConstraint",
]


@dataclass(frozen=True)
class FiniteConstraint:
    values: tuple[Any, ...]


@dataclass(frozen=True)
class TypeConstraint:
    shape: TypeShape
    language_complete: bool = True

    @property
    def atoms(self) -> frozenset[str]:
        return self.shape.atoms


@dataclass(frozen=True)
class NumericConstraint:
    shape: NumericShape


@dataclass(frozen=True)
class StringLengthConstraint:
    shape: StringShape


@dataclass(frozen=True)
class StringLanguageConstraint:
    shape: StringLanguageShape


@dataclass(frozen=True)
class ArrayLengthConstraint:
    shape: ArrayShape


@dataclass(frozen=True)
class ArrayUniquenessConstraint:
    shape: ArrayUniquenessShape


@dataclass(frozen=True)
class ObjectPropertyCountConstraint:
    shape: ObjectPropertyCountShape


@dataclass(frozen=True)
class ObjectPropertyNamesConstraint:
    shape: ObjectPropertyNamesShape


@dataclass(frozen=True)
class ObjectPropertyValuesConstraint:
    shape: ObjectPropertyValuesShape


@dataclass(frozen=True)
class ObjectClosedPropertiesConstraint:
    shape: ClosedObjectPropertiesShape


from __future__ import annotations

from typing import Any

from jsonschema.exceptions import SchemaError

__all__ = [
    "ConflictingDialectError",
    "SchemaError",
    "SubschemaError",
    "UnknownDialectError",
    "UnsupportedEnumCanonicalizationError",
    "UnsupportedKeywordError",
    "UnsupportedNegatedArrayError",
    "UnsupportedNegatedObjectError",
    "UnsupportedProofError",
    "UnsupportedRecursiveRefError",
]


class SubschemaError(Exception):
    """Base class for subschema-owned errors."""


class UnsupportedProofError(SubschemaError):
    """Raised when the prover cannot decide a supported public query."""

    def __init__(self, reason: str, *, status: str | None = None):
        self.reason = reason
        self.status = status

    def __str__(self) -> str:
        return self.reason


class _UnsupportedCaseError(SubschemaError):
    pass


class _CanonicalizationError(_UnsupportedCaseError):
    pass


class _SubtypeCheckError(_UnsupportedCaseError):
    pass


class UnsupportedRecursiveRefError(UnsupportedProofError, _CanonicalizationError):
    def __init__(self, schema: Any, which_side: str):
        self.schema = schema
        self.which_side = which_side
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Recursive schemas are not supported. {self.which_side} is recursive."


class UnknownDialectError(_CanonicalizationError):
    def __init__(self, dialect: Any):
        self.dialect = dialect

    def __str__(self) -> str:
        return f"Unknown JSON Schema dialect: {self.dialect!r}."


class ConflictingDialectError(_CanonicalizationError):
    def __init__(self, dialects: Any):
        self.dialects = dialects

    def __str__(self) -> str:
        dialects = ", ".join(str(dialect) for dialect in self.dialects)
        return f"Conflicting JSON Schema dialect declarations: {dialects}."


class UnsupportedKeywordError(UnsupportedProofError, _CanonicalizationError):
    def __init__(self, keyword: str, dialect: Any, path: tuple[str, ...] = ()):
        self.keyword = keyword
        self.dialect = dialect
        self.path = path
        super().__init__(str(self))

    def __str__(self) -> str:
        path = "/".join(self.path) if self.path else "<root>"
        return (
            f"JSON Schema keyword {self.keyword!r} at {path} is not supported "
            f"by subschema for selected dialect {self.dialect} yet."
        )


class UnsupportedEnumCanonicalizationError(
    UnsupportedProofError, _CanonicalizationError
):
    def __init__(self, tau: str, schema: Any):
        self.tau = tau
        self.schema = schema
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Canonicalizing an enum schema of type {self.tau} is not supported."


class UnsupportedNegatedObjectError(UnsupportedProofError, _SubtypeCheckError):
    def __init__(self, schema: Any):
        self.schema = schema
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Object negation at {self.schema} is not supported."


class UnsupportedNegatedArrayError(UnsupportedProofError, _SubtypeCheckError):
    def __init__(self, schema: Any):
        self.schema = schema
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Array negation at {self.schema} is not supported."

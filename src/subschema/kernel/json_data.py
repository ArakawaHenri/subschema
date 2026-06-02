"""
Strict JSON data-model helpers.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, TextIO


def ensure_json_value(value: Any, *, label: str = "value") -> None:
    """Raise ValueError when a Python value is not representable as JSON."""
    _ensure_json_value(value, path=label)


def strict_json_dumps(
    value: Any, *, sort_keys: bool = True, separators: tuple[str, str] = (",", ":")
) -> str:
    ensure_json_value(value)
    return json.dumps(
        value, sort_keys=sort_keys, separators=separators, allow_nan=False
    )


def strict_json_load(fp: TextIO) -> Any:
    return json.load(
        fp,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_reject_duplicate_object_names,
    )


def strict_json_loads(value: str) -> Any:
    return json.loads(
        value,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_reject_duplicate_object_names,
    )


def _ensure_json_value(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"{path} contains a non-finite number, which is not valid JSON"
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(
                    f"{path} contains a non-string object key {key!r}, which is "
                    f"not valid JSON"
                )
            _ensure_json_value(item, path=f"{path}/{_escape_pointer_segment(key)}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        if not isinstance(value, list):
            raise ValueError(
                f"{path} contains {type(value).__name__}, which is not valid JSON"
            )
        for index, item in enumerate(value):
            _ensure_json_value(item, path=f"{path}/{index}")
        return
    raise ValueError(f"{path} contains {type(value).__name__}, which is not valid JSON")


def _reject_json_constant(constant: str) -> None:
    raise ValueError(f"{constant} is not valid JSON")


def _reject_duplicate_object_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate object key {key!r} is not valid strict JSON")
        obj[key] = value
    return obj


def _escape_pointer_segment(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")

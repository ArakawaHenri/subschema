"""
Budgeted regular-language operations for JSON Schema regex fragments.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Hashable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from greenery import parse

from subschema.kernel.contracts import ProofResult, UnsupportedDiagnostic
from subschema.kernel.protocols import RegexWorkContext


class GreeneryFsm(Protocol):
    initial: Any
    finals: set[Any]
    map: dict[Any, dict[Any, Any]]
    states: set[Any]

    def issubset(self, other: GreeneryFsm) -> bool: ...
    def isdisjoint(self, other: GreeneryFsm) -> bool: ...
    def equivalent(self, other: GreeneryFsm) -> bool: ...


class GreeneryPattern(Hashable, Protocol):
    def reduce(self) -> GreeneryPattern: ...
    def empty(self) -> bool: ...
    def everythingbut(self) -> GreeneryPattern: ...
    def difference(self, other: GreeneryPattern) -> GreeneryPattern: ...
    def to_fsm(self) -> GreeneryFsm: ...
    def matches(self, value: str) -> bool: ...
    def __and__(self, other: GreeneryPattern) -> GreeneryPattern: ...
    def __or__(self, other: GreeneryPattern) -> GreeneryPattern: ...


_REGEX_CACHE_SIZE = 4096
_MAX_FAST_WITNESS_LENGTH = 1024
_UNICODE_MAX = 0x10FFFF

_ECMA_WHITESPACE_RANGES = (
    (0x09, 0x0D),
    (0x20, 0x20),
    (0xA0, 0xA0),
    (0x2003, 0x2003),
    (0x2029, 0x2029),
    (0xFEFF, 0xFEFF),
)
_DIGIT_RANGES = ((ord("0"), ord("9")),)
_WORD_RANGES = (
    (ord("0"), ord("9")),
    (ord("A"), ord("Z")),
    (ord("_"), ord("_")),
    (ord("a"), ord("z")),
)
_ECMA_CONTROL_ESCAPES = {
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}
_CHAR_SET_REPRESENTATIVES = (
    "0",
    "1",
    "a",
    "b",
    "c",
    "_",
    "-",
    " ",
    "\t",
    "\n",
    "\r",
    "\f",
    "\v",
    "\u00a0",
    "\ufeff",
    "\u2029",
    "\u2003",
)


@dataclass(frozen=True)
class _RegexCharSet:
    ranges: tuple[tuple[int, int], ...]
    negated: bool = False

    @classmethod
    def empty(cls) -> _RegexCharSet:
        return cls(())

    @classmethod
    def from_ranges(cls, ranges: tuple[tuple[int, int], ...]) -> _RegexCharSet:
        return cls(_normalize_codepoint_ranges(ranges))

    @classmethod
    def singleton(cls, value: str) -> _RegexCharSet:
        return cls(((ord(value), ord(value)),))

    @classmethod
    def range(cls, start: str, end: str) -> _RegexCharSet:
        start_codepoint = ord(start)
        end_codepoint = ord(end)
        if start_codepoint > end_codepoint:
            start_codepoint, end_codepoint = end_codepoint, start_codepoint
        return cls(((start_codepoint, end_codepoint),))

    def complement(self) -> _RegexCharSet:
        return _RegexCharSet(self.ranges, not self.negated)

    def union(self, other: _RegexCharSet) -> _RegexCharSet:
        if not self.negated and not other.negated:
            return _RegexCharSet.from_ranges(self.ranges + other.ranges)
        if self.negated and other.negated:
            return _RegexCharSet(
                _intersect_codepoint_ranges(self.ranges, other.ranges),
                negated=True,
            )
        if self.negated:
            return _RegexCharSet(
                _subtract_codepoint_ranges(self.ranges, other.ranges),
                negated=True,
            )
        return _RegexCharSet(
            _subtract_codepoint_ranges(other.ranges, self.ranges),
            negated=True,
        )

    def contains_codepoint(self, codepoint: int) -> bool:
        contained = any(
            start <= codepoint <= end for start, end in self.ranges
        )
        return not contained if self.negated else contained

    def representative(self) -> str | None:
        preferred = (
            ("a", "0", "1", "b", "c", "_", "-", " ")
            if self.negated
            else _CHAR_SET_REPRESENTATIVES
        )
        for candidate in preferred:
            if self.contains_codepoint(ord(candidate)):
                return candidate
        if self.negated:
            for codepoint in range(0, min(_UNICODE_MAX, 256) + 1):
                if self.contains_codepoint(codepoint):
                    return chr(codepoint)
            return "a" if self.contains_codepoint(ord("a")) else None
        for start, end in self.ranges:
            representative_codepoint = _representative_codepoint_for_range(start, end)
            if representative_codepoint is not None:
                return chr(representative_codepoint)
        return None

    def singleton_codepoint(self) -> int | None:
        if self.negated or len(self.ranges) != 1:
            return None
        start, end = self.ranges[0]
        return start if start == end else None


@dataclass(frozen=True)
class RegexLanguage:
    pattern: GreeneryPattern
    json_pattern: str | None = None
    witness_hint: str | None = None

    def __str__(self) -> str:
        return str(self.pattern)

    @classmethod
    def all(cls) -> RegexLanguage:
        return cls(_all_pattern(), witness_hint="")

    @classmethod
    def empty(cls) -> RegexLanguage:
        return cls(_empty_pattern())

    @classmethod
    def exact(cls, value: str) -> RegexLanguage:
        return cls(_exact_pattern(value), witness_hint=value)

    @classmethod
    def from_json_regex(cls, pattern: str) -> RegexLanguage | ProofResult:
        unsupported = _unsupported_regex_result(pattern)
        if unsupported is not None:
            return unsupported
        try:
            return cls(_json_regex_pattern(pattern), json_pattern=pattern)
        except Exception as err:
            reason = (
                "unsupported-regex-syntax: regex syntax is outside the "
                "supported regular-language fragment"
            )
            return ProofResult.unsupported(
                reason,
                err,
                UnsupportedDiagnostic(
                    "non-regular-regex",
                    reason,
                    keyword="pattern",
                ),
            )

    @classmethod
    def maybe_from_json_regex(cls, pattern: str) -> RegexLanguage | None:
        parsed = cls.from_json_regex(pattern)
        return parsed if isinstance(parsed, RegexLanguage) else None

    @classmethod
    def from_length_range(cls, lower: int, upper: int | None) -> RegexLanguage | None:
        if not isinstance(lower, int) or isinstance(lower, bool):
            return None
        if upper is not None and (
            not isinstance(upper, int) or isinstance(upper, bool)
        ):
            return None
        if upper is not None and lower > upper:
            return cls.empty()
        quantifier = f".{{{lower},}}" if upper is None else f".{{{lower},{upper}}}"
        witness_hint = "a" * lower if lower <= _MAX_FAST_WITNESS_LENGTH else None
        try:
            return cls(parse(quantifier).reduce(), witness_hint=witness_hint)
        except Exception:
            return None

    def is_empty(self) -> bool:
        return self.pattern.empty()

    def matches(self, value: str) -> bool:
        return _pattern_matches(self.pattern, value)

    def intersection(
        self,
        other: RegexLanguage,
        context: RegexWorkContext | None = None,
    ) -> RegexLanguage | ProofResult:
        if self._is_all():
            return other
        if other._is_all():
            return self
        if self._is_empty() or other._is_empty():
            return RegexLanguage.empty()
        exhausted = self._spend_product_states(other, context, "regex intersection")
        if exhausted is not None:
            return exhausted
        return RegexLanguage(_pattern_intersection(self.pattern, other.pattern))

    def union(
        self, other: RegexLanguage, context: RegexWorkContext | None = None
    ) -> RegexLanguage | ProofResult:
        if self._is_all() or other._is_all():
            return RegexLanguage.all()
        if self._is_empty():
            return other
        if other._is_empty():
            return self
        exhausted = self._spend_product_states(other, context, "regex union")
        if exhausted is not None:
            return exhausted
        return RegexLanguage(_pattern_union(self.pattern, other.pattern))

    def complement(
        self, context: RegexWorkContext | None = None
    ) -> RegexLanguage | ProofResult:
        exhausted = self._spend_states(context, "regex complement")
        if exhausted is not None:
            return exhausted
        return RegexLanguage(_pattern_complement(self.pattern))

    def difference(
        self, other: RegexLanguage, context: RegexWorkContext | None = None
    ) -> RegexLanguage | ProofResult:
        if self._is_empty() or other._is_all():
            return RegexLanguage.empty()
        if other._is_empty():
            return self
        exhausted = self._spend_product_states(other, context, "regex difference")
        if exhausted is not None:
            return exhausted
        return RegexLanguage(_pattern_difference(self.pattern, other.pattern))

    def is_subset_of(
        self, other: RegexLanguage, context: RegexWorkContext | None = None
    ) -> bool | ProofResult:
        exhausted = self._spend_product_states(other, context, "regex subset")
        if exhausted is not None:
            return exhausted
        return _pattern_is_subset(self.pattern, other.pattern)

    def is_disjoint_from(
        self, other: RegexLanguage, context: RegexWorkContext | None = None
    ) -> bool | ProofResult:
        exhausted = self._spend_product_states(other, context, "regex disjointness")
        if exhausted is not None:
            return exhausted
        return _pattern_is_disjoint(self.pattern, other.pattern)

    def equivalent_to(
        self, other: RegexLanguage, context: RegexWorkContext | None = None
    ) -> bool | ProofResult:
        exhausted = self._spend_product_states(other, context, "regex equivalence")
        if exhausted is not None:
            return exhausted
        return _pattern_is_equivalent(self.pattern, other.pattern)

    def witness(
        self, context: RegexWorkContext | None = None
    ) -> str | ProofResult | None:
        if self.pattern.empty():
            return None
        fast_witness = self._fast_witness()
        if fast_witness is not None and self._fast_witness_is_verified(fast_witness):
            return fast_witness
        witness, visited_states = _pattern_shortest_witness(self.pattern)
        if context is not None:
            exhausted = context.spend_work(
                visited_states,
                "regex witness",
                "regex product exceeded proof work budget",
            )
            if exhausted is not None:
                return exhausted
        return witness

    def intersection_witness(
        self,
        other: RegexLanguage,
        context: RegexWorkContext | None = None,
    ) -> str | ProofResult | None:
        witness, visited_states = _pattern_intersection_witness(
            self.pattern, other.pattern
        )
        if context is not None:
            exhausted = context.spend_work(
                visited_states,
                "regex witness",
                "regex product exceeded proof work budget",
            )
            if exhausted is not None:
                return exhausted
        return witness

    def finite_strings(self, *, max_values: int) -> tuple[str, ...] | None:
        return _pattern_finite_strings(self.pattern, max_values)

    def _spend_states(
        self, context: RegexWorkContext | None, kind: str
    ) -> ProofResult | None:
        if context is None:
            return None
        return context.spend_work(
            self._state_count(), kind, "regex product exceeded proof work budget"
        )

    def _spend_product_states(
        self,
        other: RegexLanguage,
        context: RegexWorkContext | None,
        kind: str,
    ) -> ProofResult | None:
        if context is None:
            return None
        return context.spend_work(
            self._state_count() * other._state_count(),
            kind,
            "regex product exceeded proof work budget",
        )

    def _state_count(self) -> int:
        return _pattern_state_count(self.pattern)

    def _is_all(self) -> bool:
        return self.pattern is _all_pattern()

    def _is_empty(self) -> bool:
        return self.pattern is _empty_pattern()

    def _fast_witness(self) -> str | None:
        if self.witness_hint is not None:
            return self.witness_hint
        if self.json_pattern is None:
            return None
        return _fast_json_regex_witness(self.json_pattern)

    def _fast_witness_is_verified(self, witness: str) -> bool:
        if self.json_pattern is not None:
            matched = _fast_json_regex_matches(self.json_pattern, witness)
            if matched is not None:
                return matched
        return self.matches(witness)


@lru_cache(maxsize=1)
def _all_pattern() -> GreeneryPattern:
    return parse(".*")


@lru_cache(maxsize=1)
def _empty_pattern() -> GreeneryPattern:
    return parse("[]")


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _exact_pattern(value: str) -> GreeneryPattern:
    return parse(
        "".join(_greenery_literal(char, in_class=False) for char in value)
    ).reduce()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _json_regex_pattern(pattern: str) -> GreeneryPattern:
    return parse(
        _prepare_pattern_for_greenery(_json_regex_unanchor(_ecma_dot_pattern(pattern)))
    ).reduce()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_intersection(
    lhs: GreeneryPattern, rhs: GreeneryPattern
) -> GreeneryPattern:
    return (lhs & rhs).reduce()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_union(lhs: GreeneryPattern, rhs: GreeneryPattern) -> GreeneryPattern:
    return (lhs | rhs).reduce()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_complement(pattern: GreeneryPattern) -> GreeneryPattern:
    return pattern.everythingbut().reduce()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_difference(lhs: GreeneryPattern, rhs: GreeneryPattern) -> GreeneryPattern:
    return lhs.difference(rhs).reduce()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_is_subset(lhs: GreeneryPattern, rhs: GreeneryPattern) -> bool:
    return _pattern_fsm(lhs).issubset(_pattern_fsm(rhs))


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_is_disjoint(lhs: GreeneryPattern, rhs: GreeneryPattern) -> bool:
    return _pattern_fsm(lhs).isdisjoint(_pattern_fsm(rhs))


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_is_equivalent(lhs: GreeneryPattern, rhs: GreeneryPattern) -> bool:
    return _pattern_fsm(lhs).equivalent(_pattern_fsm(rhs))


@lru_cache(maxsize=_REGEX_CACHE_SIZE * 8)
def _pattern_matches(pattern: GreeneryPattern, value: str) -> bool:
    return pattern.matches(value)


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_state_count(pattern: GreeneryPattern) -> int:
    try:
        return max(len(_pattern_fsm(pattern).states), 1)
    except Exception:
        return 1


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_fsm(pattern: GreeneryPattern) -> GreeneryFsm:
    return pattern.to_fsm()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_shortest_witness(pattern: GreeneryPattern) -> tuple[str | None, int]:
    try:
        fsm = _pattern_fsm(pattern)
    except Exception:
        return None, 1

    queue = deque([(fsm.initial, "")])
    seen = {fsm.initial}
    visited_states = 0
    while queue:
        state, value = queue.popleft()
        visited_states += 1
        if state in fsm.finals:
            return value, visited_states
        for charclass, next_state in sorted(
            fsm.map.get(state, {}).items(), key=lambda item: str(item[0])
        ):
            if next_state in seen:
                continue
            representative = _representative_for_charclass(charclass)
            if representative is None:
                continue
            seen.add(next_state)
            queue.append((next_state, value + representative))
    return None, max(visited_states, 1)


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_intersection_witness(
    lhs: GreeneryPattern, rhs: GreeneryPattern
) -> tuple[str | None, int]:
    try:
        lhs_fsm = _pattern_fsm(lhs)
        rhs_fsm = _pattern_fsm(rhs)
    except Exception:
        return None, 1

    start = (lhs_fsm.initial, rhs_fsm.initial)
    queue = deque([(start, "")])
    seen = {start}
    visited_states = 0
    while queue:
        (lhs_state, rhs_state), value = queue.popleft()
        visited_states += 1
        if lhs_state in lhs_fsm.finals and rhs_state in rhs_fsm.finals:
            return value, visited_states
        lhs_transitions = sorted(
            lhs_fsm.map.get(lhs_state, {}).items(), key=lambda item: str(item[0])
        )
        rhs_transitions = sorted(
            rhs_fsm.map.get(rhs_state, {}).items(), key=lambda item: str(item[0])
        )
        for lhs_charclass, next_lhs_state in lhs_transitions:
            for rhs_charclass, next_rhs_state in rhs_transitions:
                charclass = lhs_charclass & rhs_charclass
                representative = _representative_for_charclass(charclass)
                if representative is None:
                    continue
                next_state = (next_lhs_state, next_rhs_state)
                if next_state in seen:
                    continue
                seen.add(next_state)
                queue.append((next_state, value + representative))
    return None, max(visited_states, 1)


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_finite_strings(
    pattern: GreeneryPattern, max_values: int
) -> tuple[str, ...] | None:
    try:
        fsm = _pattern_fsm(pattern)
    except Exception:
        return None
    if max_values < 0:
        return None

    productive = _productive_fsm_states(fsm)
    if fsm.initial not in productive:
        return ()
    if _productive_fsm_has_cycle(fsm, productive):
        return None

    values: list[str] = []

    def visit(state: Any, prefix: str) -> bool:
        if state in fsm.finals:
            values.append(prefix)
            if len(values) > max_values:
                return False
        for charclass, next_state in sorted(
            fsm.map.get(state, {}).items(), key=lambda item: str(item[0])
        ):
            if next_state not in productive:
                continue
            chars = _characters_for_charclass(charclass, max_values)
            if chars is None:
                return False
            for char in chars:
                if not visit(next_state, prefix + char):
                    return False
        return True

    return tuple(values) if visit(fsm.initial, "") else None


def _productive_fsm_states(fsm: Any) -> set[Any]:
    reachable = set()
    stack = [fsm.initial]
    while stack:
        state = stack.pop()
        if state in reachable:
            continue
        reachable.add(state)
        stack.extend(fsm.map.get(state, {}).values())

    reverse: dict[Any, set[Any]] = {state: set() for state in fsm.states}
    for state, transitions in fsm.map.items():
        for next_state in transitions.values():
            reverse.setdefault(next_state, set()).add(state)

    can_reach_final = set()
    stack = list(fsm.finals)
    while stack:
        state = stack.pop()
        if state in can_reach_final:
            continue
        can_reach_final.add(state)
        stack.extend(reverse.get(state, ()))

    return reachable & can_reach_final


def _productive_fsm_has_cycle(fsm: Any, productive: set[Any]) -> bool:
    visiting: set[Any] = set()
    visited: set[Any] = set()

    def visit(state: Any) -> bool:
        if state in visiting:
            return True
        if state in visited:
            return False
        visiting.add(state)
        for next_state in fsm.map.get(state, {}).values():
            if next_state in productive and visit(next_state):
                return True
        visiting.remove(state)
        visited.add(state)
        return False

    return visit(fsm.initial)


def _characters_for_charclass(
    charclass: Any, max_values: int
) -> tuple[str, ...] | None:
    if getattr(charclass, "negated", False):
        return None
    chars: list[str] = []
    for start, end in getattr(charclass, "ord_ranges", ()):
        if end < start:
            continue
        if len(chars) + (end - start + 1) > max_values:
            return None
        chars.extend(chr(codepoint) for codepoint in range(start, end + 1))
    return tuple(chars)


def _representative_for_charclass(charclass: Any) -> str | None:
    preferred = ("a", "b", "c", "0", "1", "_", "-", " ")
    for candidate in preferred:
        try:
            if charclass.accepts(candidate):
                return candidate
        except Exception:
            pass
    for start, end in getattr(charclass, "ord_ranges", ()):
        codepoint = _representative_codepoint_for_range(start, end)
        if codepoint is None:
            continue
        candidate = chr(codepoint)
        try:
            if charclass.accepts(candidate):
                return candidate
        except Exception:
            continue
    if getattr(charclass, "negated", False):
        for candidate in preferred:
            try:
                if charclass.accepts(candidate):
                    return candidate
            except Exception:
                continue
    return None


def _representative_codepoint_for_range(start: int, end: int) -> int | None:
    for codepoint in (max(start, 32), start, end):
        if start <= codepoint <= end and 0 <= codepoint <= 0x10FFFF:
            return codepoint
    return None


def _normalize_codepoint_ranges(
    ranges: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    normalized: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        start = max(0, min(start, _UNICODE_MAX))
        end = max(0, min(end, _UNICODE_MAX))
        if end < start:
            start, end = end, start
        if normalized and start <= normalized[-1][1] + 1:
            previous_start, previous_end = normalized[-1]
            normalized[-1] = (previous_start, max(previous_end, end))
        else:
            normalized.append((start, end))
    return tuple(normalized)


def _subtract_codepoint_ranges(
    lhs: tuple[tuple[int, int], ...],
    rhs: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    remaining = list(_normalize_codepoint_ranges(lhs))
    for rhs_start, rhs_end in _normalize_codepoint_ranges(rhs):
        next_remaining: list[tuple[int, int]] = []
        for start, end in remaining:
            if rhs_end < start or rhs_start > end:
                next_remaining.append((start, end))
                continue
            if start < rhs_start:
                next_remaining.append((start, rhs_start - 1))
            if rhs_end < end:
                next_remaining.append((rhs_end + 1, end))
        remaining = next_remaining
    return tuple(remaining)


def _intersect_codepoint_ranges(
    lhs: tuple[tuple[int, int], ...],
    rhs: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    intersections: list[tuple[int, int]] = []
    for lhs_start, lhs_end in _normalize_codepoint_ranges(lhs):
        for rhs_start, rhs_end in _normalize_codepoint_ranges(rhs):
            start = max(lhs_start, rhs_start)
            end = min(lhs_end, rhs_end)
            if start <= end:
                intersections.append((start, end))
    return _normalize_codepoint_ranges(tuple(intersections))


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _fast_json_regex_witness(pattern: str) -> str | None:
    pattern = _strip_supported_anchors(pattern)
    parsed = _parse_fast_regex_alternation(pattern, 0, stop_chars=frozenset())
    if parsed is None:
        return None
    witness, index = parsed
    if index != len(pattern) or len(witness) > _MAX_FAST_WITNESS_LENGTH:
        return None
    return witness


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _fast_json_regex_matches(pattern: str, value: str) -> bool | None:
    if "\\c" in pattern or _has_ecma_whitespace_escape(pattern):
        return None
    python_pattern = _strict_python_end_anchor(pattern)
    try:
        return re.search(python_pattern, value) is not None
    except re.error:
        return None


def _parse_fast_regex_alternation(
    pattern: str, index: int, *, stop_chars: frozenset[str]
) -> tuple[str, int] | None:
    alternatives: list[str] = []
    current_index = index
    while True:
        parsed = _parse_fast_regex_sequence(
            pattern, current_index, stop_chars=stop_chars | {"|"}
        )
        if parsed is None:
            return None
        witness, current_index = parsed
        alternatives.append(witness)
        if current_index >= len(pattern) or pattern[current_index] != "|":
            break
        current_index += 1
    if not alternatives:
        return None
    return min(alternatives, key=len), current_index


def _parse_fast_regex_sequence(
    pattern: str, index: int, *, stop_chars: frozenset[str]
) -> tuple[str, int] | None:
    parts: list[str] = []
    current_index = index
    while current_index < len(pattern) and pattern[current_index] not in stop_chars:
        parsed = _parse_fast_regex_piece(pattern, current_index)
        if parsed is None:
            return None
        witness, current_index = parsed
        parts.append(witness)
        if sum(len(part) for part in parts) > _MAX_FAST_WITNESS_LENGTH:
            return None
    return "".join(parts), current_index


def _parse_fast_regex_piece(pattern: str, index: int) -> tuple[str, int] | None:
    parsed = _parse_fast_regex_atom(pattern, index)
    if parsed is None:
        return None
    atom, index = parsed
    repeat = _parse_fast_regex_quantifier(pattern, index)
    if repeat is None:
        return atom, index
    minimum, index = repeat
    if len(atom) * minimum > _MAX_FAST_WITNESS_LENGTH:
        return None
    return atom * minimum, index


def _parse_fast_regex_atom(pattern: str, index: int) -> tuple[str, int] | None:
    if index >= len(pattern):
        return None
    char = pattern[index]
    if char == "\\":
        return _parse_fast_regex_escape(pattern, index)
    if char == "[":
        return _parse_fast_charclass(pattern, index)
    if char == "(":
        parsed = _parse_fast_regex_alternation(
            pattern, index + 1, stop_chars=frozenset({")"})
        )
        if parsed is None:
            return None
        witness, next_index = parsed
        if next_index >= len(pattern) or pattern[next_index] != ")":
            return None
        return witness, next_index + 1
    if char == ".":
        return "a", index + 1
    if char in "*+?{}[]()|":
        return None
    return char, index + 1


def _parse_fast_regex_escape(pattern: str, index: int) -> tuple[str, int] | None:
    literal_escape = _ecma_literal_escape(pattern, index)
    if literal_escape is not None:
        return literal_escape
    if index + 1 >= len(pattern):
        return None
    escaped = pattern[index + 1]
    if escaped in _ECMA_CONTROL_ESCAPES:
        return _ECMA_CONTROL_ESCAPES[escaped], index + 2
    char_set = _ecma_escape_char_set(escaped)
    if char_set is not None:
        representative = char_set.representative()
        return (representative, index + 2) if representative is not None else None
    return escaped, index + 2


def _parse_fast_charclass(pattern: str, index: int) -> tuple[str, int] | None:
    parsed = _parse_ecma_charclass(pattern, index)
    if parsed is None:
        return None
    char_set, next_index = parsed
    representative = char_set.representative()
    return (representative, next_index) if representative is not None else None


def _representative_for_codepoint_range(start: str, end: str) -> str:
    start_ord = ord(start)
    end_ord = ord(end)
    if start_ord > end_ord:
        start_ord, end_ord = end_ord, start_ord
    for preferred in ("0", "1", "a", "b", "c"):
        codepoint = ord(preferred)
        if start_ord <= codepoint <= end_ord:
            return preferred
    return chr(start_ord)


def _parse_fast_regex_quantifier(pattern: str, index: int) -> tuple[int, int] | None:
    if index >= len(pattern):
        return None
    char = pattern[index]
    if char in "?*":
        return 0, index + 1
    if char == "+":
        return 1, index + 1
    if char != "{":
        return None
    match = re.match(r"\{([0-9]+)(?:,([0-9]*))?\}", pattern[index:])
    if match is None:
        return None
    return int(match.group(1)), index + match.end()


def _strip_supported_anchors(pattern: str) -> str:
    if _has_unescaped_leading_caret(pattern):
        pattern = pattern[1:]
    if _has_unescaped_trailing_dollar(pattern):
        pattern = pattern[:-1]
    return pattern


def _strict_python_end_anchor(pattern: str) -> str:
    if _has_unescaped_trailing_dollar(pattern):
        return pattern[:-1] + r"\Z"
    return pattern


def _ecma_escape_char_set(escaped: str) -> _RegexCharSet | None:
    if escaped == "d":
        return _RegexCharSet.from_ranges(_DIGIT_RANGES)
    if escaped == "D":
        return _RegexCharSet.from_ranges(_DIGIT_RANGES).complement()
    if escaped == "w":
        return _RegexCharSet.from_ranges(_WORD_RANGES)
    if escaped == "W":
        return _RegexCharSet.from_ranges(_WORD_RANGES).complement()
    if escaped == "s":
        return _RegexCharSet.from_ranges(_ECMA_WHITESPACE_RANGES)
    if escaped == "S":
        return _RegexCharSet.from_ranges(_ECMA_WHITESPACE_RANGES).complement()
    return None


def _parse_ecma_charclass(
    pattern: str,
    index: int,
) -> tuple[_RegexCharSet, int] | None:
    if index >= len(pattern) or pattern[index] != "[":
        return None
    current_index = index + 1
    negated = False
    if current_index < len(pattern) and pattern[current_index] == "^":
        negated = True
        current_index += 1

    char_set = _RegexCharSet.empty()
    saw_item = False
    while current_index < len(pattern):
        if pattern[current_index] == "]" and saw_item:
            if negated:
                char_set = char_set.complement()
            return char_set, current_index + 1
        parsed = _parse_ecma_charclass_item(pattern, current_index)
        if parsed is None:
            return None
        item_set, endpoint, next_index = parsed
        if (
            endpoint is not None
            and next_index < len(pattern)
            and pattern[next_index] == "-"
            and next_index + 1 < len(pattern)
            and pattern[next_index + 1] != "]"
        ):
            range_end = _parse_ecma_charclass_item(pattern, next_index + 1)
            if range_end is None:
                return None
            _, end_endpoint, current_index = range_end
            if end_endpoint is None:
                return None
            char_set = char_set.union(
                _RegexCharSet.range(chr(endpoint), chr(end_endpoint))
            )
        else:
            char_set = char_set.union(item_set)
            current_index = next_index
        saw_item = True
    return None


def _parse_ecma_charclass_item(
    pattern: str,
    index: int,
) -> tuple[_RegexCharSet, int | None, int] | None:
    if index >= len(pattern):
        return None
    if pattern[index] != "\\":
        codepoint = ord(pattern[index])
        return _RegexCharSet.singleton(pattern[index]), codepoint, index + 1

    literal_escape = _ecma_literal_escape(pattern, index)
    if literal_escape is not None:
        literal, next_index = literal_escape
        codepoint = ord(literal)
        return _RegexCharSet.singleton(literal), codepoint, next_index
    if index + 1 >= len(pattern):
        return None
    escaped = pattern[index + 1]
    if escaped in _ECMA_CONTROL_ESCAPES:
        literal = _ECMA_CONTROL_ESCAPES[escaped]
        codepoint = ord(literal)
        return _RegexCharSet.singleton(literal), codepoint, index + 2
    if escaped == "b":
        return None
    char_set = _ecma_escape_char_set(escaped)
    if char_set is not None:
        return char_set, char_set.singleton_codepoint(), index + 2
    return _RegexCharSet.singleton(escaped), ord(escaped), index + 2


def _render_char_set_for_greenery(char_set: _RegexCharSet) -> str:
    if not char_set.negated and not char_set.ranges:
        return "[]"
    if char_set.negated and not char_set.ranges:
        return "."
    prefix = "^" if char_set.negated else ""
    body = "".join(
        _render_charclass_range_for_greenery(start, end)
        for start, end in char_set.ranges
    )
    return f"[{prefix}{body}]"


def _render_charclass_range_for_greenery(start: int, end: int) -> str:
    if start == end:
        return _greenery_literal(chr(start), in_class=True)
    return (
        _greenery_literal(chr(start), in_class=True)
        + "-"
        + _greenery_literal(chr(end), in_class=True)
    )


def _prepare_pattern_for_greenery(pattern: str) -> str:
    transformed = []
    in_class = False
    class_start = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "[" and not in_class:
            parsed_charclass = _parse_ecma_charclass(pattern, index)
            if parsed_charclass is not None:
                char_set, next_index = parsed_charclass
                transformed.append(_render_char_set_for_greenery(char_set))
                index = next_index
                class_start = False
                continue
            in_class = True
            class_start = True
            transformed.append(char)
            index += 1
            continue
        if char == "\\":
            escape = _ecma_literal_escape(pattern, index)
            if escape is not None:
                literal, next_index = escape
                transformed.append(_greenery_literal(literal, in_class=in_class))
                index = next_index
                class_start = False
                continue
            if index + 1 >= len(pattern):
                transformed.append("\\")
                index += 1
                class_start = False
                continue
            escaped_char = pattern[index + 1]
            if escaped_char in _ECMA_CONTROL_ESCAPES:
                transformed.append(
                    _greenery_literal(
                        _ECMA_CONTROL_ESCAPES[escaped_char],
                        in_class=in_class,
                    )
                )
            else:
                escape_char_set = _ecma_escape_char_set(escaped_char)
                if escape_char_set is not None:
                    transformed.append(_render_char_set_for_greenery(escape_char_set))
                elif escaped_char == "^":
                    transformed.append("\\^" if in_class else "^")
                elif escaped_char == "$":
                    transformed.append("$")
                else:
                    transformed.extend(("\\", escaped_char))
            index += 2
            class_start = False
            continue
        if char == "]" and in_class and not class_start:
            in_class = False
            transformed.append(char)
            index += 1
            continue
        if char == "^" and in_class and not class_start:
            transformed.append("\\^")
            index += 1
            class_start = False
            continue
        if char in "^$" and not in_class:
            index += 1
            class_start = False
            continue
        transformed.append(char)
        index += 1
        class_start = False
    return "".join(transformed)


def _ecma_literal_escape(pattern: str, index: int) -> tuple[str, int] | None:
    if pattern.startswith("\\x", index) and _is_hex_escape(pattern, index + 2, 2):
        return chr(int(pattern[index + 2 : index + 4], 16)), index + 4
    if pattern.startswith("\\u", index) and _is_hex_escape(pattern, index + 2, 4):
        return chr(int(pattern[index + 2 : index + 6], 16)), index + 6
    if (
        index + 2 < len(pattern)
        and pattern[index + 1] == "c"
        and pattern[index + 2].isalpha()
    ):
        return chr(ord(pattern[index + 2].upper()) - 64), index + 3
    return None


def _is_hex_escape(pattern: str, start: int, length: int) -> bool:
    end = start + length
    if end > len(pattern):
        return False
    return all(char in "0123456789abcdefABCDEF" for char in pattern[start:end])


def _greenery_literal(value: str, *, in_class: bool) -> str:
    if in_class:
        if value == "^":
            return "\\^"
        if value == "$":
            return "$"
        if value in {"\\", "[", "]", "-"}:
            return "\\" + value
        return value
    if value in {"^", "$", "-"}:
        return value
    if value in {"\\", "(", ")", "[", "]", "{", "}", ".", "*", "+", "?", "|"}:
        return "\\" + value
    return value


def _ecma_dot_pattern(pattern: str) -> str:
    transformed = []
    escaped = False
    in_class = False
    class_start = False
    for char in pattern:
        if escaped:
            transformed.append(char)
            escaped = False
            class_start = False
            continue
        if char == "\\":
            transformed.append(char)
            escaped = True
            continue
        if char == "[" and not in_class:
            in_class = True
            class_start = True
            transformed.append(char)
            continue
        if char == "]" and in_class and not class_start:
            in_class = False
            transformed.append(char)
            continue
        if char == "." and not in_class:
            transformed.append("[^\n]")
            class_start = False
            continue
        transformed.append(char)
        class_start = False
    return "".join(transformed)


def _json_regex_unanchor(pattern: str) -> str:
    if not pattern:
        return ".*"
    has_leading_anchor = _has_unescaped_leading_caret(pattern)
    has_trailing_anchor = _has_unescaped_trailing_dollar(pattern)
    if has_leading_anchor:
        pattern = pattern[1:]
    elif not pattern.startswith(".*"):
        pattern = ".*" + pattern
    if has_trailing_anchor:
        pattern = pattern[:-1]
    elif not pattern.endswith(".*"):
        pattern = pattern + ".*"
    return pattern


def _unsupported_regex_result(pattern: str) -> ProofResult | None:
    reason = _unsupported_regex_reason(pattern)
    if reason is None:
        return None
    return ProofResult.unsupported(
        reason,
        diagnostics=UnsupportedDiagnostic(
            "non-regular-regex",
            reason,
            keyword="pattern",
        ),
    )


def _unsupported_regex_reason(pattern: str) -> str | None:
    if re.search(r"(?<!\\)\\(?:[1-9]|k<)", pattern) or "(?P=" in pattern:
        return "non-regular-regex: backreferences are unsupported"
    if any(
        token in pattern for token in ("(?=", "(?!", "(?<=", "(?<!")
    ) or _has_word_boundary_assertion(pattern):
        return "non-regular-regex: lookaround/zero-width assertions are unsupported"
    if _has_ecma_nul_or_octal_escape(pattern):
        return (
            "unsupported-regex-syntax: NUL/octal escapes are outside the "
            "supported validation backend"
        )
    if any(token in pattern for token in ("(?R", "(?0", "(?&", "(?P>", "(?(")):
        return (
            "non-regular-regex: recursive or conditional regex constructs "
            "are unsupported"
        )
    if _has_unsupported_anchor_placement(pattern):
        return (
            "unsupported-regex-syntax: anchors are only supported at the "
            "start/end of a pattern"
        )
    return None


def _has_unescaped_leading_caret(pattern: str) -> bool:
    return bool(pattern) and pattern[0] == "^"


def _has_word_boundary_assertion(pattern: str) -> bool:
    return _has_unescaped_escape(pattern, {"b", "B"}, outside_charclass_only=True)


def _has_ecma_whitespace_escape(pattern: str) -> bool:
    return _has_unescaped_escape(pattern, {"s", "S"}, outside_charclass_only=False)


def _has_ecma_nul_or_octal_escape(pattern: str) -> bool:
    return _has_unescaped_escape(pattern, {"0"}, outside_charclass_only=False)


def _has_unescaped_escape(
    pattern: str,
    escape_chars: set[str],
    *,
    outside_charclass_only: bool,
) -> bool:
    escaped = False
    in_class = False
    for char in pattern:
        if escaped:
            if (not outside_charclass_only or not in_class) and char in escape_chars:
                return True
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "[":
            in_class = True
            continue
        if char == "]" and in_class:
            in_class = False
    return False


def _has_unescaped_trailing_dollar(pattern: str) -> bool:
    return _unescaped_anchor_positions(pattern, "$") == [len(pattern) - 1]


def _has_unsupported_anchor_placement(pattern: str) -> bool:
    for position in _unescaped_anchor_positions(pattern, "^"):
        if position != 0:
            return True
    for position in _unescaped_anchor_positions(pattern, "$"):
        if position != len(pattern) - 1:
            return True
    return False


def _unescaped_anchor_positions(pattern: str, anchor: str) -> list[int]:
    positions = []
    escaped = False
    in_class = False
    class_start = False
    for index, char in enumerate(pattern):
        if escaped:
            escaped = False
            class_start = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "[" and not in_class:
            in_class = True
            class_start = True
            continue
        if char == "]" and in_class and not class_start:
            in_class = False
            continue
        if char == anchor and not in_class:
            positions.append(index)
        class_start = False
    return positions

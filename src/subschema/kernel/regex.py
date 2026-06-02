"""
Budgeted regular-language operations for JSON Schema regex fragments.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from greenery import parse

from subschema.kernel.contracts import ProofResult, UnsupportedDiagnostic

if TYPE_CHECKING:
    from subschema.kernel.context import ProofContext


_REGEX_CACHE_SIZE = 4096
_MAX_FAST_WITNESS_LENGTH = 1024


@dataclass(frozen=True)
class RegexLanguage:
    pattern: Any
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
        context: ProofContext | None = None,
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
        self, other: RegexLanguage, context: ProofContext | None = None
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
        self, context: ProofContext | None = None
    ) -> RegexLanguage | ProofResult:
        exhausted = self._spend_states(context, "regex complement")
        if exhausted is not None:
            return exhausted
        return RegexLanguage(_pattern_complement(self.pattern))

    def difference(
        self, other: RegexLanguage, context: ProofContext | None = None
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
        self, other: RegexLanguage, context: ProofContext | None = None
    ) -> bool | ProofResult:
        exhausted = self._spend_product_states(other, context, "regex subset")
        if exhausted is not None:
            return exhausted
        return _pattern_is_subset(self.pattern, other.pattern)

    def is_disjoint_from(
        self, other: RegexLanguage, context: ProofContext | None = None
    ) -> bool | ProofResult:
        exhausted = self._spend_product_states(other, context, "regex disjointness")
        if exhausted is not None:
            return exhausted
        return _pattern_is_disjoint(self.pattern, other.pattern)

    def equivalent_to(
        self, other: RegexLanguage, context: ProofContext | None = None
    ) -> bool | ProofResult:
        exhausted = self._spend_product_states(other, context, "regex equivalence")
        if exhausted is not None:
            return exhausted
        return _pattern_is_equivalent(self.pattern, other.pattern)

    def witness(self, context: ProofContext | None = None) -> str | ProofResult | None:
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
        context: ProofContext | None = None,
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
        self, context: ProofContext | None, kind: str
    ) -> ProofResult | None:
        if context is None:
            return None
        return context.spend_work(
            self._state_count(), kind, "regex product exceeded proof work budget"
        )

    def _spend_product_states(
        self,
        other: RegexLanguage,
        context: ProofContext | None,
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
def _all_pattern() -> Any:
    return parse(".*")


@lru_cache(maxsize=1)
def _empty_pattern() -> Any:
    return parse("[]")


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _exact_pattern(value: str) -> Any:
    return parse(_prepare_pattern_for_greenery(re.escape(value))).reduce()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _json_regex_pattern(pattern: str) -> Any:
    return parse(
        _prepare_pattern_for_greenery(_json_regex_unanchor(_ecma_dot_pattern(pattern)))
    ).reduce()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_intersection(lhs: Any, rhs: Any) -> Any:
    return (lhs & rhs).reduce()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_union(lhs: Any, rhs: Any) -> Any:
    return (lhs | rhs).reduce()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_complement(pattern: Any) -> Any:
    return pattern.everythingbut().reduce()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_difference(lhs: Any, rhs: Any) -> Any:
    return lhs.difference(rhs).reduce()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_is_subset(lhs: Any, rhs: Any) -> bool:
    return _pattern_fsm(lhs).issubset(_pattern_fsm(rhs))


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_is_disjoint(lhs: Any, rhs: Any) -> bool:
    return _pattern_fsm(lhs).isdisjoint(_pattern_fsm(rhs))


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_is_equivalent(lhs: Any, rhs: Any) -> bool:
    return _pattern_fsm(lhs).equivalent(_pattern_fsm(rhs))


@lru_cache(maxsize=_REGEX_CACHE_SIZE * 8)
def _pattern_matches(pattern: Any, value: str) -> bool:
    return pattern.matches(value)


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_state_count(pattern: Any) -> int:
    try:
        return max(len(_pattern_fsm(pattern).states), 1)
    except Exception:
        return 1


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_fsm(pattern: Any) -> Any:
    return pattern.to_fsm()


@lru_cache(maxsize=_REGEX_CACHE_SIZE)
def _pattern_shortest_witness(pattern: Any) -> tuple[str | None, int]:
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
def _pattern_intersection_witness(lhs: Any, rhs: Any) -> tuple[str | None, int]:
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
def _pattern_finite_strings(pattern: Any, max_values: int) -> tuple[str, ...] | None:
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
    if "\\c" in pattern:
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
    if escaped == "d":
        return "0", index + 2
    if escaped == "D":
        return "a", index + 2
    if escaped == "w":
        return "a", index + 2
    if escaped == "W":
        return "-", index + 2
    return escaped, index + 2


def _parse_fast_charclass(pattern: str, index: int) -> tuple[str, int] | None:
    current_index = index + 1
    if current_index < len(pattern) and pattern[current_index] == "^":
        return None
    representatives: list[str] = []
    while current_index < len(pattern):
        if pattern[current_index] == "]" and current_index > index + 1:
            representative = _choose_fast_charclass_representative(representatives)
            if representative is None:
                return None
            return representative, current_index + 1
        parsed = _parse_fast_charclass_char(pattern, current_index)
        if parsed is None:
            return None
        char, next_index = parsed
        if (
            next_index < len(pattern)
            and pattern[next_index] == "-"
            and next_index + 1 < len(pattern)
            and pattern[next_index + 1] != "]"
        ):
            range_end = _parse_fast_charclass_char(pattern, next_index + 1)
            if range_end is None:
                return None
            end_char, current_index = range_end
            representatives.append(_representative_for_codepoint_range(char, end_char))
            continue
        representatives.append(char)
        current_index = next_index
    return None


def _parse_fast_charclass_char(
    pattern: str, index: int
) -> tuple[str, int] | None:
    if index >= len(pattern):
        return None
    if pattern[index] == "\\":
        return _parse_fast_regex_escape(pattern, index)
    return pattern[index], index + 1


def _choose_fast_charclass_representative(
    representatives: list[str],
) -> str | None:
    if not representatives:
        return None
    for preferred in ("0", "1", "a", "b", "c", "_", "-", " "):
        if preferred in representatives:
            return preferred
    return representatives[0]


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


def _prepare_pattern_for_greenery(pattern: str) -> str:
    transformed = []
    in_class = False
    class_start = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
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
            if escaped_char == "^":
                transformed.append("\\^" if in_class else "^")
            elif escaped_char == "$":
                transformed.append("$")
            else:
                transformed.extend(("\\", escaped_char))
            index += 2
            class_start = False
            continue
        if char == "[" and not in_class:
            in_class = True
            class_start = True
            transformed.append(char)
            index += 1
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
    if _has_ecma_whitespace_escape(pattern):
        return (
            "unsupported-regex-syntax: ECMA whitespace escapes are "
            "outside the supported regex frontend"
        )
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

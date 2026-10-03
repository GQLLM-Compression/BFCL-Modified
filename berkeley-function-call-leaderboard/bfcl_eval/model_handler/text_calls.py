"""Tool calls that arrive as text: one of the two changes BFCL-Modified makes (see MODIFICATIONS.md).

BFCL's function-calling path reads a call only from the reply's `tool_calls` slot. An endpoint whose
serving stack does not parse the model's own call syntax puts the call into `content` instead, and
BFCL then scores a reply without any call although the model did call the tool. BFCL-Modified
credits such a reply as the call it is; BFCL's own checker then scores that call exactly as it
scores a structured one.

A reply is credited only when all of these hold, so prose that merely mentions a function is never
mistaken for a call:

- the reply ends with the call(s): everything before them is a lead-in, nothing follows them;
- every call names a tool the request offered (a dotted spelling of an underscored name counts);
- every argument is a literal value: keywords with literals in the Python form, a JSON object in
  the JSON forms. Positional arguments, names, expressions and `**kwargs` are not credited, because
  which parameter a positional value belongs to would be a guess.

The forms read: a Python call list or single call (`[f(a=1), g(b="x")]`), a JSON object or list with
`name` and `arguments` or `parameters` (also the OpenAI `{"function": {...}}` nesting), `functools`
and `[TOOL_CALLS]` prefixes, `<tool_call>` tags, and any of these inside one closed code fence.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# Lines scanned from the end of the reply for where the call begins; a call sits at the tail.
_MAX_START_LINES = 120

_FENCE = re.compile(r"```[^\n`]*\n(.*?)\n?```", re.DOTALL)
_TAG = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_TAIL_START = re.compile(r"\[|\{|```|<tool_call>|functools|[A-Za-z_][\w.]*\s*\(")
_CONSTANT_NAMES: dict[str, bool | None] = {"true": True, "false": False, "null": None, "none": None}
_NOT_A_LITERAL = object()


@dataclass(frozen=True)
class TextCall:
    """One call found in text: a tool name as the request spelled it, and its keyword arguments."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class TextCalls:
    """The calls a reply carries as text, the lead-in before them and the form they were written in."""

    calls: tuple[TextCall, ...]
    lead_in: str
    shape: str


def recover_text_calls(text: str, tool_names: Iterable[str]) -> TextCalls | None:
    """The calls `text` ends with, or None when it does not end with a call to an offered tool."""
    tools = {name: name for name in tool_names}
    if not tools or not text or not text.strip():
        return None
    line_starts = [match.end() for match in re.finditer(r"\n", text)]
    for start in sorted({0, *line_starts[-_MAX_START_LINES:]}):
        tail = text[start:].strip()
        if not tail or not _TAIL_START.match(tail):
            continue
        found = _calls_from_tail(tail, tools)
        if found is not None:
            calls, shape = found
            return TextCalls(tuple(calls), text[:start].strip(), shape)
    return None


def _calls_from_tail(tail: str, tools: Mapping[str, str]) -> tuple[list[TextCall], str] | None:
    body = tail
    fenced = _FENCE.fullmatch(body)
    if body.startswith("```"):
        if fenced is None:
            return None
        body = fenced.group(1).strip()
    found = _calls_from_body(body, tools)
    if found is None:
        return None
    calls, shape = found
    return calls, f"{shape} in a code fence" if fenced else shape


def _calls_from_body(body: str, tools: Mapping[str, str]) -> tuple[list[TextCall], str] | None:
    if body.startswith("<tool_call>"):
        return _calls_from_tags(body, tools)
    shape = "json"
    if body.startswith("[TOOL_CALLS]"):
        body, shape = body[len("[TOOL_CALLS]") :].strip(), "[TOOL_CALLS] json"
    elif body.startswith("functools"):
        body, shape = _unwrap_functools(body), "functools json"
    decoded = _json_value(body)
    if decoded is not None:
        calls = _calls_from_json(decoded, tools)
        return (calls, shape) if calls else None
    if shape != "json":
        return None
    calls = _calls_from_python(body, tools)
    return (calls, "python calls") if calls else None


def _unwrap_functools(body: str) -> str:
    rest = body[len("functools") :].strip()
    if rest.startswith("(") and rest.endswith(")"):
        rest = rest[1:-1].strip()
    return rest


def _json_value(body: str) -> Any | None:
    if not body or body[0] not in "[{":
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def _calls_from_tags(body: str, tools: Mapping[str, str]) -> tuple[list[TextCall], str] | None:
    blocks = _TAG.findall(body)
    if not blocks or _TAG.sub("", body).strip():
        return None
    calls: list[TextCall] = []
    for block in blocks:
        decoded = _json_value(block.strip())
        found = _calls_from_json(decoded, tools) if decoded is not None else None
        if not found:
            return None
        calls.extend(found)
    return calls, "tool_call tags"


def _calls_from_json(decoded: Any, tools: Mapping[str, str]) -> list[TextCall] | None:
    items = decoded if isinstance(decoded, list) else [decoded]
    calls: list[TextCall] = []
    for item in items:
        call = _json_call(item, tools)
        if call is None:
            return None
        calls.append(call)
    return calls or None


def _json_call(item: Any, tools: Mapping[str, str]) -> TextCall | None:
    if not isinstance(item, dict):
        return None
    nested = item.get("function")
    source = nested if isinstance(nested, dict) else item
    name = source.get("name")
    if not isinstance(name, str) and isinstance(nested, str):
        name = nested
    if not isinstance(name, str):
        return None
    arguments = source.get("arguments", source.get("parameters"))
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except ValueError:
            return None
    if arguments is None:
        arguments = {}
    canonical = _tool_name(name, tools)
    if canonical is None or not isinstance(arguments, dict):
        return None
    return TextCall(canonical, arguments)


def _tool_name(written: str, tools: Mapping[str, str]) -> str | None:
    return tools.get(written) or tools.get(written.replace(".", "_"))


def _calls_from_python(body: str, tools: Mapping[str, str]) -> list[TextCall] | None:
    try:
        node = ast.parse(body, mode="eval").body
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    elements = node.elts if isinstance(node, ast.List) else [node]
    calls: list[TextCall] = []
    for element in elements:
        call = _python_call(element, tools)
        if call is None:
            return None
        calls.append(call)
    return calls or None


def _python_call(node: ast.expr, tools: Mapping[str, str]) -> TextCall | None:
    if not isinstance(node, ast.Call) or node.args:
        return None
    written = _dotted_name(node.func)
    canonical = _tool_name(written, tools) if written else None
    if canonical is None:
        return None
    arguments: dict[str, Any] = {}
    for keyword in node.keywords:
        value = _literal(keyword.value)
        if keyword.arg is None or value is _NOT_A_LITERAL:
            return None
        arguments[keyword.arg] = value
    return TextCall(canonical, arguments)


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted_name(node.value)
        return f"{head}.{node.attr}" if head else None
    return None


def _literal(node: ast.expr) -> Any:
    """The JSON-compatible value of a literal expression, or `_NOT_A_LITERAL`."""
    if isinstance(node, ast.Name):
        return _CONSTANT_NAMES.get(node.id.lower(), _NOT_A_LITERAL)
    if isinstance(node, ast.List | ast.Tuple):
        items = [_literal(element) for element in node.elts]
        return _NOT_A_LITERAL if any(item is _NOT_A_LITERAL for item in items) else items
    if isinstance(node, ast.Dict):
        return _literal_dict(node)
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return _NOT_A_LITERAL
    return value if value is None or isinstance(value, bool | int | float | str) else _NOT_A_LITERAL


def _literal_dict(node: ast.Dict) -> Any:
    result: dict[str, Any] = {}
    for key_node, value_node in zip(node.keys, node.values, strict=True):
        key = _literal(key_node) if key_node is not None else _NOT_A_LITERAL
        value = _literal(value_node)
        if not isinstance(key, str) or value is _NOT_A_LITERAL:
            return _NOT_A_LITERAL
        result[key] = value
    return result

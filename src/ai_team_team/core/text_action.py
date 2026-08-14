import ast
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from .exceptions import ToolArgumentError


@dataclass(frozen=True)
class ParsedTextAction:
    name: str
    arguments: str


def _strip_fence(value: str) -> str:
    stripped = value.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if not lines or not lines[-1].strip().endswith("```"):
        raise ToolArgumentError("The Markdown action fence is not closed.")
    return "\n".join(lines[1:-1]).strip()


def _scan_balanced_call(text: str, start: int) -> Tuple[str, int]:
    opening = text[start]
    if opening != "(":
        raise ToolArgumentError("Action must contain an opening parenthesis.")
    stack = [")"]
    quote = None
    triple = False
    escaped = False
    index = start + 1
    pairs = {"(": ")", "[": "]", "{": "}"}
    while index < len(text):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
                index += 1
                continue
            if char == "\\":
                escaped = True
                index += 1
                continue
            if triple:
                if text.startswith(quote * 3, index):
                    quote = None
                    triple = False
                    index += 3
                    continue
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            triple = text.startswith(char * 3, index)
            index += 3 if triple else 1
            continue
        if char in pairs:
            stack.append(pairs[char])
        elif char in {")", "]", "}"}:
            if not stack or char != stack[-1]:
                raise ToolArgumentError("Action arguments contain unbalanced delimiters.")
            stack.pop()
            if not stack:
                return text[start + 1 : index], index + 1
        index += 1
    raise ToolArgumentError("Action arguments are truncated or unclosed.")


def parse_text_action(response: str) -> ParsedTextAction:
    """Extracts exactly one XML or Python-call Text ReAct action."""
    response = _strip_fence(response)
    xml = list(
        re.finditer(
            r'<action\s+name="([A-Za-z_]\w*)"\s*>(.*?)</action>',
            response,
            re.DOTALL | re.IGNORECASE,
        )
    )
    action_markers = list(re.finditer(r"Action\s*:", response, re.IGNORECASE))
    external_action_markers = [
        marker
        for marker in action_markers
        if not any(match.start() <= marker.start() < match.end() for match in xml)
    ]
    if xml and external_action_markers:
        raise ToolArgumentError("The response contains ambiguous action formats.")
    if len(xml) > 1:
        raise ToolArgumentError("The response contains more than one action.")
    if xml:
        return ParsedTextAction(xml[0].group(1), _strip_fence(xml[0].group(2)))
    if not action_markers:
        raise ToolArgumentError("No Action was found in the response.")

    tail = response[action_markers[0].end() :].lstrip()
    fenced = tail.startswith("```")
    if fenced:
        first_newline = tail.find("\n")
        if first_newline < 0:
            raise ToolArgumentError("The Markdown action fence is not closed.")
        tail = tail[first_newline + 1 :]
    name_match = re.match(r"([A-Za-z_]\w*)\s*", tail)
    if not name_match:
        raise ToolArgumentError("Action tool name is invalid.")
    name = name_match.group(1)
    open_index = name_match.end()
    if open_index >= len(tail) or tail[open_index] != "(":
        raise ToolArgumentError("Action must use tool_name(arguments) syntax.")
    arguments, end = _scan_balanced_call(tail, open_index)
    remainder = tail[end:].strip()
    if fenced:
        if not remainder.startswith("```"):
            raise ToolArgumentError("The Markdown action fence is not closed.")
        remainder = remainder[3:].strip()
    if remainder:
        raise ToolArgumentError("Unexpected content follows the Action call.")
    return ParsedTextAction(name, arguments.strip())


def parse_tool_arguments(value: str) -> Tuple[List[Any], Dict[str, Any]]:
    """Parses literal positional and keyword arguments without fallback."""
    if not value.strip():
        return [], {}
    try:
        tree = ast.parse(f"_att_tool({value})", mode="eval")
    except SyntaxError as exc:
        raise ToolArgumentError(f"Invalid tool argument syntax: {exc.msg}") from exc
    call = tree.body
    if not isinstance(call, ast.Call):
        raise ToolArgumentError("Tool arguments must form a function call.")
    if any(keyword.arg is None for keyword in call.keywords):
        raise ToolArgumentError("Expanded keyword arguments are not allowed.")
    keyword_names = [keyword.arg for keyword in call.keywords]
    if len(keyword_names) != len(set(keyword_names)):
        raise ToolArgumentError("Duplicate keyword arguments are not allowed.")
    if any(isinstance(argument, ast.Starred) for argument in call.args):
        raise ToolArgumentError("Expanded positional arguments are not allowed.")
    try:
        args = [ast.literal_eval(argument) for argument in call.args]
        kwargs = {
            keyword.arg: ast.literal_eval(keyword.value)
            for keyword in call.keywords
        }
    except (ValueError, TypeError) as exc:
        raise ToolArgumentError(
            "Tool arguments must be Python literal values."
        ) from exc
    return args, kwargs

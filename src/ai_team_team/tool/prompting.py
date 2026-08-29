"""Text-mode rendering for Tool JSON Schemas."""

import json
from typing import Any, Dict

from .contract import Tool


def _resolve_schema_ref(schema: Dict[str, Any], root: Dict[str, Any]) -> Dict[str, Any]:
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        return schema
    return root.get("$defs", {}).get(ref.rsplit("/", 1)[-1], schema)


def _compact_schema_type(schema: Dict[str, Any], root: Dict[str, Any]) -> str:
    schema = _resolve_schema_ref(schema, root)
    if "anyOf" in schema:
        return " | ".join(
            _compact_schema_type(item, root) for item in schema["anyOf"]
        )
    if "enum" in schema:
        return "literal[" + ", ".join(repr(v) for v in schema["enum"]) + "]"
    value_type = schema.get("type", "any")
    if value_type == "array":
        return f"list[{_compact_schema_type(schema.get('items', {}), root)}]"
    if value_type == "object":
        properties = schema.get("properties", {})
        if properties:
            required = set(schema.get("required", []))
            fields = []
            for name, child in properties.items():
                marker = "" if name in required else "?"
                fields.append(
                    f"{name}{marker}: {_compact_schema_type(child, root)}"
                )
            return "{" + ", ".join(fields) + "}"
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            return f"dict[str, {_compact_schema_type(additional, root)}]"
        return "dict"
    return str(value_type)


def render_tool_prompt(tool: Tool, mode: str) -> str:
    """Renders one tool contract for a Text ReAct system prompt."""
    schema = tool.json_schema
    if mode == "full":
        rendered = json.dumps(schema, ensure_ascii=False, sort_keys=True)
    else:
        required = set(schema.get("required", []))
        parts = []
        for name, child in schema.get("properties", {}).items():
            marker = "required" if name in required else "optional"
            default = (
                f", default={child['default']!r}"
                if "default" in child
                else ""
            )
            parts.append(
                f"{name}: {_compact_schema_type(child, schema)} ({marker}{default})"
            )
        rendered = "; ".join(parts) if parts else "no arguments"
    line = f"- **{tool.name}**: {tool.description}\n  Schema: {rendered}"
    if mode == "compact_with_examples" and tool.examples:
        line += "\n  Examples: " + json.dumps(
            tool.examples, ensure_ascii=False, sort_keys=True
        )
    elif mode == "full" and tool.examples:
        line += "\n  Examples: " + json.dumps(
            tool.examples, ensure_ascii=False, sort_keys=True
        )
    return line

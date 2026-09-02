"""Tool interface, registry, validation, and error conversion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import JarvisError, ToolError
from .policy import Policy
from .types import ToolResult


ToolHandler = Callable[[dict[str, Any], Policy], ToolResult]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def api_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool], policy: Policy) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("Tool names must be unique")
        self.policy = policy

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [tool.api_schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, f"Unknown tool: {name}")
        try:
            self._validate(arguments, tool.parameters)
            return tool.handler(arguments, self.policy)
        except JarvisError as error:
            return ToolResult(False, str(error), {"error_type": error.code})
        except (OSError, UnicodeError) as error:
            return ToolResult(False, f"Local tool failed: {error}", {"error_type": "os_error"})
        except Exception as error:  # defensive boundary around tool plugins
            return ToolResult(False, f"Unexpected tool failure: {error}", {"error_type": "internal_tool_error"})

    @classmethod
    def _validate(cls, arguments: dict[str, Any], schema: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ToolError("Tool arguments must be a JSON object")
        cls._validate_value(arguments, schema, path="")

    @classmethod
    def _validate_value(cls, value: Any, schema: dict[str, Any], *, path: str) -> None:
        python_types = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        expected_name = schema.get("type")
        expected = python_types.get(expected_name)
        numeric_bool = expected_name in {"integer", "number"} and isinstance(value, bool)
        if expected and (not isinstance(value, expected) or numeric_bool):
            label = repr(path) if path else "tool arguments"
            raise ToolError(f"Argument {label} must be of type {expected_name}")

        allowed = schema.get("enum")
        if isinstance(allowed, list) and value not in allowed:
            label = repr(path) if path else "tool arguments"
            choices = ", ".join(repr(item) for item in allowed)
            raise ToolError(f"Argument {label} must be one of: {choices}")

        if isinstance(value, dict):
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            for name in required:
                if name not in value:
                    if path:
                        raise ToolError(f"Missing required argument: {path}.{name}")
                    raise ToolError(f"Missing required argument: {name}")
            extra = set(value) - set(properties)
            if extra and schema.get("additionalProperties") is False:
                raise ToolError("Unexpected argument(s): " + ", ".join(sorted(extra)))
            for name, child in value.items():
                child_schema = properties.get(name)
                if isinstance(child_schema, dict):
                    child_path = f"{path}.{name}" if path else name
                    cls._validate_value(child, child_schema, path=child_path)

        if isinstance(value, list):
            minimum_items = schema.get("minItems")
            maximum_items = schema.get("maxItems")
            if isinstance(minimum_items, int) and len(value) < minimum_items:
                raise ToolError(f"Argument {path!r} must contain at least {minimum_items} item(s)")
            if isinstance(maximum_items, int) and len(value) > maximum_items:
                raise ToolError(f"Argument {path!r} must contain at most {maximum_items} item(s)")
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    cls._validate_value(item, item_schema, path=f"{path}[{index}]")

        if isinstance(value, str):
            minimum_length = schema.get("minLength")
            maximum_length = schema.get("maxLength")
            if isinstance(minimum_length, int) and len(value) < minimum_length:
                raise ToolError(f"Argument {path!r} must contain at least {minimum_length} character(s)")
            if isinstance(maximum_length, int) and len(value) > maximum_length:
                raise ToolError(f"Argument {path!r} must contain at most {maximum_length} character(s)")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if isinstance(minimum, (int, float)) and value < minimum:
                raise ToolError(f"Argument {path!r} must be at least {minimum}")
            if isinstance(maximum, (int, float)) and value > maximum:
                raise ToolError(f"Argument {path!r} must be at most {maximum}")

